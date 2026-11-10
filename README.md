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

### On macOS

The same steps work on a Mac with Docker Desktop, with these differences:

- **Install mise with its official installer** (step 1), not Homebrew.
  Homebrew has no prebuilt mise for Intel Macs and compiles it, cmake and
  Rust from source.
- **Shell startup files.** A bash login shell on macOS reads
  `~/.bash_profile` and neither `~/.bashrc` nor `~/.profile`, so put both
  lines from step 1 in `~/.bash_profile`. For zsh, use
  `eval "$(~/.local/bin/mise activate zsh)"` in `~/.zshrc` and the shims
  line in `~/.zprofile`. mise has to come first in `PATH`: older
  `kubectl`, `helm` or `terraform` binaries in `/usr/local/bin` would win
  otherwise (`which kubectl` should print a path under `~/.local/share/mise`).
- **Docker Desktop memory.** The cluster runs in Docker Desktop's Linux VM,
  so the VM plays the role of WSL: set Settings, Resources, Memory limit to
  10 GB. With less, the node's 7 GiB cap leaves the VM nearly nothing.
  `task doctor` reads the VM's memory, not the Mac's.
- **registry.localhost (optional).** Add `127.0.0.1 registry.localhost` to
  `/etc/hosts` (`sudo`; macOS keeps the file). Add
  `"insecure-registries": ["registry.localhost:5000"]` in Docker Desktop,
  Settings, Docker Engine, then Apply & restart.
- **Ollama** is a Homebrew service: `brew install ollama`. `task llm:up` and
  `task llm:down` call `brew services`, which needs no `sudo`.
- **Secrets.** Copy the `.env` from the old machine to
  `~/.config/sizjobs/.env` yourself and `chmod 600` it. Never paste it into a
  chat.

## Local cluster

One k3s node in Docker, created by [k3d](https://k3d.io) from
[k3d/sizjobs.yaml](k3d/sizjobs.yaml), plus a local image registry. The
node container is capped at 7 GiB of RAM, leaving about 3 GB of WSL's 10
for Docker, VS Code and the agent's browser. Design notes:
[ADR 0004](docs/adr/0004-local-k3d-cluster.md).

### Daily routine

```bash
task dev:up       # morning: create the cluster, or start it; waits until Ready
task dev:status   # nodes, kubectl top, and memory use of the k3d containers
task dev:down     # evening: stop it and free its RAM; nothing is lost
```

`task dev:up` is safe to repeat: it creates the cluster if it does not
exist, starts it if it is stopped, and only says so if it is running. It
switches kubectl to the `k3d-sizjobs` context in `~/.kube/config`. Then it
installs or upgrades ArgoCD, points the app-of-apps at your current branch
(which must be pushed: ArgoCD reads GitHub, not your working copy), and
runs `task secrets` if `~/.config/sizjobs/.env` exists.

```bash
task argocd:ui       # UI on http://localhost:8080 (port-forward, Ctrl+C to stop)
task argocd:status   # every Application with its sync wave, sync and health
```

Everything in the cluster comes from `platform/` through ArgoCD; see
[platform/README.md](platform/README.md). Change it in git, not with
`kubectl apply`: ArgoCD reverts manual changes.

### Pushing an image

One image reference works on both sides: `localhost:5000/<name>:<tag>`.

```bash
docker build -t localhost:5000/sizjobs-agent:dev services/agent
docker push localhost:5000/sizjobs-agent:dev
# and in a manifest:   image: localhost:5000/sizjobs-agent:dev
```

`task build` does this for every `services/*/Dockerfile`. On the laptop,
`localhost:5000` is the registry container's published port. Inside the
node, a containerd mirror in the k3d config sends the same name to that
container. Use this registry for quick branch builds only; images from
`main` come from GHCR, signed.

**Optional: pushing as `registry.localhost:5000`.** That is the registry's
name on the k3d network, and pods can pull it too, but the laptop needs two
one-time steps first. `localhost:5000` needs neither, so skip this unless
you want that name. Without them, `docker push` fails with "server gave
HTTP response to HTTPS client" (Docker only allows plain HTTP to registries
it is told are insecure).

1. `registry.localhost` must resolve to 127.0.0.1. Check with
   `getent hosts registry.localhost`. WSL regenerates `/etc/hosts` at
   every start, so a line added there is lost. Either add
   `127.0.0.1 registry.localhost` to the Windows hosts file
   (`C:\Windows\System32\drivers\etc\hosts`, as administrator), which WSL
   copies in, or set `generateHosts = false` under `[network]` in
   `/etc/wsl.conf` and edit `/etc/hosts` yourself.
2. Mark the registry insecure in Docker. Merge it into the existing
   `/etc/docker/daemon.json` rather than overwriting the file:

   ```bash
   # Ubuntu's own python3 (not the mise one, which sudo cannot see) reads
   # the file, or {} if it is missing, adds the entry unless it is already
   # there, and writes it back with every other setting kept.
   sudo /usr/bin/python3 - <<'EOF'
   import json, pathlib
   p = pathlib.Path("/etc/docker/daemon.json")
   cfg = json.loads(p.read_text()) if p.exists() else {}
   regs = cfg.setdefault("insecure-registries", [])
   if "registry.localhost:5000" not in regs:
       regs.append("registry.localhost:5000")
   p.write_text(json.dumps(cfg, indent=2) + "\n")
   EOF
   # k3d containers have a restart policy, so they come back with Docker.
   sudo systemctl restart docker
   docker info --format '{{json .RegistryConfig.IndexConfigs}}'   # should list registry.localhost:5000
   ```

`task doctor` warns if either step is missing.

### Where data lives

| Path on the WSL disk | What |
|---|---|
| `~/.local/share/sizjobs/storage` | PersistentVolume data (k3s local-path provisioner), one `pvc-<uid>_<namespace>_<name>` directory per PVC |
| `~/.local/share/sizjobs/registry` | Images pushed to `localhost:5000` |

Both survive `task dev:down` and `task dev:delete`. Deleting a PVC
deletes its directory (the StorageClass reclaim policy is `Delete`).

After `task dev:delete` the PVC directories stay on disk, but a
re-created PVC has a new UID and gets a new, empty directory. To get old
data back, copy it from the old directory into the new one. Postgres has
real backups (see [Database](#database)); for everything else, treat
cluster delete as losing in-cluster state.

### Resetting

```bash
task dev:delete   # asks first; removes the cluster, keeps ~/.local/share/sizjobs
task dev:up       # fresh cluster from k3d/sizjobs.yaml

# Full reset, data too. PVC directories are created by root inside
# the node, so removing them needs sudo.
task dev:delete && sudo rm -rf ~/.local/share/sizjobs
```

Re-create the cluster after changing `k3d/sizjobs.yaml`: most settings
(memory cap, registry, volumes) only apply at creation.

## Database

One PostgreSQL 17 cluster, `jobs`, in namespace `data`, run by the
[CloudNativePG](https://cloudnative-pg.io) operator (CNPG). It holds the
agent's results (database `agent`) and LiteLLM's state (`litellm`).
Why CNPG and how backups are named:
[ADR 0007](docs/adr/0007-postgres-cloudnativepg.md).

### What runs

| ArgoCD app | Wave | What | Namespace |
|---|---|---|---|
| `cert-manager` | -3 | TLS certificates for the plugin's connection to the operator | `cert-manager` |
| `cnpg-operator` | -2 | the CNPG operator 1.30 | `cnpg-system` |
| `barman-cloud-plugin` | -1 | the Barman Cloud Plugin: backups and WAL archiving to S3 | `cnpg-system` |
| `postgres` | 1 | chart [platform/postgres](platform/postgres): Cluster, ObjectStore, ScheduledBackup, Databases | `data` |

The Cluster has one instance (pod `jobs-1`, 256Mi requested, 512Mi
limit, `shared_buffers` 128MB) with a 2Gi PVC, from the standard CNPG
image. Settings are in
[platform/postgres/values.yaml](platform/postgres/values.yaml).

The roles `agent` and `litellm` own their databases. Their passwords come
from `PG_AGENT_PASSWORD` and `PG_LITELLM_PASSWORD` in the .env, which
`task secrets` turns into the basic-auth Secrets `pg-agent` and
`pg-litellm`. Change a password in the .env and run `task secrets` again
to rotate it. The `postgres` superuser has no password and no network
login. `task pg:psql` uses it through `kubectl exec`.

### How backups work

Backups go to `s3://backups/cnpg` on SeaweedFS (AWS S3 in Part B) through
the Barman Cloud Plugin, in two streams:

- **WAL archiving.** Postgres writes changes to its write-ahead log in
  16MB segments. The plugin's sidecar in pod `jobs-1` uploads each
  finished segment within seconds, so the archive is always nearly
  current. The Cluster's `ContinuousArchiving` condition says whether
  this works.
- **Base backups.** A full copy of the data directory, daily at 02:00
  Israel time (ScheduledBackup `jobs-daily`), and whenever you run
  `task pg:backup`.

A restore takes the newest base backup and replays the archived WAL after
it. That brings back everything up to the last archived segment, not
only what the 02:00 backup had. The plugin deletes backups and WAL older
than 7 days, always keeping enough to restore to any point in that
window.

```bash
task pg:status        # cluster, last base backup, ContinuousArchiving
task pg:backup        # base backup now, waits until it completes
task pg:backups       # what is in the bucket, per generation
task pg:psql          # psql as postgres; DB=agent task pg:psql for another database
task pg:psql DB=agent -- -c 'select now()'   # one statement, no prompt
```

### Generations

Every cluster archives into its own folder, its *serverName*:
`s3://backups/cnpg/jobs-g1/`, then `jobs-g2/`, and so on. A cluster
restored from `jobs-g1` must not archive back into `jobs-g1`. That folder
already holds the old cluster's WAL. The plugin refuses to archive into a
non-empty folder ("Expected empty archive"), because two timelines in one
folder would corrupt it. So `bootstrap` in `values.yaml` names both
sides:

```yaml
bootstrap:
  mode: recovery        # initdb: new, empty cluster; recovery: restore
  restoreFrom: jobs-g1  # generation to restore from (recovery only)
  archiveTo: jobs-g2    # generation this cluster writes to
```

The block is only read when the Cluster is created. Any time the Cluster
is created again from scratch, bump the generation first.

### Bumping the generation by hand

You need this when the cluster must be rebuilt from its backups outside
the drill: lost PVC, `task dev:delete`, a broken cluster. It is the
drill's steps 3 to 5 by hand. The order matters, so pause ArgoCD first.
If ArgoCD syncs the bump into a cluster that is still running, that
cluster starts archiving into the new generation, and the restored one
then finds the folder taken. With `archiveTo: jobs-gN`, on a branch
ArgoCD tracks (`task dev:up`):

```bash
kubectl -n argocd annotate applications.argoproj.io postgres argocd.argoproj.io/skip-reconcile=true
# If a Cluster exists (old, broken, or an empty one ArgoCD just made):
kubectl -n data delete clusters.postgresql.cnpg.io jobs   # its PVC goes with it
# Edit platform/postgres/values.yaml:
#   mode: recovery, restoreFrom: jobs-gN, archiveTo: jobs-gN+1
git commit -m "pg: archive generation jobs-gN -> jobs-gN+1" platform/postgres/values.yaml
git push
kubectl -n argocd annotate applications.argoproj.io postgres argocd.argoproj.io/skip-reconcile- argocd.argoproj.io/refresh=hard
task pg:status   # until Ready, then:
task pg:backup   # a base backup of the new generation's own
```

Then merge the change to main, so the next rebuild starts from it. The
Cluster is marked `Prune=false`, so ArgoCD never deletes it on its own.

Old generations are not deleted by the retention policy, which only
covers the folder being archived to. Once the new generation has a base
backup, remove old ones with `aws s3 rm --recursive` on
`s3://backups/cnpg/jobs-gN/` (`task s3:forward` gives you the endpoint).

### Restore drill

```bash
task pg:restore-drill   # asks first; --yes skips the question
```

The full cycle, run on a branch that ArgoCD tracks, with no other
unpushed commits. It takes a few minutes:

1. Checks that `jobs` is Ready and archiving.
2. Writes canary row 1, takes a base backup, then writes canary row 2 and
   waits until its WAL segment is archived. Row 2 is in no base backup,
   so it can only come back through WAL replay.
3. Pauses ArgoCD for `postgres` (annotation
   `argocd.argoproj.io/skip-reconcile`), so it cannot recreate the cluster
   from the old values.
4. Deletes Cluster `jobs` and its PVC.
5. Bumps the generation in `values.yaml`, commits and pushes, and resumes
   ArgoCD with a hard refresh.
6. Waits for ArgoCD to create `jobs` in recovery mode and for the restore.
   Then checks four things: it restored from the old generation, it
   archives to the new one, both canary rows are back, and
   `ContinuousArchiving` is True. Prints PASS or FAIL.
7. On PASS, takes a base backup in the new generation.

If the drill stops before step 4, it resumes ArgoCD and nothing is lost.
If it stops later, ArgoCD stays paused and the drill prints what to do.
Merge the drill's commit with your branch, so main knows the new
generation.

### The kubectl cnpg plugin

Optional, for more detail (`kubectl cnpg status jobs -n data` shows
replication, WAL and backup state on one page; `task pg:status` calls it
when it is installed). mise has no package for it, so install it with
[krew](https://krew.sigs.k8s.io), kubectl's plugin manager, which is
pinned in `.mise.toml`:

```bash
# Once: krew installs plugins into ~/.krew/bin; put that on PATH
# (in ~/.bashrc and ~/.profile, like the mise shims).
export PATH="$HOME/.krew/bin:$PATH"
# mise installs krew as a plain `krew` binary, so call it directly
# (`kubectl krew` would need it named kubectl-krew).
krew update
krew install cnpg
kubectl cnpg version     # should match the operator's minor, 1.30
```

krew always installs the newest plugin release. `krew upgrade cnpg`
updates it; keep its minor version in line with the operator.

## Cluster security

The application namespaces `data`, `llm` and `agents` have two layers of
protection, both from git through the ArgoCD app `security`
(`platform/security`, sync wave -4, so they exist before any workload).
Platform namespaces (`argocd`, `cnpg-system`, `cert-manager`,
`kube-system`) are left to their own charts. Why this shape:
[ADR 0008](docs/adr/0008-cluster-security.md).

### Layer 1: Pod Security "restricted"

Pod Security Admission is built into the API server. Labels on each
namespace set the level for three modes: `enforce` rejects a pod that
breaks the rules, `audit` logs it, `warn` prints a warning to whoever
created it. All three are `restricted`, pinned to `v1.36` (the k3s
version) so a Kubernetes upgrade cannot tighten the rules by surprise.

`restricted` means every container must run as non-root, set
`allowPrivilegeEscalation: false`, drop all capabilities, use the
`RuntimeDefault` (or a custom) seccomp profile, and use no host
namespaces, ports or paths. A pod spec that passes:

```yaml
spec:
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000          # a fixed UID when the image defaults to root
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: app
      securityContext:
        allowPrivilegeEscalation: false
        capabilities:
          drop: [ALL]
```

If a pod is rejected, fix its spec; never lower the namespace's level.
Pods inside a Job or Deployment are checked when the controller creates
them, so a bad template shows up as an event on the Job or ReplicaSet
(`kubectl -n data get events`), not as an error from `kubectl apply`.

### Layer 2: NetworkPolicies, default-deny

k3s enforces NetworkPolicy out of the box (its embedded kube-router), on
k3d too. Every application namespace has:

- `default-deny-all`: no traffic in or out for any pod.
- `allow-dns`: every pod may query CoreDNS on port 53.

Everything else is an explicit exception, selected by pod and namespace
labels (never by IP, except the API server, which on k3s runs on the node
and is allowed as the `kubeAPI.cidr` ipBlock). The flows and the policy
for each are in [docs/network-flows.md](docs/network-flows.md).

### Adding an allow rule for a new service

1. Find the real flows: which pods connect to which, on which ports
   (the service's docs, then check them against the running pods).
2. Give the pods a stable label, such as `app.kubernetes.io/name: litellm`.
3. In `platform/security/templates/networkpolicies-<namespace>.yaml`, add
   a policy that selects those pods with their egress (what they connect
   to) and their ingress (who connects to them). If the other end is in
   an application namespace too, it needs the matching rule there:
   default-deny blocks both directions. Across namespaces, put
   `namespaceSelector` (on `kubernetes.io/metadata.name`) and
   `podSelector` in the same list item so both must match. The data
   template ends with a commented example for Postgres clients.
4. Add a row to `docs/network-flows.md`.
5. Commit, push, let ArgoCD sync, and check the service works and
   `task sec:test` still passes.

### Testing

```bash
task sec:status   # Pod Security labels and NetworkPolicies per namespace
task sec:psa      # a privileged pod in data must be rejected
task sec:test     # from a pod with no allow rule: Postgres, S3 and the
                  # internet blocked, DNS working
```

`sec:test` first checks that Postgres and S3 have ready endpoints, so a
blocked connection really is the policy and not a service that is down.
`sec:status` also warns when the node's address has left `kubeAPI.cidr`:
Docker picks the k3d network's subnet when the cluster is created, so a
re-created cluster can land on another one.

## AI gateway

Every model call in the cluster goes through
[LiteLLM](https://docs.litellm.ai/) in namespace `llm` (ArgoCD app
`litellm`, sync wave 2; chart values and `config.yaml` in
[platform/litellm/values.yaml](platform/litellm/values.yaml)). Why this
shape: [ADR 0009](docs/adr/0009-litellm-gateway.md).

### What it does

- **One endpoint, logical names.** Clients call the OpenAI-compatible API
  at `http://litellm.llm.svc.cluster.local:4000/v1` and ask for a logical
  model name. LiteLLM maps it to a real deployment, so switching provider
  is a change to `config.yaml`, never to the agent.
- **Retries and fallback.** A failed call is retried twice
  (`num_retries: 2`, 60 s `timeout` per call), then sent to the fallback.
- **Keys and budgets.** Every client has its own virtual key, limited to
  certain models and a budget. LiteLLM stores keys (hashed), budgets and
  one spend-log row per request (key, model, tokens, cost, but no prompt or
  response text) in the `litellm` database of the `jobs` Postgres cluster.
- **The only holder of provider credentials** (from a3-2). Apps never see
  them, nor the master key.

### Logical model names

| Name | What answers today | Who may call it |
|---|---|---|
| `agent-model` | alias of `agent-model-primary`, falling back to `agent-model-backup` | the agent's key |
| `agent-model-primary` | mock: `MOCK PRIMARY: agent-model-primary answered.` | master key only |
| `agent-model-backup` | mock: `MOCK BACKUP: agent-model-backup answered.` | master key only |

The mocks use LiteLLM's `mock_response`: no provider is called, and
made-up prices make the spend tracking count something. a3-2 puts Bedrock
behind `agent-model`; a3-3 adds `local-small` (Ollama).

### Keys and budgets

| Key | Where | Can |
|---|---|---|
| Master key `LITELLM_MASTER_KEY` | `.env` → Secret `llm/litellm` | everything: admin API, admin UI. Only LiteLLM and the `llm:*` tasks use it |
| Salt key `LITELLM_SALT_KEY` | `.env` → Secret `llm/litellm` | encrypts credentials LiteLLM stores in its DB. Never change it once set |
| Agent key `LITELLM_AGENT_KEY` | `.env` → Secret `agents/llm-key` | model `agent-model` only; routes `/v1/chat/completions` and `/v1/models` only; 10 USD per 30 days |

`task llm:key` creates the agent key through the admin API and writes it
straight into the `.env` (it prints only `LITELLM_AGENT_KEY written`);
`task secrets` then copies it into the cluster. When the key's spend
reaches `max_budget`, LiteLLM rejects its calls until the budget resets,
once per `budget_duration` (30d). LiteLLM picks the reset date itself (a key
created on 2026-11-09 resets on 2026-12-01); `task llm:spend` shows it.

```bash
task llm:key        # once: create the agent key (refuses if one exists)
task secrets        # push it to Secret agents/llm-key
task llm:smoke      # PASS/FAIL: primary, fallback, no key, wrong model, MCP
task llm:spend      # the agent key's spend, budget and requests per model
task llm:health     # pods, liveness, readiness, database
task llm:forward    # http://localhost:4000/ui, the admin UI (user admin,
                    # password: the master key)
```

**Rotating the agent key** (monthly, or at once if it may have leaked):

```bash
task llm:key ROTATE=1   # revoke the old key in LiteLLM, create a new one, write it to the .env
task secrets            # update Secret agents/llm-key
# Restart whatever uses it (the agent, from a4), so it reads the new value.
```

The old key stops working the moment it is revoked, so expect the agent's
calls to fail until `task secrets` and its restart are done. Rotating the
master key means changing it in the `.env`, `task secrets`, and
`kubectl -n llm rollout restart deployment litellm`; virtual keys stay
valid.

### What is switched off

- **MCP gateway.** LiteLLM 1.106.6 open source cannot unmount its `/mcp`
  routes (the global `allowed_routes` setting is Enterprise-only). So:
  no MCP servers in `config.yaml`; stdio MCP servers (which run commands
  in the pod) disabled with `LITELLM_ENABLE_MCP_STDIO=false`; models and
  servers cannot be added through the API (`store_model_in_db: false`);
  and the agent key's `allowed_routes` excludes every MCP route
  (`task llm:smoke` check e). Only the master key could reach them, and
  only through a port-forward.
- **Test switches, still on.** `dangerously_allow_mock_testing_request_params: true` lets any key send `mock_testing_fallbacks` (used by `task llm:smoke` check b). Harmless with mock models only; a3-2 turns it off before real providers arrive.
- **Swagger and ReDoc pages** (`NO_DOCS`, `NO_REDOC`). The admin UI at
  `/ui` stays, reachable only through `task llm:forward`: the Service is
  ClusterIP and the NetworkPolicies let only the agent's pods in
  ([docs/network-flows.md](docs/network-flows.md) rows 12-13).
- **Internet egress.** None from `llm` yet; LiteLLM uses the price list
  in its image (`LITELLM_LOCAL_MODEL_COST_MAP`). a3-2 adds HTTPS for
  Bedrock.
- **Bundled extras of the chart**: its Bitnami Postgres, its generated
  master-key Secret, its migrations Job (the proxy migrates at startup),
  its helm test pods.

### Upgrading LiteLLM safely

On 2026-10-21 LiteLLM's release pipeline was compromised: `1.107.0` on
PyPI and Docker, and the floating tags `latest`, `main-latest` and
`main-stable`, shipped a credential stealer
([LiteLLM's post](https://docs.litellm.ai/blog/security-incident-oct-21-2026)).
A valid signature is not proof of safety: the bad images were signed with
the then-current key. So an upgrade is deliberate:

1. **Read the advisories** first: LiteLLM's
   [security posts](https://docs.litellm.ai/blog/tags/security) and
   [GitHub advisories](https://github.com/BerriAI/litellm/security/advisories).
   Pick an exact `vX.Y.Z` that is about two weeks old, is not named in an
   incident, and is past every advisory's fixed version. Never `latest`,
   `main-latest`, `main-stable`, `lts` or any other floating tag.
2. **Pin by digest.** Look up the multi-arch digest of the non-root image:
   `docker buildx imagetools inspect ghcr.io/berriai/litellm-non_root:vX.Y.Z`
   (the top-level `Digest:`). Set `image.tag: vX.Y.Z@sha256:...` in
   `platform/litellm/values.yaml`, and `targetRevision` of the chart in
   `platform/apps/templates/litellm.yaml` to the same version. Read the
   release notes for chart value changes.
3. **Verify** with `task llm:verify-image`: it checks the key's
   fingerprint, then the image (by digest) and chart signatures with
   cosign. If LiteLLM rotates its key again, update
   `LITELLM_COSIGN_KEY_URL` (a commit, not a branch) and
   `LITELLM_COSIGN_FINGERPRINT` in `Taskfile.yml` from their announcement.
4. Commit on a branch, `task dev:up`, then `task llm:health` and
   `task llm:smoke` before merging.

Why 1.106.6 today: published 2026-10-28 on the 1.106.x line the incident
post recommends, signed with the key rotated on 2026-10-23, and past
GHSA-w4c7-34wj-hqm8 (critical master-key leak, fixed in 1.106.5), so
newer than the post's "pin 1.106.2". The 1.108.x LTS line was days old
with three patches in three days.

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
