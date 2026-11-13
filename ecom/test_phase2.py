"""Phase 2 Comprehensive Verification and Benchmark Test Suite.

Verifies:
1. Strict Dual-Sided Pydantic v2 Contracts (Input & Output validation)
2. Fast-Path Deterministic Routing with sub-80ms latency benchmark (50 iterations)
3. Zero-LLM-cost guarantee on Fast Path (0 prompt tokens, 0 completion tokens)
4. Fast-Path Customer Scoping & Ownership Isolation
5. Slow-Path Fallback for ambiguous, multi-step, and policy questions
6. Dynamic Role-Based Tool Scoping (Customer tool list vs Admin tool list)
7. Defense-in-Depth Execution Boundary (blocks unauthorized tool invocation)
"""

import asyncio
import logging
import statistics
import time
from typing import Any, Dict

import httpx
from httpx import ASGITransport
import pydantic
from contextlib import contextmanager

@contextmanager
def assert_raises(exc_type):
    try:
        yield
    except exc_type:
        pass
    else:
        raise AssertionError(f"Expected exception {exc_type.__name__} was not raised")

from app.main import app
from app.db.session import AsyncSessionLocal
from app.db.models import User
from app.router.intent_router import DeterministicIntentRouter, RouteTarget, FastPathIntent
from app.router.tool_registry import (
    get_tools_for_role,
    validate_tool_authorization,
    CUSTOMER_ALLOWED_TOOLS,
    ADMIN_ALLOWED_TOOLS,
    BLOCKED_FROM_CUSTOMER,
)
from app.contracts.tool_contracts import (
    OrderLookupInput,
    OrderLookupOutput,
    InventoryCheckInput,
    InventoryCheckOutput,
    OrderDetail,
    OrderItemDetail,
    ProductDetail,
    PlaceOrderOutput,
    RequestReturnOutput,
    ProcessRefundOutput,
    PolicySearchOutput,
    ApproveRefundInput,
)
from app.tools.mcp_tools import execute_tool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ecom.test_phase2")


# ─── Test 1: Pydantic v2 Dual-Sided Contract Validation ──────────────────────

async def test_pydantic_contracts():
    logger.info("--> [Test 1] Testing Strict Dual-Sided Pydantic v2 Contracts...")

    # 1. Input schema validation
    # Missing required field or invalid quantity in Inventory/Order
    with assert_raises(pydantic.ValidationError):
        # Quantity cannot be <= 0
        from app.contracts.tool_contracts import OrderItemInput
        OrderItemInput(product_id="PRD-001", quantity=0)

    # 2. Output schema validation (Valid)
    valid_order_output = {
        "success": True,
        "count": 1,
        "orders": [
            {
                "order_id": "ORD-2024-001",
                "customer_email": "alice@email.com",
                "status": "delivered",
                "total_amount": 149.99,
                "tracking_number": "TRK-12345678",
                "items": [
                    {
                        "product_id": "PRD-001",
                        "product_name": "Wireless Noise Canceling Headphones",
                        "quantity": 1,
                        "unit_price": 149.99,
                        "net_amount": 149.99,
                    }
                ],
                "returns": [],
            }
        ],
        "message": "Order found.",
    }
    validated_order = OrderLookupOutput.model_validate(valid_order_output)
    assert validated_order.count == 1
    assert validated_order.orders[0].total_amount == 149.99
    assert validated_order.orders[0].items[0].product_name == "Wireless Noise Canceling Headphones"

    # 3. Output schema defense-in-depth (Corrupted data rejection)
    # Negative total_amount or missing required fields must fail output validation
    corrupted_order_output = {
        "success": True,
        "count": 1,
        "orders": [
            {
                "order_id": "ORD-CORRUPT",
                "customer_email": "corrupt@email.com",
                "status": "delivered",
                "total_amount": -50.0,  # Negative amount violates ge=0.0 constraint!
            }
        ],
    }
    with assert_raises(pydantic.ValidationError):
        OrderLookupOutput.model_validate(corrupted_order_output)

    # 4. Inventory output contract
    valid_inv_output = {
        "success": True,
        "count": 1,
        "products": [
            {
                "product_id": "PRD0000001",
                "name": "Wireless Mouse",
                "category": "Electronics",
                "price": 29.99,
                "stock_quantity": 45,
                "in_stock": True,
                "warranty_months": 12,
                "description": "Ergonomic wireless mouse",
            }
        ],
        "message": "1 product found.",
    }
    validated_inv = InventoryCheckOutput.model_validate(valid_inv_output)
    assert validated_inv.products[0].in_stock is True

    logger.info("[Test 1 PASSED] Dual-sided Pydantic v2 contracts strictly enforced.")


# ─── Test 2: Fast-Path Intent Routing & Sub-80ms Latency Benchmark ──────────

async def test_fast_path_and_benchmark():
    logger.info("--> [Test 2] Benchmarking Deterministic Fast Path (Sub-80ms Target)...")
    router = DeterministicIntentRouter()

    # Verify classification accuracy
    sample_queries = [
        ("Where is ORD-2024-001?", FastPathIntent.ORDER_LOOKUP),
        ("What is the status of my order ORD-2024-001?", FastPathIntent.ORDER_LOOKUP),
        ("Track order ORD-2024-001", FastPathIntent.ORDER_LOOKUP),
        ("Is PROD-001 in stock?", FastPathIntent.INVENTORY_CHECK),
        ("What is the price of PROD-001?", FastPathIntent.INVENTORY_CHECK),
        ("Check stock for PRD0000001", FastPathIntent.INVENTORY_CHECK),
    ]

    for q, expected_intent in sample_queries:
        dec = router.classify(q)
        assert dec.target == RouteTarget.FAST_PATH, f"Query '{q}' was not classified as FAST_PATH"
        assert dec.intent == expected_intent, f"Query '{q}' expected {expected_intent}, got {dec.intent}"

    # Latency Benchmark: 50 iterations via ASGI transport
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Login as Alice
        login_res = await client.post("/api/auth/login", json={"email": "alice@email.com", "password": "user123"})
        assert login_res.status_code == 200
        alice_token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {alice_token}"}

        latencies_ms = []
        for i in range(50):
            t0 = time.perf_counter()
            res = await client.post(
                "/api/chat",
                json={"message": "Where is ORD-2024-001?"},
                headers=headers,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            latencies_ms.append(elapsed_ms)

            assert res.status_code == 200
            data = res.json()
            assert "ORD-2024-001" in data["response"]
            # Zero-LLM cost guarantee
            assert data["trace"]["prompt_tokens"] == 0
            assert data["trace"]["completion_tokens"] == 0
            assert data["trace"]["status"] == "fast_path_success"

        mean_ms = statistics.mean(latencies_ms)
        median_ms = statistics.median(latencies_ms)
        p95_ms = statistics.quantiles(latencies_ms, n=20)[18] if len(latencies_ms) >= 20 else max(latencies_ms)

        logger.info(
            "Benchmark Results (50 requests): Mean: %.2fms | Median: %.2fms | P95: %.2fms",
            mean_ms,
            median_ms,
            p95_ms,
        )
        assert median_ms < 80.0, f"Benchmark target sub-80ms failed: Median was {median_ms:.2f}ms"
        logger.info("[Test 2 PASSED] Fast-path achieved sub-80ms median latency (%.2fms) with 0 tokens.", median_ms)


# ─── Test 3: Customer Scoping on Fast Path ───────────────────────────────────

async def test_fast_path_scoping_isolation():
    logger.info("--> [Test 3] Testing Fast-Path Scoping & Ownership Isolation...")
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Login as Alice
        res = await client.post("/api/auth/login", json={"email": "alice@email.com", "password": "user123"})
        alice_token = res.json()["access_token"]
        headers = {"Authorization": f"Bearer {alice_token}"}

        # Alice attempts to fast-path query Bob's order ORD-2024-002
        res = await client.post(
            "/api/chat",
            json={"message": "Where is ORD-2024-002?"},
            headers=headers,
        )
        assert res.status_code == 200
        reply = res.json()["response"]
        # Must NOT expose Bob's order details
        assert "bob@email.com" not in reply.lower()
        assert "No orders were found" in reply or "Unable" in reply or "not found" in reply.lower()
        logger.info("Scoping confirmed: Alice cannot query Bob's order via fast-path.")

        # Alice queries her own order ORD-2024-001
        res = await client.post(
            "/api/chat",
            json={"message": "Where is ORD-2024-001?"},
            headers=headers,
        )
        assert res.status_code == 200
        reply = res.json()["response"]
        assert "ORD-2024-001" in reply
        assert "Status:" in reply
        logger.info("[Test 3 PASSED] Customer ownership scoping strictly enforced on fast-path.")


# ─── Test 4: Slow-Path Fallback for Complex & Policy Queries ────────────────

async def test_slow_path_fallback():
    logger.info("--> [Test 4] Testing Slow-Path ReAct Fallback...")
    router = DeterministicIntentRouter()

    slow_queries = [
        "Can I return an item if the original packaging is missing?",
        "I received a damaged package for ORD-2024-001, what should I do?",
        "Why was my refund rejected?",
        "What is your store compensation policy for delayed shipments?",
    ]

    for q in slow_queries:
        dec = router.classify(q)
        assert dec.target == RouteTarget.SLOW_PATH, f"Query '{q}' should route to SLOW_PATH but was {dec.target}"

    # Verify slow-path execution via API uses ReAct agent with policy search
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        res = await client.post("/api/auth/login", json={"email": "alice@email.com", "password": "user123"})
        alice_token = res.json()["access_token"]
        headers = {"Authorization": f"Bearer {alice_token}"}

        res = await client.post(
            "/api/chat",
            json={"message": "What is the return window for defective items according to store policy?"},
            headers=headers,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["trace"]["status"] == "completed"
        # Policy search was utilized
        assert any(t.get("tool") == "policy_search" for t in data["tool_calls"])
        logger.info("[Test 4 PASSED] Complex policy query routed to Slow Path with grounded answer.")


# ─── Test 5: Dynamic Role-Based Tool Scoping & Defense-in-Depth ──────────────

async def test_role_based_tool_scoping_and_defense():
    logger.info("--> [Test 5] Testing Dynamic Role-Based Tool Scoping & Defense-in-Depth...")

    # 1. Customer LLM Schema Scoping
    customer_tools = get_tools_for_role("customer")
    customer_tool_names = {t["function"]["name"] for t in customer_tools}
    assert customer_tool_names == CUSTOMER_ALLOWED_TOOLS
    for blocked in BLOCKED_FROM_CUSTOMER:
        assert blocked not in customer_tool_names, f"Admin tool '{blocked}' exposed to customer!"

    # 2. Admin LLM Schema Scoping
    admin_tools = get_tools_for_role("admin")
    admin_tool_names = {t["function"]["name"] for t in admin_tools}
    assert admin_tool_names == ADMIN_ALLOWED_TOOLS
    assert "approve_refund" in admin_tool_names
    assert "reembed_policies" in admin_tool_names

    # 3. Defense-in-Depth: Direct Tool Execution Boundary
    async with AsyncSessionLocal() as session:
        # Create a mock customer user
        alice_user = User(
            id="usr_test_alice",
            email="alice@email.com",
            name="Alice",
            password_hash="x",
            role="customer",
        )

        # Alice attempts to execute 'approve_refund' directly
        with assert_raises(PermissionError):
            validate_tool_authorization("approve_refund", alice_user.role)

        # Call execute_tool directly to ensure security boundary catches it
        denied_result = await execute_tool(
            "approve_refund",
            {"refund_id": "REF-5001"},
            session,
            current_user=alice_user,
        )
        assert denied_result["success"] is False
        assert "Access Denied" in denied_result["error"]
        logger.info("Defense-in-depth caught and rejected unauthorized execution of 'approve_refund' by customer.")

        # Admin user executes authorized tool
        admin_user = User(
            id="usr_test_admin",
            email="admin1@ecom.com",
            name="Admin",
            password_hash="x",
            role="admin",
        )
        validate_tool_authorization("approve_refund", admin_user.role)  # Should not raise

    logger.info("[Test 5 PASSED] Dynamic role scoping and defense-in-depth security boundary verified.")


# ─── Runner ──────────────────────────────────────────────────────────────────

async def run_all_phase2_tests():
    logger.info("==================================================")
    logger.info("STARTING PHASE 2 VERIFICATION & BENCHMARK SUITE")
    logger.info("==================================================")
    await test_pydantic_contracts()
    await test_fast_path_and_benchmark()
    await test_fast_path_scoping_isolation()
    await test_slow_path_fallback()
    await test_role_based_tool_scoping_and_defense()
    logger.info("==================================================")
    logger.info("ALL PHASE 2 TESTS PASSED SUCCESSFULLY!")
    logger.info("==================================================")


if __name__ == "__main__":
    asyncio.run(run_all_phase2_tests())
