"""Talk to Claude through the Claude Code CLI (`claude -p`).

Why the CLI and not the API SDK: the CLI authenticates with either
  - CLAUDE_CODE_OAUTH_TOKEN  (from `claude setup-token`, bills your Pro/Max plan), or
  - ANTHROPIC_API_KEY        (pay-as-you-go API),
so the same code runs "free on your subscription" or on the API with no changes.
"""
from __future__ import annotations

import json
import os
import re
import subprocess

SYSTEM = ("You are a senior D2C creative strategist doing competitor Ad Library "
          "teardowns. You answer with a single JSON value and nothing else.")


class LLMError(RuntimeError):
    pass


def ask_json(prompt: str, model: str = "sonnet", cwd: str | None = None,
             allow_read: bool = False, timeout: int = 600, retries: int = 2):
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
    cmd = ["claude", "-p", prompt, "--output-format", "json", "--model", model,
           "--system-prompt", SYSTEM, "--strict-mcp-config", "--no-session-persistence",
           "--max-turns", "6" if allow_read else "1"]
    cmd += ["--tools", "Read", "--allowedTools", "Read"] if allow_read else ["--tools", ""]
    last = ""
    for _ in range(retries + 1):
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd, env=env)
        except subprocess.TimeoutExpired:
            last = "timeout"
            continue
        try:
            envelope = json.loads(p.stdout)
        except json.JSONDecodeError:
            last = (p.stderr or p.stdout)[-400:]
            continue
        if envelope.get("is_error"):
            last = str(envelope.get("result"))[:400]
            if "limit" in last.lower():  # usage cap hit: retrying won't help
                raise LLMError(last)
            continue
        try:
            return extract_json(envelope.get("result", ""))
        except ValueError as e:
            last = str(e)
    raise LLMError(f"Claude call failed: {last}")


def extract_json(text: str):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    for opener, closer in (("{", "}"), ("[", "]")):
        i, j = text.find(opener), text.rfind(closer)
        if i != -1 and j > i:
            try:
                return json.loads(text[i:j + 1])
            except json.JSONDecodeError:
                pass
    raise ValueError(f"no JSON in response: {text[:200]}")
