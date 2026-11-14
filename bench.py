"""uuid4 cost with and without a thread competing for the GIL.

Prints one JSON document on stdout. Run once on the plain kernel and once inside gVisor.
"""
import asyncio
import json
import os
import platform
import sys
import threading
import time
import uuid

import uuid_utils
import uuid_utils.compat

FNS = {
    "stdlib": uuid.uuid4,
    "urandom16": lambda: os.urandom(16),
    "uuid_utils": uuid_utils.compat.uuid4,
}
EDGES_US = [0.1, 0.3, 1, 3, 10, 30, 100, 300, 1000, 3000, 10000, 30000]
pc = time.perf_counter_ns


def spin(stop, duty):
    """Pure-Python work: wants the GIL all the time (duty=1) or part of the time."""
    period = 0.010
    while not stop.is_set():
        if duty >= 1.0:
            x = 0
            for i in range(5000):
                x += i
        else:
            end = time.perf_counter() + period * duty
            while time.perf_counter() < end:
                for _ in range(200):
                    pass
            time.sleep(period * (1 - duty))


class Busy:
    def __init__(self, n, duty=1.0):
        self.stop = threading.Event()
        self.threads = [threading.Thread(target=spin, args=(self.stop, duty), daemon=True) for _ in range(n)]

    def __enter__(self):
        for t in self.threads:
            t.start()
        time.sleep(0.05)

    def __exit__(self, *a):
        self.stop.set()
        for t in self.threads:
            t.join()


def stats(ns):
    ns = sorted(ns)
    n = len(ns)
    q = lambda p: ns[min(n - 1, int(p * n))] / 1000
    hist = [0] * (len(EDGES_US) + 1)
    for v in ns:
        us = v / 1000
        i = 0
        while i < len(EDGES_US) and us >= EDGES_US[i]:
            i += 1
        hist[i] += 1
    return {
        "n": n,
        "mean_us": sum(ns) / n / 1000,
        "p50_us": q(0.5),
        "p90_us": q(0.9),
        "p99_us": q(0.99),
        "max_us": ns[-1] / 1000,
        "stalls_ge_1ms": sum(1 for v in ns if v >= 1_000_000),
        "stall_ms_total": sum(v for v in ns if v >= 1_000_000) / 1e6,
        "hist": hist,
    }


def per_call(fn, max_n, budget_s):
    out = []
    deadline = pc() + int(budget_s * 1e9)
    for _ in range(max_n):
        t0 = pc()
        fn()
        t1 = pc()
        out.append(t1 - t0)
        if t1 > deadline:
            break
    return out


def matrix():
    res = []
    for busy in (0, 1, 2):
        for name, fn in FNS.items():
            with Busy(busy):
                s = stats(per_call(fn, 20000, 6))
            s.update(fn=name, busy=busy)
            res.append(s)
            print(f"  matrix {name} busy={busy}: mean {s['mean_us']:.2f} us n={s['n']}", file=sys.stderr)
    return res


def switch_sweep():
    res = []
    default = sys.getswitchinterval()
    for ms in (5, 2, 1, 0.5):
        sys.setswitchinterval(ms / 1000)
        for name in ("stdlib", "uuid_utils"):
            with Busy(1):
                s = stats(per_call(FNS[name], 20000, 4))
            s.update(fn=name, switch_ms=ms)
            res.append(s)
            print(f"  switch {ms} ms {name}: mean {s['mean_us']:.2f} us", file=sys.stderr)
    sys.setswitchinterval(default)
    return res


async def one_pickup(fn, ids=167):
    """A synthetic pickup: 167 ids on the event loop, mixed with small Python work."""
    in_uuid = 0
    stalls = 0
    payload = {"k": list(range(40))}
    t_start = pc()
    for i in range(ids):
        t0 = pc()
        fn()
        d = pc() - t0
        in_uuid += d
        if d >= 1_000_000:
            stalls += 1
        json.dumps(payload)
        if i % 8 == 0:
            await asyncio.sleep(0)
    return {"uuid_ms": in_uuid / 1e6, "stalls": stalls, "wall_ms": (pc() - t_start) / 1e6}


def pickup():
    res = []
    for duty in (0.0, 0.25, 0.5, 1.0):
        for name in ("stdlib", "uuid_utils"):
            runs = []
            with Busy(1 if duty > 0 else 0, duty or 1.0):
                for _ in range(20):
                    runs.append(asyncio.run(one_pickup(FNS[name])))
            runs_sorted = sorted(r["uuid_ms"] for r in runs)
            res.append({
                "fn": name,
                "duty": duty,
                "uuid_ms_median": runs_sorted[len(runs) // 2],
                "uuid_ms_mean": sum(runs_sorted) / len(runs),
                "uuid_ms_min": runs_sorted[0],
                "uuid_ms_max": runs_sorted[-1],
                "stalls_median": sorted(r["stalls"] for r in runs)[len(runs) // 2],
                "wall_ms_median": sorted(r["wall_ms"] for r in runs)[len(runs) // 2],
                "runs": [round(r["uuid_ms"], 3) for r in runs],
            })
            print(f"  pickup duty={duty} {name}: median {res[-1]['uuid_ms_median']:.2f} ms", file=sys.stderr)
    return res


def main():
    label = sys.argv[1]
    doc = {
        "label": label,
        "kernel": platform.release(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "uuid_utils": uuid_utils.__version__,
        "cpus": os.cpu_count(),
        "switch_interval_ms": sys.getswitchinterval() * 1000,
        "edges_us": EDGES_US,
        "matrix": matrix(),
        "switch": switch_sweep(),
        "pickup": pickup(),
    }
    print("JSON_BEGIN" + json.dumps(doc) + "JSON_END")


if __name__ == "__main__":
    main()
