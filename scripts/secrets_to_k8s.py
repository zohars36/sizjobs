#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml==6.0.3"]
# ///
"""Create or update Kubernetes Secrets from the local .env file.

Run through `task secrets` (or `task secrets DRY_RUN=1`). Reads the .env
and config/secrets-map.yaml, and for each Secret in the map applies one
built from the keys that have a value.

Values never appear on a command line (anyone can read those in `ps`) or
in the output. For each Secret they are written to a temporary env file
in /dev/shm (RAM, not disk) with mode 600, handed to kubectl with
--from-env-file, and deleted right after, also on Ctrl+C or SIGTERM.
"""

import argparse
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
MANAGER = "sizjobs-task-secrets"


def fail(msg):
    sys.exit(f"==> ERROR: {msg}")


def read_env(path):
    """Parse KEY=value lines. Errors name the line number, never the value."""
    values = {}
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = line.removeprefix("export ")
        key, sep, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not sep or not KEY_RE.match(key):
            fail(f"{path}:{n} is not KEY=value")
        # Allow one pair of matching quotes, as shells and dotenv tools do.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key] = value
    return values


def kubectl(context, *args, stdin=None):
    """Run kubectl; on failure print its stderr, which never holds values."""
    result = subprocess.run(
        ["kubectl", "--context", context, *args],
        check=False,
        input=stdin,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        fail(f"kubectl {' '.join(args[:3])} failed:\n{result.stderr.strip()}")
    return result.stdout


def ensure_namespace(context, namespace, created):
    if namespace in created:
        return
    probe = subprocess.run(
        ["kubectl", "--context", context, "get", "namespace", namespace],
        check=False,
        capture_output=True,
    )
    if probe.returncode != 0:
        print(f"==> Creating namespace {namespace}")
        kubectl(context, "create", "namespace", namespace)
    created.add(namespace)


def apply_secret(context, name, namespace, data):
    # mkstemp creates the file with mode 600, readable only by us.
    fd, tmp = tempfile.mkstemp(dir="/dev/shm", prefix="sizjobs-secret-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.writelines(f"{k}={v}\n" for k, v in data.items())
        # Build the Secret locally (--dry-run=client never contacts the
        # cluster), add a label, then apply it. The manifest goes through
        # pipes (stdin/stdout), never through arguments.
        manifest = kubectl(
            context, "create", "secret", "generic", name,
            "--namespace", namespace, f"--from-env-file={tmp}",
            "--dry-run=client", "--output=yaml",
        )  # fmt: skip
    finally:
        os.unlink(tmp)
    labelled = kubectl(
        context, "label", "--local", "--filename=-", "--output=yaml",
        f"app.kubernetes.io/managed-by={MANAGER}",
        stdin=manifest,
    )  # fmt: skip
    # --server-side: plain `kubectl apply` copies the whole object, values
    # included, into a last-applied-configuration annotation. Server-side
    # apply tracks field ownership instead, and still removes keys that
    # were deleted from the .env since the last run.
    kubectl(
        context, "apply", "--server-side", f"--field-manager={MANAGER}",
        "--filename=-",
        stdin=labelled,
    )  # fmt: skip


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--map", type=Path, required=True)
    parser.add_argument("--context", required=True, help="kubeconfig context")
    args = parser.parse_args()
    # Set by `task secrets DRY_RUN=1`: list what would be applied, touch
    # nothing.
    dry_run = os.environ.get("DRY_RUN", "") == "1"

    # Turn SIGTERM and SIGHUP into a normal exit so the `finally` above
    # deletes the temp file. Only SIGKILL skips it; /dev/shm is RAM and is
    # cleared on reboot.
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_: sys.exit(1))

    if not args.env_file.is_file():
        fail(f"{args.env_file} not found.")
    if stat.S_IMODE(args.env_file.stat().st_mode) != 0o600:
        fail(f"{args.env_file} must be mode 600: chmod 600 {args.env_file}")

    env = read_env(args.env_file)
    secrets = yaml.safe_load(args.map.read_text(encoding="utf-8"))["secrets"]

    mapped = {k for s in secrets for k in s["keys"]}
    unknown = sorted(set(env) - mapped)
    if unknown:
        print(
            f"==> WARNING: keys in the .env but not in {args.map}: {', '.join(unknown)}"
        )

    if dry_run:
        print("==> DRY_RUN=1: names only, nothing is applied")
    created = set()
    applied = skipped = 0
    for s in secrets:
        name, namespace, keys = s["name"], s["namespace"], s["keys"]
        data = {k: env[k] for k in keys if env.get(k)}
        missing = [k for k in keys if k not in data]
        where = f"{namespace}/{name}"
        if not data:
            print(f"==> SKIP {where}: no values yet for {', '.join(missing)}")
            skipped += 1
            continue
        if missing:
            print(f"==> WARNING {where}: missing {', '.join(missing)}")
        if dry_run:
            print(f"==> would apply {where}: {', '.join(data)}")
        else:
            ensure_namespace(args.context, namespace, created)
            print(f"==> Applying {where}: {', '.join(data)}")
            apply_secret(args.context, name, namespace, data)
        applied += 1

    verb = "would apply" if dry_run else "applied"
    print(f"==> Done: {applied} Secret(s) {verb}, {skipped} skipped.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
