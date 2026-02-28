"""Security gate: user allowlist, command blocklist, rate limiting."""

import re
import time
from dataclasses import dataclass, field

DEFAULT_BLOCKED = [
    r"\brm\s+-rf\b", r"\bsudo\b", r"\bmkfs\b", r"\bdd\s+if=",
    r"\bcurl\b.*\|\s*sh", r"\bwget\b.*\|\s*sh", r"\b:\(\)\s*\{",
    r"\bchmod\s+777\b", r"\bshutdown\b", r"\breboot\b",
    r"\b>/dev/sd[a-z]", r"\bnc\s+-[el]",
    # Block secret exfiltration
    r"\benv\b", r"\bprintenv\b", r"\bset\b(?!.*=)",
    r"/proc/\S*environ", r"\bexport\b\s+-p",
    r"\$\w*KEY\b", r"\$\w*TOKEN\b", r"\$\w*SECRET\b", r"\$\w*PASSWORD\b",
    r"\bcat\b.*\.env\b", r"\bless\b.*\.env\b", r"\bmore\b.*\.env\b",
]
MAX_RATE = 20  # messages per window
RATE_WINDOW = 60  # seconds


@dataclass
class SecurityGate:
    """Enforces allowlist, rate limit, and command blocklist."""

    allowed_users: dict[str, set[str]] = field(default_factory=dict)
    blocked_patterns: list[re.Pattern] = field(default_factory=list)
    rate_limit: int = MAX_RATE
    rate_window: int = RATE_WINDOW
    _hits: dict[str, list[float]] = field(default_factory=dict, repr=False)

    @classmethod
    def from_config(cls, cfg: dict) -> "SecurityGate":
        sec = cfg.get("security", {})
        allowed: dict[str, set[str]] = {}
        for channel, users in sec.get("allowlist", {}).items():
            allowed[channel] = {str(u) for u in users}

        raw = sec.get("blocked_commands", DEFAULT_BLOCKED)
        patterns = [re.compile(p) for p in raw]

        return cls(
            allowed_users=allowed,
            blocked_patterns=patterns,
            rate_limit=sec.get("rate_limit", MAX_RATE),
            rate_window=sec.get("rate_window", RATE_WINDOW),
        )

    def check_user(self, channel: str, user_id: str) -> bool:
        """Return True if user is allowed (or no allowlist configured for channel)."""
        users = self.allowed_users.get(channel)
        if users is None:
            return True  # no allowlist = open
        return str(user_id) in users

    def check_rate(self, user_id: str) -> bool:
        """Return True if user is within rate limit."""
        now = time.monotonic()
        key = str(user_id)
        hits = self._hits.setdefault(key, [])
        cutoff = now - self.rate_window
        self._hits[key] = hits = [t for t in hits if t > cutoff]
        if len(hits) >= self.rate_limit:
            return False
        hits.append(now)
        return True

    def check_command(self, cmd: str) -> str | None:
        """Return matching pattern string if command is blocked, else None."""
        for pat in self.blocked_patterns:
            if pat.search(cmd):
                return pat.pattern
        return None

    def authorize(self, channel: str, user_id: str) -> str | None:
        """Full pre-message check. Returns error string or None if OK."""
        if not self.check_user(channel, user_id):
            return "User not in allowlist."
        if not self.check_rate(user_id):
            return "Rate limit exceeded. Please wait."
        return None
