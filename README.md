# uuid4-gvisor-bench

A small benchmark that shows why `uuid.uuid4()` can stall a Python event loop inside gVisor.

## The short version

- Each standard `uuid4()` makes one `getrandom` system call. Python releases the GIL during it.
- Inside gVisor that call is slow enough for another thread to take the GIL.
- The calling thread then waits for Python's switch interval (5 ms by default) to get the GIL back.
- `uuid_utils` makes ids without a system call, so it never stalls.

```
plain Linux   main:  [python][syscall 0.35 us][python ...............]
              other: [waiting .......................................]

gVisor        main:  [python][syscall ~3-6 us][waiting ~5 ms][python]
              other: [waiting ][ takes the GIL, runs ~5 ms  ][waiting]
```

## Results

Average time per id, two runs each.

| Measure | Plain Linux (arm64 VM) | gVisor (same VM) | LiveKit Cloud (gVisor, x86) |
|---|---|---|---|
| One `getrandom` system call | 0.35 us | 2.61 us | 5.77 us |
| stdlib `uuid4`, idle | 1.04 us | 3.46 us | 7.84 us |
| stdlib `uuid4`, one busy thread | 360 us | 4,890 us | 5,190 us |
| Calls that stall 1 ms or longer, one busy thread | 6% | 81% | 96% |
| Length of each stall | 6.0 ms | 6.0 ms | 5.4 ms |
| `uuid_utils.compat.uuid4`, one busy thread | 0.55 us | 0.55 us | 1.62 us |

Proof that the stall is a wait for the GIL (`proof.py`, LiveKit Cloud):

| Check | Result |
|---|---|
| `getrandom` through ctypes, GIL released (`CDLL`) | 76.5% of calls stall |
| Same call, GIL kept (`PyDLL`) | 0.18% of calls stall |
| Stalls during which the other thread ran Python | 270 of 270 |
| Fast calls during which the other thread ran Python | 0 of 30 |

Your numbers will differ with the machine, the gVisor platform and the Python version.

## Files

| File | What it does |
|---|---|
| `bench.py` | Per-call timing of stdlib `uuid4`, `os.urandom(16)` and `uuid_utils`, with 0, 1 and 2 busy threads. Also sweeps Python's switch interval. |
| `pickup.py` | Timer-free cost per call, then 167 ids spread over about one second on an asyncio loop while another thread is busy part of the time. |
| `proof.py` | Two direct checks that the stall is a wait for the GIL. |
| `Dockerfile.local`, `run.sh` | Local rig: plain Linux and gVisor (`runsc do`) in one image. |
| `agent.py`, `Dockerfile` | Probe that runs the three scripts inside LiveKit Cloud and prints the results to the agent logs. |

Each script prints one JSON document on stdout between `JSON_BEGIN` and `JSON_END`. Progress goes to stderr.

## Run it locally

Needs Docker on a Linux host or VM. `runsc do` needs a privileged container.

```sh
# arm64 host (default). On x86 add: --build-arg GVISOR_ARCH=x86_64
docker build -f Dockerfile.local -t uuid4-gvisor-bench .

docker run --rm --privileged uuid4-gvisor-bench ./run.sh plain   > plain.txt
docker run --rm --privileged uuid4-gvisor-bench ./run.sh gvisor  > gvisor.txt
docker run --rm --privileged uuid4-gvisor-bench ./run.sh strace
```

`run.sh gvisor kvm` selects another gVisor platform if the host has `/dev/kvm`.

## Run it on LiveKit Cloud

Needs the `lk` CLI, logged in to a project you can deploy to.

```sh
lk agent create --project <your-project> --region us-east --yes .
lk agent logs --project <your-project>      # wait for "PROBE DONE"
lk agent delete --project <your-project> --yes
```

- The probe starts the benchmark when the worker boots. No call is needed.
- It registers under the agent name `uuid-gvisor-probe`, so it never receives a room unless dispatched by that name.
- Results appear in the logs as `PROBE <tag> <part>/<parts> <json>` lines. Join the parts of one tag to get the JSON.
- The `env` dump lists environment variable names only, never values.
- `lk agent create` writes a `livekit.toml` with your project subdomain. It is git-ignored.

## Limits

- The busy thread is a pure-Python loop. Real applications hold the GIL in other patterns.
- `pickup.py` is a synthetic stand-in for a real workload. Its middle rows vary a lot between machines.
- The gVisor platform used by LiveKit Cloud is not visible from inside the sandbox.
- No tracing inside CPython. The GIL proof is made from the outside.
