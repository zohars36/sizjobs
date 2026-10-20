#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["openai==3.26.0"]
# ///
"""Smoke test for an OpenAI-compatible LLM endpoint: is it up, and can the
model make a tool call?

Run through `task smoke`. Configured from the environment (config, not
secrets):
  LLM_BASE_URL  default http://localhost:11434/v1  (local Ollama)
  LLM_MODEL     default qwen2.5:1.5b
  LLM_API_KEY   default "ollama" (Ollama ignores it; LiteLLM will not)

The same variables will point the agent at LiteLLM later (a3), so this
test also works against the real gateway. The API key is never printed.
"""

import json
import os
import sys
import time

import openai

BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1")
MODEL = os.environ.get("LLM_MODEL", "qwen2.5:1.5b")
API_KEY = os.environ.get("LLM_API_KEY", "ollama")
ATTEMPTS = 3

# Hints are Ollama-specific only when we are talking to local Ollama.
IS_OLLAMA = ":11434" in BASE_URL

SCORE_JOB = {
    "type": "function",
    "function": {
        "name": "score_job",
        "description": "Score how well a job posting matches the candidate, 0-100.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Job title"},
                "company": {"type": "string", "description": "Company name"},
            },
            "required": ["title", "company"],
        },
    },
}


def report(ok, name, started, detail=""):
    mark = "✔" if ok else "✘"
    line = f"{mark} {name} ({time.monotonic() - started:.1f}s)"
    print(f"{line}: {detail}" if detail else line, flush=True)


def check_models(client):
    started = time.monotonic()
    name = "endpoint up and model available"
    try:
        ids = {m.id for m in client.models.list()}
    except openai.APIConnectionError:
        hint = " Ollama not running? sudo systemctl start ollama (or task llm:up)"
        report(
            False, name, started, f"cannot reach {BASE_URL}.{hint if IS_OLLAMA else ''}"
        )
        return False
    except openai.APIStatusError as e:
        report(False, name, started, f"HTTP {e.status_code} from {BASE_URL}")
        return False
    if MODEL not in ids:
        hint = f" Run: ollama pull {MODEL}" if IS_OLLAMA else ""
        report(False, name, started, f"model {MODEL} not found.{hint}")
        return False
    report(True, name, started, MODEL)
    return True


def tool_call_once(client):
    """Return (ok, detail) for one chat completion with the score_job tool."""
    response = client.chat.completions.create(
        model=MODEL,
        # temperature 0: as deterministic as the model allows.
        temperature=0,
        tools=[SCORE_JOB],
        messages=[
            {
                "role": "system",
                "content": "You score job postings. Always answer by calling "
                "the score_job tool. Never answer in plain text.",
            },
            {
                "role": "user",
                "content": "Call score_job for this posting: title "
                '"Senior Platform Engineer", company "Acme Robotics".',
            },
        ],
    )
    calls = response.choices[0].message.tool_calls or []
    if not calls:
        return False, "no tool call in the response"
    call = calls[0]
    if call.function.name != "score_job":
        return False, f"called {call.function.name!r} instead of score_job"
    try:
        args = json.loads(call.function.arguments)
    except json.JSONDecodeError:
        return False, "tool arguments are not valid JSON"
    if not isinstance(args, dict) or not all(
        isinstance(args.get(k), str) for k in ("title", "company")
    ):
        return False, f"arguments missing title/company: {sorted(args)}"
    return True, f"score_job({json.dumps(args, ensure_ascii=False)})"


def check_tool_call(client):
    # Small models are sometimes flaky with tools, so allow a few attempts
    # and say which one passed. The first call also loads the model into
    # RAM, which is the slow part on CPU.
    started = time.monotonic()
    name = "tool call with valid JSON arguments"
    detail = ""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            ok, detail = tool_call_once(client)
        except openai.APIError as e:
            ok, detail = False, f"{type(e).__name__}: {e.message}"
        if ok:
            report(True, name, started, f"attempt {attempt}/{ATTEMPTS}: {detail}")
            return True
        print(f"  attempt {attempt}/{ATTEMPTS} failed: {detail}", flush=True)
    report(False, name, started, f"all {ATTEMPTS} attempts failed")
    return False


def main():
    print(f"==> LLM smoke test: {BASE_URL}, model {MODEL}", flush=True)
    # max_retries=0: the SDK would otherwise retry connection errors with
    # backoff, which only delays the "not running" message. Our own
    # attempts above handle model flakiness. The timeout covers loading
    # the model on CPU on the first request.
    client = openai.OpenAI(
        base_url=BASE_URL, api_key=API_KEY, max_retries=0, timeout=180
    )
    if not check_models(client) or not check_tool_call(client):
        print("==> Smoke test FAILED", flush=True)
        sys.exit(1)
    print("==> Smoke test passed", flush=True)


if __name__ == "__main__":
    main()
