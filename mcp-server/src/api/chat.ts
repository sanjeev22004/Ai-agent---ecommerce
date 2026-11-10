/**
 * Express chat endpoint — the HTTP API layer.
 *
 * POST /chat
 *   Body: { message: string, sessionId?: string, history?: ConversationMessage[] }
 *   Returns: { response, toolCalls, sessionId, timing, trace }
 */

import { Router, type Request, type Response } from "express";
import { orchestrate, type ConversationMessage } from "../agent/orchestrator.js";
import { SessionStore } from "../agent/session.js";

export const chatRouter = Router();

interface ChatRequest {
  message: string;
  sessionId?: string;
  history?: ConversationMessage[];
}

chatRouter.post("/chat", async (req: Request, res: Response) => {
  const startTime = Date.now();

  try {
    const { message, sessionId, history } = req.body as ChatRequest;

    if (!message || typeof message !== "string" || message.trim().length === 0) {
      res.status(400).json({
        error: "Missing or empty 'message' field in request body",
      });
      return;
    }

    const session = SessionStore.getOrCreate(sessionId);
    if (history && history.length > 0 && session.history.length === 0) {
      session.history = [...history];
    }

    console.log(`\n[Chat] [Session ${session.sessionId}] Received: "${message}"`);

    const result = await orchestrate(message.trim(), session);

    const elapsed = Date.now() - startTime;
    console.log(
      `[Chat] Responded in ${elapsed}ms (${result.toolCalls.length} MCP tool call(s))`
    );

    res.json({
      response: result.response,
      toolCalls: result.toolCalls,
      sessionId: result.sessionId,
      timing: {
        totalMs: elapsed,
      },
      trace: result.trace,
    });
  } catch (error) {
    const elapsed = Date.now() - startTime;
    console.error(`[Chat] Error after ${elapsed}ms:`, error);

    res.status(500).json({
      error: "Internal server error",
      message:
        error instanceof Error
          ? error.message
          : "An unexpected error occurred",
    });
  }
});
