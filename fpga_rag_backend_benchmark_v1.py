#!/usr/bin/env python3
"""Benchmark JSON vs SQLite query backend performance."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any, Dict, List

from fpga_rag_query_v4 import SQLiteQueryEngine
from fpga_rag_query_v3 import QueryEngine as JsonQueryEngine


BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = BASE_DIR / "fpga_rag_v2_outputs"
DEFAULT_GRAPH = OUT_DIR / "stage6_graph_vector_commit_v3.json"
DEFAULT_DB = OUT_DIR / "fpga_rag_arch_v2.sqlite"
DEFAULT_OUT_JSON = OUT_DIR / "query_perf_benchmark_v2.json"
DEFAULT_OUT_MD = OUT_DIR / "query_perf_benchmark_v2.md"


QUERIES = [
    "axi_dma_0 nedir ve ne işe yarar?",
    "Neden DMA seçildi, alternatifler neydi?",
    "DMA-REQ-L0-001'in alt gereksinimleri neler?",
    "Clock wizard her iki projede de var mı, farkları ne?",
    "Bu projenin bilinen sorunları neler?",
    "DMA-REQ-L1-001'i hangi component'ler karşılıyor?",
    "Bu projede Ethernet var mı?",
]


def bench_engine(engine: Any, queries: List[str], iterations: int) -> Dict[str, Any]:
    per_query: Dict[str, List[float]] = {}
    for q in queries:
        _ = engine.query(q)  # warmup
        times: List[float] = []
        for _ in range(iterations):
            t0 = time.perf_counter()
            _ = engine.query(q)
            t1 = time.perf_counter()
            times.append((t1 - t0) * 1000.0)
        per_query[q] = times
    all_times = [t for lst in per_query.values() for t in lst]
    return {
        "per_query_ms": per_query,
        "summary_ms": {
            "avg": statistics.mean(all_times),
            "p50": statistics.median(all_times),
            "p95": sorted(all_times)[max(0, int(0.95 * len(all_times)) - 1)],
            "min": min(all_times),
            "max": max(all_times),
        },
    }


def to_markdown(result: Dict[str, Any], iterations: int) -> str:
    lines: List[str] = []
    lines.append("# Query Backend Performance Benchmark")
    lines.append("")
    lines.append(f"- iterations per query: {iterations}")
    lines.append("")
    lines.append("## Summary (ms)")
    lines.append("")
    lines.append("| Backend | Avg | P50 | P95 | Min | Max |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for backend in ["json", "sqlite"]:
        s = result[backend]["summary_ms"]
        lines.append(
            f"| {backend} | {s['avg']:.3f} | {s['p50']:.3f} | {s['p95']:.3f} | {s['min']:.3f} | {s['max']:.3f} |"
        )
    lines.append("")
    lines.append("## Per Query Avg (ms)")
    lines.append("")
    lines.append("| Query | JSON | SQLite | Speedup (json/sqlite) |")
    lines.append("|---|---:|---:|---:|")
    for q in QUERIES:
        j = statistics.mean(result["json"]["per_query_ms"][q])
        s = statistics.mean(result["sqlite"]["per_query_ms"][q])
        sp = (j / s) if s > 0 else 0.0
        lines.append(f"| {q} | {j:.3f} | {s:.3f} | {sp:.2f}x |")
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark JSON vs SQLite backend")
    parser.add_argument("--graph", default=str(DEFAULT_GRAPH))
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--out-json", default=str(DEFAULT_OUT_JSON))
    parser.add_argument("--out-md", default=str(DEFAULT_OUT_MD))
    args = parser.parse_args()

    graph_payload = json.loads(Path(args.graph).read_text(encoding="utf-8"))
    json_engine = JsonQueryEngine(graph_payload)
    sqlite_engine = SQLiteQueryEngine(Path(args.db))
    try:
        json_result = bench_engine(json_engine, QUERIES, args.iterations)
        sqlite_result = bench_engine(sqlite_engine, QUERIES, args.iterations)
    finally:
        sqlite_engine.close()

    result = {
        "iterations": args.iterations,
        "queries": QUERIES,
        "json": json_result,
        "sqlite": sqlite_result,
    }

    out_json = Path(args.out_json)
    out_md = Path(args.out_md)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out_md.write_text(to_markdown(result, args.iterations), encoding="utf-8")

    print(f"Wrote: {out_json}")
    print(f"Wrote: {out_md}")
    print("Summary:")
    for name in ["json", "sqlite"]:
        s = result[name]["summary_ms"]
        print(f"{name}: avg={s['avg']:.3f}ms p50={s['p50']:.3f}ms p95={s['p95']:.3f}ms")


if __name__ == "__main__":
    main()
