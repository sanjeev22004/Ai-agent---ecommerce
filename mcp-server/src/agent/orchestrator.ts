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

  for (let iteration = 0; iteration < MAX_ITERATIONS; iteration++) {
    const llmStartTime = Date.now();
    let choice;

    try {
      const response = await client.chat.completions.create({
        model: config.llm.model,
        messages,
        tools: tools.length > 0 ? tools : undefined,
        temperature: 0.2, // Low temperature for deterministic tool calling
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
