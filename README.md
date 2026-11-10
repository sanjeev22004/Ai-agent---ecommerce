# ecom — Unified AI E-Commerce Support Copilot

A unified, production-grade Python application refactored and rewritten using **FastAPI**, **SQLAlchemy (asyncpg)**, **PostgreSQL + pgvector**, **Pydantic**, and **Python MCP protocol**.

The multi-container Node.js and Python microservice architecture with SQLite and ChromaDB has been unified into a single Python application in `ecom/`. **Docker is no longer needed** to run the services or database.

---

## 🚀 Quick Start (Running Without Docker)

### 1. Database Connection String

PostgreSQL is running natively on your machine:
```env
DATABASE_URL=postgresql+asyncpg://postgres:Hrhk%404321@localhost:5432/ecom
```
*(Note: `@` is URL-encoded as `%40`)*

### 2. Install Python Dependencies

```bash
cd ecom
pip install -r requirements.txt
```

### 3. Seed Database (Idempotent)

```bash
cd ecom
python -m app.db.seed
```
*Seeds 2 Admins, 5 Customers, 20 Products, 30 Orders with returns & refunds, and embeds policies with `all-MiniLM-L6-v2`.*

### 4. Run the Unified FastAPI Application

```bash
cd ecom
uvicorn app.main:app --reload --port 3000
```

Open your browser at:
👉 **http://localhost:3000**

---

## 👥 Demo Logins

- **Customer:** `alice@email.com` / `user123` (Scoped to Alice's orders only)
- **Customer:** `bob@email.com` / `user123` (Scoped to Bob's orders only)
- **Admin:** `admin1@ecom.com` / `admin123` (Full ERP query, refund approval, trace inspection)

For complete technical specifications, see [`ecom/README.md`](file:///c:/Users/Unthinkable-lap/Downloads/ecommerce-support/ecom/README.md).
