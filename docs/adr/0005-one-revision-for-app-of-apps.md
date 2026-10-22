# 0005. One git revision for the whole app-of-apps, passed down through a Helm chart

Date: 2026-10-21

## Status

Proposed

## Context

ArgoCD manages the cluster through an app-of-apps: a root Application
renders child Applications from `platform/apps/`, and each child points at
its own source. Every Application has its own `targetRevision`.

Locally the cluster should run the current branch, so platform changes can
be tried before they merge. On EC2 (Part B) it runs `main`. If only the
root followed the branch while the children kept `targetRevision: main`, a
branch could change which apps exist but not what they deploy, and the
cluster would run a mix of two revisions. The same files must work on both
clusters with nothing k3d-specific in `platform/`.

Options considered:

1. Plain manifests in `platform/apps/`, with `task dev:up` rewriting
   every `targetRevision` before applying. Only the root is applied by
   hand; the children come from git, so a local rewrite cannot reach them.
2. An ApplicationSet with a git generator. It works, but it is a second
   controller (we run it with zero replicas to save memory) and a
   templating language of its own.
3. Kustomize patches per environment. Needs an overlay per branch, or
   a patch generated at apply time, which is again a local rewrite.
4. `platform/apps/` as a small Helm chart whose templates use
   `.Values.revision`, set by the root Application.

## Decision

We will make `platform/apps/` a Helm chart (option 4). The root
Application (`platform/root-app.yaml`) sets two Helm parameters from
ArgoCD's build environment: `revision` from
`$ARGOCD_APP_SOURCE_TARGET_REVISION`, and `repoURL` from
`$ARGOCD_APP_SOURCE_REPO_URL`. Every child that reads this repo uses
`"{{ .Values.revision }}"` and `"{{ .Values.repoURL }}"`.

The root's `targetRevision` is therefore the only place the revision is
written. The file in git says `main`; `task dev:up` replaces that one line
with the current branch before `kubectl apply`.

Child templates stay valid YAML (expressions in quotes, no `include`
lines), so `check-yaml` and Renovate's argocd manager can read them.

## Consequences

- One edit switches the whole tree. Children cannot drift from the root.
- The chart needs no k3d-specific values; EC2 applies the same root file
  unchanged.
- Upstream charts (podinfo now, CNPG and MinIO later) are pinned by their
  own chart version. Their values come from this repo through a second
  source with `ref: values`, so the values follow the branch too.
- Each child template repeats its sync policy (about ten lines) instead of
  sharing a Helm helper. That keeps them valid YAML and readable on their
  own.
- A mistake in a template breaks rendering for every child at once; the
  root shows a ComparisonError until it is fixed. `helm template
  platform/apps` catches this before pushing.
