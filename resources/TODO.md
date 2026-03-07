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

- [ ] Build LangGraph RAG agent with nodes:
  - [ ] **Input**: receive inbound WhatsApp message
  - [ ] **Sanitiser**: strip HTML tags, script tags, excessive special characters
  - [ ] **Rate Limit Check**: max 20 messages/client/hour; if exceeded, drop + log → Done
  - [ ] **Language Detection**: detect English or Hindi
  - [ ] **Prompt Injection Guard**: reject out-of-scope queries with configured system prompt
  - [ ] **Embedding**: embed query via `text-embedding-3-small`
  - [ ] **Retrieval**: ChromaDB top-k, filter is_active=true and tenant_id
  - [ ] **Context Check**: if no results → Fallback Node
  - [ ] **Response Generation**: LLM with retrieved context only (retrieval-only prompt)
  - [ ] **Confidence Check**: if score < 0.75 → flag conversation in DB
  - [ ] **Fallback**: polite "contact the business directly" response
  - [ ] **Output**: send reply via Gupshup; store in `conversations` table
- [ ] Log all conversations (confidence_score, flagged, language, direction)

### 3.3 Inbound Webhook Handler

> **Architecture Decision:** Use **async FastAPI handler** (not Celery) for bot responses.
> Celery adds queue latency (100ms–1s+); conversational bot responses must feel near-instant.
> Celery is reserved for broadcast sending only (high-volume, latency-tolerant).

- [ ] `POST /webhooks/whatsapp` — inbound Gupshup message webhook
  - [ ] Verify HMAC signature
  - [ ] Parse sender phone, message text, timestamp
  - [ ] Look up client by (phone, tenant_id)
  - [ ] `await` LangGraph bot handler directly in async FastAPI route
  - [ ] Return 200 OK after response is sent to client (target < 3 seconds end-to-end)

---

## 📊 PHASE 4 — Operator Dashboard (Frontend)

### 4.1 Design System & UI Component Library (Build First — All Screens Depend on These)

- [ ] Set up React + Vite project (or Next.js)
- [ ] Install and configure Tailwind CSS + shadcn/ui
- [ ] Apply dark theme globally (`dark` class on `<html>`)
- [ ] Define CSS custom properties for all color tokens:
  - [ ] Background `#0A0A0F`, Surface `#12121A`, Surface-Alt `#1A1A26`
  - [ ] Accent `#6366F1`, Accent-Hover `#4F46E5`
  - [ ] Text-Primary, Text-Secondary, Border, Status colors (green/yellow/red)
- [ ] Install Google Font: Inter
- [ ] **Build shared components (prerequisite for all screens below):**
  - [ ] **KPI Metric Card** — icon, value, label, trend indicator; used in 4.3
  - [ ] **Status Badge** — Sent / Delivered / Read / Failed / Indexed / Active / Expired; used in 4.4, 4.6, 4.7
  - [ ] **Primary / Secondary / Ghost / Destructive Button** — used everywhere
  - [ ] **Data Table** — sort, pagination (10/25/50 rows), empty state, loading skeleton, alternating rows; used in 4.4, 4.5
  - [ ] **Toast Notification** — bottom-right, 360px, auto-dismiss 5s, manual X; used everywhere
  - [ ] **WhatsApp Quality Rating Widget** — Green/Yellow/Red dot + label; used in sidebar footer + 4.3
  - [ ] **File Upload Zone** — drag-and-drop + click, file type validation; used in 4.5, 4.6
  - [ ] **Side Sheet / Drawer** — 480px right-side, overlay; used in 4.4, 4.6
  - [ ] **Modal** — centered, backdrop blur; used in 4.5
  - [ ] **Progress Stepper** — 8-step indicator; used in 4.2
  - [ ] **Chat Bubble** — inbound/outbound, timestamp, status; used in 4.7
  - [ ] **Confidence Score Badge** — numerical, green >0.9 / yellow 0.75–0.9 / red <0.75; used in 4.7
- [ ] Build base 3-zone layout: fixed left sidebar + top header (64px) + fluid main workspace

### 4.2 Onboarding Wizard (8 Steps)

- [ ] Full-screen modal overlay; no sidebar visible during wizard
- [ ] Use **Progress Stepper** component (from 4.1)
- [ ] Step 1: Business name, logo upload, default language selection
- [ ] Step 2: Upload client list (CSV/Excel) — use **File Upload Zone** + column mapping preview
- [ ] Step 3: Opt-in bulk confirmation — mandatory, **cannot be skipped**
- [ ] Step 4: Upload first document (product PDF or offer) — confirm Indexed status badge
- [ ] Step 5: Send test broadcast to owner's own number
- [ ] Step 6: Test the bot — owner sends WhatsApp message, reviews bot response
- [ ] Step 7: Review flagged messages — teach owner resolution workflow
- [ ] Step 8: Go-live broadcast to 10–20 clients — mandatory, **cannot be skipped**
- [ ] Completion: confetti animation + redirect to Dashboard

### 4.3 Dashboard Overview Screen

- [ ] KPI cards row — use **KPI Metric Card** component (4.1):
  - [ ] Total Clients (opted-in count)
  - [ ] Broadcasts Sent (this month)
  - [ ] Delivery Rate (%)
  - [ ] Bot Resolution Rate (%)
  - [ ] Active Offers
  - [ ] Flagged Messages (unresolved count — click to go to Conversations)
- [ ] Recent Broadcasts table (last 5) — use **Data Table** + **Status Badge**
- [ ] **WhatsApp Quality Rating Widget** in sidebar footer (always visible)

### 4.4 Broadcasts Screen

- [ ] Broadcast list — use **Data Table** + **Status Badge** components (4.1)
- [ ] "New Broadcast" button → opens **Side Sheet** (480px right-side):
  - [ ] Broadcast name field
  - [ ] Message editor (with {{variable}} support)
  - [ ] Language selector
  - [ ] Schedule date/time picker
  - [ ] Real-time personalisation preview for a sample client
  - [ ] "Send Now" / "Schedule" buttons
- [ ] Broadcast Detail page (`/broadcasts/{id}`):
  - [ ] Header: name, channel, timestamp, **Status Badge**
  - [ ] 4 **KPI Metric Cards**: Sent, Delivered, Read, Failed (count + %)
  - [ ] Delivery timeline chart
  - [ ] Per-client delivery table — **Data Table** + **Status Badge**
  - [ ] **SSE real-time update** — subscribe to `/broadcasts/{id}/stream` on mount (see Phase 2.3)
  - [ ] Export CSV button

### 4.5 Clients Screen

- [ ] Clients table — use **Data Table** + **Status Badge** for opted-in status
- [ ] Search bar + filter by opted-in status
- [ ] "Upload CSV/Excel" button → **Modal**:
  - [ ] **File Upload Zone** (accepts .csv, .xlsx)
  - [ ] Column mapping preview (auto-detect; manual remap if needed)
  - [ ] Validation summary (valid count, skipped duplicates)
  - [ ] Opt-in confirmation checkbox
  - [ ] Import progress bar → success **Toast**
- [ ] Edit / delete individual client

### 4.6 Knowledge Base Screen

- [ ] Document grid (card per document) — use **Status Badge** (Indexed / Processing / Failed)
- [ ] "Upload Document" button → **Side Sheet**:
  - [ ] **File Upload Zone** (PDF, image, text)
  - [ ] Category selector: Products / Offers / Documents
  - [ ] For Offers: valid_from and valid_until date pickers
  - [ ] Processing status indicator: Uploading → Parsing → Embedding → Indexed
- [ ] Delete document → success **Toast**

### 4.7 Conversations Screen (Flagged Inbox)

- [ ] Inbound messages list — **Confidence Score Badge** + **Status Badge** (resolved/unresolved)
- [ ] Filter: All / Flagged Only / Unresolved
- [ ] Conversation thread panel — **Chat Bubble** components (inbound/outbound)
- [ ] "Mark as Resolved" button per flagged conversation
- [ ] Alert banner if same question type flagged 3+ times in a week (prompt to upload document)

### 4.8 Analytics Screen

- [ ] Delivery Rate trend (line chart, last 30 days)
- [ ] Read Rate trend chart
- [ ] Reply Rate chart
- [ ] Bot Resolution Rate chart
- [ ] Escalation Rate chart
- [ ] Multi-broadcast comparison table

### 4.9 Settings Screen

- [ ] Business profile: name, logo, default language
- [ ] WhatsApp API settings: provider, API key, sender phone, webhook URL
- [ ] Notification preferences: email alerts for flagged messages
- [ ] Send window override (default 9am–7pm)
- [ ] Broadcast frequency cap settings
- [ ] Danger zone: reset knowledge base, delete all clients

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
