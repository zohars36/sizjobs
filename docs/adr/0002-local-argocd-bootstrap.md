# 0002. Bootstrap ArgoCD locally from the Taskfile, tracking the current branch

Date: 2026-10-20

## Status

Proposed

## Context

ArgoCD manages everything in the cluster from `platform/` (app-of-apps,
a2-2), but something has to install ArgoCD itself and create the root
Application before GitOps can take over. Locally this happens on every
`task dev:up`, on a laptop where WSL has 10GB of RAM for everything.

When working on a branch, the local cluster should run that branch, not
`main`, so platform changes can be tried before they are merged. The repo
is public, so ArgoCD can pull from GitHub without credentials. It cannot see
the local working copy.

(ADR 0001 is reserved for the AWS region choice, b1-1.)

## Decision

We will install ArgoCD with Helm from `task dev:up`, using the official
`argo-cd` chart at a version pinned in `Taskfile.yml` (bumped by Renovate)
and the values in `platform/argocd/values-local.yaml`: Dex, notifications
and the ApplicationSet controller are off, and every container has memory
requests and limits.

`task dev:up` then applies `platform/root-app.yaml` with every
`targetRevision` replaced by the current git branch. The file in git keeps
`main`, which is what the EC2 cluster runs in Part B.

## Consequences

- ArgoCD syncs what is pushed to GitHub, not local edits. `task dev:up`
  warns when the branch is missing on origin or has unpushed commits.
- Branch testing reaches the child Applications only if a2-2 passes the
  root's revision down to them (for example as a Helm value), rather than
  hard-coding `main` in each one.
- ArgoCD is installed outside GitOps, so its own upgrades go through the
  Taskfile, not through a sync. Making ArgoCD manage itself can come later.
- The chart version lives in the Taskfile; Renovate needs the custom regex
  manager in `renovate.json` to find it.
