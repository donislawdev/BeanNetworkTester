"""``proxy._Linux``: the desktop's proxy settings and the proxy variables on Linux.

``gsettings`` is stood in by a recorder that answers with what the real one printed on
Ubuntu 26.04 (GNOME 50, 2026-10-27) - the person's settings set to a manual proxy for
the measurement, and back to "none" after it. The variables' files are written into a
temporary root and home, so every case runs on any runner.
"""
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from beantester import proxy
from beantester.nettools import proxy as logic
from beantester.nettools.adapters import Words
from fakes import check

# `gsettings list-recursively org.gnome.system.proxy`, as printed (ftp lines kept).
MANUAL = """org.gnome.system.proxy autoconfig-url ''
org.gnome.system.proxy ignore-hosts ['localhost', '*.corp', "it's"]
org.gnome.system.proxy mode 'manual'
org.gnome.system.proxy use-same-proxy true
org.gnome.system.proxy.ftp host ''
org.gnome.system.proxy.ftp port 0
org.gnome.system.proxy.http authentication-password 'secret-\\'quoted'
org.gnome.system.proxy.http authentication-user 'someone'
org.gnome.system.proxy.http enabled false
org.gnome.system.proxy.http host '192.0.2.10'
org.gnome.system.proxy.http port 3128
org.gnome.system.proxy.http use-authentication false
org.gnome.system.proxy.https host ''
org.gnome.system.proxy.https port 0
org.gnome.system.proxy.socks host 'proxy.example'
org.gnome.system.proxy.socks port 1080
"""
NONE = MANUAL.replace("mode 'manual'", "mode 'none'")
HOME = "/home/someone"


class Gsettings:
    """``proxy._run`` standing in for gsettings: records each ``(argv, env)``, answers
    with ``out`` / ``err`` / ``code``, or raises ``raises``."""

    def __init__(self, out=NONE, err="", code=0, raises=None):
        self.out, self.err, self.code, self.raises = out, err, code, raises
        self.calls = []

    def __call__(self, argv, env):
        self.calls.append((argv, env))
        if self.raises:
            raise self.raises
        return SimpleNamespace(stdout=self.out.encode(), stderr=self.err.encode(),
                               returncode=self.code)


def which(found=("gsettings", "setpriv")):
    return lambda name: f"/usr/bin/{name}" if name in found else None


def linux(run=None, found=("gsettings", "setpriv"), person=None, own_uid=1000, root="/",
          home=HOME):
    return proxy._Linux(run=run or Gsettings(), which=which(found), root=root, person=person,
                        own_uid=own_uid, home=home)


def test_the_desktops_manual_proxy_reads_as_the_servers_and_what_goes_around():
    got = linux(Gsettings(MANUAL)).user()
    check("the servers in Learn's grammar, what is set only",
          got.server == "http=192.0.2.10:3128;socks=proxy.example:1080", f"({got})")
    check("the names that go around it", got.bypass == "localhost;*.corp;it's")
    check("nothing automatic", (got.detect, got.script) == (False, ""))
    values = proxy.gnome_values(MANUAL)
    check("the proxy's account and password are never read",
          not {k for _s, k in values} & proxy.GNOME_SECRETS
          and "secret" not in repr(values) and "someone" not in repr(values))


def test_each_mode_of_the_desktop_reads_as_windows_reads_its_own():
    check("none: nothing", linux(Gsettings(NONE)).user() == proxy.NOTHING)
    auto = MANUAL.replace("mode 'manual'", "mode 'auto'")
    check("auto without an address: the network is asked",
          linux(Gsettings(auto)).user() == proxy.UserProxy(True, "", "", ""))
    script = auto.replace("autoconfig-url ''", "autoconfig-url 'http://192.0.2.5/p.pac'")
    check("auto with an address: that script",
          linux(Gsettings(script)).user() == proxy.UserProxy(False, "http://192.0.2.5/p.pac",
                                                             "", ""))
    v6 = MANUAL.replace("host '192.0.2.10'", "host '2001:db8::7'").replace("port 1080", "port 0")
    check("an IPv6 host in brackets, a port of 0 left out",
          linux(Gsettings(v6)).user().server == "http=[2001:db8::7]:3128;socks=proxy.example")
    odd = MANUAL.replace("mode 'manual'", "mode 'unheard-of'")
    with pytest.raises(ValueError, match="does not know"):
        linux(Gsettings(odd)).user()


def test_gvariant_text_reads_as_g_variant_print_writes_it():
    cases = {"'plain'": "plain", '"it\'s"': "it's", r"'a\'b\\c\n'": "a'b\\c\n",
             r"'é\U0001F600'": "é\U0001F600", "@as []": [], "[]": [],
             "['a', \"b'c\"]": ["a", "b'c"], "8080": 8080, "-1": -1, "true": True,
             "false": False}
    for text, want in cases.items():
        value, rest = proxy._value(text)
        check(f"{text} -> {want!r}", (value, rest) == (want, ""), f"({value!r}, {rest!r})")
    for broken in ("'unclosed", "['a'", "nothing", "['a' 'b']"):
        with pytest.raises(ValueError):
            proxy._value(broken)
    with pytest.raises(ValueError, match="more after a value"):
        proxy.gnome_values("org.gnome.system.proxy mode 'none' 'again'\n")


def test_under_sudo_the_desktop_asked_is_the_persons_and_nothing_else_reaches_the_child():
    run = Gsettings()
    linux(run, person=(1000, 1000), own_uid=0).user()
    argv, env = run.calls[0]
    check("started as the person who typed sudo", argv == [
        "/usr/bin/setpriv", "--reuid=1000", "--regid=1000", "--init-groups",
        "/usr/bin/gsettings", "list-recursively", "org.gnome.system.proxy"], f"({argv})")
    check("with their home, a fixed PATH and UTF-8 in English, and nothing of root's",
          env == {"HOME": HOME, "PATH": "/usr/bin:/bin", "LC_ALL": "C.UTF-8"})
    run = Gsettings()
    linux(run, person=None, own_uid=1000).user()
    check("without sudo: gsettings itself, as this account",
          run.calls[0][0][0] == "/usr/bin/gsettings")
    run = Gsettings()
    linux(run, person=(0, 0), own_uid=0, home="/root").user()
    check("root that typed sudo: nobody to become", run.calls[0][0][0] == "/usr/bin/gsettings")
    with pytest.raises(OSError, match="setpriv was not found"):
        linux(person=(1000, 1000), own_uid=0, found=("gsettings",)).user()
    with pytest.raises(OSError, match="no home directory"):
        linux(person=(1000, 1000), own_uid=0, home="").user()


def test_the_one_program_started_gets_nothing_of_this_process(monkeypatch):
    seen = []
    monkeypatch.setattr(proxy.subprocess, "run", lambda argv, **kwargs: seen.append(
        (argv, kwargs)) or "done")
    check("the run's answer is handed back", proxy._run(["/usr/bin/gsettings"], {"HOME": HOME})
          == "done")
    argv, kwargs = seen[0]
    check("only the environment it is given, no terminal, a time limit, its output kept",
          kwargs == {"stdin": subprocess.DEVNULL, "capture_output": True,
                     "timeout": proxy.GSETTINGS_WAIT_S, "env": {"HOME": HOME}, "check": False},
          f"({kwargs})")
    check("the default reader runs through it", proxy._Linux(
        which=which(), person=None, own_uid=1000, home=HOME).run is proxy._run)


def test_a_system_without_the_desktops_settings_has_no_such_part():
    check("no gsettings", linux(found=()).user() is None)
    check("no such schema", linux(Gsettings("", "No such schema “org.gnome.system.proxy"
                                                "”\n", 1)).user() is None)
    memory = ("GLib-GIO-Message: Using the 'memory' GSettings backend.  Your settings will "
              "not be saved or shared with other applications.\n")
    check("GLib with nowhere the desktop keeps them", linux(Gsettings(NONE, memory)).user() is None)
    with pytest.raises(OSError, match="gsettings answered 2: something else"):
        linux(Gsettings("", "something else\nmore\n", 2)).user()


def test_a_gsettings_that_fails_costs_only_the_desktops_part(monkeypatch, tmp_path):
    monkeypatch.setattr(proxy.crashlog, "note", lambda *a: None)
    native = linux(Gsettings(raises=subprocess.TimeoutExpired(["gsettings"], 2)),
                   root=str(tmp_path))
    reading = proxy.read(native)
    check("the desktop's part says why", reading.user is None
          and "TimeoutExpired" in reading.user_error, f"({reading})")
    check("Linux: no WinHTTP part, and that is not a failure",
          (reading.machine, reading.machine_error, reading.system) == (None, "", "linux"))
    check("the variables still read", reading.env == () and reading.env_error == "")
    check("unreadable for the part that failed", logic.unreadable(reading))
    calm = proxy.read(linux(Gsettings(NONE), root=str(tmp_path)))
    check("and not for a part the system lacks", not logic.unreadable(calm), f"({calm})")


def _write(base, relative, text):
    path = os.path.join(base, *relative.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def test_the_variables_come_from_every_file_a_new_program_gets_them_from(tmp_path):
    root, home = str(tmp_path / "root"), str(tmp_path / "home")
    _write(root, "etc/environment", 'PATH="/usr/bin"\nhttp_proxy="http://192.0.2.1:3128"\n'
                                    "# no_proxy=commented\n")
    _write(root, "usr/lib/environment.d/50-proxy.conf", "https_proxy=http://192.0.2.2:3128\n")
    _write(root, "etc/environment.d/50-proxy.conf", "https_proxy='http://192.0.2.3:3128'\n")
    _write(root, "etc/environment.d/60-more.conf", "export HTTP_PROXY=http://192.0.2.4:8080\n")
    _write(home, ".config/environment.d/10-mine.conf",
           "http_proxy=http://u:pw@192.0.2.9:3128\nno_proxy=localhost,${OTHER}\nnot a line\n")
    native = linux(root=root, home=home, own_uid=os.stat(home).st_uid, person=None)
    got = {v.name: v for v in native.env()}
    check("case-sensitive names, in the program's order", list(got) == [
        "http_proxy", "HTTP_PROXY", "https_proxy", "no_proxy"], f"({list(got)})")
    check("the person's file wins over every account's, and says so",
          got["http_proxy"] == proxy.Variable("http_proxy", "http://u:pw@192.0.2.9:3128", "user",
                                              replaces=True))
    check("a file in /etc replaces the one of the same name in /usr/lib, quotes off",
          got["https_proxy"] == proxy.Variable("https_proxy", "http://192.0.2.3:3128", "machine"))
    check("export allowed, a variable shown as written",
          (got["HTTP_PROXY"].value, got["no_proxy"].value)
          == ("http://192.0.2.4:8080", "localhost,${OTHER}"))


def test_a_persons_files_that_are_not_theirs_are_not_read(tmp_path):
    root, home = str(tmp_path / "root"), str(tmp_path / "home")
    _write(home, ".config/environment.d/10-mine.conf", "http_proxy=http://192.0.2.9:3128\n")
    stranger = os.stat(home).st_uid + 4242
    native = linux(root=root, home=home, person=(stranger, stranger), own_uid=0)
    check("a directory someone else owns is skipped", native.env() == ())


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="links and owners of Linux")
def test_a_link_to_a_file_the_person_does_not_own_is_not_read(tmp_path):  # pragma: no cover - Linux
    root, home = str(tmp_path / "root"), str(tmp_path / "home")
    _write(home, ".config/environment.d/keep.conf", "https_proxy=http://192.0.2.8:3128\n")
    _write(str(tmp_path), "other/secret", "http_proxy=http://192.0.2.66:1\n")
    os.symlink(str(tmp_path / "other" / "secret"),
               os.path.join(home, ".config", "environment.d", "10-link.conf"))
    own = os.stat(home).st_uid
    native = linux(root=root, home=home, person=None, own_uid=own)
    check("their own link to their own file reads",
          [v.name for v in native.env()] == ["http_proxy", "https_proxy"])
    native.uid = own + 1                    # the same files, as someone else's
    check("as another account's files: nothing", native.env() == ())


def test_the_rows_and_the_report_say_linuxs_places():
    reading = proxy.Reading(None, "", None, "", (
        proxy.Variable("http_proxy", "http://192.0.2.9:3128", "user"),
        proxy.Variable("HTTP_PROXY", "http://192.0.2.4:8080", "machine")), "", "linux")
    rows = logic.details(reading)
    check("the desktop's part: not on this system", rows[0].item == Words(
        "tools.adapters.proxy.item.desktop") and rows[0].value == Words(
        "tools.adapters.proxy.value.not_here"), f"({rows[0]})")
    check("no WinHTTP rows", not [r for r in rows if r.key.startswith("winhttp")])
    by_name = {r.item: r for r in rows if isinstance(r.item, str)}
    check("lowercase http_proxy sends programs to its server, offered to the Control page",
          by_name["http_proxy"].address == "192.0.2.9" and logic.in_use(reading))
    check("uppercase HTTP_PROXY: curl does not read it",
          Words("tools.adapters.proxy.note.curl_lowercase") in by_name["HTTP_PROXY"].note)
    windows = reading._replace(system="windows", user=proxy.NOTHING,
                               machine=proxy.MachineProxy("", ""))
    check("on Windows the same name has no such note",
          Words("tools.adapters.proxy.note.curl_lowercase") not in {
              n for r in logic.details(windows) for n in r.note})
    report = logic.report_lines(reading)
    check("the report: the desktop's part by its name, no WinHTTP line", report == [
        "proxy, desktop (GNOME): not on this system",
        "proxy variables: http_proxy=http://192.0.2.9:3128 (user), "
        "HTTP_PROXY=http://192.0.2.4:8080 (machine)"], f"({report})")
    detect = reading._replace(user=proxy.UserProxy(True, "", "", ""))
    check("detection on Linux: programs look, not Windows", Words(
        "tools.adapters.proxy.note.detect_linux") in logic.details(detect)[0].note)


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="this runner's own system")
def test_this_machines_proxy_reads_without_raising():  # pragma: no cover - Linux
    reading = proxy.read()
    check("Linux's places", reading.system == "linux" and reading.machine is None
          and reading.machine_error == "", f"({reading})")
