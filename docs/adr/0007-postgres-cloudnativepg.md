# 0007. Postgres on CloudNativePG, backed up by the Barman Cloud Plugin in generations

Date: 2026-11-08

## Status

Proposed

## Context

The agent's results and LiteLLM's state need PostgreSQL. It is the only
stateful component that matters: in Part B the whole environment is
destroyed every evening and rebuilt every morning, so the database has to
come back from object storage on every bring-up. Locally the same path
must work against SeaweedFS ([ADR 0006](0006-local-s3-seaweedfs.md)).

Constraints: one node with 7 GiB for everything; deployed by ArgoCD from
git; secrets only from `task secrets` (later SSM); the same chart has to
point at AWS S3 in Part B by changing values.

Options considered:

- **CloudNativePG (CNPG).** A CNCF operator that manages Postgres through
  Kubernetes resources (Cluster, Backup, ScheduledBackup, Database) and
  has backup, WAL archiving and point-in-time recovery to S3 built into
  its design. One instance costs one pod.
- **A plain StatefulSet, or the Bitnami chart, with pg_dump CronJobs.**
  Fewer moving parts, but restores are hand-written scripts, recovery
  only reaches the last dump, and there is no WAL archive.
- **Amazon RDS in Part B.** Billed by the hour, survives the nightly
  teardown only if it is left running, and has no local stand-in.

Within CNPG there are two ways to back up to S3. The in-tree
`spec.backup.barmanObjectStore` has been deprecated since CNPG 1.26 and is
being removed. The **Barman Cloud Plugin** (CNPG-I) replaces it and
brings its own ObjectStore resource and a sidecar per Postgres pod.

The WAL archive has one catch for clusters that are recreated often.
barman-cloud stores everything under `<destinationPath>/<serverName>/`.
When a new cluster starts archiving, it checks that this folder is empty
and refuses otherwise ("Expected empty archive"), because WAL from two
timelines in one folder corrupts the archive. A cluster restored from
folder X therefore cannot archive into X.

## Decision

We will run PostgreSQL 17 with CloudNativePG 1.30 (one instance,
`jobs`, namespace `data`, standard image), back it up with the Barman
Cloud Plugin to `s3://backups/cnpg`, and deploy it with ArgoCD in four
waves: cert-manager (-3, which the plugin needs for its TLS), the
operator (-2), the plugin (-1) and our chart `platform/postgres` (1).

- **Backups.** WAL archiving through the plugin (`isWALArchiver: true`),
  a daily base backup at 02:00 Israel time, a retention policy of 7 days.
  CNPG schedules have no time zone field, so the operator runs with
  `TZ=Asia/Jerusalem`.
- **Bootstrap.** One value, `bootstrap.mode`, chooses `initdb` (new
  cluster) or `recovery` (latest base backup, then WAL replay, through an
  externalCluster that uses the plugin).
- **Generations.** The serverName carries a generation suffix:
  `jobs-g1`, `jobs-g2`, and so on. The values name both `restoreFrom`
  and `archiveTo`; every recreation from scratch bumps them by one, and
  the chart refuses to render if they are equal. The bump is a commit,
  so git always says which generation is live.
- **Roles and databases.** `agent` and `litellm` are CNPG managed roles
  with passwords from basic-auth Secrets, and each owns a database
  declared with the Database resource. The secrets map gained optional
  `type`, `literals`, `labels` and renamed keys for this.
- **Safety.** The Cluster resource carries `Prune=false,Delete=false`,
  so neither a mistake in git nor deleting the Application deletes it.
- **Proof.** `task pg:restore-drill` runs the whole cycle against the
  live cluster: it deletes the cluster and restores it through git and
  ArgoCD.

## Consequences

- A restore is a git change: pause ArgoCD for `postgres`, delete the
  Cluster, push the bump, resume (README "Database"). The drill automates
  this. Done in the wrong order, the running cluster starts archiving
  into the new generation and the restore fails its archive check, but
  no data is lost.
- Old generations stay in the bucket: retention only covers the folder
  being archived to. They have to be removed by hand, or by a later
  lifecycle rule.
- Part B rebuilds every morning, which means a bump every day. A commit
  per morning is not workable, so b-tasks will have to derive the
  generation at bring-up (for example from the newest folder in the
  bucket) and pass it as Helm parameters. This chart already takes both
  values, so only the caller changes.
- Three more operators run all the time (cert-manager about 100Mi, CNPG
  and the plugin about 100Mi together) on top of Postgres itself
  (256Mi to 512Mi) and its sidecar.
- The endpoint is stated twice, in the `s3-config` ConfigMap and in the
  chart values, because ObjectStore takes a string, not a reference.
- `TZ` on the operator applies to every ScheduledBackup in the cluster;
  with one cluster that is what we want.
- SeaweedFS has to keep up with barman-cloud's S3 use; the drill tests
  exactly that, and Part B repeats it against AWS S3.
