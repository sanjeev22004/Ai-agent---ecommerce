# ecom — Unified AI E-Commerce Support Copilot

A unified, high-performance Python application refactored and rewritten using **FastAPI**, **SQLAlchemy (asyncpg)**, **pgvector**, **Pydantic**, and **Python MCP protocol**. Replaces SQLite microservices and ChromaDB with a single cohesive architecture.

---

## 🌟 Key Features

1. **Unified Python Architecture**: Removed the separate Node.js/TypeScript MCP service and standalone Python microservice. The entire system now runs as a single FastAPI application.
2. **PostgreSQL + pgvector Integration**: Native vector storage and HNSW cosine similarity search (`<=>`), with resilient in-process cosine similarity fallback for environments without pgvector binaries.
3. **Token-Based Authentication (JWT)**:
   - Role-Based Access Control (`admin` and `customer`).
   - Customer ownership scoping: customers can ONLY query, return, and refund their own orders.
   - Admin portal with pending refund approval and full execution trace inspection.
4. **Complete Transactional Lifecycle**:
   - `order_lookup`: Query orders with line items, shipment tracking, and customer scoping.
   - `inventory_check`: Live inventory stock, prices, categories, and warranty durations.
   - `place_order`: Inventory validation, atomic stock decrements, and order creation.
   - `request_return`: Validates delivered state, registers return reason, and generates RMA codes.
   - `process_refund`: Idempotency key protection and automatic $50 threshold guardrail (auto-completes <= $50; flags > $50 for administrator approval).
   - `policy_search`: Semantic vector search over store policies with active date filtering (`effective_from <= order_date <= effective_to`).
5. **Advanced Agent Guardrails**:
   - **Off-Topic Triage**: Greetings, coding problems, math equations, and general essays are answered directly with ZERO tool calls.
   - **Prompt Injection Defense**: Tool results are isolated strictly in OpenAI-compatible `role: "tool"` blocks; parameters are sanitized against instruction overrides.
   - **ReAct Loop Protection**: Capped at 5 iterations with duplicate signature suppression.
   - **Observability**: Real-time token counting, latency breakdown, and USD cost estimation stored in `execution_traces`.
6. **Minimalist Vanilla UI**:
   - Zero-bloat SPA built with pure HTML, CSS, and modern JavaScript.
   - Tool execution badges with latency chips.
   - Highlighted grounded source citations (`[Source: returns_policy.md]`).
   - Sliding Trace Inspector drawer for per-step observability.
   - One-click demo user switcher.

---

## 🚀 Quickstart & Setup

### 1. Database Setup (Choose Option A or Option B)

#### Option A: Native Local PostgreSQL (Recommended — Zero Docker!)
If PostgreSQL is running locally on your machine (e.g., PostgreSQL 18 on port 5432):
Configure `.env`:
```env
DATABASE_URL=postgresql+asyncpg://postgres:Hrhk%404321@localhost:5432/ecom
```
*(Note: If your password contains `@`, encode it as `%40`)*

#### Option B: Docker PostgreSQL with pgvector
```bash
docker run --name ecom-postgres -e POSTGRES_PASSWORD=postgres -p 5432:5432 -d pgvector/pgvector:pg16
```
Configure `.env`:
```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/ecom
```

---

### 2. Install Dependencies

```bash
cd ecom
pip install -r requirements.txt
```

---

### 3. Configure Environment Variables

Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Ensure your Groq API key (or Ollama configuration) is set:
```env
LLM_PROVIDER=groq
LLM_MODEL=openai/gpt-oss-120b
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_API_KEY=gsk_your_api_key_here
```

---

### 4. Idempotent Database Seeding

Run the seed script:
```bash
python -m app.db.seed
```
This automatically:
- Creates tables and pgvector indexes.
- Seeds 2 Admins (`admin1@ecom.com`, `admin2@ecom.com` / `admin123`).
- Seeds 5 Customers (`alice@email.com`, `bob@email.com`, `carol@email.com`, `david@email.com`, `emma@email.com` / `user123`).
- Inserts 20 catalog products across electronics, clothing, home & garden, and sports.
- Seeds 30 orders with diverse delivery dates (including 5-day delivered returns and 40-day warranty orders).
- Embeds and ingests all policies from `data/policies/` into pgvector.
- **Idempotency**: If data already exists, seeding safely skips.

---

### 5. Launch the Application

Start the unified FastAPI server:
```bash
uvicorn app.main:app --reload --port 3000
```

Open your browser at:
👉 **http://localhost:3000**

---

## 👥 Demo Accounts

| Role | Email | Password | Permissions |
|---|---|---|---|
| **Customer** | `alice@email.com` | `user123` | Scoped to Alice's orders (`ORD-2024-001`, `ORD-2024-003`, etc.) |
| **Customer** | `bob@email.com` | `user123` | Scoped to Bob's orders (`ORD-2024-002`, etc.) |
| **Customer** | `carol@email.com` | `user123` | Scoped to Carol's orders (`ORD-2024-004`, etc.) |
| **Admin** | `admin1@ecom.com` | `admin123` | Unrestricted order queries, approve pending refunds, view all traces |

---

## 🧪 Architecture Overview

```
ecom/
├── .env.example
├── pyproject.toml
├── requirements.txt
├── README.md
├── app/
│   ├── __init__.py
│   ├── main.py                     # FastAPI entrypoint, router & static file mounting
│   ├── config.py                   # Settings (DATABASE_URL, JWT, LLM provider)
│   ├── auth.py                     # JWT token auth, bcrypt hashing & customer scoping
│   ├── db/
│   │   ├── __init__.py
│   │   ├── session.py              # Async PostgreSQL engine & sessionmaker
│   │   ├── models.py               # SQLAlchemy async models (relational + pgvector + traces)
│   │   └── seed.py                 # Idempotent database seeder
│   ├── rag/
│   │   ├── __init__.py
│   │   ├── ingest.py               # Markdown & JSON chunking & pgvector embedding loader
│   │   └── retriever.py            # Cosine similarity vector search with date filtering
│   ├── tools/
│   │   ├── __init__.py
│   │   └── mcp_tools.py            # Python MCP tools with strict Pydantic schemas
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── orchestrator.py         # ReAct loop, triage & prompt injection defenses
│   │   ├── prompts.py              # Orchestrator system prompt & evidence rules
│   │   └── tracer.py               # Token counter, latency tracker & USD cost estimator
│   └── static/
│       ├── index.html              # Minimalist modern UI
│       ├── style.css               # Clean styling (dark/light theme)
│       └── app.js                  # Frontend state, JWT handling & trace inspector
└── data/
    └── policies/                   # Standard operating store policies & FAQ json
```

---

## 🛡️ Guardrails Summary

1. **Off-Topic Triage**: Direct zero-tool answers for greetings, coding requests, LeetCode, math, and essays.
2. **Ownership Scoping**: Customer roles cannot view, return, or refund other customers' orders.
3. **Refund Threshold**: Refunds > $50 are queued as `pending_admin_approval` and require an admin to click "Approve Refund".
4. **Idempotency Protection**: Repeated refund attempts with the same idempotency key are rejected safely without duplicate transactions.
5. **Prompt Injection Isolation**: Tool results are never mixed into system prompt strings; they are structured strictly as `role: "tool"` blocks.

