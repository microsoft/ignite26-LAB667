import http.client
import json
import time
import concurrent.futures
import statistics
import urllib.parse

def run_scenario(name, method, path, headers, body_data, total_requests, concurrency, expected_substr):
    results = []
    errors = []
    
    parts = urllib.parse.urlparse("http://127.0.0.1:8000")
    
    def do_request():
        start = time.perf_counter()
        try:
            conn = http.client.HTTPConnection(parts.hostname, parts.port, timeout=10)
            conn.request(method, path, body=body_data, headers=headers)
            resp = conn.getresponse()
            content = resp.read().decode('utf-8', errors='ignore')
            resp_headers = resp.getheaders()
            status = resp.status
            conn.close()
            
            elapsed = (time.perf_counter() - start) * 1000
            if status == 200 and expected_substr in content:
                return elapsed, None
            else:
                err_msg = f"Status {status}, Body contains '{expected_substr}': {expected_substr in content}"
                if status != 200:
                    err_msg += f", Snippet: {content[:100]}"
                return None, err_msg
        except Exception as e:
            return None, str(e)

    start_scenario = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(do_request) for _ in range(total_requests)]
        for f in concurrent.futures.as_completed(futures):
            res, err = f.result()
            if res is not None:
                results.append(res)
            else:
                errors.append(err)
    
    end_scenario = time.perf_counter()
    duration = end_scenario - start_scenario
    
    ok = len(results)
    failed = len(errors)
    
    print(f"Scenario: {name}")
    print(f"Total: {total_requests}, Concurrency: {concurrency}, OK: {ok}, Failed: {failed}")
    print(f"Elapsed: {duration:.2f}s, Req/s: {total_requests/duration:.2f}")
    
    if results:
        results.sort()
        print(f"Min: {results[0]:.2f}ms, P50: {statistics.median(results):.2f}ms, P95: {results[int(len(results)*0.95)]:.2f}ms, P99: {results[int(len(results)*0.99)]:.2f}ms, Max: {results[-1]:.2f}ms")
    
    if errors:
        print("Sample errors:")
        for e in list(set(errors))[:3]:
            print(f"  - {e}")
    print("-" * 40)

# Scenarios
scenarios = [
    {
        "name": "1) GET /",
        "method": "GET",
        "path": "/",
        "headers": {},
        "body": None,
        "total": 200,
        "concurrency": 20,
        "expect": "lost-in-the-city"
    },
    {
        "name": "2) POST /san-francisco/mcp initialize",
        "method": "POST",
        "path": "/san-francisco/mcp",
        "headers": {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
        "body": json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "test-client", "version": "1.0"}}}),
        "total": 200,
        "concurrency": 20,
        "expect": "game-san-francisco"
    },
    {
        "name": "3) POST /san-francisco/mcp tools/call begin_session (200/20)",
        "method": "POST",
        "path": "/san-francisco/mcp",
        "headers": {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
        "body": json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "begin_session", "arguments": {}}}),
        "total": 200,
        "concurrency": 20,
        "expect": "awaiting_identity"
    },
    {
        "name": "4) POST /san-francisco/mcp tools/call begin_session (500/50)",
        "method": "POST",
        "path": "/san-francisco/mcp",
        "headers": {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
        "body": json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "begin_session", "arguments": {}}}),
        "total": 500,
        "concurrency": 50,
        "expect": "awaiting_identity"
    }
]

for s in scenarios:
    run_scenario(s["name"], s["method"], s["path"], s["headers"], s["body"], s["total"], s["concurrency"], s["expect"])

