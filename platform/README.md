# platform

Everything running in the cluster, managed by ArgoCD with the app-of-apps
pattern. The same files serve the local k3d cluster (Part A) and k3s on
EC2 (Part B): nothing here may be k3d-specific.

```
platform/
  bootstrap/argocd-values.yaml   Helm values for ArgoCD itself (installed by task dev:up)
  root-app.yaml                  the root Application, applied once by hand
  apps/                          Helm chart: one template per child Application
  <app>/values.yaml              values a child reads from this repo, e.g. demo/
```

Every workload sets memory requests and limits: the cluster has 7 GiB.

## How a change reaches the cluster

1. Commit and push to a branch.
2. `task dev:up` points the root Application at that branch.
3. The root renders `platform/apps` with `revision` set to the same branch,
   so every child Application reads this repo at that branch too
   ([ADR 0005](../docs/adr/0005-one-revision-for-app-of-apps.md)).
4. ArgoCD polls git about every 3 minutes and syncs. To sync now:
   `argocd app sync root --core` or the UI (`task argocd:ui`).

Never `kubectl apply`, `edit` or `delete` resources ArgoCD manages:
selfHeal reverts the change within seconds.

## Adding an app

Copy `apps/templates/demo.yaml` and change the name, source, namespace and
wave. Every child Application has:

- `syncPolicy.automated` with `prune: true` and `selfHeal: true`
- `syncOptions: [CreateNamespace=true]`
- the `resources-finalizer.argocd.argoproj.io` finalizer, so removing the
  app from git deletes its resources too
- a sync wave (below)
- any source in this repo at `"{{ .Values.revision }}"`, never a fixed branch

## Sync waves

The annotation `argocd.argoproj.io/sync-wave` orders the child
Applications. ArgoCD syncs lower waves first and waits until they are
healthy before the next wave (that waiting relies on the Application health
check in `bootstrap/argocd-values.yaml`).

| Wave | What | Examples |
|---|---|---|
| -2 | Namespaces and CRDs | namespaces with Pod Security labels (a2-5) |
| -1 | Operators | CloudNativePG operator |
| 0 | Infrastructure | MinIO, Postgres clusters, LiteLLM |
| 1+ | Workloads | demo, the agent |

Use the lowest wave that is still after everything the app needs.
