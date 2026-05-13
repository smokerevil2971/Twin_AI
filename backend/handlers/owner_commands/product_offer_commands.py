import logging
import re
from fastapi import Response
from sqlalchemy import select
from core.database import get_db_context, AsyncSessionLocal
from models.models import Product, Offer
from services.messaging_adapter import get_messaging_adapter
from handlers.owner_commands.base import BaseCommand, CommandPayload, register_command

logger = logging.getLogger(__name__)

@register_command(r"/products", exact=True)
class ProductsCommand(BaseCommand):
    async def execute(self, payload: CommandPayload) -> Response:
        adapter = get_messaging_adapter()
        async with get_db_context() as db:
            result = await db.execute(
                select(Product).where(Product.is_active == True).order_by(Product.name)
            )
            products = result.scalars().all()

        if not products:
            await adapter.send_message(
                phone=payload.sender_phone,
                message="📦 No products yet. Add one with:\n`PRODUCT: <name> | <price> | <description>`",
            )
        else:
            lines = [f"📦 *Products ({len(products)})*\n"]
            for i, p in enumerate(products, 1):
                price_str = f"₹{p.price:,.0f}" if p.price else "Price on request"
                desc = f" — {p.description[:50]}" if p.description else ""
                img = " 🖼️" if p.image_url else ""
                lines.append(f"{i}. *{p.name}* ({price_str}){desc}{img}")
            lines.append("\n_Use `DEL PRODUCT: <name>` to remove._")
            await adapter.send_message(phone=payload.sender_phone, message="\n".join(lines))
        return Response(status_code=200, content="ok")

@register_command(r"/offers", exact=True)
class OffersCommand(BaseCommand):
    async def execute(self, payload: CommandPayload) -> Response:
        adapter = get_messaging_adapter()
        async with get_db_context() as db:
            result = await db.execute(
                select(Offer).where(Offer.is_active == True).order_by(Offer.title)
            )
            offers = result.scalars().all()

        if not offers:
            await adapter.send_message(
                phone=payload.sender_phone,
                message="💰 No offers yet. Add one with:\n`OFFER: <title> | <description>`",
            )
        else:
            lines = [f"💰 *Offers ({len(offers)})*\n"]
            for i, o in enumerate(offers, 1):
                desc = f" — {o.description[:60]}" if o.description else ""
                lines.append(f"{i}. *{o.title}*{desc}")
            lines.append("\n_Use `DEL OFFER: <title>` to remove._")
            await adapter.send_message(phone=payload.sender_phone, message="\n".join(lines))
        return Response(status_code=200, content="ok")

@register_command(r"product:\s*(.+?)\s*\|\s*([\d.,]*)\s*(?:\|\s*(.+?))?\s*(?:\|\s*(https?://\S+))?")
class AddProductCommand(BaseCommand):
    async def execute(self, payload: CommandPayload) -> Response:
        adapter = get_messaging_adapter()
        name        = payload.match.group(1).strip()
        price_raw   = (payload.match.group(2) or "").strip().replace(",", "")
        description = (payload.match.group(3) or "").strip() or None
        image_url   = (payload.match.group(4) or "").strip() or None
        price       = float(price_raw) if price_raw else None

        try:
            async with AsyncSessionLocal() as db:
                existing = (await db.execute(
                    select(Product).where(Product.name.ilike(name), Product.is_active == True)
                )).scalar_one_or_none()
                if existing:
                    await adapter.send_message(
                        phone=payload.sender_phone,
                        message=f"⚠️ Product already exists: *{existing.name}*\nUse `DEL PRODUCT: {existing.name}` first to replace it.",
                    )
                else:
                    product = Product(
                        name=name, description=description,
                        price=price, image_url=image_url, is_active=True
                    )
                    db.add(product)
                    await db.commit()
                    price_str = f"₹{price:,.0f}" if price else "Price on request"
                    img_tag = "\n🖼️ Image: attached" if image_url else ""
                    await adapter.send_message(
                        phone=payload.sender_phone,
                        message=(
                            f"✅ *Product added!*\n"
                            f"🛒 Name: *{name}*\n"
                            f"💰 Price: {price_str}\n"
                            f"📝 Description: {description or '—'}{img_tag}\n\n"
                            f"_It will now appear in the client product menu._"
                        ),
                    )
                    if payload.message_id:
                        await adapter.send_reaction(payload.sender_phone, payload.message_id, "👍")
                    logger.info(f"[CMD] Product added: {name} @ {price} image={'yes' if image_url else 'no'}")
        except Exception as exc:
            logger.error(f"[CMD] PRODUCT add failed: {exc}", exc_info=True)
            await adapter.send_message(phone=payload.sender_phone, message="❌ Failed to add product. Check server logs for details.")
        return Response(status_code=200, content="ok")

@register_command(r"offer:\s*(.+?)\s*\|\s*(.+)")
class AddOfferCommand(BaseCommand):
    async def execute(self, payload: CommandPayload) -> Response:
        adapter = get_messaging_adapter()
        title = payload.match.group(1).strip()
        description = payload.match.group(2).strip()

        try:
            async with AsyncSessionLocal() as db:
                existing = (await db.execute(
                    select(Offer).where(Offer.title.ilike(title), Offer.is_active == True)
                )).scalar_one_or_none()
                if existing:
                    await adapter.send_message(
                        phone=payload.sender_phone,
                        message=f"⚠️ Offer already exists: *{existing.title}*\nUse `DEL OFFER: {existing.title}` first to replace it.",
                    )
                else:
                    offer = Offer(title=title, description=description, is_active=True)
                    db.add(offer)
                    await db.commit()
                    await adapter.send_message(
                        phone=payload.sender_phone,
                        message=(
                            f"✅ *Offer added!*\n"
                            f"💰 Title: *{title}*\n"
                            f"📝 Description: {description}\n\n"
                            f"_It will now appear in the client offers menu._"
                        ),
                    )
                    logger.info(f"[CMD] Offer added: {title}")
        except Exception as exc:
            logger.error(f"[CMD] OFFER add failed: {exc}", exc_info=True)
            await adapter.send_message(phone=payload.sender_phone, message="❌ Failed to add offer. Check server logs for details.")
        return Response(status_code=200, content="ok")

@register_command(r"del\s+product:\s*(.+)")
class DelProductCommand(BaseCommand):
    async def execute(self, payload: CommandPayload) -> Response:
        adapter = get_messaging_adapter()
        name = payload.match.group(1).strip()
        try:
            async with AsyncSessionLocal() as db:
                product = (await db.execute(
                    select(Product).where(Product.name.ilike(name), Product.is_active == True)
                )).scalar_one_or_none()
                if not product:
                    await adapter.send_message(
                        phone=payload.sender_phone,
                        message=f"⚠️ No active product found matching: *{name}*\nUse `/products` to see all products.",
                    )
                else:
                    product.is_active = False
                    await db.commit()
                    await adapter.send_message(
                        phone=payload.sender_phone,
                        message=f"🗑️ Product removed: *{product.name}*\n_It will no longer appear in the client menu._",
                    )
                    logger.info(f"[CMD] Product deactivated: {product.name}")
        except Exception as exc:
            logger.error(f"[CMD] DEL PRODUCT failed: {exc}", exc_info=True)
            await adapter.send_message(phone=payload.sender_phone, message="❌ Failed to remove product. Check server logs for details.")
        return Response(status_code=200, content="ok")

@register_command(r"del\s+offer:\s*(.+)")
class DelOfferCommand(BaseCommand):
    async def execute(self, payload: CommandPayload) -> Response:
        adapter = get_messaging_adapter()
        title = payload.match.group(1).strip()
        try:
            async with AsyncSessionLocal() as db:
                offer = (await db.execute(
                    select(Offer).where(Offer.title.ilike(title), Offer.is_active == True)
                )).scalar_one_or_none()
                if not offer:
                    await adapter.send_message(
                        phone=payload.sender_phone,
                        message=f"⚠️ No active offer found matching: *{title}*\nUse `/offers` to see all offers.",
                    )
                else:
                    offer.is_active = False
                    await db.commit()
                    await adapter.send_message(
                        phone=payload.sender_phone,
                        message=f"🗑️ Offer removed: *{offer.title}*\n_It will no longer appear in the client menu._",
                    )
                    logger.info(f"[CMD] Offer deactivated: {offer.title}")
        except Exception as exc:
            logger.error(f"[CMD] DEL OFFER failed: {exc}", exc_info=True)
            await adapter.send_message(phone=payload.sender_phone, message="❌ Failed to remove offer. Check server logs for details.")
        return Response(status_code=200, content="ok")

@register_command(r"update\s+product:\s*(.+?)\s*\|\s*([\d.]+)\s*")
class UpdateProductCommand(BaseCommand):
    async def execute(self, payload: CommandPayload) -> Response:
        adapter = get_messaging_adapter()
        name       = payload.match.group(1).strip()
        new_price  = float(payload.match.group(2))
        async with AsyncSessionLocal() as db:
            product = (await db.execute(
                select(Product).where(Product.name.ilike(f"%{name}%"), Product.is_active == True)
            )).scalar_one_or_none()
            if not product:
                await adapter.send_message(
                    phone=payload.sender_phone,
                    message=f"⚠️ No active product found matching: *{name}*",
                )
            else:
                old_price = product.price
                product.price = new_price
                await db.commit()
                await adapter.send_message(
                    phone=payload.sender_phone,
                    message=(
                        f"✅ *Price updated!*\n\n"
                        f"🛍️ Product: *{product.name}*\n"
                        f"💰 Old price: ₹{old_price:,.0f}\n"
                        f"💰 New price: ₹{new_price:,.0f}"
                    ),
                )
                if payload.message_id:
                    await adapter.send_reaction(payload.sender_phone, payload.message_id, "👍")
                logger.info(f"[CMD] Product price updated: {product.name} → ₹{new_price}")
        return Response(status_code=200, content="ok")
