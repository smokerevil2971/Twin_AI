# Twin AI — Lessons Learned

> Updated after every correction. Purpose: prevent repeating the same mistakes.
> Location: `resources/lessons.md` (alongside TODO.md)

---

## 2026-03-02

### L1 — Use the existing TODO.md, don't create a parallel one

- **What happened:** Created `tasks/todo.md` as a separate tracker alongside `resources/TODO.md`
- **Rule:** The plan is the plan. Track progress directly in `resources/TODO.md` by marking `[ ]` → `[x]`. No duplicate todo files.

### L2 — Always inject tenant_id from JWT, never from request body

- **Pattern:** `core/security.py` — `get_tenant_id()` FastAPI dependency reads `tenant_id` from JWT claims attached via `request.state`
- **Rule:** No route handler accepts `tenant_id` as query param or body field. Only from JWT. Prevents tenant spoofing.

### L3 — Mock adapter from Day 1 for all external providers

- **Pattern:** Meta + Gupshup approval takes up to 6 weeks. `services/gupshup_adapter.py` has `MockGupshupAdapter` (logs calls, returns fake success)
- **Rule:** All external provider calls go through an injectable interface. Swap via `GUPSHUP_MODE=mock|real` in `.env`.

### L4 — orders table goes in first migration even if UI is Phase 2+

- **Pattern:** Schema debt is harder to fix than an empty table
- **Rule:** All planned tables go into `migrations/versions/001_initial_schema.py`. UI for orders is Phase 2, schema is Day 1.

---

## 2026-03-04

### L5 — Docker port conflict: "port is already allocated"

- **What happened:** Redis container failed to start because port `6379` was already bound by another process (local Redis service or another container)
- **Rule:** Before running `docker compose up`, check for port conflicts: `netstat -ano | findstr :6379`. Either stop the conflicting service (`net stop Redis`) or remap the host port in `docker-compose.yml` (e.g., `6380:6379`). Host port ≠ container port — internal service-to-service communication is unaffected.

### L6 — PowerShell does not support `&&` for command chaining — use `;` instead

- **What happened:** `docker rm -f twinai_chroma && docker volume rm ...` threw a parser error in PowerShell
- **Rule:** In PowerShell, always chain commands with `;` (runs next regardless of exit code) or use `if ($?) { next-command }` for conditional chaining. Never use `&&` or `||` — those are Bash/CMD syntax.

### L7 — `chromadb/chroma` image has no `curl` or `python` in PATH

- **What happened:** Healthcheck used `python -c "import urllib.request..."` — container reported unhealthy because `python` executable not found in `$PATH`
- **Rule:** Never assume CLI tools exist in third-party Docker images. For ChromaDB specifically: use `nc -z localhost 8000` (TCP port check via netcat) as the healthcheck. If uncertain about available tools, run `docker exec <container> which python curl nc` to verify first.

### L8 — Use `service_started` not `service_healthy` for dependencies that can't be health-checked

- **What happened:** `api` depended on `chromadb: condition: service_healthy` — this permanently blocked the API from starting because ChromaDB's healthcheck always failed
- **Rule:** If a dependency cannot reliably pass a healthcheck (third-party image, no suitable test command), set `condition: service_started`. Reserve `service_healthy` only for services with a proven, working healthcheck (postgres via `pg_isready`, redis via `redis-cli ping`).

### L9 — `passlib==1.7.4` is incompatible with `bcrypt>=4.0` — always pin bcrypt explicitly

- **What happened:** `passlib[bcrypt]==1.7.4` pulled in a newer bcrypt that removed the `__about__` attribute, causing a 500 on any password hash/verify call
- **Rule:** Always declare `bcrypt==4.0.1` separately alongside `passlib==1.7.4` in requirements. Do NOT use `passlib[bcrypt]` — it doesn't pin bcrypt and will pull the latest breaking version.

---

## 2026-03-07

### L10 — Gemini Embedding Model names changed from embedding-001 to text-embedding-004 to gemini-embedding-001

- **What happened:** Attempted to use `models/embedding-001` and `models/text-embedding-004`, both returned `404 not found` or `not supported for embedContent`.
- **Rule:** The only currently supported Gemini embedding model for `embedContent` is `models/gemini-embedding-001`. Always run `[m.name for m in genai.list_models() if 'embedContent' in m.supported_generation_methods]` to verify available models instead of guessing from stale documentation.
# Twin AI — Lessons Learned

> Updated after every correction. Purpose: prevent repeating the same mistakes.
> Location: `resources/lessons.md` (alongside TODO.md)

---

## 2026-03-02

### L1 — Use the existing TODO.md, don't create a parallel one

- **What happened:** Created `tasks/todo.md` as a separate tracker alongside `resources/TODO.md`
- **Rule:** The plan is the plan. Track progress directly in `resources/TODO.md` by marking `[ ]` → `[x]`. No duplicate todo files.

### L2 — Always inject tenant_id from JWT, never from request body

- **Pattern:** `core/security.py` — `get_tenant_id()` FastAPI dependency reads `tenant_id` from JWT claims attached via `request.state`
- **Rule:** No route handler accepts `tenant_id` as query param or body field. Only from JWT. Prevents tenant spoofing.

### L3 — Mock adapter from Day 1 for all external providers

- **Pattern:** Meta + Gupshup approval takes up to 6 weeks. `services/gupshup_adapter.py` has `MockGupshupAdapter` (logs calls, returns fake success)
- **Rule:** All external provider calls go through an injectable interface. Swap via `GUPSHUP_MODE=mock|real` in `.env`.

### L4 — orders table goes in first migration even if UI is Phase 2+

- **Pattern:** Schema debt is harder to fix than an empty table
- **Rule:** All planned tables go into `migrations/versions/001_initial_schema.py`. UI for orders is Phase 2, schema is Day 1.

---

## 2026-03-04

### L5 — Docker port conflict: "port is already allocated"

- **What happened:** Redis container failed to start because port `6379` was already bound by another process (local Redis service or another container)
- **Rule:** Before running `docker compose up`, check for port conflicts: `netstat -ano | findstr :6379`. Either stop the conflicting service (`net stop Redis`) or remap the host port in `docker-compose.yml` (e.g., `6380:6379`). Host port ≠ container port — internal service-to-service communication is unaffected.

### L6 — PowerShell does not support `&&` for command chaining — use `;` instead

- **What happened:** `docker rm -f twinai_chroma && docker volume rm ...` threw a parser error in PowerShell
- **Rule:** In PowerShell, always chain commands with `;` (runs next regardless of exit code) or use `if ($?) { next-command }` for conditional chaining. Never use `&&` or `||` — those are Bash/CMD syntax.

### L7 — `chromadb/chroma` image has no `curl` or `python` in PATH

- **What happened:** Healthcheck used `python -c "import urllib.request..."` — container reported unhealthy because `python` executable not found in `$PATH`
- **Rule:** Never assume CLI tools exist in third-party Docker images. For ChromaDB specifically: use `nc -z localhost 8000` (TCP port check via netcat) as the healthcheck. If uncertain about available tools, run `docker exec <container> which python curl nc` to verify first.

### L8 — Use `service_started` not `service_healthy` for dependencies that can't be health-checked

- **What happened:** `api` depended on `chromadb: condition: service_healthy` — this permanently blocked the API from starting because ChromaDB's healthcheck always failed
- **Rule:** If a dependency cannot reliably pass a healthcheck (third-party image, no suitable test command), set `condition: service_started`. Reserve `service_healthy` only for services with a proven, working healthcheck (postgres via `pg_isready`, redis via `redis-cli ping`).

### L9 — `passlib==1.7.4` is incompatible with `bcrypt>=4.0` — always pin bcrypt explicitly

- **What happened:** `passlib[bcrypt]==1.7.4` pulled in a newer bcrypt that removed the `__about__` attribute, causing a 500 on any password hash/verify call
- **Rule:** Always declare `bcrypt==4.0.1` separately alongside `passlib==1.7.4` in requirements. Do NOT use `passlib[bcrypt]` — it doesn't pin bcrypt and will pull the latest breaking version.

---

## 2026-03-07

### L10 — Gemini Embedding Model names changed from embedding-001 to text-embedding-004 to gemini-embedding-001

- **What happened:** Attempted to use `models/embedding-001` and `models/text-embedding-004`, both returned `404 not found` or `not supported for embedContent`.
- **Rule:** The only currently supported Gemini embedding model for `embedContent` is `models/gemini-embedding-001`. Always run `[m.name for m in genai.list_models() if 'embedContent' in m.supported_generation_methods]` to verify available models instead of guessing from stale documentation.

### L11 — ChromaDB Python Client must perfectly match Docker Image version

- **What happened:** API threw `ValueError: Could not connect to tenant default_tenant. Are you sure it exists?` during `get_or_create_collection`.
- **Rule:** ChromaDB introduced a breaking architecture change in `0.5.x` regarding tenants. If `requirements.txt` has `chromadb==0.4.24`, the `docker-compose.yml` MUST use `image: chromadb/chroma:0.4.24`. Never use `:latest` for stateful databases or vector stores.

### L12 — ChromaDB Telemetry Warning can be safely ignored

- **What happened:** Client output `Failed to send telemetry event ClientStartEvent: capture() takes 1 positional argument but 3 were given`.
- **Rule:** When `ANONYMIZED_TELEMETRY: "false"` is set in `docker-compose.yml` for ChromaDB 0.4.x, the Python client has a bug where it still attempts connection and fails formatting the abort message. This does not affect functionality and can be safely ignored.

### L13 — Gemini LLM model names must also be verified via list_models()

- **What happened:** `genai.GenerativeModel("gemini-1.5-flash")` returned `404 models/gemini-1.5-flash is not found for API version v1beta`.
- **Rule:** Like embedding models (L10), LLM model names are not stable across SDK versions. Always use `[m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]` to discover available models. The confirmed working model for `google-generativeai==0.5.4` is `models/gemini-2.0-flash`.

### L15 — Gemini free-tier has a daily RPD (requests per day) limit per model

- **What happened:** After testing the LLM call repeatedly during development, `ResourceExhausted: 429 You exceeded your current quota` was returned for `gemini-2.0-flash` and `gemini-2.0-flash-lite`.
- **Rule:** The Gemini free tier has daily request limits per model. During heavy development testing, rotate between models (flash vs flash-lite) or wait for daily reset (midnight Pacific). In `.env`, keep `LLM_MODEL=models/gemini-2.0-flash-lite` as the cheaper default. A successful embedding run + confidence score proves the pipeline is wired correctly even without an LLM response.

### L14 — Celery + asyncpg "Future attached to a different loop"

- **What happened:** Broadcast tasks were stuck in "pending" state. The `twinai_worker` logs showed `Future <Future pending cb=[Protocol._on_waiter_completed()]> attached to a different loop` inside `asyncpg`.
- **Rule:** Never reuse a global module-level SQLAlchemy `async_sessionmaker` or `create_async_engine` inside a Celery task when using `asyncio.run()`. Celery tasks create fresh event loops per execution. Sharing the global engine means the connection pool gets bound to the first task's event loop, crashing all subsequent tasks.
- **Fix:** Keep the global engine for FastAPI routes, but explicitly create a `get_async_sessionmaker()` helper in `database.py` that generates a new engine/sessionmaker on demand for Celery tasks.

### L16 — FastAPI async dependencies must be properly injected

- **What happened:** The `/dashboard/stats` route crashed with a 500 error: `object has no attribute 'bytes' for query argument $1: <coroutine object get_tenant_id at ...>`.
- **Rule:** A function declared as `async def get_tenant_id(...)` cannot be called synchronously like `tenant_id = get_tenant_id(request)` inside a route handler. It must rely on FastAPI's dependency injection system: `tenant_id: str = Depends(get_tenant_id)`.

### L17 — React Query `queryFn` extracting paginated response objects

- **What happened:** The frontend crashed with a black screen when rendering `DataTable` because `data.map` is not a function.
- **Rule:** APIs utilizing FastAPI-Pagination or custom pagination dictionaries return structures like `{"data": {"clients": [], "total": 0, "page": 1}}`. React Query's `queryFn` must extract the specific array (e.g., `r.data.data.clients`), not just the root `r.data.data`, otherwise the frontend component crashes when attempting to map over an object.
