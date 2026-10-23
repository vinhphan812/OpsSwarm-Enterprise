from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Command:
    name: str
    argument: str = ""


ALLOWED = {"approve", "reject", "investigate", "provide", "abort", "resume"}


def parse_command(body: str) -> Command | None:
    line = (body or "").strip().splitlines()[0].strip()
    if not line.startswith("/opsswarm "):
        return None
    rest = line[len("/opsswarm ") :].strip()
    if not rest:
        return None
    parts = rest.split(maxsplit=1)
    name = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""
    if name not in ALLOWED:
        return None
    return Command(name, arg)
