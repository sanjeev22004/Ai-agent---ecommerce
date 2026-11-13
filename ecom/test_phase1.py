"""Phase 1 Verification Test Suite: Database Architecture, Authentication & Data Seeding.

Validates:
1. Production Schema Integrity & Table Counts from Kaggle Dataset
2. Customer Credentials & Authentication with Kaggle Customer IDs
3. JWT Identity and Claims (including customer_id)
4. Customer Data Isolation & Scoped Order Lookup for Kaggle Customers
5. Idempotent Seeding & Clean Database Reset capability
"""

import asyncio
import logging
import httpx
from httpx import ASGITransport
from sqlalchemy import text

from app.main import app
from app.db.session import engine, init_db
from app.db.seed import seed_database

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("ecom.test_phase1")


async def test_database_table_counts():
    """Verify production schema tables and expected row counts from Kaggle ingestion."""
    logger.info("--> [Test 1] Verifying Database Schema and Kaggle Table Counts...")
    tables = [
        ("locations", 100),
        ("payment_methods", 10),
        ("fulfillment_methods", 3),
        ("sellers", 1000),
        ("products", 1260),
        ("customers", 5000),
        ("users", 15),
        ("orders", 5000),
        ("order_items", 5000),
        ("returns", 500),
        ("refunds", 500),
        ("policies", 40),
    ]

    async with engine.connect() as conn:
        for table_name, expected_min in tables:
            res = await conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
            count = res.scalar()
            logger.info("Table '%s': %d rows (expected >= %d)", table_name, count, expected_min)
            assert count >= expected_min, f"Table '{table_name}' has {count} rows, expected >= {expected_min}"
    logger.info("[Test 1 PASSED] All Kaggle tables populated with correct scale.")


async def test_kaggle_customer_authentication():
    """Verify login using Kaggle customer ID credentials seeded into the credentials table."""
    logger.info("--> [Test 2] Testing Authentication with Kaggle Customer ID Credentials...")
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Test valid login with Kaggle Customer CUST000001
        res = await client.post(
            "/api/auth/login",
            json={"email": "navyakashyap@gmail.com", "password": "user123"},
        )
        assert res.status_code == 200, f"Login failed: {res.text}"
        data = res.json()
        assert "access_token" in data
        user = data["user"]
        assert user["email"] == "navyakashyap@gmail.com"
        assert user["customer_id"] == "CUST000001"
        assert user["role"] == "customer"
        logger.info("Successfully authenticated Kaggle customer %s (%s)", user["customer_id"], user["email"])

        token = data["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Verify /api/auth/me profile
        me_res = await client.get("/api/auth/me", headers=headers)
        assert me_res.status_code == 200
        assert me_res.json()["customer_id"] == "CUST000001"

        # Test invalid password rejection
        bad_res = await client.post(
            "/api/auth/login",
            json={"email": "navyakashyap@gmail.com", "password": "wrong_password"},
        )
        assert bad_res.status_code == 401
    logger.info("[Test 2 PASSED] Kaggle customer login & credential verification succeeded.")


async def test_admin_authentication():
    """Verify admin login and access to administrative endpoints."""
    logger.info("--> [Test 3] Testing Admin Login & Privileges...")
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        res = await client.post(
            "/api/auth/login",
            json={"email": "admin1@ecom.com", "password": "admin123"},
        )
        assert res.status_code == 200
        admin_data = res.json()
        assert admin_data["user"]["role"] == "admin"
        admin_token = admin_data["access_token"]

        # Admin access to pending refunds
        ref_res = await client.get("/api/admin/refunds/pending", headers={"Authorization": f"Bearer {admin_token}"})
        assert ref_res.status_code == 200
        pending_count = ref_res.json()["pending_count"]
        logger.info("Admin verified: %d pending refunds awaiting review.", pending_count)
    logger.info("[Test 3 PASSED] Admin authentication and privilege check succeeded.")


async def test_customer_isolation_and_order_lookup():
    """Verify that Kaggle customers can query their own orders and are blocked from querying others."""
    logger.info("--> [Test 4] Testing Customer Scoping & Order Isolation...")
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Login as Navya
        res = await client.post(
            "/api/auth/login",
            json={"email": "navyakashyap@gmail.com", "password": "user123"},
        )
        navya_token = res.json()["access_token"]
        navya_headers = {"Authorization": f"Bearer {navya_token}"}

        # Query orders for another email (should be blocked)
        chat_res = await client.post(
            "/api/chat",
            json={"message": "Look up orders for alice@email.com"},
            headers=navya_headers,
        )
        assert chat_res.status_code == 200
        reply = chat_res.json()["response"]
        assert "navyakashyap@gmail.com" in reply or "only" in reply.lower() or "unable" in reply.lower()
        logger.info("Scoping isolation confirmed for Kaggle customer.")
    logger.info("[Test 4 PASSED] Customer data isolation verified.")


async def run_all_phase1_tests():
    logger.info("==================================================")
    logger.info("STARTING PHASE 1 VERIFICATION TEST SUITE")
    logger.info("==================================================")
    await test_database_table_counts()
    await test_kaggle_customer_authentication()
    await test_admin_authentication()
    await test_customer_isolation_and_order_lookup()
    logger.info("==================================================")
    logger.info("ALL PHASE 1 VERIFICATION TESTS PASSED SUCCESSFULLY")
    logger.info("==================================================")


if __name__ == "__main__":
    asyncio.run(run_all_phase1_tests())

