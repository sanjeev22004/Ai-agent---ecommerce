/**
 * Agent Orchestrator — the "brain" of the support copilot.
 *
 * Implements genuine Model Context Protocol (MCP) integration:
 * - Discovers available tools dynamically via MCP Client protocol (tools/list)
 * - Converts MCP schemas into LLM function specifications
 * - Executes tool calls over MCP protocol (tools/call)
 * - Tracks per-step execution traces (latency, token usage, cost)
 * - Manages stateful sessions
 */

import OpenAI from "openai";
import type {
  ChatCompletionMessageParam,
  ChatCompletionTool,
} from "openai/resources/chat/completions.js";
import { config } from "../config.js";
import { getAgentMcpClient } from "./mcp-client.js";
import { SessionStore, type SessionState, type ConversationMessage } from "./session.js";
import { Tracer, type ExecutionTrace } from "./tracer.js";
import { ORCHESTRATOR_SYSTEM_PROMPT } from "./prompts.js";

export { ConversationMessage };

export interface ToolCallRecord {
  tool: string;
  args: Record<string, unknown>;
  result: string;
  isError?: boolean;
  durationMs?: number;
}

export interface OrchestratorResult {
  response: string;
  toolCalls: ToolCallRecord[];
  trace?: ExecutionTrace;
  sessionId: string;
}

const MAX_ITERATIONS = 5;

/**
 * Unwraps and normalizes tool call arguments from LLMs.
 * Handles quirks of local/quantized models (e.g. Llama 3.2 1B emitting JSON schema
 * wrappers, empty object parameters, or stringified numbers).
 */
export function cleanToolArguments(
  toolName: string,
  rawArgs: Record<string, unknown>,
  userMessage: string,
  activeOrderId?: string
): Record<string, unknown> {
  let args: Record<string, unknown> = { ...rawArgs };

  // 1. Unwrap JSON Schema wrappers: { type: "object", properties: { ... } }
  if (args.properties && typeof args.properties === "object" && !Array.isArray(args.properties)) {
    args = { ...(args.properties as Record<string, unknown>) };
  }
  if (args.parameters && typeof args.parameters === "object" && !Array.isArray(args.parameters)) {
    args = { ...(args.parameters as Record<string, unknown>) };
  }
  if (args.arguments && typeof args.arguments === "object" && !Array.isArray(args.arguments)) {
    args = { ...(args.arguments as Record<string, unknown>) };
  }
  if (args.input && typeof args.input === "object" && !Array.isArray(args.input)) {
    args = { ...(args.input as Record<string, unknown>) };
  }

  // 2. Remove any property where value is an object containing schema definition metadata ({ type: "...", description: "..." }) or is empty
  for (const [key, value] of Object.entries(args)) {
    if (value !== null && typeof value === "object") {
      const obj = value as Record<string, unknown>;
      if (
        obj.type ||
        obj.description ||
        Object.keys(obj).length === 0 ||
        Array.isArray(obj)
      ) {
        delete args[key];
      }
    }
  }

  // 3. Tool-specific normalization and fallbacks
  if (toolName === "policy_search") {
    // If query is missing or not a non-empty string, extract from alternatives or userMessage
    if (typeof args.query !== "string" || !args.query.trim()) {
      const fallbackQuery =
        (typeof args.question === "string" && args.question) ||
        (typeof args.q === "string" && args.q) ||
        (typeof args.text === "string" && args.text) ||
        (typeof args.topic === "string" && args.topic) ||
        (typeof args.policy === "string" && args.policy) ||
        (typeof args.prompt === "string" && args.prompt) ||
        userMessage;
      args.query = String(fallbackQuery || userMessage || "return policy").trim();
    }

    // top_k must be an integer number, or omitted
    if (typeof args.top_k === "string") {
      const parsed = parseInt(args.top_k, 10);
      if (!isNaN(parsed) && parsed > 0) {
        args.top_k = parsed;
      } else {
        delete args.top_k;
      }
    } else if (typeof args.top_k !== "number" || isNaN(args.top_k as number)) {
      delete args.top_k;
    }

    // method must be dense | bm25 | hybrid
    if (
      args.method &&
      !["dense", "bm25", "hybrid"].includes(String(args.method).toLowerCase())
    ) {
      delete args.method;
    }
  } else if (toolName === "order_lookup") {
    if (!args.order_id && args.orderId) {
      args.order_id = args.orderId;
    }

    // If order_id is not a string, delete it so we can re-infer
    if (typeof args.order_id !== "string" || !args.order_id.trim()) {
      delete args.order_id;
    } else {
      // If it has spaces or extra words, extract the ORD-XXXX pattern
      const m = (args.order_id as string).match(/\b(ORD-\d{4})\b/i);
      if (m) {
        args.order_id = m[1].toUpperCase();
      }
    }

    // If email is not a valid string containing @, delete it
    if (typeof args.email !== "string" || !args.email.includes("@")) {
      delete args.email;
    }

    // If status is not a recognized string, delete it
    if (typeof args.status !== "string") {
      delete args.status;
    }

    // Infer order_id or email from user message or active session if missing
    if (!args.order_id && !args.email && !args.status) {
      const orderMatch = userMessage.match(/\b(ORD-\d{4})\b/i);
      if (orderMatch) {
        args.order_id = orderMatch[1].toUpperCase();
      } else if (activeOrderId) {
        args.order_id = activeOrderId;
      } else {
        const emailMatch = userMessage.match(/[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/);
        if (emailMatch) {
          args.email = emailMatch[0].toLowerCase();
        }
      }
    }
  } else if (toolName === "inventory_check") {
    if (!args.product_id && args.productId) {
      args.product_id = args.productId;
    }
    if (!args.product_name && args.productName) {
      args.product_name = args.productName;
    }

    if (typeof args.product_id === "string") {
      const m = (args.product_id as string).match(/\b(PROD-\d{3})\b/i);
      if (m) args.product_id = m[1].toUpperCase();
    } else {
      delete args.product_id;
    }

    if (typeof args.product_name !== "string" || !args.product_name.trim()) {
      delete args.product_name;
    }

    if (!args.product_id && !args.product_name && !args.category) {
      const prodMatch = userMessage.match(/\b(PROD-\d{3})\b/i);
      if (prodMatch) {
        args.product_id = prodMatch[1].toUpperCase();
      } else {
        args.product_name = userMessage;
      }
    }
  } else if (toolName === "response_draft") {
    if (!args.customer_message || typeof args.customer_message !== "string") {
      args.customer_message = userMessage;
    }
    if (!args.context || typeof args.context !== "string") {
      args.context = "Support query regarding order or policy.";
    }
  }

  return args;
}

/**
 * Run the agent orchestrator.
 *
 * Discovers tools dynamically via the MCP client, runs the reasoning loop,
 * logs execution traces, and updates session state.
 */
export async function orchestrate(
  userMessage: string,
  sessionOrHistory: SessionState | ConversationMessage[] = [],
  explicitSessionId?: string
): Promise<OrchestratorResult> {
  // Normalize session
  let session: SessionState;
  if ("sessionId" in sessionOrHistory && typeof sessionOrHistory.sessionId === "string") {
    session = sessionOrHistory;
  } else {
    session = SessionStore.getOrCreate(explicitSessionId);
    if (Array.isArray(sessionOrHistory) && sessionOrHistory.length > 0) {
      session.history = [...sessionOrHistory];
    }
  }

  // Initialize tracer
  const activeTrace = Tracer.createTrace(session.sessionId, userMessage);

  // Initialize MCP client & fetch dynamic tool schemas
  const mcpClient = await getAgentMcpClient();
  const tools: ChatCompletionTool[] = await mcpClient.getOpenAITools();

  const client = new OpenAI({
    baseURL: config.llm.baseUrl,
    apiKey: config.llm.apiKey,
  });

  // Build message history
  const contextHeader = session.context.activeOrderId
    ? `\nActive Context: Customer Order ID is ${session.context.activeOrderId}.`
    : "";

  const messages: ChatCompletionMessageParam[] = [
    { role: "system", content: ORCHESTRATOR_SYSTEM_PROMPT + contextHeader },
    ...session.history.map((msg) => ({
      role: msg.role as "user" | "assistant" | "system",
      content: msg.content,
    })),
    { role: "user", content: userMessage },
  ];

  const toolCallRecords: ToolCallRecord[] = [];
  const seenCalls = new Set<string>();

  // Detect non-ecommerce / coding / algorithm / greeting queries
  const isGeneralOrCoding =
    /\b(code|cpp|c\+\+|python|java|javascript|typescript|spiral\s*matrix|algorithm|leetcode|programming|function|write\s*a\s*program)\b/i.test(userMessage) ||
    /^(hi|hello|hey|good\s*morning|good\s*afternoon|howdy)\b/i.test(userMessage.trim());

  for (let iteration = 0; iteration < MAX_ITERATIONS; iteration++) {
    const llmStartTime = Date.now();
    let choice;

    // Disallow tools if it's a coding/general query, or if tools were already executed in prior iterations
    const allowTools =
      !isGeneralOrCoding &&
      tools.length > 0 &&
      (toolCallRecords.length === 0 || iteration < 2);

    try {
      const response = await client.chat.completions.create({
        model: config.llm.model,
        messages,
        tools: allowTools ? tools : undefined,
        temperature: 0.1, // Low temperature for deterministic tool calling
        max_tokens: 600,  // Bound output tokens to prevent runaway generations
      });

      const llmDuration = Date.now() - llmStartTime;
      choice = response.choices[0];

      activeTrace.recordStep("llm_reasoning", config.llm.model, llmDuration, {
        promptTokens: response.usage?.prompt_tokens,
        completionTokens: response.usage?.completion_tokens,
        totalTokens: response.usage?.total_tokens,
        model: config.llm.model,
      });
    } catch (err) {
      const llmDuration = Date.now() - llmStartTime;
      const errorMsg = err instanceof Error ? err.message : "LLM API error";
      console.error("[Orchestrator] LLM completion failed:", errorMsg);

      activeTrace.recordStep("llm_reasoning", config.llm.model, llmDuration, {
        isError: true,
        output: errorMsg,
      });

      const finalTrace = activeTrace.finalize(
        "I encountered a temporary service issue connecting to the AI model. Please try again shortly.",
        config.llm.model,
        "error"
      );

      return {
        response:
          "I apologize, but our automated resolution service is temporarily degraded. Please try again in a few moments or contact support@example.com.",
        toolCalls: toolCallRecords,
        trace: finalTrace,
        sessionId: session.sessionId,
      };
    }

    if (!choice) {
      const finalTrace = activeTrace.finalize(
        "No response generated from LLM",
        config.llm.model,
        "error"
      );
      return {
        response: "I'm sorry, I wasn't able to process your request.",
        toolCalls: toolCallRecords,
        trace: finalTrace,
        sessionId: session.sessionId,
      };
    }

    const assistantMessage = choice.message;

    // Fallback: If no tool_calls array, check if model output JSON tool call in text
    if (
      (!assistantMessage.tool_calls || assistantMessage.tool_calls.length === 0) &&
      assistantMessage.content
    ) {
      const jsonMatch = assistantMessage.content.match(
        /\{[\s\S]*"(?:name|tool)"\s*:\s*"(order_lookup|policy_search|inventory_check|response_draft)"[\s\S]*\}/
      );
      if (jsonMatch) {
        try {
          const parsed = JSON.parse(jsonMatch[0]);
          const toolName = parsed.name || parsed.tool;
          if (toolName) {
            assistantMessage.tool_calls = [
              {
                id: `call_${Date.now()}`,
                type: "function",
                function: {
                  name: toolName,
                  arguments: JSON.stringify(
                    parsed.arguments || parsed.parameters || parsed.args || parsed.properties || {}
                  ),
                },
              },
            ];
          }
        } catch {
          // Ignore invalid JSON regex matches
        }
      }
    }

    // Handle MCP Tool Calls
    if (assistantMessage.tool_calls && assistantMessage.tool_calls.length > 0) {
      messages.push(assistantMessage);

      for (const toolCall of assistantMessage.tool_calls) {
        let args: Record<string, unknown> = {};
        try {
          args = JSON.parse(toolCall.function.arguments || "{}");
        } catch {
          args = {};
        }

        // Clean & normalize tool arguments across model families
        args = cleanToolArguments(
          toolCall.function.name,
          args,
          userMessage,
          session.context.activeOrderId
        );

        const callSignature = `${toolCall.function.name}:${JSON.stringify(args)}`;
        if (seenCalls.has(callSignature)) {
          console.log(`  [Loop Protection] Skipping duplicate tool call: ${callSignature}`);
          continue;
        }
        seenCalls.add(callSignature);

        console.log(
          `  [MCP Tool Call] ${toolCall.function.name}(${JSON.stringify(args)})`
        );

        // Track context if user provided order_id
        if (typeof args.order_id === "string") {
          SessionStore.updateContext(session.sessionId, {
            activeOrderId: args.order_id,
          });
        }

        const toolStartTime = Date.now();
        // Invoke via the MCP Client protocol boundary
        const mcpResult = await mcpClient.callTool(toolCall.function.name, args);
        const toolDuration = Date.now() - toolStartTime;

        activeTrace.recordStep("mcp_tool_call", toolCall.function.name, toolDuration, {
          input: args,
          output: mcpResult.content.slice(0, 500),
          isError: mcpResult.isError,
        });

        toolCallRecords.push({
          tool: toolCall.function.name,
          args,
          result:
            mcpResult.content.length > 500
              ? mcpResult.content.substring(0, 500) + "... (truncated)"
              : mcpResult.content,
          isError: mcpResult.isError,
          durationMs: toolDuration,
        });

        // Append tool result into LLM message history
        messages.push({
          role: "tool",
          tool_call_id: toolCall.id,
          content: mcpResult.content,
        });
      }

      // Continue loop for LLM to reason over tool output or call additional dependent tools
      continue;
    }

    // No tool calls — final response generated
    const finalAnswer =
      assistantMessage.content || "I'm sorry, I wasn't able to generate a response.";

    // Update conversation session history
    session.history.push({ role: "user", content: userMessage });
    session.history.push({ role: "assistant", content: finalAnswer });

    const finalTrace = activeTrace.finalize(finalAnswer, config.llm.model, "success");

    return {
      response: finalAnswer,
      toolCalls: toolCallRecords,
      trace: finalTrace,
      sessionId: session.sessionId,
    };
  }

  // Hit iteration limit
  const maxLimitMsg =
    "I gathered the relevant details but reached my single-turn processing limit. Please confirm if you would like me to proceed with the next step.";
  const finalTrace = activeTrace.finalize(
    maxLimitMsg,
    config.llm.model,
    "max_iterations_reached"
  );

  return {
    response: maxLimitMsg,
    toolCalls: toolCallRecords,
    trace: finalTrace,
    sessionId: session.sessionId,
  };
}
