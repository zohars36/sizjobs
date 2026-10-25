# 0006. SeaweedFS as the local S3 stand-in

Date: 2026-10-25

## Status

Proposed

## Context

Part A needs a local stand-in for S3 (CLAUDE.md: every AWS dependency has
one). It holds Postgres backups and the private files that never go into
git, in buckets `backups` and `private`. Apps must reach it through the S3
API only, so that Part B can switch to AWS S3 by changing an endpoint.

The plan assumed MinIO. MinIO's community edition has been source-only
since October 2025, with no published images or binaries, and the
repository was archived in April 2026. A self-built image would be ours
to patch; the last published image gets no security fixes at all.

Constraints: the cluster has 7 GiB for everything, so the store should
idle well under 256Mi; it must run from a pinned Helm chart under ArgoCD
with its keys in a Secret that is never in git; and it must run under Pod
Security "restricted" (a2-5).

Options considered:

- **SeaweedFS.** Apache-2.0, in development since 2014, frequent
  releases. Official Helm chart with an all-in-one mode: one pod runs
  master, volume server, filer and S3 gateway. Its S3 identities file can
  reference keys through environment variables, so the keys can come from
  a Secret.
- **Garage.** AGPL, small Rust binary, made for small self-hosted
  clusters. After the first start the cluster layout has to be assigned
  with its CLI, which is an imperative step outside git, and it supports
  less of the S3 API (no versioning or bucket policies).
- **RustFS.** Apache-2.0, built as a drop-in MinIO replacement, but young
  and still changing quickly; we would be early adopters for data we want
  to keep.
- **The last MinIO image.** Works today and needs no new knowledge, but
  every future CVE stays open, and the problem only gets deferred.

## Decision

We will run SeaweedFS in namespace `data` from its official Helm chart in
all-in-one mode, one pod with a local-path PVC, deployed by the ArgoCD
Application `seaweedfs` (sync wave 0).

The S3 gateway requires signed requests. Its identities file
(`platform/seaweedfs/manifests/s3-identities.yaml`) holds only `${VAR}`
references, filled from the `s3` Secret (keys `S3_ACCESS_KEY`,
`S3_SECRET_KEY`) that `task secrets` creates. Buckets are created by an
idempotent Job using the same keys. Apps get the endpoint and region from
the ConfigMap `s3-config`.

Apps use only the S3 API, never SeaweedFS's filer or master APIs.

## Consequences

- The store idles at about 60Mi in one pod, instead of four pods in the
  chart's split mode. There is no redundancy, which a single-node cluster
  does not have anyway.
- Part B swaps the endpoint in `s3-config` for AWS S3 and replaces the
  static keys with IAM roles; apps that only speak S3 do not change. Any
  use of a SeaweedFS-only feature would break this, which is why apps are
  limited to the S3 API.
- SeaweedFS's S3 coverage differs from AWS in corners (some bucket
  configuration APIs, checksum and signing edge cases). Anything that
  depends on such a feature, CNPG's backups first, must be tested against
  SeaweedFS locally and against AWS S3 in Part B.
- The chart's own generated S3 Secret is not used: it relies on Helm
  `lookup`, which ArgoCD does not support, so its random keys would change
  on every render. The chart still renders an unused SFTP Secret with
  random passwords as a Helm hook; it is harmless but changes on each sync.
- Deleting the `seaweedfs` Application deletes the PVC and the data in it
  (local-path reclaim policy `Delete`). `task dev:delete` does not.
- MinIO knowledge from tutorials does not carry over to the server side
  (`mc admin`, the MinIO console); the S3 client side is the same.
