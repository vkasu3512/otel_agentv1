import httpx

print("=" * 80)
print("TRACE DATA SUMMARY")
print("=" * 80)

print("\nSpan Metrics from Services:")
print("-" * 80)

services = {"8000": "Orchestrator", "8001": "add_sub MCP", "8002": "mul_div MCP"}
total_spans = 0

for port, name in services.items():
    try:
        resp = httpx.get(f"http://localhost:{port}/metrics", timeout=5)
        spans = 0
        for line in resp.text.split("\n"):
            if "otel_sdk_span_started_total" in line and not line.startswith("#"):
                try:
                    spans = float(line.split()[-1])
                except:
                    pass
        print(f"\n  {name} ({port}):")
        print(f"    Spans Started: {int(spans)}")
        total_spans += spans
    except:
        pass

print("\n" + "=" * 80)
print(f"Total Spans: {int(total_spans)}")
print("=" * 80)

print("\nKPI Metrics:")
print("-" * 80)
try:
    resp = httpx.get("http://localhost:8900/kpis", timeout=5)
    data = resp.json()
    for kpi in data.get("kpis", []):
        print(f"  - {kpi.get('name')}: {kpi.get('value')}")
except Exception as e:
    print(f"  Error: {e}")
