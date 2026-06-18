import asyncio
import httpx
import json
import time
from typing import List, Dict

API_URL = "http://localhost:8000/api"

async def run_benchmark():
    try:
        with open("benchmark_cases.json", "r") as f:
            cases = json.load(f)
    except FileNotFoundError:
        print("benchmark_cases.json not found. Creating default cases...")
        cases = [
            {
                "repo": "fastapi",
                "question": "How does dependency injection work?",
                "expected_files": ["fastapi/dependencies/utils.py", "fastapi/params.py"]
            }
        ]
        with open("benchmark_cases.json", "w") as f:
            json.dump(cases, f, indent=2)

    results = []
    async with httpx.AsyncClient(timeout=60.0) as client:
        for case in cases:
            print(f"Testing: {case['question']} on {case['repo']}...")
            start_time = time.time()
            try:
                response = await client.post(f"{API_URL}/query", json={
                    "repo_name": case["repo"],
                    "question": case["question"]
                })
                data = response.json()
                latency = time.time() - start_time
                
                # Check accuracy
                found_files = [c["file"] for c in data.get("citations", [])]
                top_1 = 1 if found_files and found_files[0] in case["expected_files"] else 0
                top_3 = 1 if any(f in case["expected_files"] for f in found_files[:3]) else 0
                
                results.append({
                    "question": case["question"],
                    "mode": data.get("mode"),
                    "latency": latency,
                    "top_1": top_1,
                    "top_3": top_3,
                    "success": True
                })
            except Exception as e:
                print(f"Error benchmarking case: {e}")
                results.append({"question": case["question"], "success": False})

    # Summary
    successful = [r for r in results if r["success"]]
    if not successful:
        print("No successful benchmark runs.")
        return

    avg_latency = sum(r["latency"] for r in successful) / len(successful)
    top_1_acc = sum(r["top_1"] for r in successful) / len(successful)
    top_3_acc = sum(r["top_3"] for r in successful) / len(successful)

    summary = {
        "avg_latency_s": avg_latency,
        "top_1_accuracy": top_1_acc,
        "top_3_accuracy": top_3_acc,
        "total_cases": len(cases),
        "successful_cases": len(successful)
    }

    print("\n--- Benchmark Summary ---")
    print(json.dumps(summary, indent=2))
    
    with open("benchmark_results.json", "w") as f:
        json.dump({"summary": summary, "details": results}, f, indent=2)

if __name__ == "__main__":
    asyncio.run(run_benchmark())
