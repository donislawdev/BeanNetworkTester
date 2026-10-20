#!/bin/sh
# Run as root:  PY=<venv python> BNT_SRC=<product source tree> sh run.sh <test> [<test> ...]
#
# Builds the network namespace bntp (veth: 10.231.0.1 + .3 / fd00:231::1 + ::3 in the
# root namespace, 10.231.0.2 / fd00:231::2 inside), starts the far end in the ROOT
# namespace, runs each test INSIDE bntp with a hard timeout, and always tears it all
# down. Every TC hook a test attaches lands on bntp's own interfaces - never on the
# machine's real ones.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
: "${PY:?set PY to the python of a venv holding req-linux.txt}"
: "${BNT_SRC:?set BNT_SRC to the product source tree (holds beantester/)}"
export BNT_SRC
NS=bntp
# `ip netns exec` mounts a fresh /sys in a private mount namespace, so cgroup2 is not
# in /proc/self/mountinfo there, and eBPFDivert's SOCKET/FLOW layers answer EOPNOTSUPP
# (measured). Mounted again inside that private namespace only.
CG="mount -t cgroup2 none /sys/fs/cgroup"

cleanup() {
    [ -n "${FAR:-}" ] && kill "$FAR" 2>/dev/null
    ip netns exec $NS "$PY" -c "from pydivert import EBPFDivert; EBPFDivert.unregister()" 2>/dev/null
    ip netns del $NS 2>/dev/null
    ip link del bntp-h 2>/dev/null
    echo "CLEANED netns=$(ip netns list | grep -c $NS) veth=$(ip link show bntp-h 2>/dev/null | grep -c bntp-h)"
}
trap cleanup EXIT INT TERM

ip netns del $NS 2>/dev/null
ip link del bntp-h 2>/dev/null
ip netns add $NS
ip link add bntp-h type veth peer name bntp-c
ip link set bntp-c netns $NS
ip addr add 10.231.0.1/29 dev bntp-h
ip addr add 10.231.0.3/29 dev bntp-h
ip addr add fd00:231::1/64 dev bntp-h nodad
ip addr add fd00:231::3/64 dev bntp-h nodad
ip link set bntp-h up
ip -n $NS addr add 10.231.0.2/29 dev bntp-c
ip -n $NS addr add fd00:231::2/64 dev bntp-c nodad
ip -n $NS link set bntp-c up
ip -n $NS link set lo up

timeout 900 "$PY" "$HERE/far_end.py" --life 880 > /tmp/bntp-far.log 2>&1 &
FAR=$!
sleep 0.5
grep -q FAR_END_UP /tmp/bntp-far.log || { echo "far end did not start"; cat /tmp/bntp-far.log; exit 1; }

for t in "$@"; do
    case "$t" in
        socket|filters) timeout 120 ip netns exec $NS sh -c "$CG && exec $PY $HERE/probe.py $t" ;;
        product) timeout 60 ip netns exec $NS sh -c "$CG && exec $PY $HERE/product_run.py" ;;
        repro_*) timeout 60 ip netns exec $NS sh -c "$CG && exec $PY $HERE/$t.py" ;;
        rate:*) timeout 60 ip netns exec $NS "$PY" "$HERE/probe.py" rate --seconds 3 --pps "${t#rate:}" ;;
        *) timeout 60 ip netns exec $NS "$PY" "$HERE/probe.py" "$t" ;;
    esac
    echo "EXIT $t $?"
done
