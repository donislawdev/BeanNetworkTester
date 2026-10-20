# Linux eBPFDivert probe (throwaway branch, never merged)

Measures pydivert 4.0.0's Linux backend (eBPFDivert) against what this project needs
from a capture driver: pass-through, drop, delay, payload changes, the project's own
RST builder, SOCKET-layer events, which of the project's filter shapes the kernel
takes exactly, recovery after `kill -9`, throughput, and the real CLI with only the
capture class swapped.

`run.sh` builds a network namespace (`bntp`) joined to the root namespace by a veth
pair, starts `far_end.py` in the root namespace and runs every test inside `bntp`,
so a capture never touches the machine's real interfaces. The workflow
`.github/workflows/probe-linux-ebpf.yml` runs it on GitHub's Ubuntu runners.

    sudo PY=<venv python with req-linux.txt> BNT_SRC=<repository root> sh run.sh <test>...

`repro_*.py` are self-contained reproductions (pydivert only) for upstream reports.
