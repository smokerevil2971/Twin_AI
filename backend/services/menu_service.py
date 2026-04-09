"""
Menu Service — Interactive WhatsApp Button Menu

Handles the full menu state machine for client-facing interactions:
  - Main menu: 3 quick-reply buttons (Products / Offers / Catalog)
  - Products sub-menu: list-picker with one row per active product (paginated)
  - Offers sub-menu:   list-picker with one row per active offer (paginated)
  - Catalog: re-uses existing catalogue send logic

State is tracked per-phone in Redis (menu:{phone}).
Button→item mappings for the current page are in Redis (menu_page:{phone}).

Called from routes/webhooks.py:
  1. After onboarding completes   → send_main_menu()
  2. Before RAG bot               → handle_menu_input() returns True if handled
  3. After RAG bot answers        → send_main_menu()
"""
import logging
import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.redis_client import (
    get_menu_state, set_menu_state, clear_menu_state,
    get_menu_page, set_menu_page,
    MENU_STATE_MAIN, MENU_STATE_PRODUCTS, MENU_STATE_OFFERS,
    increment_menu_counter,  # 2.3: analytics tap counting
)
from models.models import Product, Offer

logger = logging.getLogger(__name__)

# ── Main menu button definitions (fixed) ──────────────────────────────────────

MAIN_MENU_BODY = (
    "What would you like to explore today? 🔍\n\n"
    "Tap a button below to explore 👇"
)

MAIN_MENU_BUTTONS = [
    {"id": "products", "title": "🛍️ Products"},
    {"id": "offers",   "title": "💰 Offers & Deals"},
    {"id": "catalog",  "title": "📄 Catalog"},
]

# Special row IDs used for pagination and navigation control
_ROW_NEXT      = "nav_next_page"
_ROW_BACK      = "nav_back"
_ROW_BACK_MAIN = "nav_back_main"  # 4.1: back to main menu button

# 4.1: Reserve 2 rows for navigation (Back to Menu + Next/Prev)
# WhatsApp list limit = 10 rows. We cap page_items at 8 to always fit nav rows.
_MAX_ITEM_ROWS = 8


# ─── Public API ───────────────────────────────────────────────────────────────

async def send_main_menu(adapter, phone: str) -> None:
    """Send the 3-button quick-reply main menu and set menu state."""
    try:
        await adapter.send_interactive_message(
            phone=phone,
            body=MAIN_MENU_BODY,
            buttons=MAIN_MENU_BUTTONS,
            use_list=False,
        )
        await set_menu_state(phone, MENU_STATE_MAIN)
        logger.info(f"[MENU] Main menu sent to {phone}")
    except Exception as exc:
        logger.error(f"[MENU] send_main_menu failed for {phone}: {exc}")


async def send_products_menu(adapter, phone: str, db: AsyncSession, page: int = 0) -> None:
    """Fetch active products from DB and send as a list-picker (paginated)."""
    try:
        result = await db.execute(
            select(Product).where(Product.is_active == True).order_by(Product.name)
        )
        products = result.scalars().all()

        if not products:
            await adapter.send_message(
                phone=phone,
                message=(
                    "📦 *Our Products*\n\n"
                    "We're updating our product list. "
                    "Ask me anything about our products! 😊"
                ),
            )
            await set_menu_state(phone, MENU_STATE_MAIN)
            await send_main_menu(adapter, phone)
            return

        page_size = min(settings.menu_page_size, _MAX_ITEM_ROWS)
        offset = page * page_size
        page_items = products[offset: offset + page_size]
        has_next = (offset + page_size) < len(products)
        has_prev = page > 0

        # Build list rows + record button→product mapping
        list_rows: list[dict] = []
        mapping: dict[str, str] = {}

        for product in page_items:
            row_id = f"prod_{product.id}"
            price_str = f"₹{product.price:,.0f}" if product.price else "Price on request"
            description = product.description[:60] if product.description else price_str
            list_rows.append({"id": row_id, "title": product.name, "description": description})
            mapping[row_id] = str(product.id)

        # 4.1: Always show Back to Menu as first navigation row
        list_rows.append({"id": _ROW_BACK_MAIN, "title": "⬅️ Back to Menu", "description": ""})
        mapping[_ROW_BACK_MAIN] = "back_main"

        # Pagination controls (prev / next) after Back button
        if has_prev:
            list_rows.append({"id": _ROW_BACK, "title": "◀ Previous Page", "description": ""})
            mapping[_ROW_BACK] = f"products_page_{page - 1}"
        if has_next:
            list_rows.append({"id": _ROW_NEXT, "title": "▶ Next Page", "description": ""})
            mapping[_ROW_NEXT] = f"products_page_{page + 1}"

        total_pages = (len(products) + page_size - 1) // page_size
        page_label = f" (Page {page + 1}/{total_pages})" if total_pages > 1 else ""
        body = f"📦 *Our Products{page_label}*\n\nTap a product to learn more:"

        await adapter.send_interactive_message(
            phone=phone,
            body=body,
            buttons=[{"id": "products_header", "title": "Select a product"}],
            use_list=True,
            list_items=list_rows,
        )
        await set_menu_page(phone, mapping)
        await set_menu_state(phone, MENU_STATE_PRODUCTS)
        logger.info(f"[MENU] Products menu (page {page}) sent to {phone} — {len(page_items)} items")

    except Exception as exc:
        logger.error(f"[MENU] send_products_menu failed for {phone}: {exc}")


async def send_offers_menu(adapter, phone: str, db: AsyncSession, page: int = 0) -> None:
    """Fetch active offers from DB and send as a list-picker (paginated)."""
    try:
        result = await db.execute(
            select(Offer).where(Offer.is_active == True).order_by(Offer.title)
        )
        offers = result.scalars().all()

        if not offers:
            await adapter.send_message(
                phone=phone,
                message=(
                    "💰 *Offers & Deals*\n\n"
                    "No active offers right now — check back soon! "
                    "You can ask me about our products anytime. 😊"
                ),
            )
            await set_menu_state(phone, MENU_STATE_MAIN)
            await send_main_menu(adapter, phone)
            return

        page_size = min(settings.menu_page_size, _MAX_ITEM_ROWS)
        offset = page * page_size
        page_items = offers[offset: offset + page_size]
        has_next = (offset + page_size) < len(offers)
        has_prev = page > 0

        list_rows: list[dict] = []
        mapping: dict[str, str] = {}

        for offer in page_items:
            row_id = f"offr_{offer.id}"
            description = offer.description[:60] if offer.description else "Tap to learn more"
            list_rows.append({"id": row_id, "title": offer.title, "description": description})
            mapping[row_id] = str(offer.id)

        # 4.1: Always show Back to Menu
        list_rows.append({"id": _ROW_BACK_MAIN, "title": "⬅️ Back to Menu", "description": ""})
        mapping[_ROW_BACK_MAIN] = "back_main"

        if has_prev:
            list_rows.append({"id": _ROW_BACK, "title": "◀ Previous Page", "description": ""})
            mapping[_ROW_BACK] = f"offers_page_{page - 1}"
        if has_next:
            list_rows.append({"id": _ROW_NEXT, "title": "▶ Next Page", "description": ""})
            mapping[_ROW_NEXT] = f"offers_page_{page + 1}"

        total_pages = (len(offers) + page_size - 1) // page_size
        page_label = f" (Page {page + 1}/{total_pages})" if total_pages > 1 else ""
        body = f"💰 *Offers & Deals{page_label}*\n\nTap an offer to learn more:"

        await adapter.send_interactive_message(
            phone=phone,
            body=body,
            buttons=[{"id": "offers_header", "title": "Select an offer"}],
            use_list=True,
            list_items=list_rows,
        )
        await set_menu_page(phone, mapping)
        await set_menu_state(phone, MENU_STATE_OFFERS)
        logger.info(f"[MENU] Offers menu (page {page}) sent to {phone} — {len(page_items)} items")

    except Exception as exc:
        logger.error(f"[MENU] send_offers_menu failed for {phone}: {exc}")


async def handle_menu_input(
    adapter,
    phone: str,
    msg: str,
    button_payload: str,
    list_id: str,
    db: AsyncSession,
    client_id: str,
) -> bool:
    """
    Route an inbound message through the menu state machine.

    Returns True  → message was handled by the menu (caller should NOT call RAG bot).
    Returns False → message was not handled (caller SHOULD fall through to RAG bot).

    Parameters:
      button_payload — value of Twilio's ButtonPayload field (quick-reply taps)
      list_id        — value of Twilio's ListId field (list-picker selections)
    """
    menu_state = await get_menu_state(phone)
    trigger = button_payload or list_id   # whichever is set

    logger.info(
        f"[MENU] handle_menu_input: phone={phone} state={menu_state} "
        f"trigger={trigger!r} msg={msg[:40]!r}"
    )

    # ── Main menu button taps ───────────────────────────────────────────────────────────────────────────────
    # 4.1: Handle back-to-main from any submenu first
    if trigger == _ROW_BACK_MAIN or trigger == "nav_back_main":
        await clear_menu_state(phone)
        await send_main_menu(adapter, phone)
        logger.info(f"[MENU] {phone} navigated back to main menu")
        return True

    if trigger == "products" or (menu_state == MENU_STATE_MAIN and msg.strip() == "1"):
        await send_products_menu(adapter, phone, db, page=0)
        return True

    if trigger == "offers" or (menu_state == MENU_STATE_MAIN and msg.strip() == "2"):
        await send_offers_menu(adapter, phone, db, page=0)
        return True

    if trigger == "catalog" or (menu_state == MENU_STATE_MAIN and msg.strip() == "3"):
        await _send_catalogue(adapter, phone)
        return True

    # ── List-picker selection (product or offer row tapped) ───────────────────
    if trigger and menu_state in (MENU_STATE_PRODUCTS, MENU_STATE_OFFERS):
        page_map = await get_menu_page(phone)
        mapped_value = page_map.get(trigger)

        if not mapped_value:
            # Unknown selection — fall through to RAG
            await clear_menu_state(phone)
            return False

        # Pagination controls
        if mapped_value.startswith("products_page_"):
            page_num = int(mapped_value.split("_")[-1])
            await send_products_menu(adapter, phone, db, page=page_num)
            return True

        if mapped_value.startswith("offers_page_"):
            page_num = int(mapped_value.split("_")[-1])
            await send_offers_menu(adapter, phone, db, page=page_num)
            return True

        # Real product / offer selected — look up the item, build a RAG query
        if menu_state == MENU_STATE_PRODUCTS:
            product = await _get_product(db, mapped_value)
            if product:
                # 2.3: track this product tap for analytics
                await increment_menu_counter("product", mapped_value)
                await clear_menu_state(phone)

                # 3.2: Send product image card if available
                if product.image_url:
                    price_str = f"₹{product.price:,.0f}" if product.price else "Price on request"
                    caption = f"*{product.name}*\n{price_str}"
                    if product.description:
                        caption += f"\n{product.description[:80]}"
                    try:
                        await adapter.send_media_message(
                            phone=phone,
                            media_url=product.image_url,
                            media_type="image",
                            caption=caption,
                            filename="product_image.jpg",
                        )
                        logger.info(f"[MENU] Sent product image for {product.name} to {phone}")
                    except Exception as img_exc:
                        logger.warning(f"[MENU] Product image send failed (non-fatal): {img_exc}")

                # Run RAG bot to generate full product explanation
                from services.rag_bot import run_bot
                await run_bot(
                    phone=phone,
                    raw_message=f"Tell me about the product: {product.name}",
                    client_id=client_id,
                    db=db,
                    is_menu_request=True,
                )
                return True

        elif menu_state == MENU_STATE_OFFERS:
            offer_title = await _get_offer_title(db, mapped_value)
            if offer_title:
                # 2.3: track this offer tap for analytics
                await increment_menu_counter("offer", mapped_value)
                await clear_menu_state(phone)
                from services.rag_bot import run_bot
                await run_bot(
                    phone=phone,
                    raw_message=f"Tell me about this offer: {offer_title}",
                    client_id=client_id,
                    db=db,
                    is_menu_request=True,
                )
                return True

        # Fallback — couldn't resolve item
        await clear_menu_state(phone)
        return False

    # ── No active menu state or unrecognised input ────────────────────────────
    # Clear any stale state and let the RAG bot handle it
    if menu_state:
        await clear_menu_state(phone)

    return False


# ─── Private helpers ──────────────────────────────────────────────────────────

async def _send_catalogue(adapter, phone: str) -> None:
    """Send the catalogue PDF (or a message if no URL is configured)."""
    from core.config import settings as app_settings
    from core.redis_client import get_redis
    r = get_redis()
    dynamic_url = await r.get(app_settings.catalogue_redis_key)
    final_url = dynamic_url or app_settings.catalogue_url

    if final_url:
        await adapter.send_media_message(
            phone=phone,
            media_url=final_url,
            media_type="document",
            filename=app_settings.catalogue_filename,
            caption="📄 Here is our latest product catalogue and price list!",
        )
    else:
        await adapter.send_message(
            phone=phone,
            message=(
                "📄 Our catalogue is being updated. "
                "Ask me about any product and I'll help right here! 😊"
            ),
        )
    logger.info(f"[MENU] Catalogue sent to {phone}")


async def _get_product(db: AsyncSession, product_id: str) -> Optional[Product]:
    """Return a full Product object by UUID string, or None if not found."""
    try:
        result = await db.execute(
            select(Product).where(Product.id == product_id, Product.is_active == True)
        )
        return result.scalar_one_or_none()
    except Exception as exc:
        logger.error(f"[MENU] _get_product failed: {exc}")
        return None


async def _get_product_name(db: AsyncSession, product_id: str) -> Optional[str]:
    """Return the name of a product by its UUID string, or None if not found."""
    try:
        result = await db.execute(
            select(Product.name).where(Product.id == product_id, Product.is_active == True)
        )
        return result.scalar_one_or_none()
    except Exception as exc:
        logger.error(f"[MENU] _get_product_name failed: {exc}")
        return None


async def _get_offer_title(db: AsyncSession, offer_id: str) -> Optional[str]:
    """Return the title of an offer by its UUID string, or None if not found."""
    try:
        result = await db.execute(
            select(Offer.title).where(Offer.id == offer_id, Offer.is_active == True)
        )
        return result.scalar_one_or_none()
    except Exception as exc:
        logger.error(f"[MENU] _get_offer_title failed: {exc}")
        return None
