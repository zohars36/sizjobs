# 0010. Pin the subnet of the k3d Docker network

Date: 2026-11-09

## Status

Proposed

## Context

Pods that talk to the Kubernetes API (the CNPG instance and its bootstrap
Jobs) are let through by an `ipBlock` NetworkPolicy rule built from
`kubeAPI.cidr` in `platform/security/values.yaml` (ADR 0008). On k3s the
API server runs on the node, so the address the policy sees is the node's
address on the `k3d-sizjobs` Docker network.

Docker picks that network's subnet when `k3d cluster create` runs: the
first free /16 from its default pools (172.17.0.0/16 to 172.31.0.0/16,
then 192.168.x). Which one is free depends on the other Docker networks on
the machine. On the WSL laptop it was 172.19.0.0/16, and that went into
git. On the Mac, where a Jenkins network already holds 172.19.0.0/16,
Docker gave 172.20.0.0/16. The rule then blocked the API, and Postgres
bootstrap failed with `dial tcp 10.43.0.1:443` timeouts. `task sec:status`
warned, but only after the fact, and the fix (edit the value, push, sync)
had to be repeated on each machine and could flip again on any re-create.

## Decision

We will set `subnet: "10.100.0.0/24"` in `k3d/sizjobs.yaml`, and
`kubeAPI.cidr: 10.100.0.0/24` in `platform/security/values.yaml` to the
same range.

- 10.100.0.0/24 is outside Docker's default address pools, so Docker never
  gives it to another network on its own.
- It does not overlap k3s's pod network (10.42.0.0/16), its Service
  network (10.43.0.0/16), Part B's VPC (10.20.0.0/16), or the home LAN.
- A /24 holds 254 addresses; the network has three containers (node,
  registry, k3d tools). A narrower range also makes the API `ipBlock`
  narrower.

The two values are kept apart (the cluster config and the chart values);
comments in both name the other, and `task sec:status` still checks that
the node is inside `kubeAPI.cidr`.

## Consequences

- Every machine and every re-created cluster gets the same node address
  range, so the API rule works on first sync without a per-machine edit.
- A cluster created before this change keeps its old subnet: it has to be
  re-created (`task dev:delete`, `task dev:up`), because k3d only reads
  the subnet at creation.
- If something else on a machine already uses 10.100.0.0/24 (another
  Docker network created by hand, a VPN route), `k3d cluster create`
  fails with an overlap error instead of silently picking another range.
  The fix is to change both values together and re-create.
- Part B is unaffected: `values-aws.yaml` sets `kubeAPI.cidr` to the VPC
  CIDR.
