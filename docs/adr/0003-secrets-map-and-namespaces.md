# 0003. One secrets map for local Secrets and ExternalSecrets, split by namespace

Date: 2026-10-20

## Status

Proposed

## Context

Workloads need credentials: MinIO, the LLM gateway and Bedrock, Gmail,
Telegram, Langfuse and Grafana Cloud. In Part A they come from
`~/.config/sizjobs/.env` on the laptop; in Part B from SSM through
External Secrets. If the two paths produced different Secret names or
keys, every workload would need per-environment configuration.

A Kubernetes Secret can be read by any pod in its namespace whose service
account is allowed to, so where a Secret lives decides who can reach it.
The repo is public: names and layout may be published, values never.

## Decision

We will keep one file, `config/secrets-map.yaml`, listing each Secret's
name, namespace and keys, with no values. `task secrets` builds Secrets
from the `.env` with it now; Part B will generate ExternalSecrets from the
same file, reading SSM parameters `/sizjobs/<secret>/<KEY>`. Inside a
Secret, keys keep their env var names.

Secrets are split by who needs them: `data` (MinIO, next to Postgres),
`llm` (LiteLLM, Bedrock and Langfuse keys), `agents` (Gmail, Telegram) and
`monitoring` (Grafana Cloud). The agent gets an LLM key from LiteLLM and
never sees provider credentials.

`task secrets` never puts a value on a command line or in output: it
writes a mode-600 temp file in `/dev/shm`, passes it with
`--from-env-file`, deletes it immediately, and applies with server-side
apply so no `last-applied-configuration` annotation copies the values.

## Consequences

- Workloads reference the same Secret names on k3d and on AWS.
- Adding a credential means editing three places: `.env.example`, the map,
  and (in Part B) the SSM parameter. The script warns about `.env` keys the
  map does not know, which catches typos.
- A Secret needed in two namespaces is listed twice and stored twice.
- `task secrets` creates missing namespaces without labels. a2-5 must
  manage the namespaces in ArgoCD so they get Pod Security labels and
  NetworkPolicies regardless of who created them first.
