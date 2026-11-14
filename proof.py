"""Two direct checks that the uuid4 stall is a wait for the GIL.

A. Same getrandom system call through ctypes, once releasing the GIL (CDLL) and once keeping it (PyDLL).
B. Record when the busy thread executes Python. Only the GIL holder can do that, so if it runs
   during a main-thread stall, the main thread did not hold the GIL.
"""
import bisect, ctypes, json, platform, sys, threading, time, uuid
from bench import Busy, per_call, stats, pc

buf = ctypes.create_string_buffer(16)


def bind(dll):
    f = dll.getrandom
    f.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_uint]
    f.restype = ctypes.c_ssize_t
    return lambda: f(buf, 16, 0)


def part_a():
    fns = {"getrandom_gil_released": bind(ctypes.CDLL(None)), "getrandom_gil_kept": bind(ctypes.PyDLL(None))}
    assert all(fn() == 16 for fn in fns.values())
    out = []
    for busy in (0, 1):
        for name, fn in fns.items():
            with Busy(busy):
                s = stats(per_call(fn, 20000, 6))
            out.append({"fn": name, "busy": busy, "n": s["n"], "mean_us": s["mean_us"], "p50_us": s["p50_us"],
                        "stalls": s["stalls_ge_1ms"], "stall_ms_each": s["stall_ms_total"] / max(1, s["stalls_ge_1ms"])})
            print(f"  A {name} busy={busy}: n={s['n']} mean={s['mean_us']:.1f} us stalls={s['stalls_ge_1ms']}", file=sys.stderr)
    return out


def part_b(fn, calls=300):
    ticks = []
    stop = threading.Event()

    def busy():
        append = ticks.append
        while not stop.is_set():
            append(pc())

    t = threading.Thread(target=busy, daemon=True)
    t.start()
    time.sleep(0.05)
    windows = []
    for _ in range(calls):
        t0 = pc()
        fn()
        t1 = pc()
        windows.append((t0, t1))
    stop.set()
    t.join()
    slow, fast = [], []
    for t0, t1 in windows:
        i, j = bisect.bisect_right(ticks, t0), bisect.bisect_left(ticks, t1)
        n = j - i
        if t1 - t0 >= 1_000_000:
            cover = (ticks[j - 1] - ticks[i]) / (t1 - t0) if n > 1 else 0.0
            slow.append({"n": n, "cover": cover, "start_delay_us": (ticks[i] - t0) / 1000 if n else None,
                         "end_gap_us": (t1 - ticks[j - 1]) / 1000 if n else None})
        else:
            fast.append(n)
    med = lambda xs: sorted(xs)[len(xs) // 2] if xs else None
    return {
        "calls": len(windows), "slow_calls": len(slow), "fast_calls": len(fast),
        "slow_with_busy_running": sum(1 for s in slow if s["n"] > 0),
        "busy_ticks_per_slow_median": med([s["n"] for s in slow]),
        "cover_median": med([s["cover"] for s in slow]), "cover_min": min([s["cover"] for s in slow], default=None),
        "start_delay_us_median": med([s["start_delay_us"] for s in slow if s["n"]]),
        "end_gap_us_median": med([s["end_gap_us"] for s in slow if s["n"]]),
        "fast_with_busy_running": sum(1 for n in fast if n > 0),
        "busy_ticks_in_fast_max": max(fast, default=None),
    }


if __name__ == "__main__":
    doc = {"label": sys.argv[1], "kernel": platform.release(), "a": part_a(),
           "b_stdlib": part_b(uuid.uuid4), "b_gil_kept": part_b(bind(ctypes.PyDLL(None)), 3000)}
    print("JSON_BEGIN" + json.dumps(doc) + "JSON_END")
