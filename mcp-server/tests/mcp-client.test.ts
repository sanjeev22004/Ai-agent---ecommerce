import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { AgentMcpClient } from "../src/agent/mcp-client.js";
import { cleanToolArguments } from "../src/agent/orchestrator.js";

describe("Model Context Protocol (MCP) Client-Server Integration", () => {
  let mcpClient: AgentMcpClient;

  beforeAll(async () => {
    mcpClient = new AgentMcpClient();
    await mcpClient.connect();
  });

  afterAll(async () => {
    await mcpClient.close();
  });

  it("should successfully connect via InMemoryTransport and discover tools", async () => {
    const tools = await mcpClient.listTools();
    expect(tools.length).toBeGreaterThanOrEqual(4);

    const toolNames = tools.map((t) => t.name);
    expect(toolNames).toContain("order_lookup");
    expect(toolNames).toContain("inventory_check");
    expect(toolNames).toContain("policy_search");
    expect(toolNames).toContain("response_draft");
  });

  it("should dynamically convert MCP tool schemas to OpenAI ChatCompletionTool format", async () => {
    const openAiTools = await mcpClient.getOpenAITools();
    expect(openAiTools.length).toBeGreaterThanOrEqual(3);

    const names = openAiTools.map((t) => t.function.name);
    expect(names).toContain("order_lookup");
    expect(names).toContain("inventory_check");
    expect(names).toContain("policy_search");

    const orderLookupTool = openAiTools.find((t) => t.function.name === "order_lookup");
    expect(orderLookupTool).toBeDefined();
    expect(orderLookupTool?.function.parameters).toHaveProperty("properties");
  });

  it("should execute order_lookup through MCP protocol and return serialized order data", async () => {
    const result = await mcpClient.callTool("order_lookup", {
      order_id: "ORD-1001",
    });

    expect(result.isError).toBe(false);
    expect(result.tool).toBe("order_lookup");
    expect(result.content).toContain("ORD-1001");
  });

  it("should handle invalid parameters safely via MCP schema validation without crashing", async () => {
    const result = await mcpClient.callTool("order_lookup", {
      status: "non_existent_status_value",
    });

    // Zod schema error or graceful validation response
    expect(typeof result.content).toBe("string");
  });

  it("should normalize complex JSON Schema wrapper and malformed arguments from local LLMs", () => {
    // Model emits nested schema wrapper: { type: "object", properties: { ... } }
    const cleaned = cleanToolArguments(
      "policy_search",
      {
        type: "object",
        properties: {
          method: "dense",
          query: "what is the return policy for electronics?",
          top_k: {},
        },
      },
      "What is the return policy?"
    );

    expect(cleaned.query).toBe("what is the return policy for electronics?");
    expect(cleaned.method).toBe("dense");
    expect(cleaned.top_k).toBeUndefined(); // Empty object was cleanly stripped

    // Model omits order_id in order_lookup
    const cleanedOrder = cleanToolArguments(
      "order_lookup",
      {},
      "Please check ORD-1002 status"
    );
    expect(cleanedOrder.order_id).toBe("ORD-1002");
  });
});

