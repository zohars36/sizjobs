# 0008. Pod Security "restricted" and default-deny NetworkPolicies, owned by one ArgoCD app

Date: 2026-11-08

## Status

Proposed

## Context

The application namespaces (`data` with SeaweedFS and Postgres, `llm` for
LiteLLM, `agents` for the agent) will hold credentials for Gmail,
Telegram, the model providers and the database. The agent reads untrusted
input (job ads, emails) and drives tools, so a compromised or confused pod
must not be able to reach whatever it likes or run with more privilege
than it needs.

Until now nothing restricted pods: no Pod Security labels, and no
NetworkPolicies, so every pod could connect to every other pod and the
internet. The namespaces were created by whichever came first: an ArgoCD
app's `CreateNamespace=true` or `task secrets`, both without labels
([ADR 0003](0003-secrets-map-and-namespaces.md)).

Facts that shape the design:

- k3s enforces NetworkPolicy through its embedded kube-router, both on k3d
  and on EC2, with no extra CNI. kube-router always accepts traffic from
  the pod's own node, so kubelet probes need no rule.
- On k3s the API server is not a pod. Traffic to the `kubernetes` Service
  is translated to the node's own address on 6443 before the policy is
  checked, so a label selector cannot match it.
- Pod Security Admission is built into the API server; the standard
  levels need no extra component (unlike Kyverno or Gatekeeper, each a few
  hundred MiB).
- Every workload in `data` already ran with a restricted-compatible
  `securityContext` (checked with a server-side dry run of the label).

## Decision

We will have one ArgoCD app, `security` (`platform/security`, a small
chart), in sync wave -4, that owns the application namespaces and their
policies:

- The `Namespace` objects, with `pod-security.kubernetes.io/{enforce,audit,warn}`
  set to `restricted`, pinned to the cluster's minor version (`v1.36`)
  rather than `latest`. They carry `Prune=false,Delete=false`, so ArgoCD
  never deletes a namespace and the data in it.
- In each namespace a `default-deny-all` policy (ingress and egress) and
  `allow-dns`, plus explicit allow rules for every real flow, selected by
  pod and namespace labels. The flows are recorded in
  [docs/network-flows.md](../network-flows.md).
- The API server is the one destination allowed by address: an `ipBlock`
  from a single value, `kubeAPI.cidr` (the k3d Docker network locally, the
  VPC CIDR in Part B).
- Object storage destinations come from values too: SeaweedFS by label
  locally, HTTPS to an external CIDR in Part B (`s3.inCluster: false`).
- Policies live next to the namespaces, not next to each workload, so one
  place answers "what can talk to what". Each workload task adds its rules
  to its namespace's template.

Platform namespaces (`argocd`, `cnpg-system`, `cert-manager`,
`kube-system`) are out of scope; their charts manage them.

## Consequences

- No pod in an application namespace can run privileged or as root, and a
  new pod reaches nothing but DNS until a rule allows it. `task sec:psa`
  and `task sec:test` check both.
- Every new service costs a policy change and a row in the flow table, in
  both namespaces when the flow crosses them. Forgetting one shows up as a
  timeout, which is slower to diagnose than a clear error.
- The API server rule depends on the k3d Docker subnet, which Docker picks
  when the cluster is created. `task sec:status` warns when the node is
  outside `kubeAPI.cidr`. Pinning the subnet in `k3d/sizjobs.yaml` would
  remove this, at the cost of a cluster re-create.
- Bumping k3s means bumping `podSecurity.version` on purpose, and reading
  what the new version changes in the `restricted` rules.
- The `CreateNamespace=true` left on other apps is harmless: it only
  creates a missing namespace and never touches labels.
- Policies are written by hand. A tool that records flows (Cilium Hubble,
  or a policy generator) would make this easier, but costs memory and
  replaces the CNI.
