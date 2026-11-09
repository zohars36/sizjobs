# Network flows

Every connection the NetworkPolicies in `platform/security` allow, and why.
Every application namespace (`data`, `llm`, `agents`) starts at
default-deny in both directions, so anything not in this table is blocked.
README.md "Cluster security" explains how the policies work and how to add
a row.

## How these were found

From the running cluster (a2-5, k3s v1.36.5, CNPG 1.30.1, SeaweedFS
4.48.0), not from documentation:

- The node's connection tracking table (`/proc/net/nf_conntrack` in the
  k3d node container), sampled every 1-2 seconds for about three minutes,
  once while idle and once during `task pg:backup`, with the addresses
  mapped back to pod and Service names. The reply direction shows where the
  Service sent each connection (for example `kubernetes:443` → node `:6443`).
- The pod specs: ports, labels, and the SeaweedFS command line
  (`-ip=${POD_IP}`, every component in one process).
- The CNPG operator binary, for the label its Job pods carry
  (`cnpg.io/jobRole`, values `initdb` and `full-recovery`).
- Checked after the policies were applied with `task pg:backup`,
  `task pg:backups`, `task pg:status` and `task pg:restore-drill`, which
  run the recovery Job.

## Namespace data

| # | From | To | Port | Policy (both sides) | Seen how |
|---|---|---|---|---|---|
| 1 | every pod | CoreDNS (`kube-system`, `k8s-app=kube-dns`) | UDP+TCP 53 | `allow-dns` | conntrack: jobs-1 → kube-dns:53 |
| 2 | CNPG operator (`cnpg-system`, `app.kubernetes.io/name=cloudnative-pg`) | jobs instance pods (`cnpg.io/cluster=jobs`, `cnpg.io/podRole=instance`) | TCP 8000 (status, HTTPS) | `pg-instances` ingress | conntrack: operator → jobs-1:8000 during reconcile |
| 3 | CNPG operator | jobs instance pods | TCP 5432 | `pg-instances` ingress | not seen in sampling; allowed for the operator's own SQL checks |
| 4 | jobs instance pods | Kubernetes API (node network, `kubeAPI.cidr`) | TCP 6443, 443 | `pg-instances` egress | conntrack: jobs-1 → `kubernetes:443`, sent to `172.19.0.2:6443` |
| 5 | jobs instance pods (Barman Cloud Plugin sidecar) | SeaweedFS (`app.kubernetes.io/name=seaweedfs`) | TCP 8333 (S3) | `pg-instances` egress, `seaweedfs` ingress | conntrack: jobs-1 → seaweedfs:8333 (WAL, base backup) |
| 6 | CNPG bootstrap Jobs (`cnpg.io/cluster=jobs`, `cnpg.io/jobRole` in `initdb`, `full-recovery`) | Kubernetes API | TCP 6443, 443 | `pg-bootstrap-jobs` egress | restore drill (recovery Job) |
| 7 | CNPG bootstrap Jobs | SeaweedFS | TCP 8333 | `pg-bootstrap-jobs` egress, `seaweedfs` ingress | restore drill: the recovery Job downloads base backup and WAL |
| 8 | create-buckets Job (`app.kubernetes.io/name=create-buckets`) | SeaweedFS | TCP 8333 | `create-buckets` egress, `seaweedfs` ingress | its script: `aws s3api` against the endpoint |
| 9 | `task pg:backups` pod (`app.kubernetes.io/name=pg-backups-ls`) | SeaweedFS | TCP 8333 | `pg-backups-ls` egress, `seaweedfs` ingress | its script: `aws s3 ls` |
| 10 | SeaweedFS | SeaweedFS | TCP 9333, 19333, 8080, 18080, 8888, 18888 | `seaweedfs` ingress and egress | today in one pod over its own IP, so no policy applies; kept for a split into separate pods |

## Not in the table, and why

| Traffic | Why no rule |
|---|---|
| kubelet health probes (node → pods, e.g. SeaweedFS :9333, jobs :8000, LiteLLM :4000) | kube-router, k3s's policy engine, always accepts traffic that starts on the pod's own node. |
| `kubectl exec`, `logs`, `port-forward` (`task pg:psql`, `task s3:forward`, `task llm:forward`) | Go through the API server and kubelet into the pod; port-forward connects inside the pod's own network namespace. |
| CNPG operator → Barman Cloud Plugin (`cnpg-system`, TCP 9090) | Both in `cnpg-system`, a platform namespace without policies. |
| Instance ↔ instance replication (5432) | One instance (`instances: 1`). Add it with the replicas. |
| Postgres metrics (9187) | Nothing scrapes them yet. Monitoring adds its own row. |

## Namespace llm

Added by a3-1 (LiteLLM 1.106.6). Flows from LiteLLM's configuration and
the chart's pod spec (one container, port 4000, no sidecars), and checked
with `task llm:health` (database) and `task llm:smoke` (clients).

| # | From | To | Port | Policy (both sides) | Seen how |
|---|---|---|---|---|---|
| 11 | every pod in `llm` | CoreDNS | UDP+TCP 53 | `allow-dns` (llm) | LiteLLM resolves `jobs-rw.data.svc.cluster.local` |
| 12 | LiteLLM (`llm`, `app.kubernetes.io/name=litellm`) | jobs instance pods (`data`, `cnpg.io/cluster=jobs`, `cnpg.io/podRole=instance`) | TCP 5432 | `litellm` egress (llm), `pg-instances` ingress (data) | `DATABASE_URL` → `jobs-rw:5432` (keys, budgets, spend logs); `task llm:health` db `connected` |
| 13 | agent pods (`agents`, `app.kubernetes.io/name` in `agent`, `llm-smoke`) | LiteLLM (`llm`, `app.kubernetes.io/name=litellm`) | TCP 4000 | `llm-clients` egress (agents), `litellm` ingress (llm) | `task llm:smoke`: its pod calls `litellm.llm.svc:4000` |

Row 13 is the only way into the gateway besides `kubectl port-forward`
(`task llm:forward`, and the temporary forwards of `llm:health`, `llm:key`
and `llm:spend`), which needs no rule ("Not in the table", above). `agent` is the agent
of a4; `llm-smoke` is the short-lived pod of `task llm:smoke`.

No internet egress from `llm`: the mock models call nothing, and
`LITELLM_LOCAL_MODEL_COST_MAP` keeps LiteLLM from downloading its price
list from GitHub at startup. a3-2 adds HTTPS egress for Bedrock.

## Namespace agents

The default-deny, `allow-dns`, and the egress half of row 13
(`llm-clients`). a4 adds the agent's own rules: agent → jobs:5432 (an
ingress item on `pg-instances` next to LiteLLM's, and egress in `agents`;
`networkpolicies-data.yaml` ends with the snippet).

Postgres clients from another namespace need two rules, because both
namespaces deny by default: ingress on `pg-instances` in `data` and
egress to `data` on 5432 in their own namespace, as row 12 shows.

## Part B (AWS)

- `kubeAPI.cidr`: the VPC CIDR instead of the k3d Docker network.
- `s3.inCluster: false`: rows 5, 7, 8 and 9 become egress to HTTPS (443)
  on `s3.externalCIDR`, and the `seaweedfs` policy is not rendered.
