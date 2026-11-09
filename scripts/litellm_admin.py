#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml==6.0.3"]
# ///
"""Talk to the LiteLLM gateway's API from the laptop: health, agent key, spend.

Run through task llm:health, llm:key and llm:spend. Each call opens its own
`kubectl port-forward` to svc/litellm on a random local port (so it works
next to a running task llm:forward) and closes it on exit.

Secrets: the master key is read from the .env (never from arguments or the
environment) and sent only in an HTTP header over the port-forward. The
agent key goes from LiteLLM's response straight into the .env. Neither is
ever printed: API messages are passed through redact() before printing.
"""

import argparse
import json
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from pathlib import Path

# The .env parser of task secrets, so both read the file the same way.
# (Python puts this script's directory on sys.path.)
from secrets_to_k8s import read_env

AGENT_KEY_ENV = "LITELLM_AGENT_KEY"
MASTER_KEY_ENV = "LITELLM_MASTER_KEY"

# The agent's virtual key: what it may call, and how much.
AGENT_KEY_ALIAS = "agent"
AGENT_KEY_SPEC = {
    "key_alias": AGENT_KEY_ALIAS,
    # Logical name only: not agent-model-primary or -backup directly.
    "models": ["agent-model"],
    # USD. LiteLLM rejects calls once spend reaches it, until the reset.
    "max_budget": 10,
    # Spend resets to 0 every 30 days, counted from the key's creation.
    "budget_duration": "30d",
    # Routes the key may call at all (exact path or prefix). Everything
    # else, the MCP gateway (/mcp, /mcp-rest, /v1/mcp) and the management
    # API included, answers 401 for this key.
    "allowed_routes": [
        "/chat/completions",
        "/v1/chat/completions",
        "/models",
        "/v1/models",
    ],
    "metadata": {"created_by": "task llm:key"},
}

# What task llm:health shows per LiteLLM pod (kubectl custom-columns).
POD_COLUMNS = (
    "custom-columns=NAME:.metadata.name,READY:.status.containerStatuses[0].ready,"
    "RESTARTS:.status.containerStatuses[0].restartCount,STATUS:.status.phase,"
    "IMAGE:.spec.containers[0].image"
)

# Anything that looks like a LiteLLM key (sk-...) in an API message.
KEY_RE = re.compile(r"sk-[A-Za-z0-9_\-]{4,}")


def fail(msg):
    sys.exit(f"==> ERROR: {msg}")


def redact(text):
    return KEY_RE.sub("sk-***", str(text))


def say(msg):
    print(f"==> {msg}", flush=True)


# ---------------------------------------------------------------------------
# Port-forward and HTTP


@contextmanager
def port_forward(context, namespace, service, port):
    """Forward a random free local port to the Service; yield the base URL."""
    # ":4000" lets kubectl pick the local port; it prints the one it chose.
    # --address 127.0.0.1: only this machine can reach it.
    proc = subprocess.Popen(
        ["kubectl", "--context", context, "-n", namespace, "port-forward",
         f"svc/{service}", f":{port}", "--address", "127.0.0.1"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )  # fmt: skip
    try:
        # "Forwarding from 127.0.0.1:41234 -> 4000". If kubectl fails, it
        # exits, stdout closes, and readline returns "".
        line = proc.stdout.readline()
        m = re.search(r"127\.0\.0\.1:(\d+)", line)
        if not m:
            proc.wait(timeout=5)
            fail(f"port-forward to svc/{service} failed: {proc.stderr.read().strip()}")
        yield f"http://127.0.0.1:{m.group(1)}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def call(base, method, path, key=None, body=None, timeout=30):
    """One HTTP request. Returns (status, parsed JSON or text)."""
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status, raw = resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read().decode(errors="replace")
    except urllib.error.URLError as e:
        fail(f"{method} {path}: {e.reason}")
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, raw


def error_text(payload):
    """LiteLLM's error message, shortened and redacted, for printing."""
    if isinstance(payload, dict):
        err = payload.get("error", payload.get("detail", payload))
        if isinstance(err, dict):
            err = err.get("message", err)
        payload = err
    return redact(payload)[:300]


# ---------------------------------------------------------------------------
# .env


def load_env(path):
    if not path.is_file():
        fail(f"{path} not found. See .env.example.")
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        fail(f"{path} must be mode 600: chmod 600 {path}")
    return read_env(path)


def master_key(env, path):
    key = env.get(MASTER_KEY_ENV, "")
    if not key:
        fail(f"{MASTER_KEY_ENV} is empty in {path}.")
    return key


def set_env_value(path, name, value):
    """Set NAME=value in the .env, keeping every other line as it is.

    Replaces the existing NAME= line (also `export NAME=`), or appends one.
    Written to a mode-600 temp file next to it, then renamed over it, so
    the .env is never half-written or briefly readable by others.
    """
    pattern = re.compile(rf"^\s*(export\s+)?{re.escape(name)}\s*=")
    lines = path.read_text(encoding="utf-8").splitlines()
    out, done = [], False
    for line in lines:
        if pattern.match(line):
            if not done:
                out.append(f"{name}={value}")
                done = True
            # Drop duplicates of the line, so the new value is the only one.
            continue
        out.append(line)
    if not done:
        out.append(f"{name}={value}")
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".env-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(out) + "\n")
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


# ---------------------------------------------------------------------------
# Commands


def agent_keys(base, mkey):
    """Keys in LiteLLM with the agent alias (full objects, never printed)."""
    q = urllib.parse.urlencode(
        {"key_alias": AGENT_KEY_ALIAS, "return_full_object": "true", "size": 100}
    )
    status, payload = call(base, "GET", f"/key/list?{q}", key=mkey)
    if status != 200:
        fail(f"/key/list answered {status}: {error_text(payload)}")
    keys = payload.get("keys", []) if isinstance(payload, dict) else []
    return [
        k for k in keys if isinstance(k, dict) and k.get("key_alias") == AGENT_KEY_ALIAS
    ]


def cmd_health(args):
    failed = False

    def report(ok, msg):
        nonlocal failed
        print(f"    {'PASS' if ok else 'FAIL'}  {msg}")
        failed |= not ok

    say(f"Pods of deployment {args.service} in namespace {args.namespace}")
    pods = subprocess.run(
        ["kubectl", "--context", args.context, "-n", args.namespace, "get", "pods",
         "-l", "app.kubernetes.io/name=litellm", "-o", POD_COLUMNS],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    print(
        "\n".join(
            "    " + line for line in (pods.stdout or pods.stderr).strip().splitlines()
        )
    )

    say(f"Port-forwarding to svc/{args.service}:{args.port}")
    with port_forward(args.context, args.namespace, args.service, args.port) as base:
        say("Liveness: GET /health/liveliness (the process answers)")
        status, payload = call(base, "GET", "/health/liveliness")
        report(status == 200, f"HTTP {status}: {redact(payload)[:80]}")

        say("Readiness: GET /health/readiness (ready to serve, database included)")
        status, payload = call(base, "GET", "/health/readiness")
        ready = isinstance(payload, dict) and payload.get("status") == "healthy"
        report(
            status == 200 and ready,
            f"HTTP {status}, status {payload.get('status') if isinstance(payload, dict) else redact(payload)[:80]}",
        )
        if isinstance(payload, dict):
            print(f"          LiteLLM version {payload.get('litellm_version')}")
            db = payload.get("db")
            say("Database: the db field of /health/readiness")
            report(db == "connected", f"db: {db}")

        # A real round trip to Postgres: virtual keys live only there. Needs
        # the master key, so only when the .env has one.
        env_path = Path(args.env_file)
        if env_path.is_file():
            env = load_env(env_path)
            if env.get(MASTER_KEY_ENV):
                say(
                    "Database: an authenticated query (GET /key/list, keys live in Postgres)"
                )
                status, payload = call(
                    base, "GET", "/key/list?size=1", key=env[MASTER_KEY_ENV]
                )
                total = (
                    payload.get("total_count") if isinstance(payload, dict) else None
                )
                report(
                    status == 200,
                    f"HTTP {status}, {total} virtual key(s) in the database"
                    if status == 200
                    else f"HTTP {status}: {error_text(payload)}",
                )

    say("Health: " + ("FAIL" if failed else "PASS"))
    return 1 if failed else 0


def cmd_key(args):
    env_path = Path(args.env_file)
    env = load_env(env_path)
    mkey = master_key(env, env_path)
    rotate = os.environ.get("ROTATE", "") == "1"
    in_env = bool(env.get(AGENT_KEY_ENV))

    say(f"Port-forwarding to svc/{args.service}:{args.port}")
    with port_forward(args.context, args.namespace, args.service, args.port) as base:
        say(f"Looking for existing keys with alias {AGENT_KEY_ALIAS!r} in LiteLLM")
        existing = agent_keys(base, mkey)
        print(
            f"    in LiteLLM: {len(existing)}; {AGENT_KEY_ENV} in the .env: {'set' if in_env else 'empty'}"
        )

        if (existing or in_env) and not rotate:
            fail(
                "an agent key already exists. Keep it, or replace it with: task llm:key ROTATE=1 "
                "(revokes the old key in LiteLLM, writes the new one to the .env), then task secrets."
            )

        if existing:
            say(
                f"ROTATE=1: revoking {len(existing)} old key(s) with alias {AGENT_KEY_ALIAS!r}"
            )
            status, payload = call(
                base,
                "POST",
                "/key/delete",
                key=mkey,
                body={"key_aliases": [AGENT_KEY_ALIAS]},
            )
            if status != 200:
                fail(
                    f"/key/delete answered {status}: {error_text(payload)}. Nothing was written."
                )
            if agent_keys(base, mkey):
                fail("old key(s) still listed after /key/delete. Nothing was written.")
        elif rotate:
            say(
                "ROTATE=1: no key in LiteLLM to revoke; replacing the value in the .env"
            )

        say(
            f"Creating virtual key {AGENT_KEY_ALIAS!r}: models {AGENT_KEY_SPEC['models']}, "
            f"max_budget {AGENT_KEY_SPEC['max_budget']} USD per {AGENT_KEY_SPEC['budget_duration']}, "
            f"routes {', '.join(AGENT_KEY_SPEC['allowed_routes'])}"
        )
        status, payload = call(
            base, "POST", "/key/generate", key=mkey, body=AGENT_KEY_SPEC
        )
        new_key = payload.get("key") if isinstance(payload, dict) else None
        if status != 200 or not new_key:
            fail(f"/key/generate answered {status}: {error_text(payload)}")

    set_env_value(env_path, AGENT_KEY_ENV, new_key)
    print(f"{AGENT_KEY_ENV} written")
    return 0


def cmd_spend(args):
    env_path = Path(args.env_file)
    env = load_env(env_path)
    mkey = master_key(env, env_path)

    say(f"Port-forwarding to svc/{args.service}:{args.port}")
    with port_forward(args.context, args.namespace, args.service, args.port) as base:
        say(f"Keys with alias {AGENT_KEY_ALIAS!r} (GET /key/list)")
        keys = agent_keys(base, mkey)
        if not keys:
            print("    none. Create one with task llm:key.")
            return 1
        for k in keys:
            spend = k.get("spend") or 0
            budget = k.get("max_budget")
            # Not key_name: LiteLLM's masked form still shows the key's end.
            print(f"    alias          {k.get('key_alias')}")
            print(f"    models         {', '.join(k.get('models') or []) or 'all'}")
            print(f"    spend          {spend:.6f} USD of {budget} USD"
                  + (f" ({100 * spend / budget:.4f}%)" if budget else ""))  # fmt: skip
            print(
                f"    budget period  {k.get('budget_duration')}, resets at {k.get('budget_reset_at')}"
            )
            print(f"    created        {k.get('created_at')}")

            # The spend log rows of this key, one per request. "token" is
            # the key's SHA-256 hash, which is how LiteLLM stores it; it is
            # not printed either.
            q = urllib.parse.urlencode({"api_key": k.get("token", "")})
            status, logs = call(base, "GET", f"/spend/logs?{q}", key=mkey)
            if status != 200 or not isinstance(logs, list):
                print(f"    spend logs     HTTP {status}: {error_text(logs)}")
                continue
            by_model = {}
            for row in logs:
                m = row.get("model_group") or row.get("model") or "?"
                n, s, t = by_model.get(m, (0, 0.0, 0))
                by_model[m] = (
                    n + 1,
                    s + (row.get("spend") or 0),
                    t + (row.get("total_tokens") or 0),
                )
            say(f"Spend logs: {len(logs)} request(s), by the model group that answered")
            for m, (n, s, t) in sorted(by_model.items()):
                print(f"    {m:24} {n:4} request(s)  {t:6} tokens  {s:.6f} USD")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["health", "key", "spend"])
    parser.add_argument("--context", required=True, help="kubeconfig context")
    parser.add_argument("--namespace", default="llm")
    parser.add_argument("--service", default="litellm")
    parser.add_argument("--port", type=int, default=4000)
    parser.add_argument("--env-file", required=True)
    args = parser.parse_args()
    # Turn SIGTERM and SIGHUP into a normal exit so the port-forward is
    # closed and no temp file is left behind.
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_: sys.exit(1))
    return {"health": cmd_health, "key": cmd_key, "spend": cmd_spend}[args.command](
        args
    )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
