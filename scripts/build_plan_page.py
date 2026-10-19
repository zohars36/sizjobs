#!/usr/bin/env python3
"""Rebuild docs/plan/index.html from docs/plan/tasks.json, the page template and the repo .gitignore.

tasks.json is the single source of truth for the plan: edit it, then run
    python3 scripts/build_plan_page.py
and commit the result.
"""
import html
import json
from pathlib import Path

PRODUCT_URL = "../product/"

repo = Path(__file__).resolve().parent.parent
root = repo / "docs" / "plan"
data = json.loads((root / "tasks.json").read_text(encoding="utf-8"))
template = (root / "plan.template.html").read_text(encoding="utf-8")
gitignore = (repo / ".gitignore").read_text(encoding="utf-8").rstrip("\n")
blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
page = (template.replace("/*__DATA__*/", blob)
        .replace("__PRODUCT_URL__", PRODUCT_URL)
        .replace("__GITIGNORE__", html.escape(gitignore)))
(root / "index.html").write_text(page, encoding="utf-8")
print(f"Wrote {root / 'index.html'}")
