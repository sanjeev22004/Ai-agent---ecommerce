import path from "node:path";
import { fileURLToPath } from "node:url";
import dotenv from "dotenv";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Load .env from project root and mcp-server root
dotenv.config({ path: path.join(__dirname, "..", ".env") });
dotenv.config({ path: path.join(__dirname, "..", "..", ".env") });

const rawProvider = (process.env.LLM_PROVIDER || "ollama").toLowerCase();
const provider = (rawProvider === "grok" ? "groq" : rawProvider) as "ollama" | "groq" | "gemini";

let defaultBaseUrl = "http://localhost:11434/v1";
let defaultModel = "llama3.2";

if (provider === "groq") {
  defaultBaseUrl = "https://api.groq.com/openai/v1";
  defaultModel = "openai/gpt-oss-120b";
} else if (provider === "gemini") {
  defaultBaseUrl = "https://generativelanguage.googleapis.com/v1beta/openai/";
  defaultModel = "gemini-2.5-flash";
}

export const config = {
  // ─── Database ────────────────────────────────────────────────────────────
  db: {
    path: process.env.DB_PATH || path.join(__dirname, "..", "data", "ecommerce.db"),
  },

  // ─── RAG Service ───────────────────────────────────────────────
  rag: {
    baseUrl: process.env.RAG_SERVICE_URL || "http://localhost:8000",
  },

  // ─── LLM Provider ──────────────────────────────────────────────────────
  llm: {
    provider,
    model: process.env.LLM_MODEL || defaultModel,
    baseUrl: process.env.LLM_BASE_URL || defaultBaseUrl,
    apiKey: process.env.LLM_API_KEY || process.env.GEMINI_API_KEY || "ollama",
  },

  // ─── Server ─────────────────────────────────────────────────────────────
  server: {
    port: parseInt(process.env.PORT || "3000", 10),
  },
} as const;
