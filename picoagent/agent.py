"""Agent: ReAct loop with persistent conversation memory and tool dispatch."""

import json
import logging

from .memory import Memory
from .providers import ProviderChain
from .security import SecurityGate
from .tools import TOOL_DEFS, TOOL_RUNNERS

log = logging.getLogger(__name__)

MAX_ROUNDS = 5
SYSTEM_PROMPT = (
    "You are Picoagent, a helpful AI assistant. You can run shell commands and fetch web pages. "
    "Be concise. When using tools, explain what you're doing briefly."
)


class Agent:
    """Core agent with ReAct loop and persistent memory."""

    def __init__(self, provider_chain: ProviderChain, security: SecurityGate,
                 memory: Memory):
        self.providers = provider_chain
        self.security = security
        self.memory = memory

    def _conv_key(self, channel: str, user_id: str) -> str:
        return f"{channel}:{user_id}"

    def _build_messages(self, conv_key: str) -> list[dict]:
        history = self.memory.load(conv_key)
        return [{"role": "system", "content": SYSTEM_PROMPT}] + history

    def _save(self, conv_key: str, msg: dict):
        self.memory.save(conv_key, msg)

    async def handle_message(self, user_id: str, channel: str, text: str) -> str:
        # Security check
        err = self.security.authorize(channel, user_id)
        if err:
            return err

        conv_key = self._conv_key(channel, user_id)
        self._save(conv_key, {"role": "user", "content": text})

        for round_num in range(MAX_ROUNDS):
            messages = self._build_messages(conv_key)
            resp = await self.providers.complete(messages, TOOL_DEFS)

            if not resp.tool_calls:
                reply = resp.text or "(no response)"
                self._save(conv_key, {"role": "assistant", "content": reply})
                self.memory.trim(conv_key)
                return reply

            # Record assistant message with tool calls
            tc_dicts = [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                for tc in resp.tool_calls
            ]
            assistant_msg = {"role": "assistant", "content": resp.text or "", "tool_calls": tc_dicts}
            self._save(conv_key, assistant_msg)

            # Execute each tool call
            for tc in resp.tool_calls:
                result = await self._execute_tool(tc.name, tc.arguments)
                self._save(conv_key, {"role": "tool", "tool_call_id": tc.id, "content": result})
                log.info("Tool %s -> %s chars", tc.name, len(result))

        self.memory.trim(conv_key)
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
