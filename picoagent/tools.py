"""Tools: shell executor and web page fetcher."""

import asyncio
import logging

import aiohttp

log = logging.getLogger(__name__)

SHELL_TIMEOUT = 30  # seconds
OUTPUT_LIMIT = 4000  # characters

TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "shell",
            "description": "Execute a shell command and return stdout+stderr.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string", "description": "Shell command to run"}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch a web page and return its text content.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "URL to fetch"}},
                "required": ["url"],
            },
        },
    },
]


async def run_shell(command: str, timeout: int = SHELL_TIMEOUT) -> str:
    """Run a shell command with timeout, return combined output."""
    try:
        proc = await asyncio.create_subprocess_shell(
            command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        text = stdout.decode(errors="replace")
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        text = f"[Command timed out after {timeout}s]"
    except Exception as e:
        text = f"[Error: {e}]"
    if len(text) > OUTPUT_LIMIT:
        text = text[:OUTPUT_LIMIT] + f"\n[...truncated at {OUTPUT_LIMIT} chars]"
    return text


async def web_fetch(url: str) -> str:
    """Fetch URL and return text content."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                text = await resp.text()
    except Exception as e:
        return f"[Fetch error: {e}]"
    if len(text) > OUTPUT_LIMIT:
        text = text[:OUTPUT_LIMIT] + f"\n[...truncated at {OUTPUT_LIMIT} chars]"
    return text


TOOL_RUNNERS = {
    "shell": lambda args: run_shell(args["command"]),
    "web_fetch": lambda args: web_fetch(args["url"]),
}
