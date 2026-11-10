"""Stateful Agent Orchestrator with ReAct loop, guardrails, and observability.

Implements:
1. Off-Topic & Greeting Triage (Zero-tool direct answering)
2. Prompt Injection Defense & Parameter Sanitization
3. Execution Loop Guardrails (Max 5 iterations, duplicate tool prevention)
4. Full Observability with ExecutionTrace and ChatMessage persistence in PostgreSQL
"""

from datetime import datetime, timezone
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import ChatMessage, ChatSession, ExecutionTrace, User
from app.tools.mcp_tools import OPENAI_TOOLS, execute_tool
from app.agent.prompts import (
    ORCHESTRATOR_SYSTEM_PROMPT,
    OFF_TOPIC_RESPONSE,
    GREETING_RESPONSE,
)
from app.agent.tracer import ActiveTrace

logger = logging.getLogger(__name__)

# Injection pattern regexes
INJECTION_REGEX = re.compile(
    r"(ignore\s+(all\s+)?(previous|prior|above)\s+instructions|"
    r"disregard\s+system\s+prompt|"
    r"system\s+override|"
    r"you\s+are\s+now\s+(in\s+developer\s+mode|unrestricted|an\s+evil)|"
    r"jailbreak|"
    r"bypass\s+all\s+safety|"
    r"reveal\s+your\s+system\s+prompt)",
    re.IGNORECASE,
)

# Greeting regex
GREETING_REGEX = re.compile(
    r"^(hi|hello|hey|howdy|greetings|good\s+(morning|afternoon|evening|day))[\s!.,?]*$",
    re.IGNORECASE,
)

# Off-topic patterns (coding, leetcode, general essays, math)
OFF_TOPIC_REGEX = re.compile(
    r"\b(write\s+(a\s+)?(python|javascript|typescript|c\+\+|java|rust|go|code|script|program)|"
    r"leetcode|hackerrank|spiral\s+matrix|binary\s+tree|quicksort|merge\s+sort|"
    r"reverse\s+linked\s+list|fibonacci|solve\s+(this\s+)?(equation|math|integral)|"
    r"write\s+(an\s+)?essay\s+on|who\s+was\s+(napoleon|caesar|alexander))\b",
    re.IGNORECASE,
)


def triage_message(user_message: str) -> Optional[str]:
    """Pre-screen queries for greetings or off-topic requests.

    Returns a direct string answer if detected, or None to proceed to the agent loop.
    """
    clean_msg = user_message.strip()

    # 1. Simple greetings
    if GREETING_REGEX.match(clean_msg):
        return GREETING_RESPONSE

    # 2. Thank yous
    if re.match(r"^(thanks|thank\s+you|thx)[\s!.,]*$", clean_msg, re.IGNORECASE):
        return "You're very welcome! Let me know if you need any other assistance with your orders or products."

    # 3. Off-topic coding / math / essays
    if OFF_TOPIC_REGEX.search(clean_msg):
        return OFF_TOPIC_RESPONSE

    return None


def sanitize_parameter_value(val: Any) -> Any:
    """Sanitize parameter values and neutralize prompt injections."""
    if isinstance(val, str):
        if INJECTION_REGEX.search(val):
            logger.warning("Potential prompt injection pattern detected in parameter: %r", val)
            # Neutralize instruction override
            return INJECTION_REGEX.sub("[BLOCKED_INJECTION_PHRASE]", val)
        return val
    elif isinstance(val, dict):
        return {k: sanitize_parameter_value(v) for k, v in val.items()}
    elif isinstance(val, list):
        return [sanitize_parameter_value(x) for x in val]
    return val


def normalize_tool_arguments(tool_name: str, raw_args: Dict[str, Any]) -> Dict[str, Any]:
    """Clean and normalize tool arguments from local or hosted models."""
    args = dict(raw_args)

    # Unwrap nested schemas like {"properties": {...}} or {"input": {...}}
    for key in ("properties", "parameters", "arguments", "input"):
        if key in args and isinstance(args[key], dict) and not isinstance(args[key], list):
            args = dict(args[key])

    # Strip empty dict metadata objects
    clean: Dict[str, Any] = {}
    for k, v in args.items():
        if isinstance(v, dict) and not v:
            continue
        clean[k] = sanitize_parameter_value(v)

    return clean


class AgentOrchestrator:
    def __init__(self):
        self.client = AsyncOpenAI(
            base_url=settings.LLM_BASE_URL,
            api_key=settings.LLM_API_KEY,
        )
        self.model_name = settings.LLM_MODEL

    async def get_or_create_session(
        self,
        db_session: AsyncSession,
        user: User,
        session_id: Optional[str] = None,
        first_message: str = "New Chat",
    ) -> ChatSession:
        """Fetch existing session or create a new session for the user."""
        if session_id:
            res = await db_session.execute(
                select(ChatSession).where(
                    ChatSession.id == session_id,
                    ChatSession.user_id == user.id if user.role != "admin" else True,
                )
            )
            chat_sess = res.scalar_one_or_none()
            if chat_sess:
                return chat_sess

        # Create fresh session
        title = first_message.strip()[:40] if first_message else "New Conversation"
        chat_sess = ChatSession(
            user_id=user.id,
            title=title,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db_session.add(chat_sess)
        await db_session.flush()
        return chat_sess

    async def run(
        self,
        db_session: AsyncSession,
        user: User,
        user_message: str,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute full ReAct loop with guardrails, tracing, and persistence."""
        chat_session = await self.get_or_create_session(
            db_session, user, session_id, first_message=user_message
        )
        user_info = {
            "user_id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role,
        }
        user_details_json = json.dumps(user_info)
        trace = ActiveTrace(
            chat_session.id,
            user_message,
            model_name=self.model_name,
            user_details=user_info,
        )

        # ── 1. Off-Topic Triage ───────────────────────────────────────────────
        direct_reply = triage_message(user_message)
        if direct_reply:
            step = trace.start_step("triage_direct", "Off-topic / Greeting direct response", {"query": user_message})
            step.finish(output=direct_reply)

            # Persist ChatMessage
            user_msg_record = ChatMessage(
                session_id=chat_session.id,
                role="user",
                content=user_message,
                created_at=datetime.now(timezone.utc),
            )
            asst_msg_record = ChatMessage(
                session_id=chat_session.id,
                role="assistant",
                content=direct_reply,
                created_at=datetime.now(timezone.utc),
            )
            db_session.add(user_msg_record)
            db_session.add(asst_msg_record)

            final_trace = trace.finalize(direct_reply, status="triage_direct")
            db_trace = ExecutionTrace(
                session_id=chat_session.id,
                user_details=user_details_json,
                trace_id=final_trace["trace_id"],
                user_message=user_message,
                final_response=direct_reply,
                total_latency_ms=final_trace["total_latency_ms"],
                prompt_tokens=final_trace["prompt_tokens"],
                completion_tokens=final_trace["completion_tokens"],
                estimated_cost_usd=final_trace["estimated_cost_usd"],
                status=final_trace["status"],
                steps_json=final_trace["steps_json"],
                created_at=datetime.now(timezone.utc),
            )
            db_session.add(db_trace)
            await db_session.commit()

            return {
                "session_id": chat_session.id,
                "response": direct_reply,
                "tool_calls": [],
                "trace": final_trace,
            }

        # ── 2. Build Message History ──────────────────────────────────────────
        role_restriction = (
            "- Customer Scoping: You are scoped ONLY to orders for " + user.email +
            ". Deny requests to view, return, or refund orders for any other customer."
            if user.role == "customer"
            else "- Admin Privileges: You can inspect any order, view pending refunds, and examine traces."
        )

        sys_prompt = ORCHESTRATOR_SYSTEM_PROMPT.format(
            user_name=user.name,
            user_email=user.email,
            user_role=user.role,
            role_restriction=role_restriction,
        )

        # Retrieve last 10 session messages for context
        res_history = await db_session.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == chat_session.id)
            .order_by(ChatMessage.id.desc())
            .limit(10)
        )
        recent_messages = list(reversed(res_history.scalars().all()))

        messages: List[Dict[str, Any]] = [{"role": "system", "content": sys_prompt}]
        for m in recent_messages:
            messages.append({"role": m.role, "content": m.content})
        messages.append({"role": "user", "content": user_message})

        # ── 3. Stateful ReAct Loop ────────────────────────────────────────────
        executed_tool_calls: List[Dict[str, Any]] = []
        executed_signatures: set[str] = set()
        iterations = 0
        final_text = ""

        while iterations < settings.MAX_ITERATIONS:
            iterations += 1
            llm_step = trace.start_step(
                "llm_reasoning",
                f"LLM Step {iterations}",
                {"messages_count": len(messages)},
            )

            try:
                completion = await self.client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    tools=OPENAI_TOOLS,
                    tool_choice="auto",
                    temperature=0.1,
                )
            except Exception as e:
                logger.exception("LLM API call failed: %s", e)
                error_msg = f"I encountered a temporary communication issue with our AI reasoning service ({str(e)[:80]}). Please try again."
                llm_step.finish(output={"error": str(e)}, is_error=True)
                final_text = error_msg
                break

            response_msg = completion.choices[0].message
            usage = completion.usage
            prompt_tok = usage.prompt_tokens if usage else 0
            comp_tok = usage.completion_tokens if usage else 0

            llm_step.finish(
                output={"content": response_msg.content, "tool_calls_count": len(response_msg.tool_calls or [])},
                prompt_tokens=prompt_tok,
                completion_tokens=comp_tok,
            )

            # If no tools called, we have our final synthesized response
            if not response_msg.tool_calls:
                final_text = response_msg.content or "How else can I assist you?"
                break

            # Process tool calls
            tool_calls_data = []
            for tc in response_msg.tool_calls:
                tool_calls_data.append({
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                })

            messages.append({
                "role": "assistant",
                "content": response_msg.content,
                "tool_calls": tool_calls_data,
            })

            # Execute each requested tool
            for tc in response_msg.tool_calls:
                fn_name = tc.function.name
                raw_args_str = tc.function.arguments or "{}"
                try:
                    raw_args = json.loads(raw_args_str)
                except Exception:
                    raw_args = {}

                norm_args = normalize_tool_arguments(fn_name, raw_args)
                sig = f"{fn_name}:{json.dumps(norm_args, sort_keys=True)}"

                # Loop Guardrail: prevent duplicate calls with same parameters
                if sig in executed_signatures:
                    logger.warning("Loop protection: duplicate call %s skipped.", sig)
                    tool_result = {"error": f"Tool '{fn_name}' was already executed with identical parameters in this turn."}
                else:
                    executed_signatures.add(sig)
                    t_step = trace.start_step("tool_call", f"Tool: {fn_name}", norm_args)
                    tool_result = await execute_tool(fn_name, norm_args, db_session, current_user=user)
                    t_step.finish(output=tool_result)

                executed_tool_calls.append({
                    "tool": fn_name,
                    "args": norm_args,
                    "result": tool_result,
                })

                # Injection Defense: strictly inject tool response as role: "tool"
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": fn_name,
                    "content": json.dumps(tool_result, ensure_ascii=False),
                })

        if not final_text:
            final_text = (
                "I have compiled the required order and policy information. "
                "Please let me know if you would like to proceed with any further steps."
            )

        # ── 4. Observability & Persistence ────────────────────────────────────
        final_trace = trace.finalize(
            final_text,
            status="success" if iterations < settings.MAX_ITERATIONS else "max_iterations_reached",
        )

        user_msg_record = ChatMessage(
            session_id=chat_session.id,
            role="user",
            content=user_message,
            created_at=datetime.now(timezone.utc),
        )
        asst_msg_record = ChatMessage(
            session_id=chat_session.id,
            role="assistant",
            content=final_text,
            tool_calls_json=json.dumps(executed_tool_calls) if executed_tool_calls else None,
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(user_msg_record)
        db_session.add(asst_msg_record)

        db_trace = ExecutionTrace(
            session_id=chat_session.id,
            user_details=user_details_json,
            trace_id=final_trace["trace_id"],
            user_message=user_message,
            final_response=final_text,
            total_latency_ms=final_trace["total_latency_ms"],
            prompt_tokens=final_trace["prompt_tokens"],
            completion_tokens=final_trace["completion_tokens"],
            estimated_cost_usd=final_trace["estimated_cost_usd"],
            status=final_trace["status"],
            steps_json=final_trace["steps_json"],
            created_at=datetime.now(timezone.utc),
        )
        db_session.add(db_trace)
        chat_session.updated_at = datetime.now(timezone.utc)
        await db_session.commit()

        return {
            "session_id": chat_session.id,
            "response": final_text,
            "tool_calls": executed_tool_calls,
            "trace": final_trace,
        }


orchestrator = AgentOrchestrator()

