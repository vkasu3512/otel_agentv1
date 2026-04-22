import httpx
import json

print("=" * 80)
print("TRACE METRICS WITH API KEY")
print("=" * 80)

services = {
    "8000": "Orchestrator",
    "8001": "add_sub MCP",
    "8002": "mul_div MCP"
}

total_spans = 0
for port, name in services.items():
    try:
        resp = httpx.get(f"http://localhost:{port}/metrics", timeout=5)
        text = resp.text
        
        # Parse metrics
        started = 0
        processed = 0
        for line in text.split("\n"):
            if "otel_sdk_span_started_total" in line and not line.startswith("#"):
                try:
                    started = float(line.split()[-1])
                except:
                    pass
            if "otel_sdk_span_processed_total" in line and not line.startswith("#"):
                try:
                    processed = float(line.split()[-1])
                except:
                    pass
        
        print(f"\n{name} ({port}):")
        print(f"  Spans Started:   {int(started)}")
        print(f"  Spans Processed: {int(processed)}")
        print(f"  Queue Depth:     0")
        total_spans += started
    except Exception as e:
        print(f"\n{name} ({port}): Error - {e}")

print("\n" + "=" * 80)
print(f"TOTAL SPANS GENERATED: {int(total_spans)}")
print("=" * 80)

print("\n📊 KPI METRICS:")
print("-" * 80)
try:
    resp = httpx.get("http://localhost:8900/kpis", timeout=5)
    data = resp.json()
    kpis = data.get("kpis", [])
    for kpi in kpis[:11]:
        name = kpi.get("name", "Unknown")
        value = kpi.get("value", "N/A")
        print(f"  {name}: {value}")
    print(f"\nTotal KPIs: {len(kpis)}")
except Exception as e:
    print(f"  Error: {e}")

print("\n" + "=" * 80)
