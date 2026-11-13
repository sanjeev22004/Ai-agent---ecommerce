# Production-Grade Agentic AI E-Commerce Support Resolution Copilot

A production-grade, stateful AI support copilot for e-commerce, powered by PostgreSQL, FastAPI, and an Agentic ReAct orchestration loop.

---

## 1. Supported Business Domains

The system is strictly scoped to 5 core e-commerce domains:
1. **Product Information** (Catalog search, inventory, specifications, warranty)
2. **Shipping** (Tracking, SLA, fulfillment methods, delivery timelines)
3. **Orders** (Order status, order items, customer order history)
4. **Returns** (Return request initiation, eligibility validation, RMA generation)
5. **Refunds** (Monetary refunds, auto-approval thresholds, admin approvals)

---

## 2. Database Schema (Phase 1 — Kaggle Dataset Alignment)

The database schema is mapped from real Kaggle e-commerce datasets (`Kaggle dataset archive/`):

### Core Dimensions
- `locations` (`DIM_LOCATION.csv`): Geographic tiers, postal codes, coordinates (113 rows)
- `payment_methods` (`DIM_PAYMENT.csv`): Credit card, debit card, UPI, wallets (14 rows)
- `fulfillment_methods` (`DIM_FULFILLMENT.csv`): Standard, Express, Same Day SLA and costs (3 rows)
- `sellers` (`DIM_SELLER.csv`): Seller profiles, categories, ratings (4,563 rows)
- `products` (`DIM_PRODUCT.csv`): Product catalog with brand, category, sub-category, list price, warranty, stock (1,260 items)
- `customers` (`DIM_CUSTOMER.csv`): Customer demographics, contact information, location (5,000+ rows)

### Authentication & Security
- `users` (Credentials Table):
  - Stores login credentials (email and bcrypt password hash)
  - References `customers.id` via Foreign Key `customer_id`
  - Seeded with administrator profiles (`admin1@ecom.com`, `admin2@ecom.com`) and Kaggle customer logins (e.g. `navyakashyap@gmail.com` -> `CUST000001` with password `user123`)

### Transactions & Lifecycle
- `orders` (`FACT_ORDERS.csv`): Aggregated order headers with customer email, status, shipping fee, tax, net total, SLA, delivery dates (5,000+ orders)
- `order_items` (`FACT_ORDERS.csv`): Line items with product ID, quantity, unit price, discounts, net amount (5,000+ items)
- `returns` (`FACT_RETURNS.csv`): RMA requests, return reasons, restocking fees, return status (749+ returns)
- `refunds`: Refund transactions linked to RMAs with idempotency keys and $50 approval threshold (749+ refunds)

### Knowledge Base & Observability
- `policies`: Store policies chunked and embedded in vector space with date boundaries
- `ingestion_metadata`: Content hashes, chunk hashes, embedding model versions
- `chat_sessions`: Stateful multi-turn conversation sessions per user
- `chat_messages`: Full message history with tool call payloads
- `execution_traces`: Granular latency, token consumption, and step-by-step audit logs
- `support_tickets`: Human support tickets for graceful degradation

---

## 3. Dataset Seeding Pipeline

To reset and seed the entire database from the Kaggle dataset:

```bash
# Seed with full clean reset
python -m app.db.seed --reset

# Run programmatic seed in Python
python -c "import asyncio, sys; sys.path.insert(0, 'ecom'); from app.db.seed import seed_database; asyncio.run(seed_database(reset=True))"
```

### Seeding Performance & Metrics
- Ingestion time: **~8-9 seconds** for full database setup and vector embedding.
- Complete referential integrity enforced by foreign key constraints.
- Idempotent: Skips ingestion if data is already present unless `--reset` is specified.

---

## 4. Seeded Authentication Accounts

### Administrator Accounts
- `admin1@ecom.com` / `admin123`
- `admin2@ecom.com` / `admin123`

### Seeded Kaggle Customer Accounts
- `navyakashyap@gmail.com` (Customer ID: `CUST000001`) / `user123`
- `faiyazluthra690@gmail.com` (Customer ID: `CUST000002`) / `user123`
- `anaysridhar@gmail.com` (Customer ID: `CUST000003`) / `user123`
- Additional demo accounts: `alice@email.com` / `user123`, `bob@email.com` / `user123`

---

## 5. Verification & Testing

Run all test suites:

```bash
# Phase 1 Verification Test Suite
python ecom/test_phase1.py

# End-to-End Integration Suite
python ecom/test_ecom.py
```

### Test Results
- `test_phase1.py`: **4/4 Tests Passed** (Table scale, Kaggle customer auth, Admin privileges, Customer data isolation)
- `test_ecom.py`: **12/12 Tests Passed** (Health, Auth, Me, Admin, Triage, Agent ReAct loop, Order Scoping, Refunds, Traces, Frontend)

