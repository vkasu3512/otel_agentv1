import httpx
import json

print('Checking trace endpoints...')
print('=' * 60)

# Check if Prometheus has data
print('\n1. Prometheus Metrics:')
try:
    resp = httpx.get('http://localhost:8000/metrics', timeout=5)
    lines = [l for l in resp.text.split('\n') if 'span' in l.lower() and not l.startswith('#')]
    print(f'   Span metrics found: {len(lines)}')
    for line in lines[:3]:
        print(f'   {line[:80]}')
except Exception as e:
    print(f'   Error: {e}')

# Check dashboard trace API
print('\n2. Dashboard /api/traces:')
try:
    resp = httpx.get('http://localhost:3000/api/traces', timeout=5)
    print(f'   Status: {resp.status_code}')
    try:
        data = resp.json()
        traces = data.get('traces', [])
        print(f'   Traces returned: {len(traces)}')
        if traces:
            print(f'   First trace: {traces[0].get("traceID", "N/A")}')
    except:
        print(f'   Response: {resp.text[:100]}')
except Exception as e:
    print(f'   Error: {e}')

# Check KPI API
print('\n3. Dashboard /api/kpi:')
try:
    resp = httpx.get('http://localhost:3000/api/kpi', timeout=5)
    print(f'   Status: {resp.status_code}')
    data = resp.json()
    kpis = data.get('kpis', [])
    print(f'   KPIs: {len(kpis)}')
except Exception as e:
    print(f'   Error: {e}')

print('\n' + '=' * 60)
