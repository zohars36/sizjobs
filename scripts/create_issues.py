#!/usr/bin/env python3
"""Create GitHub labels, milestones and issues for the SizJobs plan.

Reads the plan from docs/plan/tasks.json (the same file that drives the plan page)
and creates one issue per task in the current repository, using the gh CLI.

Idempotent: labels are created or updated, milestones and issues that already
exist (matched by title) are skipped, so the script is safe to run again.

Usage (from the repo root, after `gh auth login`):
    python3 scripts/create_issues.py --dry-run   # show what would be created
    python3 scripts/create_issues.py             # create everything
"""
import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

WHERE = {
    "console": "AWS console",
    "wsl": "WSL terminal",
    "cc": "Claude Code (local)",
    "cloud": "Claude Code (cloud)",
    "chat": "claude.ai chat",
    "gh": "GitHub",
}

FIXED_LABELS = {
    "learn-deeply": ("6b3fa0", "Core skill: write it yourself or review every line"),
    "manual-once": ("8a979e", "Manual step, done once"),
    "later": ("8a5a00", "Phase 2 work, after phase 1 is stable"),
}


def gh(*args, capture=True):
    result = subprocess.run(["gh", *args], text=True, capture_output=capture)
    if result.returncode != 0:
        sys.exit(f"gh {' '.join(args[:3])} failed:\n{result.stderr}")
    return result.stdout


def phase_label(n):
    return f"phase-{n.lower()}"


def milestone_title(phase):
    return f"Phase {phase['n']}: {phase['title']}"


def issue_title(task):
    return f"{task['id']}: {task['t']}"


def issue_body(phase, task):
    lines = [f"**{milestone_title(phase)}**", "", task["d"], "", "## Done when", f"- [ ] {task['ok']}"]
    if task.get("cost"):
        lines += ["", f"**Cost:** {task['cost']}"]
    if task.get("where"):
        lines += ["", "## Where", ", ".join(WHERE[w] for w in task["where"])]
    if task.get("steps"):
        lines += ["", "## Steps"] + [f"{i}. {s}" for i, s in enumerate(task["steps"], 1)]
    if task.get("prompt"):
        lines += ["", "## Prompt for Claude Code", "```text", task["prompt"], "```"]
    lines += ["", "---", "_Generated from `docs/plan/tasks.json`._"]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plan", default="docs/plan/tasks.json", help="path to tasks.json")
    parser.add_argument("--dry-run", action="store_true", help="print actions without changing GitHub")
    args = parser.parse_args()

    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    phases = plan["phases"]

    # Labels: one per phase plus the fixed ones. --force updates an existing label.
    labels = {phase_label(p["n"]): ("17657e", p["title"]) for p in phases}
    labels.update(FIXED_LABELS)
    for name, (color, desc) in labels.items():
        print(f"label     {name}")
        if not args.dry_run:
            gh("label", "create", name, "--color", color, "--description", desc[:100], "--force")

    # Milestones: one per phase, skipped when the title already exists.
    existing_ms = set()
    if not args.dry_run:
        out = gh("api", "repos/{owner}/{repo}/milestones?state=all&per_page=100")
        existing_ms = {m["title"] for m in json.loads(out)}
    for p in phases:
        title = milestone_title(p)
        if title in existing_ms:
            print(f"milestone {title} (exists)")
            continue
        print(f"milestone {title}")
        if not args.dry_run:
            gh("api", "repos/{owner}/{repo}/milestones", "-f", f"title={title}", "-f", f"description={p['goal']}")

    # Issues: in plan order, so issue numbers follow the plan. Skipped when the title exists.
    existing_issues = set()
    if not args.dry_run:
        out = gh("issue", "list", "--state", "all", "--limit", "1000", "--json", "title")
        existing_issues = {i["title"] for i in json.loads(out)}
    created = skipped = 0
    for p in phases:
        for t in p["tasks"]:
            title = issue_title(t)
            if title in existing_issues:
                skipped += 1
                continue
            issue_labels = [phase_label(p["n"])]
            if t.get("learn"):
                issue_labels.append("learn-deeply")
            if t.get("once"):
                issue_labels.append("manual-once")
            if p.get("later"):
                issue_labels.append("later")
            print(f"issue     {title}  [{', '.join(issue_labels)}]")
            if not args.dry_run:
                with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
                    f.write(issue_body(p, t))
                gh("issue", "create", "--title", title, "--body-file", f.name,
                   "--milestone", milestone_title(p), "--label", ",".join(issue_labels))
                Path(f.name).unlink()
                time.sleep(1)  # stay well under GitHub's secondary rate limits
            created += 1
    print(f"\n{'Would create' if args.dry_run else 'Created'} {created} issues, skipped {skipped} existing.")


if __name__ == "__main__":
    main()
