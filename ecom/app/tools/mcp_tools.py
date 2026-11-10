"""Official Python MCP tool definitions with strict Pydantic input schemas.

Implements transactional e-commerce lifecycle:
1. order_lookup (with customer role scoping)
2. inventory_check
3. place_order
4. request_return
5. process_refund (with idempotency and $50 approval threshold)
6. policy_search (with pgvector and date-filtering)
"""

from datetime import datetime, timezone
import json
import logging
import random
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from sqlalchemy import select, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Order, OrderItem, Product, Return, Refund, User
from app.rag.retriever import search_policies

# Official Python MCP MCPServer
try:
    from mcp.server.mcpserver import MCPServer
    mcp_server = MCPServer("ecom-support")
except Exception:
    mcp_server = None

logger = logging.getLogger(__name__)


# ─── Pydantic Schemas ────────────────────────────────────────────────────────

class OrderLookupInput(BaseModel):
    order_id: Optional[str] = Field(None, description="Order ID (e.g., 'ORD-1001')")
    email: Optional[str] = Field(None, description="Customer email address")
    status: Optional[str] = Field(
        None,
        description="Filter by order status: 'pending', 'processing', 'shipped', 'delivered', 'returned', 'cancelled'",
    )


class InventoryCheckInput(BaseModel):
    name: Optional[str] = Field(None, description="Product name or keyword (e.g., 'Headphones', 'Webcam')")
    id: Optional[str] = Field(None, description="Product ID (e.g., 'PROD-001')")
    category: Optional[str] = Field(
        None,
        description="Product category ('electronics', 'clothing', 'home_garden', 'sports', 'books', 'toys')",
    )


class OrderItemInput(BaseModel):
    product_id: str = Field(..., description="Product ID (e.g. 'PROD-001')")
    quantity: int = Field(..., gt=0, description="Quantity to purchase")


class PlaceOrderInput(BaseModel):
    customer_email: str = Field(..., description="Customer's email address")
    items: List[OrderItemInput] = Field(..., min_length=1, description="List of items with product_id and quantity")


class RequestReturnInput(BaseModel):
    order_id: str = Field(..., description="Order ID to return (must be in 'delivered' status)")
    product_id: str = Field(..., description="Product ID to return")
    reason: str = Field(..., min_length=3, description="Reason for return request")


class ProcessRefundInput(BaseModel):
    order_id: str = Field(..., description="Associated Order ID (e.g. 'ORD-1001')")
    rma_code: str = Field(..., description="Approved Return authorization code (e.g. 'RMA-9021')")
    amount: float = Field(..., gt=0, description="Refund amount in USD")
    idempotency_key: str = Field(..., min_length=8, description="Unique client idempotency key to prevent double refunds")


class PolicySearchInput(BaseModel):
    query: str = Field(..., description="Policy question or search keywords")
    top_k: int = Field(3, description="Maximum number of policy sections to retrieve")
    order_date: Optional[str] = Field(None, description="Order purchase date to filter applicable policies")


# ─── OpenAI Tool Specifications ───────────────────────────────────────────────

OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "order_lookup",
            "description": "Look up existing order status, delivery date, line items, and tracking number by order_id, email, or status.",
            "parameters": OrderLookupInput.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inventory_check",
            "description": "Check current stock level, unit price, category, and warranty duration for products in the catalog.",
            "parameters": InventoryCheckInput.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "place_order",
            "description": "Place a new customer order. Validates inventory, decrements stock, and creates order records.",
            "parameters": PlaceOrderInput.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_return",
            "description": "Initiate a product return request. Verifies order is 'delivered' and generates an official RMA tracking code.",
            "parameters": RequestReturnInput.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "process_refund",
            "description": "Process a monetary refund for an RMA return. Auto-approves under $50; requires admin review if > $50.",
            "parameters": ProcessRefundInput.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "policy_search",
            "description": "Search return, shipping, compensation, and warranty policies using semantic vector search with date filtering.",
            "parameters": PolicySearchInput.model_json_schema(),
        },
    },
]


# ─── Tool Implementations ─────────────────────────────────────────────────────

async def tool_order_lookup(
    session: AsyncSession,
    current_user: Optional[User],
    params: OrderLookupInput,
) -> Dict[str, Any]:
    """Execute order lookup with customer security scoping."""
    # Build query
    stmt = select(Order).options(selectinload(Order.items), selectinload(Order.returns))
    conditions = []

    # Security Scoping: Customer role can ONLY view their own orders
    if current_user and current_user.role == "customer":
        conditions.append(Order.customer_email == current_user.email)
        # If user explicitly asked for a different email, deny
        if params.email and params.email.lower().strip() != current_user.email.lower():
            return {
                "error": "Access Denied: Customers can only query orders associated with their own verified email address.",
                "orders": [],
            }
    elif params.email:
        conditions.append(Order.customer_email.ilike(f"%{params.email.strip()}%"))

    if params.order_id:
        conditions.append(Order.id == params.order_id.strip().upper())

    if params.status:
        conditions.append(Order.status == params.status.strip().lower())

    if not conditions:
        return {
            "error": "Please provide an order_id, customer email, or status to search orders.",
            "orders": [],
        }

    stmt = stmt.where(and_(*conditions)).order_by(Order.created_at.desc()).limit(10)
    result = await session.execute(stmt)
    orders = result.scalars().all()

    if not orders:
        return {
            "message": "No orders found matching the specified search criteria.",
            "orders": [],
        }

    output = []
    for o in orders:
        items_summary = [
            {
                "product_id": item.product_id,
                "product_name": item.product_name,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
            }
            for item in o.items
        ]
        returns_summary = [
            {"rma_code": r.id, "reason": r.reason, "status": r.status}
            for r in o.returns
        ]
        output.append({
            "order_id": o.id,
            "customer_email": o.customer_email,
            "status": o.status,
            "total_amount": o.total_amount,
            "tracking_number": o.tracking_number,
            "delivery_date": o.delivery_date.isoformat() if o.delivery_date else None,
            "created_at": o.created_at.isoformat() if o.created_at else None,
            "items": items_summary,
            "returns": returns_summary,
        })

    return {"count": len(output), "orders": output}


async def tool_inventory_check(
    session: AsyncSession,
    params: InventoryCheckInput,
) -> Dict[str, Any]:
    """Execute product catalog inventory and warranty search."""
    stmt = select(Product)
    conditions = []

    if params.id:
        conditions.append(Product.id == params.id.strip().upper())
    if params.name:
        conditions.append(Product.name.ilike(f"%{params.name.strip()}%"))
    if params.category:
        conditions.append(Product.category.ilike(f"%{params.category.strip()}%"))

    if conditions:
        stmt = stmt.where(or_(*conditions))

    stmt = stmt.order_by(Product.name.asc()).limit(15)
    result = await session.execute(stmt)
    products = result.scalars().all()

    if not products:
        return {"message": "No matching products found in catalog.", "products": []}

    output = [
        {
            "product_id": p.id,
            "name": p.name,
            "category": p.category,
            "price": p.price,
            "stock_quantity": p.stock_quantity,
            "in_stock": p.stock_quantity > 0,
            "warranty_months": p.warranty_months,
            "description": p.description,
        }
        for p in products
    ]
    return {"count": len(output), "products": output}


async def tool_place_order(
    session: AsyncSession,
    current_user: Optional[User],
    params: PlaceOrderInput,
) -> Dict[str, Any]:
    """Place a new customer order with inventory validation and stock decrement."""
    target_email = params.customer_email.strip().lower()

    # Customer scoping check
    if current_user and current_user.role == "customer":
        if target_email != current_user.email.lower():
            return {"error": "Customers cannot place orders under a different email address."}
        user = current_user
    else:
        # Admin or system placement
        res = await session.execute(select(User).where(User.email == target_email))
        user = res.scalar_one_or_none()
        if not user:
            return {"error": f"No registered customer account found for email: {target_email}."}

    # Validate all items
    total_amount = 0.0
    items_to_create = []

    for item_req in params.items:
        prod_res = await session.execute(select(Product).where(Product.id == item_req.product_id.strip().upper()))
        product = prod_res.scalar_one_or_none()
        if not product:
            return {"error": f"Product '{item_req.product_id}' does not exist in catalog."}

        if product.stock_quantity < item_req.quantity:
            return {
                "error": f"Insufficient stock for '{product.name}' ({product.id}). Available: {product.stock_quantity}, Requested: {item_req.quantity}."
            }

        # Decrement inventory
        product.stock_quantity -= item_req.quantity
        line_total = product.price * item_req.quantity
        total_amount += line_total

        items_to_create.append({
            "product_id": product.id,
            "product_name": product.name,
            "quantity": item_req.quantity,
            "unit_price": product.price,
        })

    order_id = f"ORD-{random.randint(1000, 9999)}"
    tracking_no = f"TRK-{random.randint(10000000, 99999999)}"

    new_order = Order(
        id=order_id,
        customer_id=user.id,
        customer_email=user.email,
        status="processing",
        total_amount=round(total_amount, 2),
        tracking_number=tracking_no,
        delivery_date=None,
        created_at=datetime.now(timezone.utc),
    )
    session.add(new_order)
    await session.flush()

    for item_data in items_to_create:
        order_item = OrderItem(
            order_id=order_id,
            product_id=item_data["product_id"],
            product_name=item_data["product_name"],
            quantity=item_data["quantity"],
            unit_price=item_data["unit_price"],
        )
        session.add(order_item)

    await session.commit()

    return {
        "status": "success",
        "order_id": order_id,
        "customer_email": user.email,
        "order_status": "processing",
        "total_amount": round(total_amount, 2),
        "tracking_number": tracking_no,
        "items_count": len(items_to_create),
        "message": f"Order {order_id} placed successfully. Warehouse status: processing.",
    }


async def tool_request_return(
    session: AsyncSession,
    current_user: Optional[User],
    params: RequestReturnInput,
) -> Dict[str, Any]:
    """Initiate a return request for an item in a delivered order."""
    order_res = await session.execute(
        select(Order)
        .options(selectinload(Order.items), selectinload(Order.returns))
        .where(Order.id == params.order_id.strip().upper())
    )
    order = order_res.scalar_one_or_none()

    if not order:
        return {"error": f"Order '{params.order_id}' was not found in our system."}

    # Ownership check
    if current_user and current_user.role == "customer":
        if order.customer_email.lower() != current_user.email.lower():
            return {"error": "Access Denied: You cannot request returns for orders belonging to another customer."}

    # State validation: must be 'delivered'
    if order.status.lower() != "delivered":
        return {
            "error": f"Cannot return order '{order.id}'. Returns are only permitted for delivered orders. Current order status: '{order.status}'."
        }

    # Verify product is part of order
    product_in_order = any(item.product_id == params.product_id.strip().upper() for item in order.items)
    if not product_in_order:
        valid_items = [f"{item.product_id} ({item.product_name})" for item in order.items]
        return {
            "error": f"Product '{params.product_id}' is not in order '{order.id}'. Valid items in this order: {', '.join(valid_items)}."
        }

    rma_code = f"RMA-{random.randint(1000, 9999)}"
    return_record = Return(
        id=rma_code,
        order_id=order.id,
        customer_id=order.customer_id,
        reason=params.reason.strip(),
        status="requested",
        created_at=datetime.now(timezone.utc),
    )
    session.add(return_record)
    await session.commit()

    return {
        "status": "success",
        "rma_code": rma_code,
        "order_id": order.id,
        "product_id": params.product_id.upper(),
        "return_status": "requested",
        "message": f"Return request initiated successfully with authorization code {rma_code}. You may print a prepaid label or proceed to refund evaluation.",
    }


async def tool_process_refund(
    session: AsyncSession,
    current_user: Optional[User],
    params: ProcessRefundInput,
) -> Dict[str, Any]:
    """Process a refund with idempotency protection and a $50 admin approval limit."""
    # 1. Guardrail: Idempotency check to prevent duplicate refunds
    existing_refund_res = await session.execute(
        select(Refund).where(Refund.idempotency_key == params.idempotency_key.strip())
    )
    existing_refund = existing_refund_res.scalar_one_or_none()
    if existing_refund:
        return {
            "status": "idempotent_duplicate",
            "refund_id": existing_refund.id,
            "refund_status": existing_refund.status,
            "amount": existing_refund.amount,
            "message": f"Refund with idempotency key '{params.idempotency_key}' was already processed with status '{existing_refund.status}'. Duplicate transaction prevented.",
        }

    # 2. Validate Order & Return
    order_res = await session.execute(select(Order).where(Order.id == params.order_id.strip().upper()))
    order = order_res.scalar_one_or_none()
    if not order:
        return {"error": f"Order '{params.order_id}' was not found."}

    return_res = await session.execute(select(Return).where(Return.id == params.rma_code.strip().upper()))
    return_record = return_res.scalar_one_or_none()
    if not return_record or return_record.order_id != order.id:
        return {
            "error": f"No valid return request matching RMA code '{params.rma_code}' for order '{order.id}'. Please initiate a return request first."
        }

    # Ownership check
    if current_user and current_user.role == "customer":
        if order.customer_email.lower() != current_user.email.lower():
            return {"error": "Access Denied: You cannot process refunds for another customer's order."}

    refund_id = f"REF-{random.randint(1000, 9999)}"
    amount = round(params.amount, 2)

    # 3. Guardrail: Threshold check ($50 limit)
    if amount <= 50.0:
        refund_status = "completed"
        order.status = "returned"
        return_record.status = "approved"
        message = f"Refund of ${amount:.2f} processed and completed automatically (under the $50 threshold). Order '{order.id}' status set to 'returned'."
    else:
        refund_status = "pending_admin_approval"
        message = f"Refund amount ${amount:.2f} exceeds automatic threshold ($50.00). Refund registered with status 'pending_admin_approval'. An administrator must approve the transaction."

    refund_obj = Refund(
        id=refund_id,
        return_id=return_record.id,
        order_id=order.id,
        amount=amount,
        status=refund_status,
        idempotency_key=params.idempotency_key.strip(),
        created_at=datetime.now(timezone.utc),
    )
    session.add(refund_obj)
    await session.commit()

    return {
        "status": "success",
        "refund_id": refund_id,
        "rma_code": return_record.id,
        "order_id": order.id,
        "amount": amount,
        "refund_status": refund_status,
        "requires_admin_approval": refund_status == "pending_admin_approval",
        "message": message,
    }


async def tool_policy_search(
    session: AsyncSession,
    params: PolicySearchInput,
) -> Dict[str, Any]:
    """Execute pgvector semantic search over store policies with active date filtering."""
    results = await search_policies(
        session=session,
        query=params.query,
        top_k=params.top_k,
        order_date=params.order_date,
    )
    if not results:
        return {
            "message": "No relevant policies found matching the query.",
            "results": [],
        }

    return {
        "count": len(results),
        "query": params.query,
        "order_date_filtered": params.order_date,
        "results": results,
    }


# ─── Tool Router ──────────────────────────────────────────────────────────────

async def execute_tool(
    name: str,
    args: Dict[str, Any],
    session: AsyncSession,
    current_user: Optional[User] = None,
) -> Dict[str, Any]:
    """Route tool call by name with strict schema validation."""
    logger.info("Executing tool '%s' with args: %s (User: %s)", name, args, current_user.email if current_user else "anonymous")
    try:
        if name == "order_lookup":
            parsed = OrderLookupInput.model_validate(args)
            return await tool_order_lookup(session, current_user, parsed)

        elif name == "inventory_check":
            parsed = InventoryCheckInput.model_validate(args)
            return await tool_inventory_check(session, parsed)

        elif name == "place_order":
            parsed = PlaceOrderInput.model_validate(args)
            return await tool_place_order(session, current_user, parsed)

        elif name == "request_return":
            parsed = RequestReturnInput.model_validate(args)
            return await tool_request_return(session, current_user, parsed)

        elif name == "process_refund":
            parsed = ProcessRefundInput.model_validate(args)
            return await tool_process_refund(session, current_user, parsed)

        elif name == "policy_search":
            parsed = PolicySearchInput.model_validate(args)
            return await tool_policy_search(session, parsed)

        else:
            return {"error": f"Unknown tool name: '{name}'"}
    except Exception as exc:
        logger.exception("Error executing tool '%s': %s", name, exc)
        return {"error": f"Failed to execute {name}: {str(exc)}"}
