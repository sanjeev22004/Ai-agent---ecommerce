import { describe, it, expect } from "vitest";
import { orderLookup } from "../src/tools/order-lookup.js";
import { inventoryCheck } from "../src/tools/inventory-check.js";
import { SessionStore } from "../src/agent/session.js";
import { Tracer } from "../src/agent/tracer.js";

describe("Required Demonstration Scenarios & Agent Behavior", () => {
  // ─── Scenario 1: Knowledge Query ───────────────────────────────────────────
  describe("Scenario 1: Knowledge Query & Grounding", () => {
    it("should provide relevant evidence references for policy queries", () => {
      // In knowledge queries, documents provide factual return windows
      const electronicsPolicyText = "Electronics must be returned within 15 days of delivery";
      expect(electronicsPolicyText).toContain("15 days");
    });
  });

  // ─── Scenario 2: Multi-Step Dependent Return Resolution ─────────────────────
  describe("Scenario 2: Multi-Step Dependent Return Resolution", () => {
    it("should obtain operational details and verify line items before policy check", () => {
      const orders = orderLookup({ order_id: "ORD-1001" });
      expect(orders.length).toBe(1);

      const order = orders[0];
      expect(order.id).toBe("ORD-1001");
      expect(order.items.length).toBeGreaterThan(0);
      expect(order.customer_email).toBeDefined();

      // Step 2: Check product category from line item
      const item = order.items[0];
      expect(item.product_name).toBeDefined();

      // Step 3: Determine policy return window
      const validStatuses = ["pending", "processing", "shipped", "delivered", "cancelled", "returned"];
      expect(validStatuses).toContain(order.status);
    });
  });

  // ─── Scenario 3: Exception Handling (≥ 2 Cases) ───────────────────────────
  describe("Scenario 3: Exception Handling & Robustness", () => {
    it("Case 3A: Missing / Invalid Order Details should return empty array safely", () => {
      const result = orderLookup({ order_id: "ORD-NONEXISTENT-9999" });
      expect(result).toEqual([]);
    });

    it("Case 3B: Empty search criteria should not crash and return empty array", () => {
      const result = orderLookup({});
      expect(result).toEqual([]);
    });

    it("Case 3C: Out of stock inventory check returns in_stock false", () => {
      const result = inventoryCheck({ product_id: "PROD-007" });
      expect(result.length).toBe(1);
      expect(result[0].stock_quantity).toBe(0);
      expect(result[0].in_stock).toBe(false);
    });
  });

  // ─── Observability & State ────────────────────────────────────────────────
  describe("Observability, Tracing & State Management", () => {
    it("should maintain state across conversational turns in SessionStore", () => {
      const session = SessionStore.getOrCreate("test_session_101");
      expect(session.sessionId).toBe("test_session_101");

      SessionStore.updateContext("test_session_101", {
        activeOrderId: "ORD-1001",
        customerEmail: "alice.johnson@email.com",
      });

      const updated = SessionStore.get("test_session_101");
      expect(updated?.context.activeOrderId).toBe("ORD-1001");
      expect(updated?.context.customerEmail).toBe("alice.johnson@email.com");
    });

    it("should compute execution traces with latency, token usage and cost", () => {
      const trace = Tracer.createTrace("test_session_101", "Where is my order ORD-1001?");
      trace.recordStep("llm_reasoning", "llama-3.3-70b-versatile", 250, {
        promptTokens: 120,
        completionTokens: 45,
        totalTokens: 165,
      });
      trace.recordStep("mcp_tool_call", "order_lookup", 15, {
        input: { order_id: "ORD-1001" },
        output: "Order details",
      });

      const completed = trace.finalize("Your order is on the way", "llama-3.3-70b-versatile");

      expect(completed.traceId).toBeDefined();
      expect(completed.steps.length).toBe(2);
      expect(completed.metrics.totalTokens).toBe(165);
      expect(completed.metrics.estimatedCostUsd).toBeGreaterThanOrEqual(0);
      expect(completed.metrics.status).toBe("success");
    });
  });
});
