# 0004. Local k3d cluster: one capped node, a same-name registry, host-mounted storage

Date: 2026-10-21

## Status

Proposed

## Context

Part A runs the whole platform on a 16GB laptop where WSL gets 10GB. Docker,
the VS Code server and the agent's headless browser need memory too, and an
unbounded cluster can push WSL into swapping or the OOM killer. Part B runs
k3s on a single EC2 instance, so local and AWS should differ as little as
possible.

Branch builds need a registry the cluster can pull from. If the laptop
pushed to one image name and pods pulled from another, every manifest
would need a local rewrite. Inside a k3d node, `localhost` is the node
itself, not the laptop.

The cluster is deleted and re-created now and then (config changes, a
broken state). Postgres and MinIO data should not live only inside the node
container.

## Decision

We will define the cluster in `k3d/sizjobs.yaml` and drive it with
`task dev:up|down|delete|status`:

- One server and no agents, on the same k3s version as EC2 (v1.36.5),
  with Traefik disabled. metrics-server and local-path stay.
- No k3d load balancer: with one server it balances nothing, and the API
  is published from the server node on 127.0.0.1:6550.
- A Docker memory limit of 7 GiB on the server node (`serversMemory`).
  k3d also fakes `/proc/meminfo` so the kubelet sees 7 GiB of capacity.
- A k3d-managed registry container, published on 127.0.0.1:5000, plus a
  containerd mirror for `localhost:5000` pointing at it. The one image
  reference is `localhost:5000/<name>:<tag>`, for `docker push` and in
  manifests alike.
- Host directories under `~/.local/share/sizjobs` mounted into the node
  (local-path storage) and the registry (image layers). The config uses
  `${HOME}` because k3d expands environment variables but not `~`.

## Consequences

- WSL keeps about 3 GB outside the cluster. Workloads must fit in 7 GiB
  in total, so the memory requests and limits in the CLAUDE.md rule matter
  for scheduling, not only for hygiene.
- The memory cap, registry and volumes only apply at creation: changing
  them means `task dev:delete` and `task dev:up`.
- Pushed images and PV files survive `task dev:delete`. A re-created PVC
  gets a new UID and so a new, empty directory under local-path's default
  `pvc-<uid>_<ns>_<name>` naming, so old data has to be copied back by
  hand. A StorageClass with a stable `pathPattern` and `Retain` could fix
  this when the first stateful workload arrives.
- `localhost:5000` in a manifest only works in the k3d cluster. Manifests
  that reach `main` (and EC2) use GHCR images; the local registry is for
  branch iteration only.
- Without the load balancer, adding servers or agents later means
  re-creating the cluster with it turned back on.
