"""Smart router: classifies message complexity and routes to the best provider."""

import logging
import re

from .providers import LLMResponse, ProviderChain

log = logging.getLogger(__name__)


# Patterns that indicate a message needs a powerful model
COMPLEX_PATTERNS = [
    r"\b(explain|analyze|compare|contrast|evaluate|summarize|review)\b",
    r"\b(write|create|compose|draft|generate)\s+(a |an |the )?(code|script|program|function|class|essay|article|report|email)",
    r"\b(debug|fix|refactor|optimize|improve)\b.*\b(code|bug|error|issue)\b",
    r"\b(why|how)\s+(does|do|is|are|can|could|would|should)\b",
    r"\b(translate|convert)\b.*\b(to|into|from)\b",
    r"\b(step.by.step|in detail|thorough|comprehensive)\b",
    r"\b(pros?\s+and\s+cons?|trade.?offs?|advantages?\s+and\s+disadvantages?)\b",
    r"\b(architecture|design pattern|algorithm|data structure)\b",
    r"```",  # code blocks
    r"\b(api|sdk|framework|library|database|sql|docker|kubernetes|aws|cloud)\b",
]

# Patterns that indicate a simple query suited for a local model
SIMPLE_PATTERNS = [
    r"^(hi|hello|hey|yo|sup|greetings|good\s+(morning|afternoon|evening))\b",
    r"^(thanks|thank you|thx|ty|cheers)\b",
    r"^(yes|no|ok|okay|sure|yep|nope|yeah|nah)\b",
    r"^(what\s+time|what\s+day|what\s+date)\b",
    r"^(who\s+(is|are|was)|what\s+is\s+\w+$)",  # simple factual questions
    r"\b(weather|temperature|forecast)\b",
    r"\b(define|meaning\s+of|definition)\b",
    r"\b(joke|riddle|fun fact)\b",
]

# Tool-related patterns -> always use powerful model (needs function calling)
TOOL_PATTERNS = [
    r"\b(run|execute|shell|command|terminal|bash)\b",
    r"\b(fetch|browse|open|visit|check)\s+(the\s+)?(url|website|page|site|link)\b",
    r"\b(download|curl|wget)\b",
    r"\b(directory|folder|file|ls|pwd|cd|cat|grep)\b",
    r"\b(install|pip|npm|apt|brew)\b",
]


def classify(text: str) -> str:
    """Classify message complexity: 'simple', 'complex', or 'tool'.

    Returns:
        'tool' - needs function calling, must use powerful model
        'complex' - needs reasoning/generation, should use powerful model
        'simple' - basic query, can use local model
    """
    lower = text.lower().strip()

    # Very short messages are usually simple
    word_count = len(lower.split())

    # Check tool patterns first (highest priority)
    for pattern in TOOL_PATTERNS:
        if re.search(pattern, lower):
            return "tool"

    # Check complex patterns
    complex_score = 0
    for pattern in COMPLEX_PATTERNS:
        if re.search(pattern, lower):
            complex_score += 1

    # Check simple patterns
    simple_score = 0
    for pattern in SIMPLE_PATTERNS:
        if re.search(pattern, lower):
            simple_score += 1

    # Long messages are more likely complex
    if word_count > 50:
        complex_score += 2
    elif word_count > 20:
        complex_score += 1

    # Multi-line messages tend to be complex
    if text.count("\n") > 2:
        complex_score += 1

    # Decision
    if complex_score >= 2:
        return "complex"
    if simple_score > 0 and complex_score == 0:
        return "simple"
    if word_count <= 5 and complex_score == 0:
        return "simple"

    # Default: complex (safer to use the better model)
    return "complex"


class SmartRouter:
    """Routes messages to the best provider based on complexity.

    Uses a local model (Ollama) for simple queries and a cloud model
    (Claude) for complex ones. Auto-escalates to cloud if local fails.
    """

    def __init__(self, cloud_chain: ProviderChain, local_chain: ProviderChain | None):
        self.cloud = cloud_chain
        self.local = local_chain

    @classmethod
    def from_config(cls, cfg: dict) -> "SmartRouter":
        """Build router from config. Separates cloud and local providers."""
        cloud_providers = []
        local_providers = []

        from .providers import ClaudeProvider, OpenAICompatibleProvider

        for p in cfg.get("providers", []):
            kind = p["type"]
            if kind == "claude":
                cloud_providers.append(ClaudeProvider(
                    api_key=p["api_key"],
                    model=p.get("model", "claude-sonnet-4-20250514"),
                ))
            elif kind in ("openai",):
                cloud_providers.append(OpenAICompatibleProvider(
                    api_key=p.get("api_key", "unused"),
                    base_url=p.get("base_url"),
                    model=p.get("model", "gpt-4o"),
                ))
            elif kind in ("ollama", "vllm", "local"):
                local_providers.append(OpenAICompatibleProvider(
                    api_key=p.get("api_key", "unused"),
                    base_url=p.get("base_url"),
                    model=p.get("model", "llama3.2"),
                ))
            else:
                log.warning("Unknown provider type: %s", kind)

        if not cloud_providers and not local_providers:
            raise ValueError("No valid providers configured")

        cloud_chain = ProviderChain(cloud_providers) if cloud_providers else None
        local_chain = ProviderChain(local_providers) if local_providers else None

        # If only one type exists, use it for both
        if cloud_chain is None:
            cloud_chain = local_chain
        if local_chain is None:
            local_chain = None  # no local fallback

        return cls(cloud_chain, local_chain)

    async def complete(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        """Route to the best provider based on message complexity."""
        # Extract the latest user message for classification
        user_text = ""
        for m in reversed(messages):
            if m["role"] == "user":
                user_text = m["content"] if isinstance(m["content"], str) else ""
                break

        complexity = classify(user_text)
        log.info("Router: complexity=%s for: %.60s...", complexity, user_text)

        # Tool calls or complex -> always use cloud
        if complexity in ("tool", "complex") or tools:
            return await self.cloud.complete(messages, tools)

        # Simple -> try local first, escalate to cloud on failure
        if self.local:
            try:
                resp = await self.local.complete(messages, [])  # no tools for local
                if resp.text and len(resp.text.strip()) > 0:
                    log.info("Router: handled locally")
                    return resp
                log.warning("Router: local returned empty, escalating to cloud")
            except Exception as e:
                log.warning("Router: local failed (%s), escalating to cloud", e)

        return await self.cloud.complete(messages, tools)
