/**
 * MCP Client Wrapper
 *
 * Implements standard Model Context Protocol (MCP) client-server integration
 * using InMemoryTransport.
 *
 * Flow:
 * 1. Creates a linked transport pair (clientTransport <-> serverTransport).
 * 2. Connects the McpServer to serverTransport and Client to clientTransport.
 * 3. Discovers registered tools dynamically via `client.listTools()`.
 * 4. Converts MCP tool schemas into OpenAI-compatible function calling format for the LLM.
 * 5. Executes tool calls via `client.callTool()`, ensuring full protocol validation.
 */

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import type { ChatCompletionTool } from "openai/resources/chat/completions.js";
import { createMcpServer } from "../server.js";

export interface McpToolCallResult {
  tool: string;
  args: Record<string, unknown>;
  content: string;
  isError: boolean;
}

export class AgentMcpClient {
  private client: Client;
  private isConnected = false;
  private cachedOpenAITools: ChatCompletionTool[] = [];

  constructor() {
    this.client = new Client(
      {
        name: "ecommerce-support-agent-client",
        version: "1.0.0",
      },
      {
        capabilities: {},
      }
    );
  }

  /**
   * Initializes the MCP Server, links transport, and connects the Client.
   */
  async connect(): Promise<void> {
    if (this.isConnected) return;

    const mcpServer = createMcpServer();
    const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();

    await mcpServer.connect(serverTransport);
    await this.client.connect(clientTransport);

    this.isConnected = true;
    console.log("[MCP Client] Successfully connected to MCP Server via InMemoryTransport");

    // Pre-cache discovered tools in OpenAI function format
    await this.refreshTools();
  }

  /**
   * Queries the MCP server for available tools using MCP protocol `tools/list`.
   */
  async listTools() {
    this.ensureConnected();
    const result = await this.client.listTools();
    return result.tools;
  }

  /**
   * Returns tools converted to OpenAI ChatCompletionTool format.
   * Enables dynamic tool schema discovery by the LLM without hardcoding.
   */
  async getOpenAITools(): Promise<ChatCompletionTool[]> {
    this.ensureConnected();
    if (this.cachedOpenAITools.length === 0) {
      await this.refreshTools();
    }
    return this.cachedOpenAITools;
  }

  /**
   * Refresh tool registry from MCP server and convert to OpenAI format.
   */
  async refreshTools(): Promise<void> {
    const mcpTools = await this.listTools();

    this.cachedOpenAITools = mcpTools
      // response_draft is excluded from the agentic tool-loop to prevent infinite loops,
      // as the orchestrator synthesizes the final response directly.
      .filter((tool) => tool.name !== "response_draft")
      .map((tool) => ({
        type: "function" as const,
        function: {
          name: tool.name,
          description: tool.description || "",
          parameters: (tool.inputSchema as Record<string, unknown>) || {
            type: "object",
            properties: {},
          },
        },
      }));

    console.log(
      `[MCP Client] Discovered and registered ${this.cachedOpenAITools.length} tools via MCP protocol:`,
      this.cachedOpenAITools.map((t) => t.function.name)
    );
  }

  /**
   * Executes a tool via MCP protocol `tools/call`.
   */
  async callTool(name: string, args: Record<string, unknown>): Promise<McpToolCallResult> {
    this.ensureConnected();

    try {
      const response = await this.client.callTool({
        name,
        arguments: args,
      });

      const isError = Boolean(response.isError);
      let contentText = "";

      if (Array.isArray(response.content)) {
        contentText = response.content
          .map((c) => (c.type === "text" ? c.text : JSON.stringify(c)))
          .join("\n");
      } else {
        contentText = JSON.stringify(response.content);
      }

      return {
        tool: name,
        args,
        content: contentText,
        isError,
      };
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : "MCP tool execution failed";
      console.error(`[MCP Client] Error calling tool ${name}:`, errorMsg);
      return {
        tool: name,
        args,
        content: `Tool execution error: ${errorMsg}`,
        isError: true,
      };
    }
  }

  /**
   * Closes the MCP client connection.
   */
  async close(): Promise<void> {
    if (this.isConnected) {
      await this.client.close();
      this.isConnected = false;
      console.log("[MCP Client] Disconnected");
    }
  }

  private ensureConnected(): void {
    if (!this.isConnected) {
      throw new Error("AgentMcpClient is not connected. Call connect() first.");
    }
  }
}

// Global singleton instance for the agent orchestrator
let defaultClient: AgentMcpClient | null = null;

export async function getAgentMcpClient(): Promise<AgentMcpClient> {
  if (!defaultClient) {
    defaultClient = new AgentMcpClient();
    await defaultClient.connect();
  }
  return defaultClient;
}

