# 💼 Twin AI (Devraj Traders) — Estimated Monthly Cost Report

### Prepared for: Client Proposal | Scale: 1,000 Clients per Owner

> **Document Date:** April 2026
> **Prepared By:** Rakesh (Development Team)
> **Scope:** All infrastructure and third-party service costs required to run the Twin AI WhatsApp automation system for one business owner with **1,000 active clients**.

---

## 📋 Executive Summary

Twin AI is a production-grade WhatsApp AI automation platform built on a modern, cloud-native stack. It consists of multiple integrated services — each with its own cost profile. The table below summarises the **total estimated monthly operating cost** across three deployment tiers.

| Tier              | Description                                     | Monthly Cost (USD) | Monthly Cost (INR) |
| ----------------- | ----------------------------------------------- | ------------------ | ------------------ |
| 🟢**Budget**      | Gemini free tier + 1 broadcast                  | ~$19 / mo          | ~₹1,560 / mo       |
| 🔵**Recommended** | Gemini 2.5 Flash + 2 broadcasts                 | ~$48 / mo          | ~₹3,955 / mo       |
| 🔴**Enterprise**  | Gemini 3.1 Pro + 4 broadcasts + full monitoring | ~$226 / mo         | ~₹18,795 / mo      |

> **Note:** WhatsApp messaging costs (Meta Cloud API) are **usage-based** and scale directly with the number of broadcast messages sent per month. By bypassing BSPs, there are no fixed WhatsApp platform fees.

---

## 📊 Detailed Cost Breakdown

### 1. 🖥️ Server / Hosting (VPS)

The entire platform (API, Worker, Scheduler, PostgreSQL, Redis, ChromaDB) runs inside Docker containers on a Linux VPS.

| Component | Requirement                         |
| --------- | ----------------------------------- |
| CPU       | Minimum 2 vCPU (4 vCPU recommended) |
| RAM       | Minimum 4 GB (8 GB recommended)     |
| Storage   | 80 GB SSD                           |
| OS        | Ubuntu 22.04 LTS                    |

| Provider                           | Plan                                      | Monthly Cost            |
| ---------------------------------- | ----------------------------------------- | ----------------------- |
| **Hetzner Cloud** (Budget pick)    | CX22 — 2 vCPU / 4 GB RAM / 40 GB NVMe     | **~$5 / mo (≈₹420)**    |
| **Hetzner Cloud** (Recommended)    | CPX22 — 3 vCPU / 4 GB RAM / 80 GB NVMe    | **~$9 / mo (≈₹750)**    |
| **DigitalOcean** (Reliable option) | Basic Droplet — 2 vCPU / 4 GB RAM / 80 GB | **~$24 / mo (≈₹2,000)** |

> ✅ **Recommended:** Hetzner CPX22 at ~$9/month offers excellent value with NVMe SSD and 20 TB bandwidth included.

---

### 2. 🤖 AI / LLM Costs — Google Gemini API

Twin AI uses **Google Gemini API** (`LLM_PROVIDER=gemini`) for all AI inference:

- **LLM:** `models/gemini-2.5-flash` — for RAG bot responses and message personalisation
- **Embeddings:** `models/gemini-embedding-001` — for knowledge base indexing and retrieval
- **Multimodal:** `models/gemini-2.5-flash` — for image/document understanding

#### Google Gemini API Pricing (April 2026)

| Model                     | Input (per 1M tokens) | Output (per 1M tokens) |                             |     |
| ------------------------- | --------------------- | ---------------------- | --------------------------- | --- | --- |
| **Gemini 2.5 Flash-Lite** | $0.10                 | $0.40                  | High-volume, cost-sensitive |     |     |
| **Gemini 2.5 Flash** ⭐   | $0.30                 | $2.50                  | Recommended — best balance  |     |     |
| **Gemini 2.5 Pro**        | $1.25                 | $10.00                 | Complex reasoning tasks     |     |     |
| **Gemini 3 Flash**        | $0.50                 | $3.00                  | Latest generation           |     |     |
| **Gemini 3.1 Pro**        | $2.00                 | $12.00                 | Enterprise / premium tasks  |     |     |

> ✅ **Free Tier:** Google AI Studio provides a **free tier with rate limits** for development and testing — ideal for getting started at $0 cost.

#### Estimated AI Token Usage (1,000 Clients/Month)

| Activity                                         | Estimated Volume   | Input Tokens    | Output Tokens    |
| ------------------------------------------------ | ------------------ | --------------- | ---------------- |
| Client RAG queries (avg 5 msgs/client/month)     | 5,000 queries      | ~3.5M           | ~1.5M            |
| AI-personalised broadcast messages (2 campaigns) | 2,000 messages     | ~1.2M           | ~0.8M            |
| Embedding knowledge base chunks                  | One-time + updates | ~500K           | —                |
| **Total per month**                              |                    | **~5.2M input** | **~2.3M output** |

#### Monthly AI Cost Calculation — Gemini 2.5 Flash (Recommended)

| Token Type                        | Volume | Rate       | Cost                    |
| --------------------------------- | ------ | ---------- | ----------------------- | --- |
| Input tokens                      | 5.2M   | $0.30 / 1M | $1.56                   |     |
| Output tokens                     | 2.3M   | $2.50 / 1M | $5.75                   |     |
| Embeddings (gemini-embedding-001) | ~500K  | $0.15 / 1M | ~$0.08                  |     |
| **Monthly AI Total**              |        |            | **~$7.50 / mo (≈₹625)** |

> 💡 **Gemini is extremely cost-efficient for this scale.** At 1,000 clients, the AI cost is only ~$7–10/month using Gemini 2.5 Flash.

#### AI Provider Comparison

| Provider                            | Model            | Est. Monthly Cost (1,000 clients) |
| ----------------------------------- | ---------------- | --------------------------------- |
| **Google Gemini** (Free tier)       | Gemini 2.5 Flash | **$0** (rate-limited dev)         |
| **Google Gemini 2.5 Flash-Lite** ⭐ | Most economical  | **~$4 / mo (≈₹330)**              |
| **Google Gemini 2.5 Flash** ⭐      | Recommended      | **~$8–10 / mo (≈₹665–830)**       |
| **Google Gemini 2.5 Pro**           | Premium quality  | **~$25–35 / mo (≈₹2,075–2,900)**  |
| **Google Gemini 3.1 Pro**           | Highest quality  | **~$50–75 / mo (≈₹4,150–6,225)**  |

---

### 3. 📱 WhatsApp Messaging Costs

By using the **Meta Cloud API directly**, there are **no fixed platform or BSP fees**. You only pay Meta's official per-message infrastructure fees.

#### 3A. Meta WhatsApp Fees (India, per message — 2026 rates)

| Message Category | Cost per Message | Use Case in Twin AI                    |
| ---------------- | ---------------- | -------------------------------------- |
| **Marketing**    | ₹0.86 – ₹1.09    | ✅ Broadcast campaigns to clients      |
| **Utility**      | ₹0.11 – ₹0.15    | ✅ Order confirmations, system alerts  |
| **Service**      | ₹0.00 FREE       | ✅ RAG bot replies within 24-hr window |

> 🟢 **Free zone:** All RAG bot replies to client queries are **FREE** (Service category) as long as the business responds within 24 hours of the client's message.

#### 3B. Monthly WhatsApp Cost Estimate (1,000 Clients)

| Scenario                       | Messages Sent | Meta Cost |                    |
| ------------------------------ | ------------- | --------- | ------------------ |
| **Light** (1 broadcast/mo)     | ~1,200 msgs   | ₹1,140    | **≈₹1,140 (~$14)** |
| **Moderate** (2 broadcasts/mo) | ~2,500 msgs   | ₹2,375    | **≈₹2,375 (~$29)** |
| **Heavy** (4 broadcasts/mo)    | ~5,000 msgs   | ₹4,750    | **≈₹4,750 (~$57)** |

> 💡 **Calculation basis:**
>
> - 1 broadcast = 1,000 marketing messages × ₹0.95 avg = ₹950 Meta fees
> - RAG reply messages within 24 hr window = ₹0 (Service category)

---

### 4. 📧 Email Alerts — SendGrid / Brevo

Used for: Owner alert emails (error notifications, broadcast delivery reports).

| Plan                           | Monthly Emails           | Cost                    |
| ------------------------------ | ------------------------ | ----------------------- |
| **SendGrid 60-day Free Trial** | 100/day                  | **$0 (trial only)**     |
| **SendGrid Essentials (paid)** | Up to 50,000 emails/mo   | **$19.95/mo (≈₹1,660)** |
| **Brevo Free (Recommended)**   | 300 emails/day — forever | **$0**                  |

> ✅ **Recommendation:** Replace SendGrid with **Brevo** (formerly Sendinblue). The free tier supports 300 emails/day (9,000/month), which far exceeds the system's needs for owner alert emails at this scale.

---

### 5. 🔍 Error Monitoring — Sentry (Optional)

Used for: Real-time backend error tracking and alert notifications.

| Plan                 | Errors/Month      | Users     | Cost                 |
| -------------------- | ----------------- | --------- | -------------------- |
| **Developer (Free)** | 5,000 errors/mo   | 1 user    | **$0/mo**            |
| **Team Plan**        | 50,000 errors/mo  | Unlimited | **$26/mo (≈₹2,160)** |
| **Business Plan**    | High volume + SSO | Unlimited | **$80/mo (≈₹6,650)** |

> ✅ **For a single-owner system with 1,000 clients, the Sentry Free plan is sufficient.**

---

### 6. 🗄️ Database & Infrastructure (Self-Hosted in Docker)

All databases run on the same VPS — **zero additional licensing fees**.

| Component                     | Technology               | Monthly Cost    |
| ----------------------------- | ------------------------ | --------------- |
| Relational DB + Vector Search | PostgreSQL 15 + pgvector | Included in VPS |
| Message Broker + Cache        | Redis 7                  | Included in VPS |
| Vector Database (RAG)         | ChromaDB (self-hosted)   | Included in VPS |
| Task Queue                    | Celery Worker + Beat     | Included in VPS |

---

## 💰 Total Monthly Cost Summary

### 🟢 Option A — Budget Setup (Minimum Viable)

| Service                                      | Monthly Cost            |
| -------------------------------------------- | ----------------------- |
| VPS — Hetzner CX22 (2 vCPU / 4 GB)           | $5 (≈₹420)              |
| Google Gemini API (free tier / rate-limited) | $0                      |
| Meta WhatsApp (1 broadcast, Light)           | $14 (≈₹1,140)           |
| Email — Brevo Free                           | $0                      |
| Sentry — Developer Free                      | $0                      |
| **Total**                                    | **~$19 / mo (≈₹1,560)** |

---

### 🔵 Option B — Recommended Production Setup ⭐

| Service                                    | Monthly Cost            |
| ------------------------------------------ | ----------------------- |
| VPS — Hetzner CPX22 (3 vCPU / 4 GB)        | $9 (≈₹750)              |
| Google Gemini 2.5 Flash (LLM + Embeddings) | $10 (≈₹830)             |
| Meta WhatsApp (2 broadcasts, Moderate)     | $29 (≈₹2,375)           |
| Email — Brevo Free                         | $0                      |
| Sentry — Developer Free                    | $0                      |
| **Total**                                  | **~$48 / mo (≈₹3,955)** |

---

### 🔴 Option C — Enterprise / High-Availability Setup

| Service                             | Monthly Cost              |
| ----------------------------------- | ------------------------- |
| VPS — DigitalOcean (4 vCPU / 8 GB)  | $48 (≈₹4,000)             |
| Google Gemini 3.1 Pro (premium LLM) | $75 (≈₹6,225)             |
| Meta WhatsApp (4 broadcasts, Heavy) | $57 (≈₹4,750)             |
| SendGrid Essentials                 | $20 (≈₹1,660)             |
| Sentry Team Plan                    | $26 (≈₹2,160)             |
| **Total**                           | **~$226 / mo (≈₹18,795)** |

---

## 📈 Cost Scaling with Client Volume

> AI costs calculated using **Gemini 2.5 Flash** ($0.30/1M input, $2.50/1M output)

| # of Clients      | Gemini AI Cost | WhatsApp (2 broadcasts) |
| ----------------- | -------------- | ----------------------- | ------ | -------------- |
| 100 clients       | ~$1            | ~$3                     | $9     | **~$13 / mo**  |
| 500 clients       | ~$4            | ~$15                    | $9     | **~$28 / mo**  |
| **1,000 clients** | **~$10**       | **~$29**                | **$9** | **~$48 / mo**  |
| 5,000 clients     | ~$45           | ~$145                   | $24    | **~$214 / mo** |
| 10,000 clients    | ~$85           | ~$290                   | $48    | **~$423 / mo** |

---

## 🧾 One-Time Setup Costs

| Item                                      | Estimated Cost                      |
| ----------------------------------------- | ----------------------------------- |
| WhatsApp Business Account (Meta approval) | **Free** (approval takes 2–6 weeks) |
| Domain name (for webhooks/API public URL) | **~$10–15 / year**                  |
| SSL Certificate                           | **Free** (via Let's Encrypt)        |
| Developer integration (Meta Cloud API)    | One-time effort                     |
| Server setup & initial deployment         | One-time developer effort           |

---
