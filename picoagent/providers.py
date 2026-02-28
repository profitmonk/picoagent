"""LLM providers: Claude, OpenAI-compatible, with fallback chain."""

import json
import logging
from dataclasses import dataclass, field

import anthropic
import openai

log = logging.getLogger(__name__)


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class LLMResponse:
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


class ClaudeProvider:
    """Anthropic Claude API provider."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = model

    def _convert_messages(self, messages: list[dict]) -> tuple[str, list[dict]]:
        """Convert OpenAI-style messages to Claude format."""
        system = ""
        conv = []
        for m in messages:
            if m["role"] == "system":
                system = m["content"]
            elif m["role"] == "assistant":
                # Convert assistant messages with tool_calls to Claude content blocks
                content = []
                if m.get("content"):
                    content.append({"type": "text", "text": m["content"]})
                for tc in m.get("tool_calls", []):
                    fn = tc["function"]
                    args = json.loads(fn["arguments"]) if isinstance(fn["arguments"], str) else fn["arguments"]
                    content.append({"type": "tool_use", "id": tc["id"], "name": fn["name"], "input": args})
                conv.append({"role": "assistant", "content": content or m.get("content", "")})
            elif m["role"] == "tool":
                # Convert tool results: Claude expects them inside a user message
                tool_result = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
                # Merge consecutive tool results into one user message
                if conv and conv[-1]["role"] == "user" and isinstance(conv[-1]["content"], list) and conv[-1]["content"] and conv[-1]["content"][0].get("type") == "tool_result":
                    conv[-1]["content"].append(tool_result)
                else:
                    conv.append({"role": "user", "content": [tool_result]})
            else:
                conv.append({"role": m["role"], "content": m["content"]})
        return system, conv

    async def complete(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        # Convert OpenAI-style tools to Claude format
        claude_tools = []
        for t in tools:
            fn = t["function"]
            claude_tools.append({
                "name": fn["name"],
                "description": fn["description"],
                "input_schema": fn["parameters"],
            })

        system, conv = self._convert_messages(messages)

        resp = await self.client.messages.create(
            model=self.model, max_tokens=2048, system=system,
            messages=conv, tools=claude_tools if claude_tools else anthropic.NOT_GIVEN,
        )

        text_parts, tool_calls = [], []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, arguments=block.input))

        return LLMResponse(text="\n".join(text_parts) if text_parts else None, tool_calls=tool_calls)


class OpenAICompatibleProvider:
    """OpenAI / Ollama / vLLM / llama.cpp provider."""

    def __init__(self, api_key: str = "unused", base_url: str | None = None,
                 model: str = "gpt-4o"):
        self.client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    async def complete(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        kwargs = {"model": self.model, "messages": messages, "max_tokens": 2048}
        if tools:
            kwargs["tools"] = tools

        resp = await self.client.chat.completions.create(**kwargs)
        choice = resp.choices[0].message

        tool_calls = []
        if choice.tool_calls:
            for tc in choice.tool_calls:
                args = json.loads(tc.function.arguments) if isinstance(tc.function.arguments, str) else tc.function.arguments
                tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))

        return LLMResponse(text=choice.content, tool_calls=tool_calls)


class ProviderChain:
    """Tries providers in order, falls back on failure."""

    def __init__(self, providers: list):
        self.providers = providers

    @classmethod
    def from_config(cls, cfg: dict) -> "ProviderChain":
        providers = []
        for p in cfg.get("providers", []):
            kind = p["type"]
            if kind == "claude":
                providers.append(ClaudeProvider(api_key=p["api_key"], model=p.get("model", "claude-sonnet-4-20250514")))
            elif kind in ("openai", "ollama", "vllm", "local"):
                providers.append(OpenAICompatibleProvider(
                    api_key=p.get("api_key", "unused"),
                    base_url=p.get("base_url"),
                    model=p.get("model", "gpt-4o"),
                ))
            else:
                log.warning("Unknown provider type: %s", kind)
        if not providers:
            raise ValueError("No valid providers configured")
        return cls(providers)

    async def complete(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        last_err = None
        for provider in self.providers:
            try:
                return await provider.complete(messages, tools)
            except Exception as e:
                log.warning("Provider %s failed: %s", type(provider).__name__, e)
                last_err = e
        raise RuntimeError(f"All providers failed. Last error: {last_err}")
