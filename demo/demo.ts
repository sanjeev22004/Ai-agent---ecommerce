/**
 * Assignment Demonstration Script
 *
 * Demonstrates the 3 mandatory assessment scenarios from the assignment document:
 *
 * Scenario 1 — Knowledge query:
 *   Answer question about applicable policy and show supporting source evidence.
 *
 * Scenario 2 — Multi-step resolution:
 *   Given an order ID and a customer question about a return, obtain operational
 *   details, consult relevant policy evidence, and determine the appropriate next step.
 *
 * Scenario 3 — Exception handling (2+ cases):
 *   Case 3A: Non-existent order ID (safe handling, no hallucination)
 *   Case 3B: Unverified or missing order details
 *   Case 3C: Out-of-stock replacement inquiry
 *
 * Run with: npx tsx demo/demo.ts
 */

const API_URL = process.env.API_URL || "http://localhost:3000";

interface TraceMetrics {
  totalDurationMs: number;
  totalTokens: number;
  promptTokens: number;
  completionTokens: number;
  estimatedCostUsd: number;
  llmCallsCount: number;
  mcpToolCallsCount: number;
  status: string;
}

interface ChatResponse {
  response: string;
  sessionId: string;
  toolCalls: {
    tool: string;
    args: Record<string, unknown>;
    result: string;
    durationMs?: number;
  }[];
  timing: {
    totalMs: number;
  };
  trace?: {
    traceId: string;
    metrics: TraceMetrics;
  };
}

const SCENARIOS = [
  {
    section: "SCENARIO 1 — Knowledge Query & Source Evidence",
    description:
      "Customer asks about electronics return policy. Agent queries policy via MCP and provides supporting source citation.",
    message: "What is your return policy for electronics, and are there any restocking fees?",
  },
  {
    section: "SCENARIO 2 — Multi-Step Resolution (Order + Policy + Return Decision)",
    description:
      "Customer asks to return an item from ORD-1001. Agent looks up order operational data, retrieves category policy, checks window eligibility, and determines the next step.",
    message:
      "I would like to return the item from my order ORD-1001. Can you check my order and let me know if I am eligible for a return and what the next step is?",
  },
  {
    section: "SCENARIO 3A — Exception: Invalid / Non-Existent Order ID",
    description:
      "Customer queries non-existent order ORD-9999. Agent safely informs the customer without hallucinating details.",
    message: "Where is my order ORD-9999? When will it arrive?",
  },
  {
    section: "SCENARIO 3B — Exception: Delivery Delay Compensation & Policy Check",
    description:
      "Customer reports late shipment on ORD-1001. Agent chains order lookup with compensation policy lookup.",
    message:
      "My order ORD-1001 seems delayed. Can you check the delivery status and tell me what compensation policy applies?",
  },
  {
    section: "SCENARIO 3C — Exception: Out of Stock Replacement Inquiry",
    description:
      "Customer asks for a replacement for Running Shoes Ultra (PROD-007). Agent queries inventory and detects 0 stock.",
    message:
      "Can I get a replacement pair of Running Shoes Ultra (PROD-007)? Are they currently in stock?",
  },
];

async function sendMessage(message: string, sessionId?: string): Promise<ChatResponse> {
  const response = await fetch(`${API_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, sessionId }),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`API error ${response.status}: ${text}`);
  }

  return (await response.json()) as ChatResponse;
}

function printDivider(): void {
  console.log("\n" + "═".repeat(78) + "\n");
}

async function runDemo(): Promise<void> {
  console.log("╔══════════════════════════════════════════════════════════════════════════════╗");
  console.log("║           Agentic AI Engineering — 1-Week Assignment Demo                    ║");
  console.log("║           MCP Server + Stateful Agent + Multi-Format RAG                     ║");
  console.log("╚══════════════════════════════════════════════════════════════════════════════╝");

  // Health check
  try {
    const health = await fetch(`${API_URL}/health`).then((r) => r.json());
    console.log(`\nSystem Health: ${health.status.toUpperCase()}`);
    console.log(`MCP Connected: ${health.mcp?.connected} (${health.mcp?.toolsCount} tools discovered)`);
    console.log(`LLM Model:     ${health.llm?.model} (${health.llm?.provider})`);
    console.log(`Orders in DB:  ${health.database?.orders}`);
  } catch (err) {
    console.error(`\nCould not connect to ${API_URL}. Ensure both services are running:`);
    console.error("  1. Terminal 1: cd rag-service && python -m src.main");
    console.error("  2. Terminal 2: cd mcp-server && npm run dev\n");
    process.exit(1);
  }

  let activeSessionId: string | undefined = undefined;

  for (let i = 0; i < SCENARIOS.length; i++) {
    const s = SCENARIOS[i];
    printDivider();
    console.log(`▶ [${s.section}]`);
    console.log(`  Intent: ${s.description}\n`);
    console.log(`  Customer: "${s.message}"\n`);

    const result = await sendMessage(s.message, activeSessionId);
    activeSessionId = result.sessionId;

    console.log(`  ⚡ MCP Tool Calls Discovered & Executed (${result.toolCalls.length}):`);
    if (result.toolCalls.length === 0) {
      console.log("     (Direct response — no tools required)");
    } else {
      for (const tc of result.toolCalls) {
        const duration = tc.durationMs ? `${tc.durationMs}ms` : "N/A";
        console.log(`     → Tool: ${tc.tool} [${duration}]`);
        console.log(`       Args:   ${JSON.stringify(tc.args)}`);
        console.log(`       Output: ${tc.result.slice(0, 140)}...`);
      }
    }

    console.log(`\n  🤖 Agent Response:`);
    console.log(`     ${result.response.replace(/\n/g, "\n     ")}`);

    if (result.trace) {
      const m = result.trace.metrics;
      console.log(`\n  📊 Observability Trace [${result.trace.traceId}]:`);
      console.log(
        `     Latency: ${m.totalDurationMs}ms | Tokens: ${m.totalTokens} (Prompt: ${m.promptTokens}, Completion: ${m.completionTokens}) | Cost: $${m.estimatedCostUsd}`
      );
    }
  }

  printDivider();
  console.log("All required demonstration scenarios completed successfully!");
}

runDemo().catch(console.error);
