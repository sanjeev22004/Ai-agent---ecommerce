/**
 * Policy Search Tool
 *
 * Calls the Python RAG microservice to search policy documents.
 * This is the microservice boundary — TypeScript calls Python via HTTP.
 *
 * Supports Dense Vector Search, BM25 Lexical Search, and Hybrid RRF Fusion.
 */

import { config } from "../config.js";

export interface PolicyChunk {
  text: string;
  source: string;
  score: number;
  format?: string;
}

export interface PolicySearchResult {
  query: string;
  results: PolicyChunk[];
  total_chunks: number;
  method?: string;
}

export interface PolicySearchInput {
  query: string;
  top_k?: number;
  method?: "dense" | "bm25" | "hybrid";
}

/**
 * Search policy documents via the RAG microservice.
 * Returns relevant policy chunks ranked by hybrid/semantic similarity.
 */
export async function policySearch(input: PolicySearchInput): Promise<PolicySearchResult> {
  const url = `${config.rag.baseUrl}/search`;

  try {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query: input.query,
        top_k: input.top_k ?? 3,
        method: input.method ?? "hybrid",
      }),
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`RAG service returned ${response.status}: ${errorText}`);
    }

    const data = (await response.json()) as PolicySearchResult;
    return data;
  } catch (error) {
    // If the RAG service is down or unreachable, return a graceful degraded structure
    if (error instanceof TypeError && error.message.includes("fetch")) {
      return {
        query: input.query,
        results: [],
        total_chunks: 0,
        method: input.method ?? "hybrid",
      };
    }

    throw error;
  }
}
