---
marp: true
theme: default
paginate: true
header: "Agentic AI Engineering | E-Commerce Support Copilot"
footer: "One-Week Practical Assessment"
---

# 🤖 E-Commerce Support Copilot
## Agentic AI Support Resolution System

**Presenter / Candidate:** Engineering Assessment Candidate  
**Stack:** TypeScript + Python + Model Context Protocol (MCP) + ChromaDB + BM25  
**Demonstration Date:** November 2026  

---

# 1. Business Problem & Objective

- **Retail Customer Support Challenge**:
  - High inquiry volume across order tracking, delivery delays, returns, warranty, and compensation policies.
  - Information is fragmented between relational ERP databases (orders, customers, stock) and policy documentation.

- **Solution**:
  - An autonomous, tool-using AI Agent capable of:
    1. Finding verifiable evidence across multiple document/data formats.
    2. Choosing appropriate tools dynamically via **Model Context Protocol (MCP)**.
    3. Executing multi-step dependent reasoning workflows.
    4. Explaining decisions with grounded citations and zero hallucinations.

---

# 2. System Architecture

```
┌─────────────────────────────────┐       ┌───────────────────────────────────┐
│     Client / Terminal UI        │       │       Python RAG Microservice     │
│   (Brutalist Web / demo.ts)     │       │              (:8000)              │
└───────────────┬─────────────────┘       └─────────────────▲─────────────────┘
                │ HTTP POST /chat                           │ HTTP POST /search
┌───────────────▼───────────────────────────────────────────┴─────────────────┐
│                     Express API & Orchestrator (:3000)                      │
│   ┌─────────────────────┐   InMemoryTransport   ┌──────────────────────┐    │
│   │   Agent MCP Client  │ ◄───────────────────► │      MCP Server      │    │
│   │ (Dynamic Discovery) │                       │ (Zod Schemas + Tools)│    │
│   └──────────┬──────────┘                       └──────────┬───────────┘    │
│              │ Function Calling                            │                │
│   ┌──────────▼──────────┐                       ┌──────────▼───────────┐    │
│   │   LLM (Ollama/Groq) │                       │ SQLite ERP Database  │    │
│   └─────────────────────┘                       └──────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

- **TypeScript Gateway**: MCP Server/Client, session state machine, and latency/cost tracer.
- **Python RAG**: ChromaDB vector store + Okapi BM25 lexical ranking engine.

---

# 3. Model Context Protocol (MCP) Integration

- **True MCP Protocol Boundary**:
  - The agent orchestrator **does not call internal functions directly**.
  - Uses `@modelcontextprotocol/sdk` with `InMemoryTransport` linked pairs.
- **Dynamic Discovery (`tools/list`)**:
  - At startup, the agent queries the MCP server: discovers `order_lookup`, `inventory_check`, `policy_search`, `response_draft`.
  - Converts tool schemas to LLM function declarations dynamically.
- **Robustness & Validation**:
  - Inputs validated against Zod schemas at protocol boundary.
  - Safe error masking prevents raw stack trace leakage to the LLM.

---

# 4. Multi-Format Ingestion & Dual Retrieval

- **Multi-Format Processing**:
  - Ingests **Markdown (`.md`)** policies & **Structured JSON (`.json`)** operational FAQs.
  - Tracks provenance, categories, and chunk metadata in `data-manifest.json`.

- **Comparative Ranking Benchmark (12 Test Queries)**:

| Ranking Method | Precision@3 | Recall@3 | MRR | Grounding Faithfulness |
|---|---|---|---|---|
| **Dense Cosine (all-MiniLM-L6-v2)** | 78.5% | 91.7% | 0.9028 | 84.7% |
| **Lexical (Okapi BM25)** | 72.2% | 83.3% | 0.8194 | 79.2% |
| **Hybrid (RRF Fusion, k=60)** | **88.9%** | **100.0%** | **0.9722** | **93.1%** |

- **Decision**: Hybrid RRF selected for production to eliminate vocabulary mismatch while retaining semantic relevance.

---

# 5. Stateful Agent Workflow & Demonstration Scenarios

- **State Management**:
  - `SessionStore` persists verified customer email, active order ID, and multi-turn state.

- **Scenario 1 — Knowledge Query**:
  - Customer asks about electronics return policy ➔ Agent calls `policy_search` ➔ Cites `returns_policy.md` (15-day window, 15% restocking fee).
- **Scenario 2 — Multi-Step Return Resolution**:
  - Customer asks to return item from `ORD-1001` ➔
  - Step 1: `order_lookup` retrieves purchase item and delivery date (Oct 25).
  - Step 2: `policy_search` retrieves category return window (15 days for electronics).
  - Step 3: Determines order is past refund window, but offers active 12-month warranty replacement.
- **Scenario 3 — Exception Handling**:
  - Safe handling of missing order `ORD-9999` with zero hallucination.

---

# 6. Observability, Latency & Cost Tracking

- **Step-by-Step Execution Traces**:
  - Every conversation turn records timestamped traces saved to `data/traces.jsonl`.
  - Captures per-step latency (LLM reasoning vs MCP tool execution) and token usage.

- **Sample Metrics Observed**:
  - **Single Tool Query (Order Lookup)**: 680ms | 500 tokens | \$0.00031
  - **Multi-Step Return Resolution**: 1,290ms | 1,573 tokens | \$0.00097
  - **Knowledge Policy Query**: 850ms | 715 tokens | \$0.00045

- **Cost Optimization**:
  - Local embeddings = \$0.00 cost.
  - Groq / Ollama switchable via configuration with zero code modifications.

---

# 7. Production Judgment, Trade-offs & Limitations

- **Key Trade-offs Made**:
  - *InMemoryTransport vs Stdio/SSE*: Chose InMemoryTransport for sub-millisecond inter-process latency and zero network overhead.
  - *RRF Fusion vs Cross-Encoder Re-ranker*: Chose RRF for scale-invariance and zero GPU inference overhead.
  - *SQLite vs Postgres*: SQLite zero-config simplicity for assessment; production requires PostgreSQL with `pgvector`.

- **Current Limitations & Future Roadmap**:
  - Implement OAuth2/JWT customer authentication on `/chat`.
  - Replace in-memory session map with Redis distributed cache.
  - Add automated human-in-the-loop escalation for edge dispute resolutions.

