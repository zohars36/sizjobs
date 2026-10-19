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
mise ls --current && \
terraform version | head -1 && \
kubectl version --client && \
helm version --short && \
k3d version && \
aws --version && \
gh --version | head -1 && \
uv --version && \
task --version && \
pre-commit --version && \
python --version
```

Each line should match the version in `.mise.toml`. `kubectl version
--client` only prints the client because no cluster exists yet.
