"""Small dependency-free HTTP smoke/load probe for a running deployment.

It intentionally defaults to the unauthenticated liveness endpoint. Use an
authenticated API route only in a private test environment and never pass a
real bearer token on a shared terminal or CI log.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def probe(url: str, timeout: float) -> tuple[bool, int, float, str]:
    started = time.perf_counter()
    request = Request(url, headers={"User-Agent": "codebase-intel-load-probe/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            response.read(256)
            return True, response.status, (time.perf_counter() - started) * 1000, ""
    except HTTPError as error:
        return False, error.code, (time.perf_counter() - started) * 1000, "http error"
    except (URLError, TimeoutError, OSError) as error:
        return False, 0, (time.perf_counter() - started) * 1000, type(error).__name__


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe Codebase Intel HTTP latency and error rate.")
    parser.add_argument("--url", default="http://127.0.0.1:8000/api/health")
    parser.add_argument("--requests", type=int, default=25)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    if args.requests < 1 or args.concurrency < 1 or args.timeout <= 0:
        parser.error("requests and concurrency must be positive and timeout must be greater than zero")

    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(args.concurrency, args.requests)) as pool:
        results = list(pool.map(lambda _index: probe(args.url, args.timeout), range(args.requests)))
    elapsed_ms = (time.perf_counter() - started) * 1000
    successful = [result for result in results if result[0]]
    latencies = sorted(result[2] for result in results)
    p95 = latencies[min(len(latencies) - 1, max(0, int(len(latencies) * 0.95) - 1))]
    print(f"url={args.url}")
    print(f"requests={args.requests} concurrency={args.concurrency} success={len(successful)} errors={len(results) - len(successful)}")
    print(f"elapsed_ms={elapsed_ms:.1f} p95_ms={p95:.1f}")
    if not successful:
        print(f"first_error={results[0][3]}")
    return 0 if len(successful) == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
