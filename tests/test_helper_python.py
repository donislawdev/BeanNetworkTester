"""The Python test helper (python/beannetworktester): pytest fixture, sessions, wheels.

Sessions run the checkout's own program (``BEANNETWORKTESTER_PROGRAM`` pointing at
bean_network_tester.py) with ``simulate=True``: no rights, nothing on the network
changes. The real capture is tried by .github/workflows/pypi.yml on the runners,
installed from the wheels the way the package README says.
"""
import ast
import io
import json
import os
import re
import socket
import subprocess
import sys
import tarfile
import textwrap
import time
import warnings
import zipfile
from pathlib import Path

import psutil
import pytest

from beantester.cli import build_arg_parser
from fakes import ROOT, check

HELPER = Path(ROOT) / "python" / "beannetworktester"
sys.path.insert(0, str(HELPER / "src"))
sys.path.insert(0, str(HELPER / "release"))

import assemble  # noqa: E402
from beannetworktester import BadNetwork, BadNetworkError, BadNetworkWarning, bad_network  # noqa: E402
from beannetworktester import _aim, _lock, _program  # noqa: E402

LAUNCHER = os.path.join(ROOT, "bean_network_tester.py")
PROGRAM_FLAGS = {o for a in build_arg_parser()._actions for o in a.option_strings}
PROGRAM_DESTS = {a.dest for a in build_arg_parser()._actions}


@pytest.fixture
def checkout_program(monkeypatch, tmp_path):
    monkeypatch.setenv(_program.PROGRAM_ENV, LAUNCHER)
    monkeypatch.setenv("BEAN_NO_ELEVATE", "1")
    monkeypatch.setattr(_lock, "lock_path", lambda: str(tmp_path / "test.lock"))


def _resolver(*addresses):
    def resolve(host, port, proto=0):
        return [(socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, proto, "",
                 (a, port)) for a in addresses]
    return resolve


# --- which program --------------------------------------------------------------- #


def test_the_environment_names_another_copy_of_the_program(tmp_path):
    exe = tmp_path / "BeanNetworkTester.exe"
    exe.write_bytes(b"")
    script = tmp_path / "bean_network_tester.py"
    script.write_text("")
    check("a program runs as it is",
          _program.program_command(env={_program.PROGRAM_ENV: str(exe)}) == [str(exe)])
    check("a .py file runs with this Python",
          _program.program_command(env={_program.PROGRAM_ENV: str(script)})
          == [sys.executable, str(script)])
    with pytest.raises(BadNetworkError, match=_program.PROGRAM_ENV):
        _program.program_command(env={_program.PROGRAM_ENV: str(tmp_path / "missing")})


def test_the_packaged_program_and_every_way_it_can_be_missing(tmp_path):
    def ask(platform, machine, here=tmp_path):
        return _program.program_command(env={}, platform=platform, machine=machine,
                                        here=str(here))

    with pytest.raises(BadNetworkError, match="Windows x64 and Linux x64 only"):
        ask("darwin", "arm64")
    with pytest.raises(BadNetworkError, match="Windows x64 and Linux x64 only"):
        ask("linux", "aarch64")
    with pytest.raises(BadNetworkError, match="has no program in it"):
        ask("linux", "x86_64")
    folder = tmp_path / "program" / "BeanNetworkTester"
    folder.mkdir(parents=True)
    with pytest.raises(BadNetworkError, match="removed it"):
        ask("win32", "AMD64")
    (folder / "BeanNetworkTester.exe").write_bytes(b"")
    (folder / "BeanNetworkTester").write_bytes(b"")
    check("Windows finds the exe", ask("win32", "AMD64") == [str(folder / "BeanNetworkTester.exe")])
    check("Linux finds its program", ask("linux", "x86_64") == [str(folder / "BeanNetworkTester")])


def test_rights_are_asked_before_anything_starts(monkeypatch):
    check("simulate needs no rights", _program.rights_prefix(simulate=True) == [])
    monkeypatch.setattr(_program, "_is_admin", lambda: False)
    with pytest.raises(BadNetworkError, match="Run as administrator"):
        _program.rights_prefix(simulate=False, platform="win32")
    monkeypatch.setattr(_program, "_is_admin", lambda: True)
    check("an elevated Windows runs it directly",
          _program.rights_prefix(simulate=False, platform="win32") == [])
    monkeypatch.setattr(_program.os, "geteuid", lambda: 1000, raising=False)
    monkeypatch.setattr(_program, "_sudo_works", lambda: True)
    check("Linux without root goes through sudo -n",
          _program.rights_prefix(simulate=False, platform="linux") == ["sudo", "-n"])
    monkeypatch.setattr(_program, "_sudo_works", lambda: False)
    with pytest.raises(BadNetworkError, match="without a password"):
        _program.rights_prefix(simulate=False, platform="linux")
    monkeypatch.setattr(_program.os, "geteuid", lambda: 0, raising=False)
    check("root runs it directly", _program.rights_prefix(simulate=False, platform="linux") == [])
    with pytest.raises(BadNetworkError, match="only"):
        _program.rights_prefix(simulate=False, platform="darwin")


# --- the aim and the settings ------------------------------------------------- #


def test_a_session_without_an_aim_is_refused():
    with pytest.raises(BadNetworkError, match="needs an aim"):
        _aim.session_flags(settings={"latency": 300})
    check("canary: simulate needs none",
          _aim.session_flags(simulate=True, settings={"latency": 3}) == ["--latency", "3"])
    # The program's own aims are an aim on their own (an API on its port, say), and they
    # narrow server= and process= when given with them.
    for own, value in (("target", "node"), ("dst_ip", "10.0.0.0/24"), ("dst_port", 8080)):
        check(f"{own} is an aim", _aim.session_flags(settings={own: value})
              == ["--" + own.replace("_", "-"), str(value)])
    check("and narrows one", _aim.session_flags(process="self", settings={"dst_port": 443})
          == ["--target", str(os.getpid()), "--dst-port", "443"])


@pytest.mark.parametrize("key, empty", [("dst_ip", ""), ("dst_ip", []), ("dst_port", " "),
                                        ("target", ","), ("target", ("", ""))])
def test_an_empty_aim_is_refused_not_passed_as_no_aim(key, empty):
    # Alone it would count as an aim and reach the program as an empty flag, which aims
    # at everything. After server= it would override the server's own addresses.
    with pytest.raises(BadNetworkError, match="names nothing"):
        _aim.session_flags(settings={key: empty})
    with pytest.raises(BadNetworkError, match="names nothing"):
        _aim.session_flags(server="localhost:3000", settings={key: empty},
                           resolve=_resolver("127.0.0.1"))


@pytest.mark.parametrize("server, port", [
    ("http://localhost:3000", "3000"), ("https://localhost", "443"), ("ws://localhost/x", "80"),
    ("localhost:5432", "5432"), (("localhost", 8443), "8443")])
def test_a_server_is_its_addresses_and_its_port(server, port):
    flags = _aim.session_flags(server=server, settings={},
                               resolve=_resolver("127.0.0.1", "::1", "127.0.0.1"))
    check(f"{server!r}", flags == ["--dst-ip", "127.0.0.1,::1", "--dst-port", port], f"({flags})")


def test_a_server_that_names_no_port_or_no_address_is_refused():
    for bad in ("http://localhost:notaport", "localhost", "://"):
        with pytest.raises(BadNetworkError):
            _aim.session_flags(server=bad, settings={}, resolve=_resolver("127.0.0.1"))
    with pytest.raises(BadNetworkError, match="has no address"):
        _aim.session_flags(server="nowhere:1", settings={}, resolve=_resolver())
    check("an IPv6 zone is not part of the aim",
          _aim.server_ips("h", 1, resolve=_resolver("fe80::1%eth0")) == ["fe80::1"])


def test_settings_become_the_programs_flags():
    flags = _aim.session_flags(process="self", settings={
        "latency": 300, "loss_burst": 4, "flap_hold": True, "asym": False, "seed": None,
        "dst_port": None, "block_port": [80, 443]})
    check("the flags", flags == ["--target", str(os.getpid()), "--latency", "300",
                                 "--loss-burst", "4", "--flap-hold", "--block-port", "80,443"],
          f"({flags})")
    for bad in ({"format": "text"}, {"Latency": 1}, {"latency-ms": 1}):
        with pytest.raises(BadNetworkError):
            _aim.session_flags(simulate=True, settings=bad)
    with pytest.raises(BadNetworkError, match="one or the other"):
        _aim.session_flags(server="h:1", settings={"dst_ip": "1.2.3.4"},
                           resolve=_resolver("127.0.0.1"))
    with pytest.raises(BadNetworkError, match="one or the other"):
        _aim.session_flags(process="self", settings={"target": "x"})
    with pytest.raises(BadNetworkError, match="process="):
        _aim.session_flags(process=True, settings={})


def test_a_process_aim_is_this_test_or_what_it_started():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        check("a running Popen is its PID",
              _aim.session_flags(process=child, settings={}) == ["--target", str(child.pid)])
    finally:
        child.kill()
        child.wait(timeout=30)
    with pytest.raises(BadNetworkError, match="already ended"):
        _aim.session_flags(process=child, settings={})
    # A number may be any process (PID 1 on Linux is every one), a name every process whose
    # name contains it: neither is something this test started, and target= takes them.
    for bad in (1, os.getpid(), "node", "chrome.exe", "*", True, object()):
        with pytest.raises(BadNetworkError, match="use target="):
            _aim.session_flags(process=bad, settings={})
    check("self is this process", _aim.session_flags(process="self", settings={})
          == ["--target", str(os.getpid())])


def test_several_servers_are_every_address_and_port_of_them():
    def resolve(host, port, proto=0):
        found = ["10.0.0.5"] if host == "10.0.0.5" else ["127.0.0.1", "::1"]
        return _resolver(*found)(host, port, proto)

    flags = _aim.session_flags(server=["http://localhost:3000", ("10.0.0.5", 5432),
                                       "localhost:3000"], settings={}, resolve=resolve)
    check("the flags", flags == ["--dst-ip", "127.0.0.1,::1,10.0.0.5",
                                 "--dst-port", "3000,5432"], f"({flags})")
    with pytest.raises(BadNetworkError, match="names no server"):
        _aim.session_flags(server=[], settings={})


def _scenario(folder, steps, name="s.json", *, bom=False, wrapped=True):
    path = folder / name
    text = json.dumps({"steps": steps} if wrapped else steps)
    path.write_text(("\ufeff" if bom else "") + text, encoding="utf-8")
    return path


def test_a_scenario_may_not_change_what_the_session_aims_at(tmp_path):
    local = _resolver("127.0.0.1")
    port_step = [{"at": 0, "settings": {"latency": 50}}, {"at": 5, "settings": {"dst_port": ""}}]
    with pytest.raises(BadNetworkError, match="step 2 changes dst_port"):
        _aim.session_flags(server="localhost:3000", resolve=local,
                           settings={"scenario": str(_scenario(tmp_path, port_step))})
    path = _scenario(tmp_path, port_step, "list.json", bom=True, wrapped=False)
    flags = _aim.session_flags(process="self", settings={"scenario": str(path)})
    check("with process=, a step on the port narrows that process: allowed, by its full path",
          flags[-2:] == ["--scenario", str(path.resolve())], f"({flags})")
    target_step = str(_scenario(tmp_path, [{"at": 0, "settings": {"target": "*"}}], "t.json"))
    with pytest.raises(BadNetworkError, match="step 1 changes target"):
        _aim.session_flags(process="self", settings={"scenario": target_step})
    check("the program's own aims are the test's to change: no check",
          _aim.session_flags(settings={"dst_port": 8080, "scenario": target_step})[-1]
          == os.path.abspath(target_step))
    # The program's own: failing-dns aims at port 53 in its first step.
    shipped = [os.path.join(ROOT, "scenarios")]
    with pytest.raises(BadNetworkError, match="step 1 changes dst_port"):
        _aim.session_flags(server="localhost:3000", resolve=local, shipped_scenarios=shipped,
                           settings={"scenario": "scenarios/failing-dns.json"})
    flags = _aim.session_flags(process="self", shipped_scenarios=shipped,
                               settings={"scenario": "scenarios/failing-dns.json"})
    check("a shipped name is found where the program keeps it", flags[-1]
          == os.path.join(ROOT, "scenarios", "failing-dns.json"), f"({flags})")
    for bad, why in (("missing.json", "no such file"), (__file__, "could not be read as JSON")):
        with pytest.raises(BadNetworkError, match=why):
            _aim.session_flags(process="self", settings={"scenario": bad})
    (tmp_path / "flat.json").write_text('{"loop": true}')
    with pytest.raises(BadNetworkError, match="no list of steps"):
        _aim.session_flags(process="self", settings={"scenario": str(tmp_path / "flat.json")})


def test_what_the_helper_sets_itself_is_the_programs_own():
    """The reserved names and the flags a session adds are real flags of the program, so
    the helper cannot drift from the parser it drives."""
    missing = {name for name in _aim.RESERVED if name not in PROGRAM_DESTS}
    check("every reserved name is a program option", not missing, f"({missing})")
    added = {"--format", "--stop-on-stdin-close", "--duration", "--simulate", "--dst-ip",
             "--dst-port", "--target"}
    check("every flag a session adds exists", added <= PROGRAM_FLAGS, f"({added - PROGRAM_FLAGS})")
    check("canary: a made-up name is caught", "latncy" not in PROGRAM_DESTS)


# --- one session at a time ------------------------------------------------------- #


def test_a_second_session_waits_for_the_first(tmp_path):
    path = str(tmp_path / "m.lock")
    first, second = _lock.MachineLock(path), _lock.MachineLock(path)
    first.acquire(0)
    start = time.monotonic()
    with pytest.raises(BadNetworkError, match="one at a time"):
        second.acquire(0.5)
    check("it waited", time.monotonic() - start >= 0.4)
    first.release()
    second.acquire(0)
    check("free again after the release", second.held)
    second.release()


def test_a_lock_file_this_user_cannot_write_is_still_a_lock(tmp_path):
    """A run under sudo leaves a lock file owned by root, which the next run's user can
    only read: opening it to write failed, and the session never started."""
    path = tmp_path / "m.lock"
    path.write_bytes(b"")
    os.chmod(path, 0o400)
    try:
        first, second = _lock.MachineLock(str(path)), _lock.MachineLock(str(path))
        first.acquire(0)
        # Read-only even where the permission bits do not bind (a suite run as root).
        check("the file is held open for reading only", first._handle.mode == "rb",
              f"({first._handle.mode})")
        with pytest.raises(BadNetworkError, match="one at a time"):
            second.acquire(0)
        first.release()
    finally:
        os.chmod(path, 0o600)


@pytest.mark.skipif(sys.platform == "win32", reason="the shared /tmp is Linux's")
def test_a_link_or_a_fifo_at_the_lock_path_is_refused_at_once(tmp_path):
    """The path is the same for every user: a link planted there would point the lock at
    another file, and a FIFO would block the open until someone writes to it."""
    target = tmp_path / "victim"
    link = tmp_path / "link.lock"
    link.symlink_to(target)                       # dangling: a create would make the victim
    with pytest.raises(BadNetworkError, match="not a plain file"):
        _lock.MachineLock(str(link)).acquire(0)
    check("nothing was made through the link", not target.exists())
    fifo = tmp_path / "fifo.lock"
    os.mkfifo(fifo)
    began = time.monotonic()
    with pytest.raises(BadNetworkError, match="not a plain file"):
        _lock.MachineLock(str(fifo)).acquire(0)
    check("refused at once, not blocked", time.monotonic() - began < 5)


def test_the_lock_is_in_the_machines_tmp_on_linux_whatever_tmpdir_says(monkeypatch):
    monkeypatch.setenv("TMPDIR", "/somewhere/else")
    monkeypatch.setattr(_lock.tempfile, "tempdir", None)
    monkeypatch.setattr(_lock.sys, "platform", "linux")
    check("/tmp", _lock.lock_path() == os.path.join("/tmp", _lock.LOCK_NAME), f"({_lock.lock_path()})")


_HOLDER = """
import sys, time
sys.path.insert(0, sys.argv[1])
from beannetworktester._lock import MachineLock
lock = MachineLock(sys.argv[2])
lock.acquire(0)
print("held", flush=True)
time.sleep(60)
"""


def test_the_lock_goes_with_the_process_that_held_it(tmp_path):
    path = str(tmp_path / "m.lock")
    holder = subprocess.Popen([sys.executable, "-c", _HOLDER, str(HELPER / "src"), path],
                              stdout=subprocess.PIPE, text=True)
    try:
        check("the other process holds it", holder.stdout.readline().strip() == "held")
        with pytest.raises(BadNetworkError):
            _lock.MachineLock(path).acquire(0.3)
    finally:
        holder.kill()
        holder.wait(timeout=30)
    lock = _lock.MachineLock(path)
    lock.acquire(5)
    check("killed, it let go", lock.held)
    lock.release()


# --- sessions, on the checkout's program ------------------------------------------ #


def test_a_session_waits_for_the_capture_and_stops_with_its_summary(checkout_program):
    session = bad_network(simulate=True, latency=20, duration=60)
    try:
        check("started: the program's start record", session.start_record
              and session.start_record["event"] == "start", f"({session.start_record})")
        check("running", session.running)
        began = time.monotonic()
        with pytest.raises(BadNetworkError, match="has not been stopped yet"):
            bad_network(simulate=True, duration=60, wait=30)
        check("a second one here is refused at once, not after waiting for its own lock",
              time.monotonic() - began < 5)
        check("the session added its own flags", session.command[-6:]
              == ["--format", "json", "--stop-on-stdin-close", "--duration", "60", "--simulate"])
    finally:
        summary = session.stop()
    check("stopped by closing its input", summary["stop_reason"] == "stdin"
          and summary["exit_code"] == 0, f"({summary})")
    check("stop again gives the same summary", session.stop() is summary)
    with bad_network(simulate=True, duration=60) as again:
        check("the lock was given back", again.running)
    check("with stops it", not again.running and again.summary["stop_reason"] == "stdin")


def test_a_session_that_outlives_its_duration_says_so(checkout_program):
    session = bad_network(simulate=True, duration=1)
    time.sleep(2.5)
    with pytest.warns(BadNetworkWarning, match="ended by its duration"):
        summary = session.stop()
    check("the summary says why", summary["stop_reason"] == "duration", f"({summary})")


def test_the_program_refusing_a_setting_fails_the_start_with_its_words(checkout_program):
    with pytest.raises(BadNetworkError, match="unrecognized arguments: --latncy"):
        bad_network(simulate=True, latncy=5)
    with pytest.raises(BadNetworkError, match="refused the settings"):
        bad_network(simulate=True, loss=500)
    with bad_network(simulate=True, duration=30) as session:
        check("canary: a failed start left the lock free", session.running)


def test_a_stop_that_is_not_heard_asks_first_then_forces():
    """A forced end on Linux leaves the aim's packets nowhere to go for about 3 s, so a
    program that did not hear its input close is asked to end before it is forced."""
    from beannetworktester import _session

    calls = []

    class Deaf:
        def terminate(self):
            calls.append("terminate")

        def kill(self):
            calls.append("kill")

        def wait(self, timeout=None):
            calls.append(f"wait {timeout:g}" if timeout else "wait")
            if timeout and "kill" not in calls:
                raise subprocess.TimeoutExpired("program", timeout)

    class Listening(Deaf):
        def wait(self, timeout=None):
            calls.append("wait")

    _session._end(Deaf())
    check("asked, given time, then forced",
          calls == ["terminate", f"wait {_session.END_GRACE_S:g}", "kill", "wait"], f"({calls})")
    calls.clear()
    _session._end(Listening())
    check("canary: one that ends when asked is not forced", calls == ["terminate", "wait"],
          f"({calls})")


def test_a_stop_interrupted_in_its_wait_still_ends_the_program_and_frees_the_lock(tmp_path):
    """Ctrl+C or a test timeout inside stop() used to leave the program running, the lock
    held and the session counted as live, so the next session in the process was refused."""
    from beannetworktester import _session

    ended = []

    class Running:
        stdin = stdout = stderr = None

        def poll(self):
            return None if not ended else 0

        def wait(self, timeout=None):
            raise KeyboardInterrupt

    session = BadNetwork(simulate=True)
    session._lock = _lock.MachineLock(str(tmp_path / "m.lock"))
    session._lock.acquire(0)
    session._proc = Running()
    _session._LIVE.add(session)
    real_end = _session._end
    _session._end = lambda proc: ended.append(proc)
    try:
        with pytest.raises(KeyboardInterrupt):
            session.stop()
    finally:
        _session._end = real_end
        _session._LIVE.discard(session)
    check("the program was ended", len(ended) == 1)
    check("the lock is free", not session._lock.held)
    check("the session no longer counts as live", session not in _session._LIVE)


def test_a_bad_duration_is_refused_before_anything_starts():
    for bad in (0, -1, None, "x", 86401):
        with pytest.raises(BadNetworkError, match="duration"):
            BadNetwork(simulate=True, duration=bad)


_ORPHAN = """
import os, sys
sys.path.insert(0, sys.argv[1])
from beannetworktester import bad_network
session = bad_network(simulate=True, duration=120)
print(session._proc.pid, flush=True)
os._exit(0)
"""


def test_the_program_ends_when_the_test_process_dies(checkout_program, tmp_path):
    done = subprocess.run([sys.executable, "-c", _ORPHAN, str(HELPER / "src")],
                          capture_output=True, text=True, timeout=120, env=os.environ.copy())
    program = psutil.Process(int(done.stdout.strip().splitlines()[-1]))
    try:
        program.wait(timeout=20)
        ended = True
    except psutil.TimeoutExpired:
        program.kill()
        ended = False
    check("the program ended with the process that started it", ended)


# --- the pytest fixture --------------------------------------------------------------- #


def _run_pytest(tmp_path, body):
    test = tmp_path / "test_case.py"
    test.write_text(textwrap.dedent(body))
    report = tmp_path / "report.xml"
    env = dict(os.environ, PYTHONPATH=str(HELPER / "src"), BEAN_NO_ELEVATE="1")
    env[_program.PROGRAM_ENV] = LAUNCHER
    done = subprocess.run([sys.executable, "-m", "pytest", "-p", "beannetworktester.pytest_plugin",
                           "-p", "no:cacheprovider", "-q", f"--junitxml={report}", str(test)],
                          capture_output=True, text=True, cwd=str(tmp_path), env=env, timeout=300)
    return done, (report.read_text() if report.exists() else "")


def test_the_fixture_starts_on_call_and_stops_with_the_test(tmp_path):
    done, report = _run_pytest(tmp_path, """
        def test_slow(bad_network):
            session = bad_network(simulate=True, latency=10, duration=60)
            assert session.running
    """)
    check("the test passed", done.returncode == 0, f"({done.stdout[-600:]})")
    check("the summary is in the report", 'name="bad_network"' in report
          and "stdin" in report, f"({report[-600:]})")


def test_canary_the_fixture_fails_a_test_without_an_aim(tmp_path):
    done, _ = _run_pytest(tmp_path, """
        def test_unaimed(bad_network):
            bad_network(latency=10)
    """)
    check("the test failed, saying why", done.returncode == 1 and "needs an aim" in done.stdout,
          f"({done.stdout[-600:]})")


# --- the wheels --------------------------------------------------------------------- #


def _fake_archives(folder, *, link=False, program=True):
    """A Windows zip and a Linux tar.gz laid out as the release lays them out."""
    folder.mkdir(parents=True, exist_ok=True)
    win = folder / "win.zip"
    with zipfile.ZipFile(win, "w") as z:
        if program:
            z.writestr("BeanNetworkTester/BeanNetworkTester.exe", b"MZ exe")
        z.writestr("BeanNetworkTester/_internal/LICENSE", b"GPL")
    members = [("BeanNetworkTester/_internal/x.so", b"lib", 0o644)]
    if program:
        members.append(("BeanNetworkTester/BeanNetworkTester", b"\x7fELF", 0o755))
    tgz = folder / "linux.tar.gz"
    with tarfile.open(tgz, "w:gz") as tar:
        for name, data, mode in members:
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), mode
            tar.addfile(info, io.BytesIO(data))
        if link:
            info = tarfile.TarInfo("BeanNetworkTester/libz.so")
            info.type, info.linkname = tarfile.SYMTYPE, "x.so"
            tar.addfile(info)
    return win, tgz


def test_the_release_makes_three_wheels_with_the_program_inside(tmp_path):
    win, tgz = _fake_archives(tmp_path / "in")
    wheels = assemble.build("v1.1.0", win, tgz, tmp_path / "out")
    names = [w.name for w in wheels]
    check("three wheels", names == ["beannetworktester-1.1.0-py3-none-win_amd64.whl",
                                    "beannetworktester-1.1.0-py3-none-manylinux_2_39_x86_64.whl",
                                    "beannetworktester-1.1.0-py3-none-any.whl"], f"({names})")
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as z:
            listing = z.namelist()
            record = z.read("beannetworktester-1.1.0.dist-info/RECORD").decode()
            for line in record.splitlines():
                name, digest, _ = line.split(",")
                if digest:
                    check(f"{wheel.name}: {name} hash", digest == assemble._record_hash(z.read(name)))
            meta = z.read("beannetworktester-1.1.0.dist-info/METADATA").decode()
            check("GPL-3.0-only", "License-Expression: GPL-3.0-only" in meta)
            check("the pytest plugin is registered", "beannetworktester.pytest_plugin" in
                  z.read("beannetworktester-1.1.0.dist-info/entry_points.txt").decode())
            check("the helper's code is in", "beannetworktester/_session.py" in listing)
            if "linux" in wheel.name:
                info = z.getinfo("beannetworktester/program/BeanNetworkTester/BeanNetworkTester")
                check("the Linux program keeps its execute bit", info.external_attr >> 16 & 0o111)
            has_program = any(n.startswith("beannetworktester/program/") for n in listing)
            check(f"{wheel.name}: a program only in the platform wheels",
                  has_program == (not wheel.name.endswith("-any.whl")))


def test_the_release_refuses_what_it_cannot_ship(tmp_path):
    check("rc versions as PyPI writes them", assemble.pep440("v1.1.0-rc.1") == "1.1.0rc1")
    for bad in ("1.1", "1.1.0-beta.1", "1.1.0rc1"):
        with pytest.raises(SystemExit):
            assemble.pep440(bad)
    win, tgz = _fake_archives(tmp_path / "a", link=True)
    with pytest.raises(SystemExit, match="link"):
        assemble.build("1.1.0", win, tgz, tmp_path / "out1")
    win, tgz = _fake_archives(tmp_path / "b", program=False)
    with pytest.raises(SystemExit, match="no executable"):
        assemble.build("1.1.0", win, tgz, tmp_path / "out2")
    # A name that climbs out of the program's folder would be a path outside the
    # package once the wheel is installed.
    for n, escape in enumerate(("BeanNetworkTester/../../evil.py", "BeanNetworkTester/..\\evil")):
        win, tgz = _fake_archives(tmp_path / f"c{n}")
        with zipfile.ZipFile(win, "a") as z:
            z.writestr(escape, b"x")
        with pytest.raises(SystemExit, match="not a file inside"):
            assemble.build("1.1.0", win, tgz, tmp_path / f"out3{n}")


def test_the_linux_wheel_names_the_c_library_of_the_machine_that_builds_it():
    """glibc of each Ubuntu runner the release could build on, and the tag that follows."""
    glibc = {"ubuntu-22.04": "2_35", "ubuntu-24.04": "2_39", "ubuntu-26.04": "2_43"}
    release = (Path(ROOT) / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    jobs = re.split(r"\n  (?=[a-z][\w-]*:\n)", release)
    linux = [job for job in jobs if " -czf " in job and "runs-on:" in job]
    check("one job builds the Linux package", len(linux) == 1, f"({len(linux)})")
    runner = re.search(r"runs-on:\s*(\S+)", linux[0]).group(1)
    check("the release builds it on a known Ubuntu", runner in glibc, f"({runner})")
    check("the wheel's tag follows it",
          assemble.LINUX_TAG == f"manylinux_{glibc[runner]}_x86_64", f"({assemble.LINUX_TAG})")


# --- the package README ----------------------------------------------------------- #


def test_every_setting_the_package_readme_names_is_a_program_flag():
    text = (HELPER / "README.md").read_text(encoding="utf-8")
    named = set(re.findall(r"`([a-z_]+)=", text)) | set(re.findall(r"\b([a-z_]+)=\d", text))
    own = {"server", "process", "duration", "simulate", "wait", "start_timeout"}
    stray = {name for name in named - own if name not in PROGRAM_DESTS}
    check("no setting the program does not have", not stray, f"({sorted(stray)})")
    check("canary: the scan finds the table's settings", {"latency", "loss", "flap_down"} <= named,
          f"({sorted(named)})")
    api = {node.name for node in ast.parse((HELPER / "src" / "beannetworktester" /
                                            "_session.py").read_text()).body
           if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    check("the README's entry point exists", "bad_network" in api and "BadNetwork" in api)


def test_the_package_readme_links_only_to_pages_the_site_has():
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import build_site
    registry = build_site.load_registry(ROOT)
    pages = {p["languages"]["en"]["dir_path"].strip("/")
             for p in build_site.load_pages(ROOT, registry) if "en" in p["languages"]}
    text = (HELPER / "README.md").read_text(encoding="utf-8")
    linked = re.findall(r"https://beannetworktester\.donislawdev\.com/([\w/-]*)", text)
    check("the README links to the site", len(linked) >= 2, f"({linked})")
    missing = [path for path in linked if path.strip("/") not in pages]
    check("every link reaches an English page", not missing, f"({missing})")
    check("canary: a made-up page is not one", "cli" not in pages)


def test_every_readme_shows_the_helpers_by_their_real_names():
    """Every language of the README shows both helpers, with the names the code has."""
    npm = (Path(ROOT) / "npm" / "beannetworktester")
    exports = json.loads((npm / "package.json").read_text(encoding="utf-8"))["exports"]
    fixture = re.search(r"\bbadNetwork: async", (npm / "playwright.js").read_text(encoding="utf-8"))
    python = (HELPER / "src" / "beannetworktester" / "pytest_plugin.py").read_text(encoding="utf-8")
    check("the code has the names the READMEs show", "./playwright" in exports and fixture
          and "def bad_network(request)" in python)
    readmes = sorted(Path(ROOT).glob("README*.md"))
    check("eight READMEs", len(readmes) == 8, f"({len(readmes)})")
    for readme in readmes:
        text = readme.read_text(encoding="utf-8")
        for needed in ("from 'beannetworktester/playwright'", "async ({ page, badNetwork })",
                       "def test_checkout_survives_a_slow_api(bad_network):",
                       "pip install beannetworktester", "npm install --save-dev beannetworktester",
                       "https://pypi.org/project/beannetworktester/",
                       "https://www.npmjs.com/package/beannetworktester"):
            check(f"{readme.name}: {needed}", needed in text)


def test_a_session_stopped_in_time_warns_about_nothing(checkout_program):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with bad_network(simulate=True, duration=60):
            pass
    ours = [w for w in caught if issubclass(w.category, BadNetworkWarning)]
    check("no BadNetworkWarning", not ours, f"({[str(w.message) for w in ours]})")


def test_the_summary_brief_names_what_a_report_needs():
    from beannetworktester.pytest_plugin import _brief
    brief = json.loads(_brief({"stop_reason": "stdin", "seed": 3, "elapsed_s": 1.0,
                               "repro_command": "x", "counters": {"seen": 9, "scoped_seen": 4}}))
    check("brief", brief == {"stop_reason": "stdin", "seed": 3, "elapsed_s": 1.0,
                             "repro_command": "x", "packets": 9, "in_scope": 4}, f"({brief})")
    check("nothing for no summary", _brief(None) == "")
