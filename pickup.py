"""Second pass: timer-free batch cost, and a pickup spread over about one second."""
import asyncio, json, os, platform, sys, threading, time, uuid
import uuid_utils.compat
from bench import FNS, pc


def burst_spin(stop, duty, burst_s=0.010):
    """Wants the GIL in 10 ms bursts, `duty` share of the time."""
    idle = burst_s * (1 - duty) / duty if duty < 1 else 0
    while not stop.is_set():
        end = time.perf_counter() + burst_s
        while time.perf_counter() < end:
            for _ in range(200):
                pass
        if idle:
            time.sleep(idle)


def batch():
    out = {}
    noop = lambda: None
    for name, fn in {"noop": noop, **FNS}.items():
        best = None
        for _ in range(5):
            t0 = pc()
            for _ in range(50000):
                fn()
            d = (pc() - t0) / 50000 / 1000
            best = d if best is None else min(best, d)
        out[name] = best
        print(f"  batch {name}: {best:.3f} us", file=sys.stderr)
    t0 = pc()
    for _ in range(50000):
        pc()
    out["timer"] = (pc() - t0) / 50000 / 1000
    return out


async def one_pickup(fn, ids=167, gap_s=0.006):
    in_uuid = 0
    stalls = 0
    stall_ns = 0
    t_start = pc()
    for _ in range(ids):
        t0 = pc()
        fn()
        d = pc() - t0
        in_uuid += d
        if d >= 1_000_000:
            stalls += 1
            stall_ns += d
        await asyncio.sleep(gap_s)
    return {"uuid_ms": in_uuid / 1e6, "stalls": stalls, "stall_ms": stall_ns / 1e6, "wall_ms": (pc() - t_start) / 1e6}


def pickup(reps):
    res = []
    for duty in (0.0, 0.1, 0.25, 0.5, 1.0):
        for name in ("stdlib", "uuid_utils"):
            stop = threading.Event()
            t = threading.Thread(target=burst_spin, args=(stop, duty), daemon=True) if duty else None
            if t:
                t.start()
            runs = [asyncio.run(one_pickup(FNS[name])) for _ in range(reps)]
            stop.set()
            if t:
                t.join()
            med = lambda k: sorted(r[k] for r in runs)[len(runs) // 2]
            res.append({
                "fn": name, "duty": duty, "reps": reps,
                "uuid_ms_median": med("uuid_ms"), "uuid_ms_min": min(r["uuid_ms"] for r in runs),
                "uuid_ms_max": max(r["uuid_ms"] for r in runs),
                "stalls_median": med("stalls"), "wall_ms_median": med("wall_ms"),
                "stall_ms_mean_each": (sum(r["stall_ms"] for r in runs) / max(1, sum(r["stalls"] for r in runs))),
                "runs": [round(r["uuid_ms"], 3) for r in runs],
            })
            print(f"  pickup duty={duty} {name}: median {res[-1]['uuid_ms_median']:.2f} ms stalls {res[-1]['stalls_median']} wall {res[-1]['wall_ms_median']:.0f}", file=sys.stderr)
    return res


if __name__ == "__main__":
    doc = {"label": sys.argv[1], "kernel": platform.release(), "batch": batch(), "pickup": pickup(int(sys.argv[2]))}
    print("JSON_BEGIN" + json.dumps(doc) + "JSON_END")
