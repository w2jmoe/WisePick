# Isolated Routing Scaffold Benchmark

**WisePick Decision API · v0.1.3** · harness output (`tests/stress_test.py`)

- **Concurrent segment wall time** (`perf_counter`): 11.8092 s  
- **Worker pool** `max_workers`: 512  

## Benchmark scope

This run is an **isolated routing scaffold** benchmark. It measures in-process work for `run_decision` only.

| Included | Excluded (stubbed or bypassed) |
| :--- | :--- |
| `run_decision` CPU path: capability extraction, scoring, winner selection | HTTP stack, FastAPI, serialization over the wire |
| Per-request elapsed time via `perf_counter` (ms) | Live PostgreSQL I/O; real `decisions` inserts |
| Concurrent load via thread pool (GIL-visible) | Network calls to **Yantrik** |
| Fixed intent → baseline `provider` / `capability_id` checks | End-to-end API latency under real DB pools / replication lag |

Do not treat these figures as production SLOs. They bound the **routing scaffold** under this harness; deployed latency adds persistence, optional plugins, and runtime overhead.

## Summary

| Metric | Value |
| :--- | :--- |
| Total requests | 20,000 |
| Worker pool size (threads) | 512 |
| Throughput (RPS) | 1,693.60 |
| Mean latency (ms), concurrent load | 2.2578 |
| P50 latency (ms), concurrent load | 0.5249 |
| P95 latency (ms), concurrent load | 0.8913 |
| P99 latency (ms), concurrent load | 55.1734 |
| Success rate (%) | 100.00 |
| Routing accuracy (%) | 100.00 |
| Concurrent mean under 1 ms goal met | No |
| Single-threaded sample count | 10,000 |
| Mean latency (ms), single-threaded | 0.6033 |
| P50 latency (ms), single-threaded | 0.5594 |
| P95 latency (ms), single-threaded | 0.8673 |
| P99 latency (ms), single-threaded | 1.0430 |
| Single-threaded mean under 1 ms (scaffold) | Yes |
| Gate: single-threaded P95 &lt; 1 ms | Yes |
| Gate: concurrent segment RPS ≥ 1,000 | Yes |
| Errors | 0 |
| Expected provider / capability | `deepl_translate` / `translation` |

## Measurement

- **Throughput (RPS):** `total_requests / wall_seconds` for the concurrent segment (wall-clock for the whole phase, not per-thread service rate).
- **Routing accuracy:** Share of responses matching the warmed baseline for the fixed task string.
- **Percentiles (P50 / P95 / P99):** Computed on **sorted** per-request durations (ms); same linear-interpolation quantile function for all listed percentiles.
- **Concurrent vs sequential:** Concurrent samples include scheduler and **GIL contention**; sequential samples approximate single-threaded scaffold cost without that contention.

## Outcome (this run)

Single-threaded path: mean **0.6033 ms**, P95 **0.8673 ms** (below 1 ms). Concurrent segment: **1,693.60 RPS** over the timed window; P50 / P95 / P99 **0.5249 / 0.8913 / 55.1734 ms** under load. Internal gates recorded in the summary table passed for P95 and RPS; concurrent mean remains above 1 ms, consistent with multi-thread scheduling on this profile.
