---
name: ship
description: "Verify, commit, PR, merge and close the issue for a plan task"
argument-hint: "[task-id, e.g. a1-2]"
disable-model-invocation: true
---

Ship task $ARGUMENTS.

1. Find the GitHub issue whose title starts with "$ARGUMENTS:" (gh issue list --search "$ARGUMENTS in:title" --state open). Read it with gh issue view.
2. Verify the work against the issue's "Done when" item and steps. If anything is missing, stop and tell me.
3. Safety review before committing:
   - Run git status and git diff, and show me a short summary of what will be committed.
   - Make sure no secrets or personal data are included (.env, keys, tokens, profile.yaml, companies.yaml, raw emails). If you find any, stop.
   - If .pre-commit-config.yaml exists, run pre-commit run -a and fix what it reports.
4. If on main, create a branch named $ARGUMENTS-<short-slug>; otherwise use the current branch.
5. Commit with a message like "$ARGUMENTS: <issue title>", plus a short body of what changed and why.
6. Push the branch and open a PR: title "$ARGUMENTS: <issue title>", body with a 3-5 bullet summary and "Closes #<issue number>".
7. Wait for status checks (gh pr checks --watch). If something fails, show me and stop.
8. Show me the PR link and summary, and ask for my confirmation before merging.
9. After I confirm: gh pr merge --squash --delete-branch, then git switch main && git pull.
10. Confirm the issue is closed, and name the next open task in the same milestone.

Never push to main directly, never use --no-verify, never force push.