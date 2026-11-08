{{/*
Checks the bootstrap block once, so every template can rely on it. Called
from cluster.yaml; a failed check stops the render, so ArgoCD shows the
message as a sync error and changes nothing in the cluster.
*/}}
{{- define "postgres.checkBootstrap" -}}
{{- $b := .Values.bootstrap -}}
{{- if not (has $b.mode (list "initdb" "recovery")) -}}
{{- fail (printf "bootstrap.mode must be initdb or recovery, not %q" $b.mode) -}}
{{- end -}}
{{- if not $b.archiveTo -}}
{{- fail "bootstrap.archiveTo must be set (e.g. jobs-g1)" -}}
{{- end -}}
{{- if eq $b.mode "recovery" -}}
{{- if not $b.restoreFrom -}}
{{- fail "bootstrap.mode is recovery, so bootstrap.restoreFrom must name the generation to restore (e.g. jobs-g1)" -}}
{{- end -}}
{{- if eq $b.restoreFrom $b.archiveTo -}}
{{- fail (printf "bootstrap.restoreFrom and bootstrap.archiveTo are both %q: a restored cluster must archive into a new generation (see the comment in values.yaml)" $b.archiveTo) -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/* The plugin's name, as it registers itself with the operator. */}}
{{- define "postgres.pluginName" -}}barman-cloud.cloudnative-pg.io{{- end -}}
