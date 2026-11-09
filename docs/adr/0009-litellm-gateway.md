# 0009. LiteLLM as the AI gateway, from its official chart, pinned by digest

Date: 2026-11-09

## Status

Proposed

## Context

The agent (a4) needs one model endpoint that hides which provider answers
(Bedrock in a3-2, Ollama in a3-3, vLLM in Part B), with retries, fallback,
a budget per caller and a record of spend. The provider credentials must
stay out of the agent's namespace.

LiteLLM's proxy does all of this and is what the plan names. Facts that
shape how we run it:

- LiteLLM's release pipeline was compromised twice in 2026. In March,
  PyPI 1.82.7 and 1.82.8 were malicious. On 2026-10-21, `1.107.0` on PyPI,
  Docker Hub and GHCR, and the floating tags `latest`, `main-latest` and
  `main-stable`, shipped a credential stealer. Those images carried a valid
  signature from LiteLLM's cosign key, which was then considered exposed
  and rotated on 2026-10-23 (commit `e82a3c6`).
- 1.106.2, the version the incident post says to pin, is vulnerable to
  GHSA-w4c7-34wj-hqm8 (critical, master key readable without auth), fixed
  in 1.106.5. 1.106.6 (2026-10-28) is the newest 1.106.x patch older than
  ten days and is signed with the new key. The 1.108.x "LTS" line started
  2026-11-04 and had three patches in three days.
- The default image runs as root. `litellm-non_root` runs as UID 65534,
  which namespace `llm` (Pod Security "restricted") accepts.
- The official Helm chart (`oci://ghcr.io/berriai/litellm-helm`) is signed
  with the same key as the images. It can take an existing database and
  master-key Secret, builds `DATABASE_URL` from Secret values with
  Kubernetes' `$(VAR)` expansion, renders `config.yaml` into a ConfigMap
  and restarts the pod when it changes. It also bundles a Bitnami Postgres,
  a generated master key, a migrations Job as an ArgoCD PreSync hook and
  helm test pods.
- The open-source proxy cannot unmount its MCP gateway routes: the global
  `allowed_routes` setting is Enterprise-only. Per-key `allowed_routes`
  is open source.

## Decision

We will run the LiteLLM proxy from its official Helm chart, as the ArgoCD
app `litellm` in namespace `llm` (wave 2), with:

- Chart and image pinned to exact versions (1.106.6), the image
  (`litellm-non_root`) by multi-arch digest. `task llm:verify-image`
  checks the cosign key's fingerprint against LiteLLM's announcement,
  then the image and chart signatures, before every upgrade. Floating
  tags are never used.
- The chart's extras off: no bundled Postgres (the `litellm` database of
  the `jobs` CNPG cluster instead), no generated master key (Secret
  `llm/litellm` from the `.env`), no migrations Job (the proxy applies
  Prisma migrations at startup; the PreSync Job would wait forever on a
  first sync for a ServiceAccount that PreSync has not created yet), no
  test pods.
- One replica, one worker, 512Mi request and 1Gi limit, read-only root
  filesystem, no ServiceAccount token.
- `config.yaml` in git (the values file): logical model names
  (`agent-model` as an alias), retries, fallback, spend logs without
  prompt or response bodies, models only from the file.
- MCP off as far as the open-source proxy allows: no MCP servers, stdio
  servers disabled, and the agent key's `allowed_routes` limited to the
  chat and models routes.
- Access only from pods labelled as LLM clients in `agents`, plus
  port-forward for the admin UI and the `llm:*` tasks. No internet egress
  until a3-2.
- One virtual key for the agent (`task llm:key`): model `agent-model`
  only, 10 USD per 30 days. The master key never leaves `llm` and the
  laptop.

## Consequences

- The agent knows one URL and one model name; providers change in
  `config.yaml` only.
- Upgrades are manual and slower: read advisories, pick a version that has
  aged about two weeks, look up its digest, verify. Renovate can propose
  chart bumps, but the digest and the checks are on us.
- A signature check only proves the image came from LiteLLM's pipeline,
  which is exactly what failed on 2026-10-21. The age rule and reading the
  advisories are what would have caught that release.
- The `/mcp` routes still exist in the process. Only the master key can
  use them, and only through a port-forward; a future LiteLLM option to
  turn them off should replace this workaround.
- Migrations at startup make the first start, and starts after an
  upgrade, slower (the startup probe allows 5 minutes). With more than one
  replica we would need the migrations Job back, with its ServiceAccount
  created before PreSync.
- The chart ships Bitnami subcharts we do not use; they stay inert (disabled by
  values), but they are part of the artifact we deploy.
- `sslmode=require` encrypts Postgres traffic without verifying the
  server certificate; verify-full needs CNPG's CA in `llm`.
