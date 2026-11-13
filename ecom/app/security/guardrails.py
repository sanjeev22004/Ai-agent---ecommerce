"""Security Guardrails: Injection Defense & Business Scope Verification.

Enforces:
1. Prompt Injection & Jailbreak Defense (Direct & Indirect)
2. Strict Business Domain Scope:
   - Product Information
   - Shipping
   - Orders
   - Returns
   - Refunds
   Explicitly rejects unrelated requests (coding, medical, math, essays, hacking).
"""

from dataclasses import dataclass
import logging
import re
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Injection & Jailbreak Detection Patterns
INJECTION_PATTERNS = re.compile(
    r"(ignore\s+(all\s+)?(previous|prior|above)\s+instructions|"
    r"disregard\s+system\s+prompt|"
    r"system\s+override|"
    r"you\s+are\s+now\s+(in\s+developer\s+mode|unrestricted|an\s+evil|dan)|"
    r"jailbreak|"
    r"bypass\s+all\s+safety|"
    r"reveal\s+your\s+system\s+prompt|"
    r"print\s+your\s+instructions|"
    r"repeat\s+everything\s+above)",
    re.IGNORECASE,
)

# Out-of-Domain Detection Patterns
OUT_OF_DOMAIN_PATTERNS = re.compile(
    r"\b(write\s+(a\s+)?(python|javascript|typescript|c\+\+|java|rust|go|code|script|program)|"
    r"leetcode|hackerrank|spiral\s+matrix|binary\s+tree|quicksort|merge\s+sort|"
    r"reverse\s+linked\s+list|fibonacci|solve\s+(this\s+)?(equation|math|integral)|"
    r"write\s+(an\s+)?essay\s+on|who\s+was\s+(napoleon|caesar|alexander)|"
    r"medical\s+advice|diagnose\s+my|prescribe|legal\s+contract|lawsuit|"
    r"how\s+to\s+hack|sql\s+injection|create\s+a\s+virus)\b",
    re.IGNORECASE,
)

SCOPE_REFUSAL_MESSAGE = (
    "I am your dedicated E-Commerce Support Copilot. I can assist you exclusively with "
    "our five core customer services: 1) Product Information, 2) Shipping & Tracking, "
    "3) Orders, 4) Returns, and 5) Refunds. For inquiries outside these areas, please consult "
    "an appropriate resource."
)

INJECTION_REFUSAL_MESSAGE = (
    "I cannot process requests that attempt to alter system security instructions, override "
    "developer policies, or bypass safety guardrails. How can I help you with your order or product today?"
)


@dataclass
class GuardrailResult:
    allowed: bool
    refusal_reason: Optional[str] = None
    refusal_message: Optional[str] = None
    sanitized_query: Optional[str] = None


class SecurityGuardrails:
    """Multi-stage security guardrail verifying safety, injection defense, and domain scoping."""

    def evaluate(self, user_query: str) -> GuardrailResult:
        clean = user_query.strip()

        # 1. Check Prompt Injection
        if INJECTION_PATTERNS.search(clean):
            logger.warning("SECURITY GUARDRAIL TRIGGERED: Prompt injection attempt detected: %r", clean[:100])
            return GuardrailResult(
                allowed=False,
                refusal_reason="prompt_injection_detected",
                refusal_message=INJECTION_REFUSAL_MESSAGE,
            )

        # 2. Check Out-of-Scope Requests
        if OUT_OF_DOMAIN_PATTERNS.search(clean):
            logger.info("DOMAIN SCOPE GUARDRAIL: Request falls outside the 5 e-commerce domains.")
            return GuardrailResult(
                allowed=False,
                refusal_reason="out_of_business_scope",
                refusal_message=SCOPE_REFUSAL_MESSAGE,
            )

        return GuardrailResult(
            allowed=True,
            sanitized_query=clean,
        )

