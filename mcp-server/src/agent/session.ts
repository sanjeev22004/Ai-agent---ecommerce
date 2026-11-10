/**
 * Session Store & Conversation State Management
 *
 * Implements stateful tracking across turns:
 * - Session lifecycle & cleanup
 * - Verified customer / order context persistence
 * - Multi-step workflow state machine (e.g. return eligibility & RMA generation)
 */

import crypto from "node:crypto";

export interface ConversationMessage {
  role: "user" | "assistant" | "system";
  content: string;
}

export interface WorkflowState {
  workflowType: "return_resolution" | "order_inquiry" | "general";
  step: number;
  data: Record<string, unknown>;
  completedSteps: string[];
}

export interface SessionState {
  sessionId: string;
  createdAt: string;
  lastActiveAt: string;
  history: ConversationMessage[];
  context: {
    customerId?: string;
    customerEmail?: string;
    activeOrderId?: string;
    activeProductId?: string;
  };
  workflow?: WorkflowState;
}

export class SessionStore {
  private static sessions = new Map<string, SessionState>();
  private static readonly TTL_MS = 60 * 60 * 1000; // 1 hour TTL

  static getOrCreate(sessionId?: string): SessionState {
    const now = new Date().toISOString();

    if (sessionId && SessionStore.sessions.has(sessionId)) {
      const session = SessionStore.sessions.get(sessionId)!;
      session.lastActiveAt = now;
      return session;
    }

    const newId = sessionId || `sess_${crypto.randomUUID().slice(0, 8)}`;
    const newSession: SessionState = {
      sessionId: newId,
      createdAt: now,
      lastActiveAt: now,
      history: [],
      context: {},
    };

    SessionStore.sessions.set(newId, newSession);
    return newSession;
  }

  static get(sessionId: string): SessionState | undefined {
    return SessionStore.sessions.get(sessionId);
  }

  static updateContext(
    sessionId: string,
    updates: Partial<SessionState["context"]>
  ): void {
    const session = SessionStore.get(sessionId);
    if (session) {
      session.context = { ...session.context, ...updates };
      session.lastActiveAt = new Date().toISOString();
    }
  }

  static setWorkflow(sessionId: string, workflow: WorkflowState): void {
    const session = SessionStore.get(sessionId);
    if (session) {
      session.workflow = workflow;
      session.lastActiveAt = new Date().toISOString();
    }
  }

  static clearWorkflow(sessionId: string): void {
    const session = SessionStore.get(sessionId);
    if (session) {
      delete session.workflow;
    }
  }

  static cleanupExpired(): void {
    const cutoff = Date.now() - SessionStore.TTL_MS;
    for (const [id, session] of SessionStore.sessions.entries()) {
      if (new Date(session.lastActiveAt).getTime() < cutoff) {
        SessionStore.sessions.delete(id);
      }
    }
  }
}

