# Grafana Observability Stack — Helm Setup Guide

Full LGTM stack (Loki + Grafana + Tempo + Prometheus) with Grafana Alloy as the
telemetry collector, deployed to a local Kubernetes cluster via Helm.

---

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| kubectl | any | connected to your local cluster |
| helm | >= 3.10 | `helm version` to verify |
| Kubernetes | >= 1.25 | Docker Desktop / kind / minikube all work |

All commands below are run from this `Grafana_stack/` directory.

---

## Step 1 — Add the Grafana Helm repository

```bash
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update
```

---

## Step 2 — Create the monitoring namespace

```bash
kubectl create namespace monitoring
```

---

## Step 3 — Install the stack (order matters)

Install in this order so that each service can resolve its dependencies.

### 3a. Prometheus + Alertmanager (kube-prometheus-stack)

```bash
helm install kube-prom-stack grafana/kube-prometheus-stack \
  --namespace monitoring \
  --values prometheus-values.yaml
```

Wait for Prometheus to be ready before continuing:

```bash
kubectl rollout status -n monitoring statefulset/prometheus-kube-prom-stack-kube-prome-prometheus
```

### 3b. Loki

```bash
helm install loki grafana/loki \
  --namespace monitoring \
  --values loki-values.yaml
```

### 3c. Tempo

```bash
helm install tempo grafana/tempo \
  --namespace monitoring \
  --values tempo-values.yaml
```

### 3d. Grafana Alloy (telemetry collector / OTLP receiver)

```bash
helm install alloy grafana/alloy \
  --namespace monitoring \
  --values alloy-values.yaml
```

### 3e. Grafana

```bash
helm install grafana grafana/grafana \
  --namespace monitoring \
  --values grafana-values.yaml
```

---

## Step 4 — Verify all pods are running

```bash
kubectl get pods -n monitoring
```

Expected output (all pods `Running`):

```
NAME                                                      READY   STATUS    
alloy-...                                                 1/1     Running
grafana-...                                               1/1     Running
loki-0                                                    1/1     Running
prometheus-kube-prom-stack-kube-prome-prometheus-0        2/2     Running
alertmanager-kube-prom-stack-kube-prome-alertmanager-0    2/2     Running
kube-prom-stack-kube-state-metrics-...                    1/1     Running
tempo-...                                                 1/1     Running
```

---

## Step 5 — Port-forward services to localhost

Run each in a separate terminal and keep them open while developing.

```bash
# Grafana UI
kubectl port-forward -n monitoring svc/grafana 3000:80

# Prometheus UI + query API
kubectl port-forward -n monitoring svc/kube-prom-stack-kube-prome-prometheus 9090:9090

# Alloy — OTLP gRPC (traces + metrics push from agent)
kubectl port-forward -n monitoring svc/alloy 4317:4317

# Alloy — OTLP HTTP (alternative)
kubectl port-forward -n monitoring svc/alloy 4318:4318

# Loki — direct log push from otel_setup.py
kubectl port-forward -n monitoring svc/loki 3100:3100
```

---

## Step 6 — Open Grafana

URL: http://localhost:3000
Login: `admin` / `grafana`

> Change the password for any shared environment.

All four datasources (Prometheus, Loki, Tempo, Alertmanager) are pre-provisioned.
Two dashboards are pre-loaded under **Dashboards → Default**:
- Kubernetes Cluster (community id 7249)
- Node Exporter Full (community id 1860)

---

## Step 7 — Verify Prometheus scrape targets

Open http://localhost:9090/targets

You should see these jobs as **UP**:

| Job | Target | Source |
|-----|--------|--------|
| `otel-agent-api` | `host.docker.internal:8000` | `agent_api.py` / `agent_auto_multiple.py` |
| `mcp-add-sub-server` | `host.docker.internal:8001` | `mcp_tool_instrumented.py add_sub` |
| `mcp-mul-div-server` | `host.docker.internal:8002` | `mcp_tool_instrumented.py mul_div` |

> These targets are only UP when the agent processes are running locally.
> Start them first with `python agent_api.py` and `python mcp_tool_instrumented.py add_sub / mul_div`.

---

## Signals flow

```
Agent process (localhost)
    │
    ├── Traces  → OTLP gRPC → localhost:4317 → Alloy → Tempo
    ├── Metrics → Prometheus pull ← localhost:8000/8001/8002 ← Prometheus scrape
    └── Logs    → HTTP push → localhost:3100 → Loki (direct, bypasses Alloy)
```

---

## Upgrading after config changes

```bash
helm upgrade kube-prom-stack grafana/kube-prometheus-stack \
  --namespace monitoring --values prometheus-values.yaml

helm upgrade loki grafana/loki \
  --namespace monitoring --values loki-values.yaml

helm upgrade tempo grafana/tempo \
  --namespace monitoring --values tempo-values.yaml

helm upgrade alloy grafana/alloy \
  --namespace monitoring --values alloy-values.yaml

helm upgrade grafana grafana/grafana \
  --namespace monitoring --values grafana-values.yaml
```

---

## Teardown

```bash
helm uninstall grafana      -n monitoring
helm uninstall alloy        -n monitoring
helm uninstall tempo        -n monitoring
helm uninstall loki         -n monitoring
helm uninstall kube-prom-stack -n monitoring
kubectl delete namespace monitoring
```

> PersistentVolumeClaims are NOT deleted by `helm uninstall`.
> To fully clean up storage: `kubectl delete pvc --all -n monitoring`
