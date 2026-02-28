"""Agent: ReAct loop with conversation memory and tool dispatch."""

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field

from .providers import ProviderChain
from .security import SecurityGate
from .tools import TOOL_DEFS, TOOL_RUNNERS

log = logging.getLogger(__name__)

MAX_ROUNDS = 5
MEMORY_WINDOW = 20  # messages kept per conversation
SYSTEM_PROMPT = (
    "You are Picoagent, a helpful AI assistant. You can run shell commands and fetch web pages. "
    "Be concise. When using tools, explain what you're doing briefly."
)


@dataclass
class Conversation:
    messages: list[dict] = field(default_factory=list)

    def append(self, role: str, content: str):
        self.messages.append({"role": role, "content": content})
        if len(self.messages) > MEMORY_WINDOW:
            self.messages = self.messages[-MEMORY_WINDOW:]

    def append_tool_result(self, tool_call_id: str, content: str):
        self.messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": content})
        if len(self.messages) > MEMORY_WINDOW:
            self.messages = self.messages[-MEMORY_WINDOW:]

    def append_assistant_with_tools(self, text: str | None, tool_calls: list[dict]):
        msg: dict = {"role": "assistant", "content": text or ""}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        self.messages.append(msg)
        if len(self.messages) > MEMORY_WINDOW:
            self.messages = self.messages[-MEMORY_WINDOW:]

    def to_messages(self) -> list[dict]:
        return [{"role": "system", "content": SYSTEM_PROMPT}] + list(self.messages)


class Agent:
    """Core agent with ReAct loop."""

    def __init__(self, provider_chain: ProviderChain, security: SecurityGate):
        self.providers = provider_chain
        self.security = security
        self.conversations: dict[str, Conversation] = defaultdict(Conversation)

    async def handle_message(self, user_id: str, channel: str, text: str) -> str:
        # Security check
        err = self.security.authorize(channel, user_id)
        if err:
            return err

        conv = self.conversations[f"{channel}:{user_id}"]
        conv.append("user", text)

        for round_num in range(MAX_ROUNDS):
            resp = await self.providers.complete(conv.to_messages(), TOOL_DEFS)

            if not resp.tool_calls:
                reply = resp.text or "(no response)"
                conv.append("assistant", reply)
                return reply

            # Record assistant message with tool calls
            tc_dicts = [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                for tc in resp.tool_calls
            ]
            conv.append_assistant_with_tools(resp.text, tc_dicts)

            # Execute each tool call
            for tc in resp.tool_calls:
                result = await self._execute_tool(tc.name, tc.arguments)
                conv.append_tool_result(tc.id, result)
                log.info("Tool %s -> %s chars", tc.name, len(result))

        return "[Reached maximum tool rounds. Please try a simpler request.]"

    async def _execute_tool(self, name: str, arguments: dict) -> str:
        runner = TOOL_RUNNERS.get(name)
        if not runner:
            return f"[Unknown tool: {name}]"

        # Security check for shell commands
        if name == "shell":
            cmd = arguments.get("command", "")
            blocked = self.security.check_command(cmd)
            if blocked:
                return f"[Command blocked by security policy: matches '{blocked}']"

        try:
            return await runner(arguments)
        except Exception as e:
            log.error("Tool %s error: %s", name, e)
            return f"[Tool error: {e}]"
