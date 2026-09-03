"""A real-driver check that process targeting still works, small enough for CI.

Why this is in ``tools/`` and not ``internal_tools/``
-----------------------------------------------------
``internal_tools/`` is outside git, so nothing there can ever run on a runner.
This is the one targeting check meant to run on every push, so it ships with the
repository (convention: a script a workflow runs must be tracked).

What it proves, and what it deliberately does not
-------------------------------------------------
Every automated targeting test runs against fakes: a hand-written socket table
with a hand-written ``ancestors()``. That is the right shape for a unit test and
it cannot fail the way the real thing fails - the live SOCKET map, the resolver's
timing and the driver are all absent, and every targeting bug found by hand in
August 2026 lived in exactly that missing part.

So this starts a REAL session against a loopback echo server it runs itself,
targets one child process by PID, and asserts both halves: the target's
connection is in scope, and a second, untargeted child's is not.

**What it is VERIFIED to catch** (mutated and run, 2026-08-05): targeting that
stops matching at all - ``__contains__`` patched to never hit gives
``FAIL: the targeted process's connection was NOT in scope`` and exit 1, while
the unmutated tree exits 0.

**What it does NOT catch, said plainly:** a flow that loses its scope PART WAY
THROUGH. The connection log's flag is sticky by design (it answers "was this
impaired at all"), and these children talk for seconds, so a port that falls out
of scope after the first packets still reads as in scope. That class needs the
per-flow timing rig, ``internal_tools/probe_scope_gap.py`` - which is how the
System-pid bug was found, and it is not something a ten-second CI step can do.

**Zero impairment.** Every knob stays at its default, so not one packet is
dropped, delayed or altered - the verdict is the connection log's ``scoped``
flag. The driver filter is narrowed to the echo port, so nothing else on the
machine is even handed to the tool. Runtime is about ten seconds.

Not Windows, not elevated, or no pydivert -> it prints SKIP and exits 0. A check
that cannot run must say so out loud rather than pass quietly.
"""
import os
import socket
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 🔴 No literal port here, and this is the one thing in the file worth reading
# before changing it. Windows RESERVES port ranges (Hyper-V, WSL, WinNAT), and a
# reserved port does not refuse `bind` with "in use" - it refuses with
# `WinError 10013`, a PERMISSION error - so a literal that happens to fall inside
# one makes this check unrunnable on that machine until a reboot moves the range.
# MEASURED 2026-09-03 with a bare socket, outside this tool: TCP 9097 gave 10013
# while UDP 9097 bound fine, and `netsh int ipv4 show excludedportrange
# protocol=tcp` named 9001-9100. The symptom was indistinguishable from broken
# targeting - the listener died on a daemon thread, both children were refused,
# and the first `int()` of an empty line raised - which is why the port is now
# asked FOR. It also means two runs of this script can overlap.
CHILD = """
import socket, sys, time
sock = socket.create_connection(("127.0.0.1", %d), timeout=5)
print(sock.getsockname()[1], flush=True)
end = time.time() + 8
while time.time() < end:
    sock.sendall(b"ping")
    sock.recv(64)
    time.sleep(0.05)
"""


def open_listener():
    """A loopback listener on a port the OS picked, plus that port.

    Bound AND listening before it is handed to the thread, which also closes a
    race the old ``time.sleep(0.3)`` was papering over: a child connecting before
    ``listen()`` got its connection refused and printed nothing for the caller to
    read. Raises ``OSError`` exactly like ``bind`` does - the caller decides what
    a machine that will not hand out a loopback port means.

    No ``SO_REUSEADDR``: with port 0 the OS never hands back a port sitting in
    TIME_WAIT, so the option only described an intent that no longer exists.
    """
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(8)
    return server, server.getsockname()[1]


def child_port(proc):
    """The local port a child printed, or ``None`` when it never got that far."""
    line = (proc.stdout.readline() or "").strip()
    return int(line) if line.isdigit() else None


def echo(server, stop):
    server.settimeout(0.2)

    def serve(conn):
        with conn:
            conn.settimeout(5.0)
            while not stop.is_set():
                try:
                    data = conn.recv(4096)
                except OSError:
                    return
                if not data:
                    return
                conn.sendall(data)

    while not stop.is_set():
        try:
            conn, _ = server.accept()
        except socket.timeout:
            continue
        except OSError:
            break
        threading.Thread(target=serve, args=(conn,), daemon=True).start()
    server.close()


def skip(reason):
    print("SKIP: %s" % reason)
    return 0


def main():
    from beantester import winenv
    if not winenv.is_windows():
        return skip("not Windows - there is no WinDivert here")
    if not winenv.is_admin():
        return skip("not elevated - a capture session cannot start")
    try:
        import pydivert                                  # noqa: F401
    except Exception as exc:
        return skip("pydivert is not importable (%s)" % exc)

    from beantester.engine import BeanEngine
    from beantester.settings import apply_targeting

    try:
        server, port = open_listener()
    except OSError as exc:
        # Deliberately NOT a skip. The three checks above are the known reasons
        # this cannot run; "the machine would not give me a loopback port" is not
        # one of them, and a runner should be told rather than shown a tick.
        print("FAIL: no loopback listener (%s)" % exc)
        return 1
    stop = threading.Event()
    threading.Thread(target=echo, args=(server, stop), daemon=True).start()

    # stderr to /dev/null: the children are terminated while they are still
    # talking, so each one prints a connection-aborted traceback that means
    # nothing here and would read like a failure in a CI log.
    quiet = dict(stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    target = subprocess.Popen([sys.executable, "-c", CHILD % port], **quiet)
    other = subprocess.Popen([sys.executable, "-c", CHILD % port], **quiet)
    target_port, other_port = child_port(target), child_port(other)
    if target_port is None or other_port is None:
        # A child that never reached the echo server. Said in one sentence rather
        # than raised out of `int("")`, and the children are collected here
        # because this path used to return without touching them.
        stop.set()
        for proc in (target, other):
            proc.terminate()
            proc.wait(timeout=5)
        # No cause in the sentence: the child could have been refused, or reached
        # the server and died after. It names the fact and the port to look at,
        # which is all this side of the pipe actually knows.
        print("FAIL: a child never reported its port, so nothing was measured "
              "(echo server on 127.0.0.1:%d)" % port)
        return 1

    engine = BeanEngine()
    targeting = apply_targeting(engine, str(target.pid), log=lambda *_: None)
    if targeting is None or not targeting.pids():
        print("FAIL: targeting pid %d resolved to nothing - the check would prove "
              "nothing (a run with targeting off reports every flow in scope)"
              % target.pid)
        return 1

    engine.start("tcp and (tcp.SrcPort == %d or tcp.DstPort == %d)" % (port, port))
    try:
        time.sleep(3.0)                    # let both children talk under capture
        rows = {row.get("local_port"): row
                for row in engine.connections_snapshot(limit=None)}
    finally:
        engine.stop()
        stop.set()
        for proc in (target, other):
            proc.terminate()
            proc.wait(timeout=5)
        from beantester import driver
        driver.mark_driver_used()
        driver.release_on_exit()

    problems = []
    hit = rows.get(target_port)
    miss = rows.get(other_port)
    if hit is None:
        problems.append("the targeted process's connection (port %d) has no row at "
                        "all - nothing was captured" % target_port)
    elif not hit.get("scoped"):
        problems.append("the targeted process's connection was NOT in scope")
    if miss is None:
        problems.append("the untargeted process's connection (port %d) has no row, "
                        "so the false-positive half proves nothing" % other_port)
    elif miss.get("scoped"):
        problems.append("an UNTARGETED process's connection was in scope")

    for line in problems:
        print("FAIL: %s" % line)
    if problems:
        return 1
    print("ok: the targeted process was in scope, the other one was not "
          "(%d rows, target pid %d)" % (len(rows), target.pid))
    return 0


if __name__ == "__main__":
    sys.exit(main())
