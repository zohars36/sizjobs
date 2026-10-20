# sizjobs
SizJobs: a personal AI job-search agent (Hermes) on Kubernetes.
Part A (now): runs locally on k3d in WSL on a 16GB laptop with no GPU; the model is an API model behind LiteLLM.
Part B (later): the same platform on k3s in AWS eu-central-1, destroyed every evening and rebuilt in the morning.

## Layout
- platform/: ArgoCD app-of-apps and Helm values (local values, plus values-aws in Part B)
- services/: agent, mcp-tools (Python, uv)
- evals/: promptfoo configs and golden dataset
- infra/persistent, infra/ephemeral: Terraform, Part B only
- docs/: plan, product description, adr/ (one decision per file, Nygard format)

## Rules
- Code, comments, commits, issues and PRs are always in English.
- Keep every workload small: memory requests and limits on everything; the laptop gives WSL 10GB.
- Anything AWS-specific must have a local stand-in in Part A: MinIO for S3, the .env for SSM.
- Images: public GHCR from main, signed with cosign; the k3d local registry only for quick branch iteration.
- Never run terraform apply or destroy locally. CI applies on merge to main (Part B).
- Tag every AWS resource project=sizjobs and layer=persistent|ephemeral.
- Cost first: no NAT gateway, no ALB, no EKS. Flag anything that bills hourly.
- No secrets in git or in prompts. Locally they live in ~/.config/sizjobs/.env, on AWS in SSM.
- Never read or print ~/.config/sizjobs/.env; use task secrets.
- A PreToolUse hook (.claude/hooks/guard-secrets.sh) blocks any tool call touching ~/.config/sizjobs.
- The repo is public: secrets and personal data (profile, company list, raw emails) never go into git, logs or PR comments.
- Never print secrets in workflows, never add self-hosted runners, never use pull_request_target.
- Run pre-commit run -a before you say a task is done.
- Never bypass hooks with --no-verify; fix the cause.
- When you make an architectural choice, draft an ADR in docs/adr/.
- Explain non-obvious flags and settings in comments. I am learning this stack.
