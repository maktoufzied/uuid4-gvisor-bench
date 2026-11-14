#!/bin/sh
# usage: run.sh plain | gvisor [platform] | strace | info
set -e
all() {
  python /bench/bench.py "$1"
  python /bench/pickup.py "$1" 12
  python /bench/proof.py "$1"
}
case "$1" in
  plain) all plain ;;
  gvisor)
    for script in "bench.py gvisor" "pickup.py gvisor 12" "proof.py gvisor"; do
      runsc --ignore-cgroups --network=none --platform="${2:-systrap}" do python /bench/$script
    done ;;
  strace)
    for mode in none stdlib uuid_utils; do
      case $mode in
        none) code="import uuid, uuid_utils.compat" ;;
        stdlib) code="import uuid, uuid_utils.compat
for _ in range(1000): uuid.uuid4()" ;;
        uuid_utils) code="import uuid, uuid_utils.compat
for _ in range(1000): uuid_utils.compat.uuid4()" ;;
      esac
      n=$(strace -f -e trace=getrandom python -c "$code" 2>&1 | grep -c 'getrandom(' || true)
      echo "getrandom calls, $mode: $n"
    done ;;
  info) runsc --version; uname -a ;;
  *) echo "usage: run.sh plain | gvisor [platform] | strace | info"; exit 1 ;;
esac
