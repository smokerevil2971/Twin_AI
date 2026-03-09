# Twin AI — Client Communication Agent System

## Full Project TODO List

> Generated from: Design_Document_CCA.docx · PRD_Client_Communication_Agent.docx · Phase1_Research_Document.docx · twin AI.docx
> Last updated: 2026-03-02 | v2 — Gaps & risks addressed

---

## ⚠️ CRITICAL PATH RISK — READ FIRST

> **#1 Blocker: Meta Business Verification + WhatsApp Provider Approval**
> Meta Business Verification alone takes **1–2 weeks**. WhatsApp provider approval takes **1–4 weeks**.
> In the worst case you are **6 weeks away from being able to send a single WhatsApp message.**
> **Everything in Phase 2 (Broadcast Agent) is fully blocked until this completes.**
>
> **Action:** Start Phase 0.1 and 0.2 on Day 1 of the project, in parallel with all development work.
> Do not assume WhatsApp access will arrive in Week 1. Build the backend and dashboard against a mock
> Gupshup API so development is not blocked while waiting for provider approval.

---

## 🗂️ PHASE 0 — Pre-Development Setup (Start Day 1, Run in Parallel)

### 0.1 WhatsApp Business API Registration

- [ ] Create a new dedicated phone number (must never have been registered on WhatsApp before)
- [ ] Create a Facebook Business Manager account
- [ ] Complete Meta business verification ⚠️ **Can take 1–2 weeks — start immediately**
- [ ] Evaluate WhatsApp Business API providers (Gupshup, Interakt, Wati, AiSensy)
- [ ] Submit registration application to selected provider (Gupshup recommended)
- [ ] Await provider approval ⚠️ **Can take 1–4 weeks — track daily**
- [ ] Obtain API key, webhook URL, and sender phone number from provider
- [ ] **Register a backup/reserve WhatsApp number** (PM.12 requirement — needed before go-live)
- [ ] Build a mock Gupshup API adapter so backend development proceeds during the wait

### 0.2 Message Template Preparation

- [ ] Prepare Template 1: Promotional Broadcast (product / offer announcement)
- [ ] Prepare Template 2: Order Confirmation
- [ ] Prepare Template 3: Follow-Up / Reminder
- [ ] Prepare Template 4: Opt-In Confirmation (consent)
- [ ] Prepare Template 5: Bot Escalation / Owner Redirect
- [ ] Submit all 5 templates in **both English and Hindi** to Meta for approval
- [ ] Wait for Meta template approval (24–48 hours per template after business verification)

### 0.3 Development Environment

- [ ] Provision Hetzner CX21 server (or equivalent VPS)
- [ ] Install Docker and Docker Compose on server
- [x] Set up PostgreSQL 15 container — `docker-compose.yml`
- [x] Set up Redis container (Celery task queue) — `docker-compose.yml`
- [x] Set up ChromaDB container (vector store) — `docker-compose.yml`
- [x] Set up FastAPI application container — `docker-compose.yml` + `backend/Dockerfile`
- [x] Set up Celery worker + beat containers — `docker-compose.yml`
- [ ] Configure Nginx as reverse proxy with HTTPS (Let's Encrypt)
- [x] Set up `.env.example` with all required keys — `GUPSHUP_MODE=mock` by default
- [ ] Validate: `docker compose up --build` starts all services without errors

---

## 🗃️ PHASE 1 — Database & Backend Foundation

### 1.1 Database Schema (PostgreSQL — all 9 tables, all in first migration)

- [x] Create Alembic migration environment — `backend/migrations/env.py` + `backend/alembic.ini`
- [x] Create `tenants` table — `models/models.py` + `migrations/versions/001_initial_schema.py`
- [x] Create `clients` table
  - [x] Fields: id (UUID), tenant_id, name, phone, email, opted_in (bool), language, created_at, updated_at
  - [x] Unique constraint on (tenant_id, phone); index on tenant_id
- [x] Create `broadcasts` table
  - [x] Fields: id, tenant_id, name, message_template, channel, status, scheduled_at, sent_at, created_at
- [x] Create `broadcast_recipients` table
  - [x] Fields: id, broadcast_id, client_id, status (sent/delivered/read/failed), sent_at, delivered_at, read_at, failed_reason
- [x] Create `conversations` table
  - [x] Fields: id, tenant_id, client_id, direction (inbound/outbound), message, language, confidence_score, flagged (bool), resolved (bool), created_at
- [x] Create `knowledge_base` table
  - [x] Fields: id, tenant_id, filename, category, chroma_ids (array), valid_from, valid_until, is_active, created_at
- [x] Create `products` table — `models/models.py`
- [x] Create `offers` table — `models/models.py`
- [x] Create `orders` table _(schema included from Day 1)_
  - [x] Fields: id (UUID), tenant_id, client_id (FK), product_name, amount, status, invoice_path, created_at, updated_at
  - [x] Index on (tenant_id, client_id)
- [ ] Validate: `alembic upgrade head` runs clean against postgres container

### 1.2 FastAPI Backend Project Structure

- [x] Initialize FastAPI project — `backend/` with `/routes`, `/models`, `/services`, `/agents`, `/tasks`, `/core`
- [x] Pin all dependencies — `backend/requirements.txt`
- [x] Implement JWT authentication
  - [x] `POST /auth/login` — returns JWT — `routes/auth.py`
  - [x] `POST /auth/register` — creates tenant + returns JWT — `routes/auth.py`
  - [x] JWT Bearer token verification — `core/security.py` `get_current_user()`
  - [x] `get_tenant_id()` dependency — tenant_id only from JWT, never from request body
- [x] Implement standard JSON response format — `core/responses.py`
- [x] Implement global error handlers (404, 422, 500) — `main.py`
- [x] Add CORS config — `main.py`
- [x] Add request logging middleware + X-Request-ID header — `core/middleware.py`
- [x] Create mock Gupshup adapter — `services/gupshup_adapter.py` (swap via `GUPSHUP_MODE=mock|real`)
- [x] Celery app + beat schedule — `core/celery_app.py`

---

## 📡 PHASE 2 — Broadcast Agent

> **Dependency:** Blocked until Phase 0.1 provider approval. Use mock Gupshup adapter during development.

### 2.1 Client Upload & Management API

- [x] `POST /clients/upload/preview` — returns column mapping preview, no DB write — `routes/clients.py`
- [x] `POST /clients/upload` — accept CSV or XLSX file upload — `routes/clients.py`
  - [x] Parse file using pandas / openpyxl — `services/client_service.py` `parse_upload_file()`
  - [x] Auto-detect columns: name, phone, email — `detect_column_mapping()`
  - [x] Validate + normalise phone numbers (Indian +91 prefix auto-added) — `normalise_phone()`
  - [x] Bulk insert valid records via `ON CONFLICT DO NOTHING` — skips existing (tenant_id, phone)
  - [x] Return summary: imported, skipped_duplicates, skipped_invalid, skipped_records list
- [x] `POST /clients/upload/skipped-export` — download skipped records as CSV — `routes/clients.py`
- [x] `GET /clients` — paginated list (filter by opted_in; search by name/phone) — `routes/clients.py`
- [x] `PATCH /clients/{id}` — update client fields (name, email, opted_in, language) — `routes/clients.py`
- [x] `DELETE /clients/{id}` — soft delete (is_deleted=True, history preserved) — `routes/clients.py`
- [x] `POST /clients/bulk-opt-in` — bulk set opted_in=true (requires confirmed=True flag) — `routes/clients.py`

### 2.2 Broadcast Creation & Sending API

- [x] `POST /broadcasts` — create new broadcast — `routes/broadcasts.py`
  - [x] Accept: template text, variable mappings, channel, language, scheduled_at (optional)
  - [x] Validate: only opted_in=true clients are eligible — `services/broadcast_service.py`
  - [x] Enforce: max 1 broadcast per client per 24-hour window — `get_eligible_clients()`
  - [x] Personalise message ({{name}}, {{1}} substitution) — `personalise()`
  - [x] Queue Celery task for immediate or scheduled dispatch — `send_broadcast.delay()` / `.apply_async(eta=...)`
- [x] `GET /broadcasts` — paginated list with status summary — `routes/broadcasts.py`
- [x] `GET /broadcasts/{id}` — full detail with per-client stats — `routes/broadcasts.py`
- [x] `GET /broadcasts/{id}/export` — download per-client delivery report as CSV — `routes/broadcasts.py`

### 2.3 Real-Time Delivery Updates (SSE / WebSocket)

- [x] **Decision:** Use **Server-Sent Events (SSE)** for delivery status streaming
- [x] `GET /broadcasts/{id}/stream` — SSE endpoint that emits delivery status events — `routes/broadcasts.py`
- [ ] Frontend Broadcast Detail page subscribes to SSE stream on mount; disconnects on unmount
- [ ] Fallback: polling every 10 seconds if SSE connection drops

### 2.4 Celery Broadcast Worker

- [x] Create `send_broadcast` Celery task — `tasks/broadcast_tasks.py`
  - [x] Fetch all eligible recipients (opted_in=true, not messaged in 24h)
  - [x] Dispatch via Gupshup API (rate limit: 80 msg/sec via RATE_LIMIT_DELAY=0.013s)
  - [x] Retry failed messages: up to 3 retries tracked in `retry_count` column
  - [x] Update `broadcast_recipients.status` per response
- [ ] Enforce send window: 9am–7pm local timezone (owner-overridable)
- [x] Schedule Celery Beat daily job: `deactivate_expired_offers` — `tasks/broadcast_tasks.py`

### 2.5 Delivery Webhook Handler

- [x] `POST /webhooks/gupshup/delivery` — inbound Gupshup delivery receipt — `routes/webhooks.py`
  - [x] Verify HMAC signature — `adapter.verify_webhook_signature()` (mock always passes)
  - [x] Parse status (sent / delivered / read / failed) and message_id — `GUPSHUP_STATUS_MAP`
  - [x] Update matching `broadcast_recipients` record in DB (status, delivered_at, read_at, failed_reason)
  - [x] Check if broadcast fully complete and update parent `Broadcast.status`
  - [x] Return 200 OK immediately — always, even for unknown IDs (stops Gupshup retries)

---

## 🤖 PHASE 3 — Client Assistant Bot (RAG Pipeline)

### 3.1 Knowledge Base Ingestion Pipeline

- [x] `POST /knowledge-base/upload` — accept PDF, image, or text file — `routes/knowledge_base.py`
  - [x] Validate file type and size — `knowledge_service.extract_text()`
  - [x] Assign category (products / offers / documents / broadcasts)
  - [x] For Offers: require valid_from and valid_until dates
  - [x] Extract text: PDF → PyMuPDF; Image → pytesseract; Text → direct read — `knowledge_service.extract_text()`
  - [x] Chunk text into semantic segments (~512 tokens with overlap) — `knowledge_service.chunk_text()`
  - [x] Generate embeddings via Gemini `models/embedding-001` — `knowledge_service.get_embeddings_model()`
  - [x] Store vectors in tenant-specific ChromaDB collection — `knowledge_service.get_chroma_collection()`
  - [x] Save record to `knowledge_base` PostgreSQL table (with chroma_ids array) — `knowledge_service.ingest_document()`
  - [x] Return processing status: indexed
- [x] `GET /knowledge-base` — list all indexed documents for tenant — `routes/knowledge_base.py`
- [x] `DELETE /knowledge-base/{id}` — delete from Chroma + mark inactive in DB — `routes/knowledge_base.py`
- [x] Celery Beat job: daily `deactivate_expired_offers` — already implemented in `tasks/broadcast_tasks.py`

### 3.2 LangGraph Client Assistant Bot

- [x] Build LangGraph RAG agent with nodes — `services/rag_bot.py`
  - [x] **Sanitiser**: strip HTML tags, script tags, excessive special characters — `sanitise_node`
  - [x] **Rate Limit Check**: max 20 messages/client/hour via Redis — `rate_limit_node`
  - [x] **Language Detection**: detect English or Hindi (Unicode ratio) — `detect_language_node`
  - [x] **Prompt Injection Guard**: keyword blocklist check — `injection_guard_node`
  - [x] **Embedding**: embed query via `models/gemini-embedding-001` — `embed_node`
  - [x] **Retrieval**: ChromaDB top-5, filter is_active=true and tenant_id — `retrieve_node`
  - [x] **Context Check**: if no results or distance > 0.7 → Fallback — `context_check_node`
  - [x] **Response Generation**: Gemini LLM with context-only system prompt — `generate_node`
  - [x] **Confidence Check**: score = 1 - min_distance/2; flag if < 0.75 — `confidence_check_node`
  - [x] **Fallback**: polite "contact the business directly" in English/Hindi — `fallback_node`
  - [x] **Output**: send reply via Gupshup; store in `conversations` table — `output_node`
- [x] Log all conversations (confidence_score, flagged, language, direction) — `output_node`
- [x] Entrypoint `run_bot()` callable from Phase 3.3 inbound webhook

### 3.3 Inbound Webhook Handler

> **Architecture Decision:** Use **async FastAPI handler** (not Celery) for bot responses.
> Celery adds queue latency (100ms–1s+); conversational bot responses must feel near-instant.
> Celery is reserved for broadcast sending only (high-volume, latency-tolerant).

- [x] `POST /webhooks/whatsapp/{tenant_id}` — inbound Gupshup message webhook — `routes/webhooks.py`
  - [x] Verify HMAC signature via `GupshupAdapter.verify_webhook_signature()`
  - [x] Parse sender phone, message text, event type (skip non-message events)
  - [x] Look up client by (phone, tenant_id) from `clients` table
  - [x] `await run_bot()` directly in async FastAPI route (no Celery)
  - [x] Return 200 OK — always, to prevent Gupshup retries

---

## 📊 PHASE 4 — Operator Dashboard (Frontend)

> Last updated: 2026-03-08 | UI replication complete — all pages match the reference design exactly.

### 4.1 Design System & UI Component Library

- [x] Set up React + Vite project
- [x] Install and configure Tailwind CSS + shadcn/ui
- [x] Apply **light mode** SaaS theme (pivoted from dark — matches reference design)
- [x] Define CSS custom properties for all color tokens — `frontend/src/index.css`
  - [x] White cards with `border-gray-100`, `bg-gray-50/60` app background
  - [x] Emerald-500 accent, gray-900 headings, gray-400 subtext
  - [x] 12px card border-radius, compact button sizes
- [x] Install Google Font: Inter — loaded via `index.css`
- [x] **Shared components built:**
  - [x] **KPI Stat Card** — icon badge, value, sub-label, trend indicator (used in all pages)
  - [x] **Status Badge** — Active/Hidden/Indexed/Processing/Expired/Archived (clickable toggle)
  - [x] **Toggle Switch** — opted-in toggle (Clients page)
  - [x] **Filter Dropdown** — category/tag filter with check marks (Clients, Products, KB)
  - [x] **Filter Tab Bar** — All/Active/Expired/Archived tab row (Offers page)
  - [x] **Modal / Confirm Dialog** — add/edit/delete/archive modals (all pages)
  - [x] **File Upload Zone** — dashed border, drag-and-drop (Products, Offers, KB)
  - [x] **Upload Progress Toast** — animated bar, % count (Knowledge Base)
  - [x] **Chat Bubble** — client/bot/owner variants with timestamps (Conversations)
  - [x] **Offer Card** — top-accent bar, countdown pill, status badge (Offers)
  - [x] **Progress Bar** — delivery/read/reply metrics (Dashboard right panel)
- [x] Base 3-zone layout: fixed `w-56` white sidebar + sticky top bar (h-16) + scrollable main — `AppShell.jsx`

### 4.2 Onboarding Wizard (8 Steps)

- [ ] Full-screen modal overlay; no sidebar visible during wizard
- [ ] Step 1: Business name, logo upload, default language selection
- [ ] Step 2: Upload client list (CSV/Excel) — column mapping preview
- [ ] Step 3: Opt-in bulk confirmation — mandatory, **cannot be skipped**
- [ ] Step 4: Upload first document — confirm Indexed status badge
- [ ] Step 5: Send test broadcast to owner's own number
- [ ] Step 6: Test the bot — owner sends WhatsApp message, reviews bot response
- [ ] Step 7: Review flagged messages — teach owner resolution workflow
- [ ] Step 8: Go-live broadcast to 10–20 clients — mandatory, **cannot be skipped**
- [ ] Completion: confetti animation + redirect to Dashboard

### 4.3 Dashboard Overview Screen

- [x] Sticky inline top bar — greeting, date, "New Broadcast" button — `Dashboard.jsx`
- [x] WhatsApp quality alert banner (dismissible) — amber style
- [x] 4 KPI stat cards — Total Clients, Active Offers, Last Broadcast, Bot Resolution Rate
  - [x] Icons: blue/violet/emerald/amber bg badges, `w-9 h-9 rounded-lg`
  - [x] `text-3xl font-semibold`, trend icons (TrendingUp / TrendingDown)
  - [x] Bot resolution card has emerald progress bar (`h-1.5`)
- [x] Recent Broadcasts table — 2-col layout (`col-span-2`)
  - [x] Columns: Broadcast Name, Date Sent, Sent (icon), Delivered (%), Read (%), Replied
  - [x] Latest row highlighted `bg-emerald-50/30` with "Latest" badge
- [x] Right panel: "Last Broadcast Results" — 3 progress bars (Delivered/Read/Replied, `h-2`)
- [x] Right panel: "Quick Actions" — 4 linked items with colored icon blocks (`space-y-2` ✅ matches reference)
- [x] Dimensions verified 100% match with reference `Dashboard.tsx`

### 4.4 Broadcasts Screen

- [x] Broadcasts list page with table — `Broadcasts.jsx`
- [x] "New Broadcast" button → opens broadcast composer — `BroadcastComposer` (full right-side panel)
- [x] Broadcast Detail page (`/broadcasts/:id`) — `BroadcastDetail.jsx`
  - [x] Header with broadcast name, status badge, timestamp
  - [x] 4 KPI cards: Sent, Delivered, Read, Replied
  - [x] Per-client delivery table with status badges
  - [ ] SSE real-time delivery update subscription on mount (Phase 2.3 backend ready)
  - [ ] Fallback polling every 10s if SSE drops

### 4.5 Clients Screen

- [x] Clients table with avatar initials, VIP/New tag badges, language badges — `Clients.jsx`
- [x] Search bar + tag filter dropdown (All / VIP / New)
- [x] Opted-in toggle switch (live `PATCH /clients/{id}` API call)
- [x] Pagination (10 rows/page, page number buttons)
- [x] "Upload CSV / Excel" button — calls `POST /clients/upload` API
- [x] "Add New Client" modal — name, phone, email, language, opted-in
- [x] Edit client modal (pre-filled)
- [x] Delete client confirmation modal
- [x] 3 stat cards: Total, Receiving Messages, Not Receiving

### 4.6 Knowledge Base Screen

- [x] Document table with file-type icons (PDF/XLSX/DOCX), category badges — `KnowledgeBase.jsx`
- [x] "Upload Document" button — local file picker (PDF, XLSX, DOCX)
- [x] Animated upload progress toast (0→100% bar)
- [x] Auto-detects category from filename (Offers/Products/Invoices/Broadcasts)
- [x] Status badges: "Ready to use" (emerald) / "Reading document…" (amber spinner)
  - [x] Auto-transitions from processing → indexed after ~3.5s
- [x] Category filter dropdown (All / Products / Offers / Broadcasts / Invoices)
- [x] Search by filename
- [x] Delete confirmation modal (disabled while processing)
- [x] 4 stat cards: Total / Ready / Being Read / Categories
- [x] "How this works" info banner

### 4.7 Conversations Screen

- [x] Split-panel layout: conversation list (left, `w-72`) + chat window (right) — `Conversations.jsx`
- [x] Conversation list:
  - [x] Search bar
  - [x] Filter tabs: All / Unread / Flagged
  - [x] Colored avatar initials, green online dot, unread count badge
  - [x] Flag icon for flagged conversations
  - [x] Emerald left-border indicator for selected conversation
- [x] Chat window:
  - [x] Header: avatar, name, phone, flag badge, AI Active badge, Phone/More buttons
  - [x] "Mark as Resolved" button → "Resolved" state + success banner
  - [x] Message bubbles: client (white/red-flagged), bot (emerald), owner (gray-900)
  - [x] Bot messages show "AI Reply" label + Bot icon
  - [x] Timestamps + double-check delivery icons
  - [x] Manual reply notice (amber dot)
  - [x] Textarea input with Paperclip/Emoji/Send buttons
  - [x] Enter to send / Shift+Enter for new line

### 4.8 Analytics Screen

- [x] Sticky top bar with "Last updated" timestamp — `Analytics.jsx`
- [x] Dismissible WhatsApp quality warning banner (amber)
- [x] 4 KPI stat cards — Delivery Rate, Read Rate, Reply Rate, Bot Resolution
  - [x] Trend indicators (TrendingUp/TrendingDown), colored mini bar underneath
- [x] Broadcast Performance bar chart (Recharts) — Sent/Opened/Replied per broadcast
- [x] "Top Questions This Week" panel — ranked list with weekly change indicators
- [x] "Offers with Highest Engagement" — 4-column grid with open-rate bars, rank badges

### 4.9 Settings Screen

- [x] Sticky top bar — `Settings.jsx`
- [x] Business Information section — name, contact phone, language picker, logo upload/preview
- [x] WhatsApp Configuration — connected number, connection status badge, reconnect button
- [x] WhatsApp Quality Rating pill — color-coded Good/Fair/Poor with advisory text
- [x] Notification Preferences — 3 toggle switches (broadcast fail, bot stuck, daily summary)
- [x] Account section — Change Password modal, Log Out (wired to AuthContext), Delete Account modal
- [x] Save toast notification (bottom-center, auto-dismiss)

### 4.10 Products Screen ✨ NEW

- [x] Sticky top bar with "Add Product" button — `Products.jsx`
- [x] 3 KPI stat cards: Total / Visible to Customers / Hidden
- [x] Product table with ShoppingBag icon placeholder, category color badges, price (GHS format)
- [x] Clickable Status badge — toggles Active ↔ Hidden inline (no reload)
- [x] Category filter dropdown (All / Sneakers / Sandals / Formal / Heels / Boots / Kids / Accessories)
- [x] Search by name, description, or category
- [x] Add / Edit product modal — name, description, price (GHS), category picker, visibility toggle, file upload
- [x] Delete confirmation modal
- [x] Hidden rows shown at 60% opacity
- [x] Sidebar: "Products" entry with ShoppingBag icon (between Conversations and Offers)

### 4.11 Offers Screen ✨ NEW

- [x] Sticky top bar with "Create Offer" button — `Offers.jsx`
- [x] 3 KPI stat cards: Active Offers / Upcoming / Total Created
- [x] Filter tab bar: All Offers / Active / Expired / Archived (with counts)
- [x] Offer cards in 3-column grid:
  - [x] Colored top-accent bar (emerald=active, blue=upcoming, gray=expired/archived)
  - [x] Animated "Active" pulse badge / "Upcoming" / "Expired" / "Archived" status chips
  - [x] Date range with calendar icon
  - [x] Days-remaining pill: green (>7d) → amber (≤7d) → red (≤3d) → "Ends today"
  - [x] Edit and Archive action buttons
  - [x] Expired/archived cards shown at 60% opacity
- [x] Create / Edit offer modal — title, description, valid-from/until date pickers, file upload
- [x] Archive confirmation modal
- [x] Auto-computes status from today's date (no manual status needed)
- [x] Sidebar: "Offers" entry with Percent icon (between Products and Knowledge Base)

---

### 🗺️ Sidebar Navigation Order (Current)

1. Dashboard
2. Clients
3. Broadcasts
4. Conversations
5. Products
6. Offers
7. Knowledge Base
8. Analytics
9. Settings

---

## 🔒 PHASE 5 — Security, Compliance & Testing

### 5.1 WhatsApp Compliance

- [ ] Enforce opt-in: never send broadcasts to clients with opted_in=false (Celery task level)
- [ ] Process opt-out: detect STOP / UNSUBSCRIBE / NO replies → set opted_in=false within 30 seconds
- [ ] Enforce template-only outbound messaging for clients who haven't messaged first
- [ ] Enforce frequency cap: max 1 broadcast per client per 24-hour period
- [ ] Enforce send window: 9am–7pm local timezone (default)

### 5.2 Bot Safety & Abuse Protection

- [ ] Rate limiting: max 20 inbound messages per client per hour; excess silently dropped + logged
- [ ] Input sanitisation: strip HTML, script tags, excessive special characters before LLM processing
- [ ] Prompt injection guard: system prompt restricts LLM to product/offer/order scope only
- [ ] Out-of-scope deflection: polite redirect response to client
- [ ] Confidence-based escalation: flag responses below 0.75 for owner review

### 5.3 Multi-Tenancy Isolation

- [ ] All DB queries must include `WHERE tenant_id = :tenant_id` — never return cross-tenant data
- [ ] ChromaDB: each tenant has isolated collection (`tenant_{id}`)
- [ ] JWT embeds tenant_id — middleware injects it into every request context
- [ ] File uploads scoped to tenant storage path
- [ ] Write integration tests verifying cross-tenant data isolation

### 5.4 Penetration Testing (PM.16 Risk Register Requirement)

- [ ] Schedule penetration test before public launch (Phase 1 go-live or Phase 2)
- [ ] Test areas: JWT token forgery / tenant_id manipulation in requests
- [ ] Test areas: ChromaDB tenant isolation bypass attempts
- [ ] Test areas: webhook endpoint abuse (unsigned requests)
- [ ] Test areas: prompt injection attacks on bot endpoint
- [ ] Test areas: file upload path traversal
- [ ] Remediate all critical/high findings before go-live

---

## 📈 PHASE 6 — Monitoring & Reliability

### 6.1 Monitoring Setup

- [ ] Integrate Sentry (error tracking for FastAPI and Celery workers)
- [ ] Set up UptimeRobot (uptime monitoring, 1-minute checks, owner alerts)
- [ ] Set up Prometheus + Grafana (CPU, memory, disk, queue depth)
- [ ] Configure structured JSON logging across all services

### 6.2 Scale Trigger Definitions

- [ ] CPU > 70% sustained → plan vertical scale to CX31
- [ ] Redis queue depth > 5,000 → add Celery worker
- [ ] ChromaDB query latency > 500ms → optimise or dedicated instance
- [ ] Gupshup error rate > 5% → pause broadcasts + alert owner
- [ ] Document runbook for each scale trigger

### 6.3 WhatsApp Quality Rating Safeguards (PM.12)

- [ ] Monitor Meta quality rating daily
- [ ] Alert owner when rating drops to Yellow
- [ ] Auto-pause broadcasts when rating drops to Red
- [ ] Track block rate per broadcast; pause if > 2% of recipients block

---

## 🧪 PHASE 7 — Testing & Go-Live

### 7.1 Backend Testing

- [ ] Unit tests: Celery broadcast task (mock Gupshup API)
- [ ] Unit tests: LangGraph bot nodes (mock ChromaDB, mock LLM)
- [ ] Unit tests: webhook HMAC signature verification
- [ ] Integration tests: full broadcast flow (create → dispatch → delivery update → SSE event)
- [ ] Integration tests: full RAG flow (inbound message → retrieval → response → stored conversation)
- [ ] Integration tests: opt-out flow (STOP message → opted_in=false within 30s)
- [ ] Integration tests: cross-tenant isolation (verify tenant A cannot access tenant B data)
- [ ] Load test: 500 clients, single broadcast — completes within acceptable time

### 7.2 Frontend Testing

- [ ] Test onboarding wizard all 8 steps (steps 3 and 8 cannot be skipped)
- [ ] Test CSV upload: valid file, duplicate phones, missing columns
- [ ] Test broadcast creation + real-time personalisation preview
- [ ] Test SSE real-time delivery updates on Broadcast Detail page
- [ ] Test knowledge base upload for all file types (PDF, image, text)
- [ ] Test offer expiry: upload offer with past valid_until → verify bot does not retrieve it
- [ ] Test flagged message resolution flow
- [ ] Test dark theme on Chrome, Firefox, Edge

### 7.3 End-to-End Go-Live Checklist

- [ ] WhatsApp number verified and all 5 templates approved in both languages
- [ ] **Backup/reserve WhatsApp number registered** (PM.12 requirement)
- [ ] Owner completes full 8-step onboarding wizard
- [ ] Test broadcast sent to owner's own number — personalisation confirmed on real WhatsApp
- [ ] Test bot query sent by owner — correct retrieval-only response confirmed
- [ ] Verify bot does NOT respond to out-of-scope questions (prompt injection guard active)
- [ ] Monitoring dashboards live (Sentry + UptimeRobot active and alerting)
- [ ] First real broadcast to 10–20 clients executed
- [ ] Delivery report reviewed; SSE real-time updates confirmed working
- [ ] Bot resolution rate confirmed > 85% on test query set
- [ ] Penetration test completed and critical findings remediated

---

## 🚀 PHASE 8 — Future Roadmap (Post Phase 1)

### Phase 2 (Month 2–3)

- [ ] SMS broadcast channel via Fast2SMS
- [ ] Telegram bot channel
- [ ] Proactive follow-up automation agent
- [ ] Onboard second paying customer (multi-tenant live)
- [ ] Conversation quality report (weekly PM summary)

### Year 2 — Revenue Engine

- [ ] In-chat order capture via WhatsApp (Razorpay integration) — `orders` table already in schema
- [ ] AI product advisor with personalised recommendations
- [ ] Automated abandoned cart follow-up
- [ ] Loyalty programme via chat

### Year 3 — Retail AI Platform

- [ ] Multi-location / multi-owner management
- [ ] Inventory-aware bot (real-time stock awareness)
- [ ] Voice bot for phone calls
- [ ] Marketplace model — agency partners onboard retail clients
- [ ] Open API for third-party CRM integration

---

_Sources: Design_Document_CCA.docx · PRD_Client_Communication_Agent.docx · Phase1_Research_Document.docx · twin AI.docx_
