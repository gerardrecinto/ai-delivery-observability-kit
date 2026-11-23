{{- define "vllm.name" -}}{{ .Release.Name }}-vllm{{- end -}}
{{- define "vllm.labels" -}}
app.kubernetes.io/name: vllm
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
tenant: {{ .Values.tenant | quote }}
team: {{ .Values.team | quote }}
cost-center: {{ .Values.costCenter | quote }}
{{- end -}}
{{- define "vllm.selector" -}}
app.kubernetes.io/name: vllm
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
