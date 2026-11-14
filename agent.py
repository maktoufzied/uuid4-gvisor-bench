"""Throwaway probe: runs the uuid4 benchmark inside the LiveKit Cloud sandbox and logs the result.

It registers under an explicit agent name, so it never receives a call unless dispatched by name.
"""
import json
import os
import platform
import re
import subprocess
import sys
import threading

from livekit.agents import JobContext, WorkerOptions, cli


def read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError as e:
        return f"ERR {e}"


def sh(cmd):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        return (r.stdout + r.stderr).strip()
    except Exception as e:
        return f"ERR {e}"


def emit(tag, doc):
    blob = json.dumps(doc, separators=(",", ":"))
    parts = [blob[i:i + 1500] for i in range(0, len(blob), 1500)]
    for i, part in enumerate(parts):
        print(f"PROBE {tag} {i + 1}/{len(parts)} {part}", flush=True)


def run(tag, script, *args):
    proc = subprocess.run([sys.executable, script, *args], capture_output=True, text=True, cwd="/app")
    m = re.search(r"JSON_BEGIN(.*)JSON_END", proc.stdout, re.S)
    if m:
        emit(tag, json.loads(m.group(1)))
    else:
        print(f"PROBE {tag} FAILED rc={proc.returncode} {proc.stderr[-800:]}", flush=True)


def probe():
    cpuinfo = read("/proc/cpuinfo")
    models = sorted(set(re.findall(r"model name\s*:\s*(.*)", cpuinfo)))
    emit("env", {
        "kernel": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "affinity": len(os.sched_getaffinity(0)),
        "cpu_models": models,
        "cpu_max": read("/sys/fs/cgroup/cpu.max"),
        "mem_max": read("/sys/fs/cgroup/memory.max"),
        "proc_version": read("/proc/version"),
        "switch_interval_ms": sys.getswitchinterval() * 1000,
        "cpu_flags": sorted(set(" ".join(re.findall(r"(?:flags|Features)\s*:\s*(.*)", cpuinfo)).split()))[:200],
        "cpu_mhz": sorted(set(re.findall(r"cpu MHz\s*:\s*(.*)", cpuinfo)))[:8],
        "hostname": platform.node(),
        "uid": os.getuid(),
        "meminfo": read("/proc/meminfo").splitlines()[:3],
        "uptime": read("/proc/uptime"),
        "cgroup": read("/proc/self/cgroup"),
        "mounts": read("/proc/mounts").splitlines()[:40],
        "pid1": read("/proc/1/cmdline").replace("\0", " "),
        "seccomp": re.findall(r"(Seccomp\w*:\s*\d+)", read("/proc/self/status")),
        "env_names": sorted(os.environ),
        "dmesg": sh("dmesg")[:3000],
        "uname": sh("uname -a"),
        "df": sh("df -h /")[:400],
        "ps": sh("ps -eo pid,ppid,comm 2>/dev/null || ls /proc | grep -E '^[0-9]+$' | tr '\n' ' '")[:800],
    })
    run("bench", "bench.py", "livekit-cloud")
    run("pickup", "pickup.py", "livekit-cloud", "12")
    run("proof", "proof.py", "livekit-cloud")
    print("PROBE DONE", flush=True)


async def entrypoint(ctx: JobContext):
    await ctx.connect()


if __name__ == "__main__":
    threading.Thread(target=probe, daemon=True).start()
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, agent_name="uuid-gvisor-probe", num_idle_processes=0))
