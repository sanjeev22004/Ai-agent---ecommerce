"""SQLAlchemy models for ecom application.

Includes relational ERP entities, pgvector-based policies, chat sessions,
and execution traces.
"""

from datetime import datetime, timezone
import uuid
from typing import Any, List, Optional

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    JSON,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator
from pgvector.sqlalchemy import Vector


class Base(DeclarativeBase):
    pass


class VectorType(TypeDecorator):
    """Vector type using pgvector on PostgreSQL when available and JSON otherwise."""

    impl = JSON
    cache_ok = True
    HAS_PGVECTOR: bool = False

    def __init__(self, dim: int = 384, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.dim = dim

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql" and VectorType.HAS_PGVECTOR:
            return dialect.type_descriptor(Vector(self.dim))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if hasattr(value, "tolist"):
            return value.tolist()
        return list(value)

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        return value


# ─── 1. User Model ────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="customer")  # 'admin' | 'customer'
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    orders: Mapped[List["Order"]] = relationship("Order", back_populates="customer", cascade="all, delete-orphan")
    returns: Mapped[List["Return"]] = relationship("Return", back_populates="customer", cascade="all, delete-orphan")
    sessions: Mapped[List["ChatSession"]] = relationship("ChatSession", back_populates="user", cascade="all, delete-orphan")


# ─── 2. Product Model ─────────────────────────────────────────────────────────

class Product(Base):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # e.g., 'PROD-001'
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    stock_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warranty_months: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    description: Mapped[str] = mapped_column(Text, nullable=False)


# ─── 3. Order Model ───────────────────────────────────────────────────────────

class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # e.g., 'ORD-1001'
    customer_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    customer_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        index=True,
    )  # 'pending', 'processing', 'shipped', 'delivered', 'returned', 'cancelled'
    total_amount: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    tracking_number: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    delivery_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    # Relationships
    customer: Mapped["User"] = relationship("User", back_populates="orders")
    items: Mapped[List["OrderItem"]] = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan", lazy="selectin")
    returns: Mapped[List["Return"]] = relationship("Return", back_populates="order", cascade="all, delete-orphan", lazy="selectin")
    refunds: Mapped[List["Refund"]] = relationship("Refund", back_populates="order", cascade="all, delete-orphan", lazy="selectin")


# ─── 4. OrderItem Model ───────────────────────────────────────────────────────

class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(32), ForeignKey("orders.id"), nullable=False, index=True)
    product_id: Mapped[str] = mapped_column(String(32), ForeignKey("products.id"), nullable=False, index=True)
    product_name: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)

    # Relationships
    order: Mapped["Order"] = relationship("Order", back_populates="items")
    product: Mapped["Product"] = relationship("Product")


# ─── 5. Return Model ──────────────────────────────────────────────────────────

class Return(Base):
    __tablename__ = "returns"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # e.g., 'RMA-9021'
    order_id: Mapped[str] = mapped_column(String(32), ForeignKey("orders.id"), nullable=False, index=True)
    customer_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="requested",
    )  # 'requested', 'approved', 'rejected'
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    order: Mapped["Order"] = relationship("Order", back_populates="returns")
    customer: Mapped["User"] = relationship("User", back_populates="returns")
    refunds: Mapped[List["Refund"]] = relationship("Refund", back_populates="return_req", cascade="all, delete-orphan", lazy="selectin")


# ─── 6. Refund Model ──────────────────────────────────────────────────────────

class Refund(Base):
    __tablename__ = "refunds"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # e.g., 'REF-5001'
    return_id: Mapped[str] = mapped_column(String(32), ForeignKey("returns.id"), nullable=False, index=True)
    order_id: Mapped[str] = mapped_column(String(32), ForeignKey("orders.id"), nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="pending_admin_approval",
    )  # 'completed', 'pending_admin_approval'
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    return_req: Mapped["Return"] = relationship("Return", back_populates="refunds")
    order: Mapped["Order"] = relationship("Order", back_populates="refunds")


# ─── 7. Policy Model (pgvector) ───────────────────────────────────────────────

class Policy(Base):
    __tablename__ = "policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    format: Mapped[str] = mapped_column(String(20), nullable=False)  # 'markdown', 'json'
    source_file: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0")
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    embedding: Mapped[List[float]] = mapped_column(VectorType(384), nullable=False)


# ─── 8. ChatSession Model ─────────────────────────────────────────────────────

class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="New Conversation")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="sessions")
    messages: Mapped[List["ChatMessage"]] = relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ChatMessage.id",
    )
    traces: Mapped[List["ExecutionTrace"]] = relationship(
        "ExecutionTrace",
        back_populates="session",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ExecutionTrace.created_at.desc()",
    )


# ─── 9. ChatMessage Model ─────────────────────────────────────────────────────

class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("chat_sessions.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # 'user', 'assistant', 'system'
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tool_calls_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    session: Mapped["ChatSession"] = relationship("ChatSession", back_populates="messages")


# ─── 10. ExecutionTrace Model ─────────────────────────────────────────────────

class ExecutionTrace(Base):
    __tablename__ = "execution_traces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("chat_sessions.id"), nullable=True, index=True)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_message: Mapped[str] = mapped_column(Text, nullable=False)
    final_response: Mapped[str] = mapped_column(Text, nullable=False)
    total_latency_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="success")
    steps_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    # Relationships
    session: Mapped[Optional["ChatSession"]] = relationship("ChatSession", back_populates="traces")
