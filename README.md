# Enterprise RAG Microservice

An end-to-end, tenant-scoped RAG API built with FastAPI, PostgreSQL/pgvector, and optional OpenAI embeddings and generation. The local providers let the full service run without cloud credentials; they are intended for development and demos, not production answer quality.

## Capabilities

- Upload and index TXT, Markdown, CSV, log, and text-based PDF files.
- Chunk documents, embed them, and retrieve similar chunks from pgvector.
- Ask grounded questions over retrieved context or stream answer tokens over SSE.
- Isolate documents by tenant and optionally bind API keys to individual tenants.
- Delete indexed documents, expose liveness/readiness checks, and publish Prometheus metrics.
- Run as a non-root container with PostgreSQL health checks and a persistent database volume.

## Run locally

Prerequisites: Docker Desktop with Compose enabled. Copy `.env.example` to `.env`, then run:

```powershell
Copy-Item .env.example .env
docker compose up --build
```

The API and interactive OpenAPI docs are at `http://localhost:8000` and `http://localhost:8000/docs`. With the default local providers, no API key is needed; use `X-Tenant-ID: demo` in API calls.
The public pipeline dashboard is at `http://localhost:8000`; its read-only API is under `/api/v1/observability`. Select a tenant, optionally enter its API key, then run the sample pipeline to watch actual upload, embedding, indexing, retrieval, and generation events appear. The event stream is live for requests handled by the current API process.

Ingest a document:

```powershell
curl.exe -X POST http://localhost:8000/api/v1/rag/documents `
  -H "X-Tenant-ID: demo" `
  -F "file=@sample_policy.txt"
```

Ask a question:

```powershell
curl.exe -X POST http://localhost:8000/api/v1/rag/query `
  -H "Content-Type: application/json" -H "X-Tenant-ID: demo" `
  -d '{"query":"What is the critical incident response SLA?","top_k":4}'
```

For real model calls, set `EMBEDDING_PROVIDER=openai`, `LLM_PROVIDER=openai`, and `OPENAI_API_KEY` in `.env`, then recreate the API container. Set `API_KEYS=demo=replace-with-a-long-random-secret` to require a tenant-bound key; include it as `X-API-Key`. In production, configure a unique secret for every tenant, terminate TLS at a trusted ingress, and use managed secret storage.

## API

- `POST /api/v1/rag/documents`: multipart upload; returns the new document ID and chunk count.
- `POST /api/v1/rag/query`: JSON `{ "query": "...", "top_k": 4 }`; returns answer and cited source chunks.
- `POST /api/v1/rag/stream`: same body; SSE emits `sources`, token `message` events, then `done`.
- `DELETE /api/v1/rag/documents/{document_id}`: delete a tenant's indexed document.
- `GET /api/v1/observability/overview`: public pipeline and stage status, without tenant identifiers or document data.
- `GET /api/v1/observability/events`: recent stage events; use `after` to resume from an event ID.
- `GET /api/v1/observability/stream`: public Server-Sent Events feed with `Last-Event-ID` reconnection support.
- `GET /healthz`: process liveness; `GET /readyz`: database readiness; `GET /metrics`: Prometheus text format.

All RAG routes require `X-Tenant-ID`. When `API_KEYS` is configured, they also require the key bound to that tenant. Keep the API behind authenticated infrastructure in production: this demo does not implement user identity, document ACLs, malware scanning, or audit retention policy.

## Tests

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest -q
```

Tests cover chunking and HTTP behavior with a fake service, so they do not need Docker, a database, or an OpenAI key. Run the full integration path with Docker Compose and inspect `/readyz` after startup.

## Architecture

Uploads are size-limited, text is extracted, and overlapping chunks are embedded in batches. Each stored row includes `tenant_id`; retrieval and deletion always filter by that tenant before touching content. PostgreSQL stores metadata and pgvector embeddings. The provider layer selects deterministic local embeddings/extractive answers or OpenAI APIs through environment configuration. Streaming uses SSE with source metadata before generated tokens. The observability ledger records stage status and duration only; it does not retain queries, answer text, tenant IDs, or secrets. It is process-local, bounded, and resets on restart; use a durable telemetry backend for multi-replica or long-term monitoring.

For a production rollout, replace startup `create_all` with versioned Alembic migrations, add OIDC/JWT identity and document-level authorization, evaluate retrieval quality with a curated test set, and set database backups, TLS, resource limits, and secret rotation.
