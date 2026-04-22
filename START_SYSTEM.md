# OBSERVE System Startup Guide

## Prerequisites Completed ✓
- ✓ Python 3.10 configured
- ✓ All packages installed (wd-otel-core, wd-otel-mcp, wd-otel-orchestrator, agents, fastapi, etc.)

## Next Steps: Configure API Key

The system requires an **`API_KEY`** environment variable to communicate with an LLM provider.

### Option 1: Groq API (Recommended)
1. Get a Groq API key from https://console.groq.com/keys
2. Set the environment variable:
   ```powershell
   $env:API_KEY = "gsk_your_actual_key_here"
   ```

### Option 2: Other Providers
Set your provider URL:
```powershell
$env:API_KEY = "your-api-key"
$env:LLM_BASE_URL = "https://your-provider.com/v1"
$env:LLM_MODEL = "model-name"
```

---

## System Architecture

The system runs 4+ components:

| Component | Port | Role |
|-----------|------|------|
| MCP Server (add_sub) | 8081 | Addition/subtraction math tool |
| MCP Server (mul_div) | 8082 | Multiplication/division multi-step solver |
| FastAPI Agent | 8080 | Main orchestrator & HTTP API |
| KPI Proxy | 8900 | Prometheus metrics aggregator |
| otel-monitor | 3000 | Next.js dashboard |
| Prometheus | 8000/8001/8002 | Metrics collection |

---

## Startup Instructions (4+ Terminals)

### Terminal 1: MCP Server - Add/Subtract
```powershell
cd c:\Obeserve
$env:API_KEY = "your-key-here"
py -3.10 otel_agent_v2/mcp_server.py add_sub
```

### Terminal 2: MCP Server - Multiply/Divide
```powershell
cd c:\Obeserve
$env:API_KEY = "your-key-here"
py -3.10 otel_agent_v2/mcp_server.py mul_div
```

### Terminal 3: FastAPI Server
```powershell
cd c:\Obeserve
$env:API_KEY = "your-key-here"
py -3.10 -m uvicorn otel_agent_v2.api:app --host 0.0.0.0 --port 8080
```

### Terminal 4: KPI Proxy (after traffic flows)
```powershell
cd c:\Obeserve
py -3.10 otel_agent_v2/kpi_proxy.py
# Access metrics at: http://localhost:8900/kpi/all
```

### Terminal 5 (Optional): Next.js Frontend
```powershell
cd c:\Obeserve\otel-monitor
npm install
npm run dev
# Access at: http://localhost:3000
```

---

## Quick Test (No FastAPI)

Run a direct calculation without HTTP:
```powershell
cd c:\Obeserve
$env:API_KEY = "your-key-here"
py -3.10 otel_agent_v2/cli.py "What is 100 - 37?"
```

---

## Test API Call

After FastAPI is running:
```powershell
$response = Invoke-RestMethod -Uri "http://localhost:8080/run" `
  -Method POST `
  -Headers @{"Content-Type" = "application/json"} `
  -Body '{"question":"What is (3+5)*2 - 4/2?"}'

$response | ConvertTo-Json
```

---

## Port Reference

- **8000**: Prometheus scrape (orchestrator)
- **8001**: Prometheus scrape (add_sub MCP)
- **8002**: Prometheus scrape (mul_div MCP)
- **8080**: FastAPI server
- **8081**: add_sub MCP HTTP
- **8082**: mul_div MCP HTTP
- **8900**: KPI proxy
- **4317**: OTLP gRPC → Tempo (optional)
- **3100**: Loki HTTP (optional)
- **3000**: Next.js frontend (optional)

---

## Optional: Full Observability Stack

The system can send metrics/traces to:
- **Prometheus** at `localhost:8000/8001/8002`
- **Tempo** at `localhost:4317` (OpenTelemetry gRPC)
- **Loki** at `localhost:3100` (logs)

See `Grafana_stackv1/run.md` for Kubernetes/Helm deployment of the full stack.

---

## Documentation References

- [otel_agent_v2/README.md](otel_agent_v2/README.md) — Agent design & architecture
- [otel-monitor/README.md](otel-monitor/README.md) — Dashboard features
- [docs/superpowers/specs/2026-04-19-otel-agent-v2-design.md](docs/superpowers/specs/2026-04-19-otel-agent-v2-design.md) — Design rationale
