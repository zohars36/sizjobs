{{/*
Egress rules shared by several NetworkPolicies. Each renders list items for
spec.egress, so a template writes:
  egress:
    {{- include "security.egressKubeAPI" . | nindent 4 }}
*/}}

{{/* The Kubernetes API server on the node network (values kubeAPI). */}}
{{- define "security.egressKubeAPI" -}}
- to:
    - ipBlock:
        cidr: {{ .Values.kubeAPI.cidr }}
  ports:
    {{- range .Values.kubeAPI.ports }}
    - protocol: TCP
      port: {{ . }}
    {{- end }}
{{- end }}

{{/* Object storage: SeaweedFS by label locally, HTTPS outside in Part B. */}}
{{- define "security.egressS3" -}}
{{- if .Values.s3.inCluster }}
- to:
    - podSelector:
        matchLabels:
          {{- toYaml .Values.s3.podLabels | nindent 10 }}
  ports:
    - protocol: TCP
      port: {{ .Values.s3.port }}
{{- else }}
- to:
    - ipBlock:
        cidr: {{ .Values.s3.externalCIDR }}
  ports:
    - protocol: TCP
      port: {{ .Values.s3.externalPort }}
{{- end }}
{{- end }}

{{/* The two policies every application namespace starts with. */}}
{{- define "security.baseline" -}}
# Deny everything, both directions, for every pod in the namespace. An
# empty podSelector selects all pods; listing both policyTypes with no
# rules means no traffic is allowed in or out. Every other policy here
# adds an exception (policies only ever add up, they never subtract).
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: {{ .ns }}
spec:
  podSelector: {}
  policyTypes: [Ingress, Egress]
---
# Every pod may look up names in CoreDNS. Without this, even an allowed
# connection to jobs-rw.data.svc would fail at the lookup.
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns
  namespace: {{ .ns }}
spec:
  podSelector: {}
  policyTypes: [Egress]
  egress:
    - to:
        # Both selectors in one entry: pods with these labels AND in this
        # namespace. As two separate list items they would mean OR.
        - namespaceSelector:
            matchLabels:
              # Set by Kubernetes on every namespace, so it cannot be faked
              # by labelling another namespace.
              kubernetes.io/metadata.name: {{ .root.Values.dns.namespace }}
          podSelector:
            matchLabels:
              {{- toYaml .root.Values.dns.podLabels | nindent 14 }}
      ports:
        # UDP for normal lookups, TCP for answers too large for UDP.
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
{{- end }}
