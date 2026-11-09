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
  <app>/manifests/               plain manifests a child deploys next to its chart, e.g. seaweedfs/
  litellm/values.yaml            the AI gateway: chart values and config.yaml, see README.md "AI gateway"
  postgres/                      a chart of our own (Cluster jobs and its backups), see README.md "Database"
  security/                      a chart of our own (namespaces, Pod Security, NetworkPolicies), see README.md "Cluster security"
```

Every workload sets memory requests and limits: the cluster has 7 GiB.

## How a change reaches the cluster

1. Commit and push to a branch.
2. `task dev:up` points the root Application at that branch.
3. The root renders `platform/apps` with `revision` set to the same branch,
   so every child Application reads this repo at that branch too
   ([ADR 0005](../docs/adr/0005-one-revision-for-app-of-apps.md)).
4. ArgoCD polls git about every 3 minutes and syncs. To sync now, open
   the UI (`task argocd:ui`) and press Refresh on the root app.
   `task argocd:status` shows where every app stands.

Never `kubectl apply`, `edit` or `delete` resources ArgoCD manages:
selfHeal reverts the change within seconds.

## UI and CLI

`task argocd:status` needs no login: it reads the Application resources
with kubectl (`kubectl get applications -n argocd`).

**UI.** `task argocd:ui` port-forwards to http://localhost:8080. Log in as
`admin` with the password from `argocd admin initial-password -n argocd`.
Then change it in the UI (User Info → Update Password) and delete the
initial one, which is no longer needed:
`kubectl -n argocd delete secret argocd-initial-admin-secret`.
The Secret is not managed by ArgoCD; it was created by the Helm install.

**CLI, daily use: core mode.** No port-forward and no password: the CLI
reads and writes the Application resources itself through your kubeconfig,
with the permissions of your kubectl context.

```sh
kubectl config use-context k3d-sizjobs
# Core mode looks for Applications in the context's default namespace.
kubectl config set-context --current --namespace=argocd
argocd login --core
argocd app list
argocd app diff demo
```

**CLI through the port-forward.** Only needed for what goes through the
API server, such as testing logins or RBAC. With `task argocd:ui` running
in another terminal:

```sh
# --grpc-web: the CLI normally speaks plain gRPC; through a port-forward
#   to an HTTP (server.insecure) server only gRPC-Web over HTTP/1.1 works.
# --plaintext: the server serves HTTP, not TLS.
argocd login localhost:8080 --grpc-web --plaintext --username admin
```

## Adding an app

Copy `apps/templates/demo.yaml` and change the name, source, namespace and
wave. Every child Application has:

- `syncPolicy.automated` with `prune: true` and `selfHeal: true`
- `syncOptions: [CreateNamespace=true]`
- the `resources-finalizer.argocd.argoproj.io` finalizer, so removing the
  app from git deletes its resources too
- a sync wave (below)
- any source in this repo at `"{{ .Values.revision }}"`, never a fixed branch

An app in a new application namespace also needs that namespace in
`security/values.yaml` (Pod Security labels) and a
`security/templates/networkpolicies-<namespace>.yaml` with its allow rules;
see README.md "Cluster security".

## S3 (SeaweedFS)

Part A's stand-in for AWS S3 is SeaweedFS in namespace `data`
([ADR 0006](../docs/adr/0006-local-s3-seaweedfs.md)). Inside the cluster
the S3 API is at

```
http://seaweedfs-all-in-one.data.svc.cluster.local:8333
```

(Service `seaweedfs-all-in-one`, port 8333, plain HTTP; the region is not
checked, use `us-east-1`). Apps do not hard-code this: they load the
ConfigMap `s3-config` (`S3_ENDPOINT`, `S3_REGION`) and the Secret `s3`
(`S3_ACCESS_KEY`, `S3_SECRET_KEY`), both in `data`:

```yaml
envFrom:
  - configMapRef:
      name: s3-config
  - secretRef:
      name: s3
```

In Part B the ConfigMap points at AWS S3 and the keys give way to an IAM
role, so apps must use only the S3 API.

Buckets (`backups`, `private`) are created by the `create-buckets` Job on
every sync of the `seaweedfs` app; add a bucket by adding its name to
`BUCKETS` in `seaweedfs/manifests/create-buckets.yaml`. From the laptop:
`task s3:forward` in one terminal, `task s3:ls` in another.

## Sync waves

The annotation `argocd.argoproj.io/sync-wave` orders the child
Applications. ArgoCD syncs lower waves first and waits until they are
healthy before the next wave (that waiting relies on the Application health
check in `bootstrap/argocd-values.yaml`).

| Wave | What | Examples |
|---|---|---|
| -4 | Namespaces and policies | `security`: application namespaces with Pod Security labels, NetworkPolicies |
| -3 | Operator prerequisites | cert-manager |
| -2 | Operators | CloudNativePG operator |
| -1 | Operator plugins | Barman Cloud Plugin (needs cert-manager and the operator) |
| 0 | Storage | SeaweedFS (S3) |
| 1 | Databases | Postgres cluster `jobs` (restores from S3 in wave 0) |
| 2+ | Workloads | LiteLLM, the agent (need Postgres); demo stays in 1 |

Use the lowest wave that is still after everything the app needs.

An app whose chart cannot be fetched or rendered (a ComparisonError) has
no resources yet and reports Healthy, so the next wave starts anyway.
Its own sync still fails and is retried. Check `task argocd:status` for
SYNC `Unknown`.
