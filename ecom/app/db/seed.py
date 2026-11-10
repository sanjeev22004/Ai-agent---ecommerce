"""Idempotent database seeder for ecom application.

Seeds users, products, orders, order items, and policy embeddings.
Executes only if the database is currently empty.
"""

import asyncio
from datetime import datetime, timedelta, timezone
import logging
import random

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import hash_password
from app.db.models import Order, OrderItem, Product, Return, Refund, User
from app.db.session import AsyncSessionLocal, init_db
from app.rag.ingest import ingest_policies

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("ecom.seed")


# ─── Seed Data Definitions ───────────────────────────────────────────────────

ADMIN_USERS = [
    {"name": "Admin One", "email": "admin1@ecom.com", "password": "admin123", "role": "admin"},
    {"name": "Admin Two", "email": "admin2@ecom.com", "password": "admin123", "role": "admin"},
]

CUSTOMER_USERS = [
    {"name": "Alice Johnson", "email": "alice@email.com", "password": "user123", "role": "customer"},
    {"name": "Bob Martinez", "email": "bob@email.com", "password": "user123", "role": "customer"},
    {"name": "Carol Chen", "email": "carol@email.com", "password": "user123", "role": "customer"},
    {"name": "David Kim", "email": "david@email.com", "password": "user123", "role": "customer"},
    {"name": "Emma Wilson", "email": "emma@email.com", "password": "user123", "role": "customer"},
]

PRODUCTS = [
    # Electronics
    {
        "id": "PROD-001",
        "name": "Wireless Bluetooth Headphones",
        "category": "electronics",
        "price": 79.99,
        "stock_quantity": 150,
        "warranty_months": 12,
        "description": "Over-ear wireless headphones with active noise cancellation and 30-hour battery life",
    },
    {
        "id": "PROD-002",
        "name": "USB-C Fast Charger 65W",
        "category": "electronics",
        "price": 34.99,
        "stock_quantity": 300,
        "warranty_months": 24,
        "description": "GaN compact USB-C charger compatible with laptops, tablets, and phones",
    },
    {
        "id": "PROD-003",
        "name": "4K Webcam Pro",
        "category": "electronics",
        "price": 129.99,
        "stock_quantity": 75,
        "warranty_months": 12,
        "description": "Ultra HD 4K webcam with dual stereo microphones and built-in ring light",
    },
    {
        "id": "PROD-004",
        "name": "Portable SSD 1TB",
        "category": "electronics",
        "price": 89.99,
        "stock_quantity": 200,
        "warranty_months": 36,
        "description": "High-speed USB 3.2 solid-state drive with up to 1050 MB/s transfer speeds",
    },
    # Clothing
    {
        "id": "PROD-005",
        "name": "Merino Wool Sweater",
        "category": "clothing",
        "price": 89.99,
        "stock_quantity": 60,
        "warranty_months": 0,
        "description": "100% fine merino wool crewneck sweater, thermal and machine washable",
    },
    {
        "id": "PROD-006",
        "name": "Waterproof Rain Jacket",
        "category": "clothing",
        "price": 149.99,
        "stock_quantity": 45,
        "warranty_months": 6,
        "description": "Breathable waterproof hooded rain jacket with heat-sealed seams",
    },
    {
        "id": "PROD-007",
        "name": "Running Shoes Ultra",
        "category": "clothing",
        "price": 119.99,
        "stock_quantity": 0,
        "warranty_months": 6,
        "description": "Carbon-plated lightweight road marathon shoes with energy foam cushioning",
    },
    {
        "id": "PROD-008",
        "name": "Cotton Graphic T-Shirt",
        "category": "clothing",
        "price": 24.99,
        "stock_quantity": 120,
        "warranty_months": 0,
        "description": "Heavyweight organic cotton vintage crewneck graphic t-shirt",
    },
    # Home & Garden
    {
        "id": "PROD-009",
        "name": "Smart LED Bulb Pack (4)",
        "category": "home_garden",
        "price": 39.99,
        "stock_quantity": 500,
        "warranty_months": 24,
        "description": "WiFi multi-color smart LED light bulbs compatible with Alexa and Google Assistant",
    },
    {
        "id": "PROD-010",
        "name": "Ceramic Plant Pot Set",
        "category": "home_garden",
        "price": 44.99,
        "stock_quantity": 120,
        "warranty_months": 0,
        "description": "Trio of minimalist white ceramic planters with drainage holes and bamboo saucers",
    },
    {
        "id": "PROD-011",
        "name": "Robot Vacuum Cleaner",
        "category": "home_garden",
        "price": 299.99,
        "stock_quantity": 30,
        "warranty_months": 12,
        "description": "LiDAR mapping robotic vacuum with auto-emptying dock and mobile app control",
    },
    {
        "id": "PROD-012",
        "name": "Stainless Steel Cookware Set",
        "category": "home_garden",
        "price": 199.99,
        "stock_quantity": 40,
        "warranty_months": 60,
        "description": "10-piece professional tri-ply stainless steel pots and pans, oven-safe up to 500F",
    },
    # Sports
    {
        "id": "PROD-013",
        "name": "Yoga Mat Premium",
        "category": "sports",
        "price": 49.99,
        "stock_quantity": 200,
        "warranty_months": 12,
        "description": "Extra-dense 6mm non-slip eco-friendly yoga mat with alignment grid and strap",
    },
    {
        "id": "PROD-014",
        "name": "Adjustable Dumbbell Set",
        "category": "sports",
        "price": 249.99,
        "stock_quantity": 15,
        "warranty_months": 24,
        "description": "Pair of quick-adjust dumbbells 5-52.5 lbs with ergonomic knurled steel grip",
    },
    {
        "id": "PROD-015",
        "name": "Insulated Water Bottle 32oz",
        "category": "sports",
        "price": 29.99,
        "stock_quantity": 350,
        "warranty_months": 12,
        "description": "Double-wall vacuum insulated stainless steel canteen keeps drinks cold for 24 hours",
    },
    {
        "id": "PROD-016",
        "name": "Resistance Exercise Bands",
        "category": "sports",
        "price": 19.99,
        "stock_quantity": 180,
        "warranty_months": 12,
        "description": "Set of 5 natural latex loop resistance bands with carry pouch and workout booklet",
    },
    # Books & Toys
    {
        "id": "PROD-017",
        "name": "The Art of Clean Code",
        "category": "books",
        "price": 34.99,
        "stock_quantity": 100,
        "warranty_months": 0,
        "description": "Essential architectural guide to engineering readable, maintainable software systems",
    },
    {
        "id": "PROD-018",
        "name": "Designing Data-Intensive Applications",
        "category": "books",
        "price": 44.99,
        "stock_quantity": 80,
        "warranty_months": 0,
        "description": "Definitive handbook on distributed systems, replication, partitioning, and batch pipelines",
    },
    {
        "id": "PROD-019",
        "name": "Building Block Set (500 pcs)",
        "category": "toys",
        "price": 39.99,
        "stock_quantity": 90,
        "warranty_months": 0,
        "description": "STEM educational interconnecting building bricks with storage tub and blueprints",
    },
    {
        "id": "PROD-020",
        "name": "RC Racing Drone",
        "category": "toys",
        "price": 79.99,
        "stock_quantity": 25,
        "warranty_months": 6,
        "description": "High-speed brushless motor FPV quadcopter with 720p live video transmission",
    },
]


async def seed_database(force: bool = False) -> bool:
    """Idempotently seed database if empty."""
    await init_db()

    async with AsyncSessionLocal() as session:
        # Check if users already exist
        user_count = await session.scalar(select(func.count()).select_from(User))
        if user_count and user_count > 0 and not force:
            logger.info("Database already initialized (%d users present). Skipping seed.", user_count)
            return False

        logger.info("Database is empty. Commencing full idempotent seed...")

        # 1. Insert Admins & Customers
        created_users = []
        for admin_data in ADMIN_USERS:
            u = User(
                name=admin_data["name"],
                email=admin_data["email"],
                password_hash=hash_password(admin_data["password"]),
                role=admin_data["role"],
            )
            session.add(u)
            created_users.append(u)

        customer_map = {}
        for cust_data in CUSTOMER_USERS:
            u = User(
                name=cust_data["name"],
                email=cust_data["email"],
                password_hash=hash_password(cust_data["password"]),
                role=cust_data["role"],
            )
            session.add(u)
            customer_map[cust_data["email"]] = u

        await session.flush()
        logger.info("Inserted %d users (2 admins, %d customers).", len(ADMIN_USERS) + len(CUSTOMER_USERS), len(CUSTOMER_USERS))

        # 2. Insert Products
        product_map = {}
        for prod_data in PRODUCTS:
            p = Product(**prod_data)
            session.add(p)
            product_map[p.id] = p

        await session.flush()
        logger.info("Inserted %d products across 5 categories.", len(PRODUCTS))

        # 3. Generate 30 Orders with diverse dates and statuses
        now = datetime.now(timezone.utc)
        customers_list = list(customer_map.values())
        orders_to_create = []

        # Explicit Orders required by specification:
        # 1) Alice: delivered 5 days ago (eligible for return within 15-day window for electronics)
        alice = customer_map["alice@email.com"]
        ord_alice_5d = Order(
            id="ORD-2024-001",
            customer_id=alice.id,
            customer_email=alice.email,
            status="delivered",
            total_amount=79.99,
            tracking_number="TRK-98214001",
            delivery_date=now - timedelta(days=5),
            created_at=now - timedelta(days=9),
        )
        orders_to_create.append((ord_alice_5d, [("PROD-001", 1)]))

        # 2) Bob: delivered 5 days ago (eligible for return within 30-day window for clothing)
        bob = customer_map["bob@email.com"]
        ord_bob_5d = Order(
            id="ORD-2024-002",
            customer_id=bob.id,
            customer_email=bob.email,
            status="delivered",
            total_amount=149.99,
            tracking_number="TRK-98214002",
            delivery_date=now - timedelta(days=5),
            created_at=now - timedelta(days=10),
        )
        orders_to_create.append((ord_bob_5d, [("PROD-006", 1)]))

        # 3) Alice: delivered 40 days ago (past return window, eligible for warranty only)
        ord_alice_40d = Order(
            id="ORD-2024-003",
            customer_id=alice.id,
            customer_email=alice.email,
            status="delivered",
            total_amount=89.99,
            tracking_number="TRK-98214003",
            delivery_date=now - timedelta(days=40),
            created_at=now - timedelta(days=46),
        )
        orders_to_create.append((ord_alice_40d, [("PROD-004", 1)]))

        # 4) Carol: delivered 40 days ago (past return window, eligible for warranty only)
        carol = customer_map["carol@email.com"]
        ord_carol_40d = Order(
            id="ORD-2024-004",
            customer_id=carol.id,
            customer_email=carol.email,
            status="delivered",
            total_amount=299.99,
            tracking_number="TRK-98214004",
            delivery_date=now - timedelta(days=40),
            created_at=now - timedelta(days=47),
        )
        orders_to_create.append((ord_carol_40d, [("PROD-011", 1)]))

        # 5) Order with existing Return and completed Refund ($39.99 <= $50 auto-approved)
        david = customer_map["david@email.com"]
        ord_david_ret = Order(
            id="ORD-2024-005",
            customer_id=david.id,
            customer_email=david.email,
            status="returned",
            total_amount=39.99,
            tracking_number="TRK-98214005",
            delivery_date=now - timedelta(days=12),
            created_at=now - timedelta(days=18),
        )
        orders_to_create.append((ord_david_ret, [("PROD-009", 1)]))

        # 6) Order with existing Return and pending admin approval refund (> $50)
        emma = customer_map["emma@email.com"]
        ord_emma_pen = Order(
            id="ORD-2024-006",
            customer_id=emma.id,
            customer_email=emma.email,
            status="delivered",
            total_amount=129.99,
            tracking_number="TRK-98214006",
            delivery_date=now - timedelta(days=7),
            created_at=now - timedelta(days=12),
        )
        orders_to_create.append((ord_emma_pen, [("PROD-003", 1)]))

        # Generate 24 additional realistic orders across customers (to total 30 orders)
        status_pool = ["delivered", "shipped", "processing", "pending", "delivered", "cancelled"]
        prod_keys = list(product_map.keys())

        for idx in range(7, 31):
            cust = customers_list[idx % len(customers_list)]
            status = status_pool[idx % len(status_pool)]
            order_id = f"ORD-2024-{idx:03d}"
            days_ago = (idx * 3) % 60 + 2
            created_time = now - timedelta(days=days_ago)

            delivery_time = None
            tracking = None
            if status == "delivered":
                delivery_time = created_time + timedelta(days=4)
                tracking = f"TRK-98214{idx:03d}"
            elif status == "shipped":
                tracking = f"TRK-98214{idx:03d}"

            # Pick 1-2 random items
            chosen_pids = [prod_keys[(idx + 2) % len(prod_keys)]]
            if idx % 3 == 0:
                chosen_pids.append(prod_keys[(idx + 5) % len(prod_keys)])

            total = sum(product_map[p].price for p in chosen_pids)
            order_obj = Order(
                id=order_id,
                customer_id=cust.id,
                customer_email=cust.email,
                status=status,
                total_amount=round(total, 2),
                tracking_number=tracking,
                delivery_date=delivery_time,
                created_at=created_time,
            )
            orders_to_create.append((order_obj, [(p, 1) for p in chosen_pids]))

        # Commit orders and items
        for ord_obj, items in orders_to_create:
            session.add(ord_obj)
            for pid, qty in items:
                p_item = product_map[pid]
                item_obj = OrderItem(
                    order_id=ord_obj.id,
                    product_id=p_item.id,
                    product_name=p_item.name,
                    quantity=qty,
                    unit_price=p_item.price,
                )
                session.add(item_obj)

        await session.flush()

        # Add RMA and Refund fixtures for ORD-2024-005 and ORD-2024-006
        rma_david = Return(
            id="RMA-9005",
            order_id="ORD-2024-005",
            customer_id=david.id,
            reason="Unwanted gift, returned within 30 days unopened.",
            status="approved",
            created_at=now - timedelta(days=4),
        )
        session.add(rma_david)

        ref_david = Refund(
            id="REF-8005",
            return_id="RMA-9005",
            order_id="ORD-2024-005",
            amount=39.99,
            status="completed",
            idempotency_key="seed-key-david-ord-005",
            created_at=now - timedelta(days=3),
        )
        session.add(ref_david)

        rma_emma = Return(
            id="RMA-9006",
            order_id="ORD-2024-006",
            customer_id=emma.id,
            reason="Camera lens has dead pixels out of the box.",
            status="requested",
            created_at=now - timedelta(days=1),
        )
        session.add(rma_emma)

        ref_emma = Refund(
            id="REF-8006",
            return_id="RMA-9006",
            order_id="ORD-2024-006",
            amount=129.99,
            status="pending_admin_approval",
            idempotency_key="seed-key-emma-ord-006",
            created_at=now - timedelta(days=1),
        )
        session.add(ref_emma)

        await session.commit()
        logger.info("Inserted %d orders with line items, returns, and refund scenarios.", len(orders_to_create))

        # 4. Ingest policy documents into pgvector
        logger.info("Ingesting standard policies into pgvector...")
        policy_count = await ingest_policies(session)
        logger.info("Seeding complete: %d policy documents ingested.", policy_count)

    return True


if __name__ == "__main__":
    asyncio.run(seed_database())

