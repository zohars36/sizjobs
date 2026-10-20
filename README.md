# sizjobs

SizJobs: a personal AI job-search agent (Hermes) on Kubernetes. It runs
locally on k3d first (Part A), then on k3s in AWS eu-central-1 (Part B).
See [docs/](docs/) for the plan and product description.

## Local setup

Takes a fresh WSL Ubuntu 24.04 to a working environment. Every CLI tool
is installed by [mise](https://mise.jdx.dev) at the versions pinned in
[.mise.toml](.mise.toml); nothing is installed with apt or curl except
mise itself.

### 1. Install and activate mise

```bash
# Official installer: puts a single binary at ~/.local/bin/mise.
curl https://mise.run | sh

# Interactive shells: `mise activate` updates PATH on every prompt, so the
# versions in .mise.toml apply as soon as you cd into the repo.
echo 'eval "$(~/.local/bin/mise activate bash)"' >> ~/.bashrc

# Non-interactive shells (VS Code tasks, Claude Code, scripts) never read
# ~/.bashrc. The shims directory holds small wrappers that pick the right
# version per directory, so put it on PATH from ~/.profile as well.
echo 'export PATH="$HOME/.local/share/mise/shims:$PATH"' >> ~/.profile

exec bash -l   # reload the shell with both files applied
```

### 2. Install the pinned tools

```bash
cd ~/code/sizjobs
mise trust     # approve this repo's .mise.toml (mise ignores untrusted configs)
mise install   # download every tool in .mise.toml
```

### 3. AWS read-only SSO profile

Day-to-day work uses a read-only role. Changes to AWS go through
Terraform in CI, never from the laptop.

```bash
aws configure sso
#   SSO session name:         sizjobs
#   SSO start URL:            <your IAM Identity Center portal URL>
#   SSO region:               eu-central-1
#   SSO registration scopes:  (accept the default)
#   Then pick the account and the ReadOnlyAccess permission set.
#   CLI default client Region: eu-central-1
#   CLI default output format: json
#   Profile name:             sizjobs-ro

# Use this profile by default in every shell.
echo 'export AWS_PROFILE=sizjobs-ro' >> ~/.bashrc
export AWS_PROFILE=sizjobs-ro

aws sso login                 # opens the browser; tokens last about 8 hours
aws sts get-caller-identity   # should show an ...AWSReservedSSO_ReadOnlyAccess... role
```

The SSO config lands in `~/.aws/config`, outside the repo. Short-lived
tokens are cached in `~/.aws/sso/cache/`, and no access keys are created.

### 4. Verify

```bash
task doctor
```

It prints every tool's version, which should match `.mise.toml`, and checks
that Docker is running, that WSL has enough free memory, and whether you are
logged in to AWS. A missing tool or a stopped Docker fails it; low memory
and no AWS login are only warnings.

## Local model

A small model on the laptop, for offline smoke tests only. The laptop has
no GPU, so it is far too weak for daily job scoring; the real runs use an
API model behind LiteLLM (a3). It answers one question quickly and for
free: does the endpoint work, and can the model make a tool call?

Ollama runs on the WSL host (not in the cluster) as a systemd service:

```bash
curl -fsSL https://ollama.com/install.sh | sh   # once
ollama pull qwen2.5:1.5b                        # once, about 1 GB

task llm:up     # start Ollama and wait for its API (asks for sudo)
task smoke      # ✔/✘ per check: models list, then one tool call
task llm:down   # stop it again (asks for sudo)
```

**RAM:** a loaded model holds about 1.2 GB of the 10 GB WSL has, in
competition with the cluster. Ollama unloads it after 5 minutes idle, but
the server keeps running until `task llm:down`. The installer also
enables the service at boot; `sudo systemctl disable ollama` makes it
start only when you ask.

The smoke test and, later, the agent read their endpoint from three
variables. They are configuration, not secrets, so they are not in the
secrets map:

| Variable | Default | Meaning |
|---|---|---|
| `LLM_BASE_URL` | `http://localhost:11434/v1` | Any OpenAI-compatible endpoint: Ollama now, LiteLLM later |
| `LLM_MODEL` | `qwen2.5:1.5b` | Model name as the endpoint knows it |
| `LLM_API_KEY` | `ollama` | Dummy for Ollama, which ignores it; a real key for LiteLLM. Never printed |

For example, `LLM_MODEL=llama3.2:1b task smoke` tests another pulled model.

## Checks

The same checks run before every commit and in CI
(`.github/workflows/pre-commit.yml`). Turn them on once per clone:

```bash
pre-commit install          # run the hooks on every `git commit`
pre-commit run --all-files  # check the whole repo by hand
```

| Hook | What it catches |
|---|---|
| trailing-whitespace, end-of-file-fixer | Whitespace noise (fixed in place) |
| check-yaml, check-merge-conflict | Broken YAML, leftover `<<<<<<<` markers |
| check-added-large-files | Files over 1 MB |
| detect-private-key, gitleaks | Keys, tokens and other secrets |
| ruff-check, ruff-format | Python lint and formatting (fixed in place) |
| terraform_fmt, terraform_validate, terraform_tflint | Terraform formatting, validity and lint (Part B) |
| trivy config | HIGH and CRITICAL misconfigurations in Terraform, Kubernetes YAML and Dockerfiles |
| workflow-guard | `self-hosted` runners or `pull_request_target` in a workflow |
| zizmor | Insecure GitHub Actions: unpinned actions, persisted credentials, risky triggers |

When a fixer changes a file, the commit stops: review the change, `git add`
it and commit again. CI also scans the full git history with
`gitleaks git`, because the hook only sees staged changes.

Never skip the hooks with `--no-verify`; fix the cause. To silence a false
positive, use the tool's own inline ignore (`# noqa`, `# zizmor: ignore[...]`,
`#trivy:ignore:<id>`, `gitleaks:allow`) with a comment saying why.
