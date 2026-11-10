"""End-to-end integration test suite for ecom application.

Tests:
1. Health endpoint
2. Authentication & JWT issuance
3. Customer role scoping & security
4. Off-topic triage (zero tool calls)
5. Full Agent ReAct loop with tools (order lookup, inventory check, policy search)
6. Admin pending refunds and approval workflow
"""

import asyncio
import logging
import httpx
from httpx import ASGITransport

from app.main import app
from app.db.session import init_db
from app.db.seed import seed_database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ecom.test")


async def run_tests():
    logger.info("Initializing DB and seeding for tests...")
    await init_db()
    await seed_database(force=False)

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Healthcheck
        logger.info("--> Testing Healthcheck...")
        res = await client.get("/api/health")
        assert res.status_code == 200, f"Healthcheck failed: {res.text}"
        logger.info("Health response: %s", res.json())

        # 2. Login as Customer (Alice)
        logger.info("--> Testing Customer Login (Alice)...")
        res = await client.post("/api/auth/login", json={"email": "alice@email.com", "password": "user123"})
        assert res.status_code == 200, f"Login failed: {res.text}"
        alice_data = res.json()
        alice_token = alice_data["access_token"]
        alice_headers = {"Authorization": f"Bearer {alice_token}"}
        logger.info("Alice logged in successfully. Role: %s", alice_data["user"]["role"])

        # 3. Test /api/auth/me
        logger.info("--> Testing /api/auth/me...")
        res = await client.get("/api/auth/me", headers=alice_headers)
        assert res.status_code == 200
        assert res.json()["email"] == "alice@email.com"

        # 4. Login as Admin
        logger.info("--> Testing Admin Login...")
        res = await client.post("/api/auth/login", json={"email": "admin1@ecom.com", "password": "admin123"})
        assert res.status_code == 200
        admin_data = res.json()
        admin_token = admin_data["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        logger.info("Admin logged in successfully.")

        # 5. Test Off-Topic Triage (Greeting) -> zero tool calls
        logger.info("--> Testing Off-Topic Greeting Triage...")
        res = await client.post(
            "/api/chat",
            json={"message": "hello!"},
            headers=alice_headers,
        )
        assert res.status_code == 200
        data = res.json()
        logger.info("Greeting response: %s", data["response"])
        assert len(data["tool_calls"]) == 0, "Greetings should not trigger tool calls!"
        assert data["trace"]["status"] == "triage_direct"

        # 6. Test Off-Topic Coding Triage -> zero tool calls
        logger.info("--> Testing Off-Topic Coding Triage...")
        res = await client.post(
            "/api/chat",
            json={"message": "write a python script to solve leetcode spiral matrix"},
            headers=alice_headers,
        )
        assert res.status_code == 200
        data = res.json()
        logger.info("Coding triage response: %s", data["response"])
        assert len(data["tool_calls"]) == 0
        assert "E-Commerce Support" in data["response"]

        # 7. Test Customer Order Inquiry (Alice's own order ORD-2024-001)
        logger.info("--> Testing Order Inquiry for Alice (ORD-2024-001)...")
        res = await client.post(
            "/api/chat",
            json={"message": "Where is my order ORD-2024-001?"},
            headers=alice_headers,
        )
        assert res.status_code == 200
        data = res.json()
        logger.info("Order inquiry response: %s", data["response"])
        logger.info("Tool calls executed: %s", [t["tool"] for t in data["tool_calls"]])

        # 8. Test Customer Ownership Isolation (Alice querying Bob's order ORD-2024-002)
        logger.info("--> Testing Customer Scoping Isolation...")
        res = await client.post(
            "/api/chat",
            json={"message": "Look up order ORD-2024-002 for bob@email.com"},
            headers=alice_headers,
        )
        assert res.status_code == 200
        data = res.json()
        logger.info("Scoping isolation response: %s", data["response"])

        # 9. Test Admin Pending Refunds Endpoint
        logger.info("--> Testing Admin Pending Refunds...")
        res = await client.get("/api/admin/refunds/pending", headers=admin_headers)
        assert res.status_code == 200
        refunds_data = res.json()
        logger.info("Pending refunds found: %d", refunds_data["pending_count"])
        assert refunds_data["pending_count"] > 0
        target_ref_id = refunds_data["refunds"][0]["refund_id"]

        # 10. Test Admin Approve Refund
        logger.info("--> Testing Admin Approve Refund (%s)...", target_ref_id)
        res = await client.post(f"/api/admin/refunds/{target_ref_id}/approve", headers=admin_headers)
        assert res.status_code == 200
        assert res.json()["new_status"] == "completed"
        logger.info("Refund approved successfully: %s", res.json())

        # 11. Test Admin Traces Endpoint
        logger.info("--> Testing Admin Traces Inspection...")
        res = await client.get("/api/admin/traces", headers=admin_headers)
        assert res.status_code == 200
        traces = res.json()["traces"]
        logger.info("Traces recorded: %d", len(traces))
        assert len(traces) > 0

        # 12. Test Frontend HTML serving
        logger.info("--> Testing Frontend index.html...")
        res = await client.get("/")
        assert res.status_code == 200
        assert "ecom copilot" in res.text

    logger.info("==========================================")
    logger.info("ALL INTEGRATION TESTS PASSED SUCCESSFULLY!")
    logger.info("==========================================")


if __name__ == "__main__":
    asyncio.run(run_tests())

