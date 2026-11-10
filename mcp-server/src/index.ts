/**
 * Entry point — starts the Express API server.
 *
 * Wires together:
 *   - Express API with POST /chat and GET /traces endpoints
 *   - Genuine Model Context Protocol (MCP) Server & Client integration
 *   - SQLite database (auto-seeds if empty)
 *   - Observability & execution trace recorder
 */

import express from "express";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { config } from "./config.js";
import { chatRouter } from "./api/chat.js";
import { getAgentMcpClient } from "./agent/mcp-client.js";
import { Tracer } from "./agent/tracer.js";
import { SessionStore } from "./agent/session.js";
import { getDb } from "./db/connection.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

async function main(): Promise<void> {
  console.log("\n╔══════════════════════════════════════════════╗");
  console.log("║   E-Commerce Support Copilot                ║");
  console.log("║   MCP Server + Agent Orchestrator           ║");
  console.log("╚══════════════════════════════════════════════╝\n");

  // ─── Database check ──────────────────────────────────────────────────────
  const db = getDb();
  const orderCount = (
    db.prepare("SELECT COUNT(*) as count FROM orders").get() as {
      count: number;
    }
  ).count;

  if (orderCount === 0) {
    console.log(
      "[DB] Database is empty. Run 'npm run seed' to populate with mock data.\n"
    );
  } else {
    console.log(`[DB] SQLite connected — ${orderCount} orders in database`);
  }

  // ─── MCP Client & Server Connection ──────────────────────────────────────
  console.log("[MCP] Initializing Model Context Protocol Client & Server...");
  const mcpClient = await getAgentMcpClient();
  const discoveredTools = await mcpClient.listTools();
  console.log(
    `[MCP] Connected! Discovered ${discoveredTools.length} tool(s) via protocol:`,
    discoveredTools.map((t) => t.name).join(", ")
  );

  // ─── Express API ─────────────────────────────────────────────────────────
  const app = express();
  app.use(express.json());

  // Health check
  app.get("/health", (_req, res) => {
    res.json({
      status: "healthy",
      service: "ecommerce-support-copilot",
      mcp: {
        connected: true,
        transport: "InMemoryTransport",
        toolsCount: discoveredTools.length,
      },
      llm: {
        provider: config.llm.provider,
        model: config.llm.model,
        baseUrl: config.llm.baseUrl,
      },
      rag: {
        serviceUrl: config.rag.baseUrl,
      },
      database: {
        orders: orderCount,
      },
    });
  });

  // Observability & traces endpoint
  app.get("/traces", (req, res) => {
    const limit = parseInt(req.query.limit as string, 10) || 20;
    res.json({
      traces: Tracer.getRecentTraces(limit),
    });
  });

  // Session inspection endpoint
  app.get("/sessions/:id", (req, res) => {
    const session = SessionStore.get(req.params.id);
    if (!session) {
      res.status(404).json({ error: "Session not found" });
      return;
    }
    res.json(session);
  });

  // Chat endpoint
  app.use(chatRouter);

  // Serve static frontend
  const publicDir = path.join(process.cwd(), "public");
  console.log(`[Static] Serving frontend from ${publicDir}`);
  app.use(express.static(publicDir));

  // Start server
  app.listen(config.server.port, () => {
    console.log(`[API] Express server listening on http://localhost:${config.server.port}`);
    console.log(`\n── Configuration ──`);
    console.log(`  LLM Provider:  ${config.llm.provider}`);
    console.log(`  LLM Model:     ${config.llm.model}`);
    console.log(`  LLM Base URL:  ${config.llm.baseUrl}`);
    console.log(`  RAG Service:   ${config.rag.baseUrl}`);
    console.log(`  Database:      ${config.db.path}`);
    console.log(`\n── Endpoints ──`);
    console.log(`  GET  /          — Brutalist chat UI`);
    console.log(`  POST /chat     — Send a customer support message`);
    console.log(`  GET  /traces   — Execution traces, token & cost observations`);
    console.log(`  GET  /health   — Health check + MCP config info`);
    console.log("");
  });
}

main().catch((error) => {
  console.error("Failed to start server:", error);
  process.exit(1);
});
