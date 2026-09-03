"""Convention 36 says the shipped program reaches no network, and nothing checked it.

Four places SAY it - `THIRD-PARTY-NOTICES.md`, both READMEs, `--license` and the
About window - and two tests guard those sentences (`test_license_surface.py`,
`test_windows.py`). Every one of them checks that we CLAIM it. This file is the
first thing that looks at the code, which matters more here than usual: this tool
intercepts the user's network traffic, so "it sends nothing anywhere" is the one
promise where being wrong is not a bug but a betrayal.

Two layers, and neither contains the other
------------------------------------------
* **Static (AST).** Reads every shipped module. Sees code that no test ever
  executes - and this package has such code: ``utils.host_identity`` has a
  ``gethostbyname`` fallback that MEASURED runs on no ordinary path, because
  ``_route_source_ip`` answers first.
  🔴 It resolves ALIASES, and that was not free knowledge. An outside review
  pointed at the shape and measurement confirmed it: the first version matched
  ``socket.x(...)`` literally, so ``import socket as s`` and ``from socket import
  create_connection`` both walked through, as did ``import subprocess as sp`` and
  ``os.popen`` (which was simply missing from the list). The fix has two halves,
  and the second is the one that matters: local names are resolved against what
  was imported, AND the IMPORT itself is registered per file - because a statement
  names its module whatever the local name becomes, so a module reaching for one
  of these fails before anything has to work out what it did with the name.
* **Runtime (audit hook, PEP 578).** Runs the CLI for real and watches what the
  interpreter reports. Sees what is not written down literally, which is exactly
  where a static scan is blind. MEASURED 2026-09-03 on CPython 3.14.7:
  ``ctypes.dlopen`` carries the library name even when it was computed,
  ``socket.connect`` carries the DESTINATION, and the ``import`` event caught
  ``__import__("url" + "lib.request")``, which no AST can see.

So the static half answers "was it written", the runtime half answers "what
actually happened", and dropping either one leaves a shape of bypass wide open.

What this CANNOT prove, said plainly
------------------------------------
* A **C extension** calling WinSock directly raises no ``socket`` event. ``psutil``
  is such an extension. ``pydivert`` reaches its driver through ``ctypes``, so it
  does show up as ``ctypes.dlopen`` - but the distinction is real and must not be
  smoothed over: the audit hook covers third-party PYTHON, not third-party C.
* The runtime layer only sees what it runs. It drives the CLI, not the GUI - the
  GUI's one network primitive is ``webbrowser`` behind a click, which no test
  clicks, and the static layer holds that instead.
* Data can leave a machine without a socket (a file written into a synced
  folder). Nothing here looks at that.
* 🔴 **The one gap BOTH layers share, found by mutating rather than by thinking:**
  a computed import (``__import__("url" + "lib")``) inside a function nothing
  calls. The static layer cannot read the string, the runtime layer never reaches
  the line. Move that same call onto a path the CLI executes and the runtime
  layer catches it at once - MEASURED, it reported
  ``['http', 'http.client', 'ssl', 'urllib']``. So the hole is narrower than it
  sounds (dead code that becomes live gets caught the moment it runs), but it is
  a hole and it is written down rather than discovered later.

This is therefore not a proof of "no telemetry". It is a LOCK on the surface:
nobody adds a way out by accident, and adding one deliberately means editing a
registry below and writing down why.

The canary at the bottom is not decoration
------------------------------------------
``tests/test_public_text_guard.py`` earned that lesson for this project - the
leak scanner had reported "clean" for months, and the first time anybody fed it
something known-bad it let a LAN address straight through. A guard nobody has
watched fail is indistinguishable from a guard that reads nothing, so every check
here is pointed at code it must reject.
"""
import ast
import os
import subprocess
import sys

from fakes import ROOT, check

# --------------------------------------------------------------------------- #
# Scope: convention 36's own scope - everything that goes into the release.
# `tools/` is deliberately OUT. `tools/downloads.py` calls the GitHub API and is
# a maintenance script that never reaches a user's machine, which the convention
# says in as many words: do not report it as a violation.
# --------------------------------------------------------------------------- #
PACKAGE = os.path.join(ROOT, "beantester")
LAUNCHER = os.path.join(ROOT, "bean_network_tester.py")

# Clients that exist to talk to a network. An import is enough to fail: there is
# no legitimate reason for one of these to be in a tool that promises silence.
FORBIDDEN_MODULES = {
    "urllib", "urllib2", "urllib3", "http", "httplib", "requests", "httpx",
    "aiohttp", "websockets", "websocket", "ftplib", "smtplib", "poplib",
    "imaplib", "nntplib", "telnetlib", "xmlrpc", "socketserver", "smtpd",
    "wsgiref", "asyncio", "ssl", "boto3", "paramiko", "pycurl",
}

# Modules whose USE is policed rather than banned. Naming them here is what makes
# the scan alias-proof: `import socket as s` still carries the name `socket` in
# the import statement, so resolving local names against this set catches
# `s.create_connection(...)` and `from socket import create_connection` alike.
# Measured 2026-09-03 - before this existed, all three of those shapes walked
# straight through, and so did `import subprocess as sp; sp.run(...)`.
WATCHED_MODULES = {"socket", "webbrowser", "subprocess", "os", "ctypes"}

# Which files may import the three that can reach outside this process at all.
# This is the stronger half of the alias answer: an import names its module
# whatever it calls it locally, so a new module reaching for `socket` fails here
# before anything has to work out what it did with it.
ALLOWED_IMPORTS = {
    ("beantester/utils.py", "socket"):
        "the route probe and the machine's own name",
    ("beantester/settings.py", "socket"):
        "the machine's own services file, for port labels",
    ("beantester/gui/app.py", "webbrowser"):
        "the support page, opened on a click",
    ("beantester/gui/panels/about.py", "webbrowser"):
        "the support page, from the About window",
    ("beantester/winenv.py", "subprocess"):
        "list2cmdline, a pure string helper - nothing here spawns anything",
}

# The exceptions, each with the reason it exists. A call on one of these modules
# that is not listed here fails, and an entry naming code that is gone fails too -
# the registry is exact in BOTH directions, like the probe inventory in
# `internal_tools/baseline.py`. Stale permission is how an allowlist rots into a
# blindfold.
#
# 🔴 Instance methods are deliberately NOT chased. ``s.send(...)`` on a socket
# object is invisible here, and it does not need to be: a socket cannot exist
# without passing through ``socket.socket`` or ``socket.create_connection``,
# which are gated above. The gate sits at CREATION, which is one place instead of
# every method a socket has. Verified rather than assumed - both
# ``socket.socket(); s.send(...)`` and the ``sendto`` form are caught by the
# canary below, at the constructor.
ALLOWED_CALLS = {
    ("beantester/utils.py", "socket", "socket"):
        "the connected-UDP route probe: it records a default peer to ask the "
        "routing table which interface would be used, and sends nothing",
    ("beantester/utils.py", "socket", "gethostname"):
        "the machine's own name, for the session panel and the repro report",
    ("beantester/utils.py", "socket", "gethostbyname"):
        "fallback for host_identity when the route probe finds no address. "
        "Owner's decision 2026-09-03: kept as an exception, to be measured later - "
        "a name resolution CAN put a query on the wire, and nobody has checked "
        "whether this one does",
    ("beantester/settings.py", "socket", "getservbyport"):
        "reads the machine's own services file to label a well-known port",
    ("beantester/gui/app.py", "webbrowser", "open_new_tab"):
        "opens the support page in the user's browser, only when they click it",
    ("beantester/gui/panels/about.py", "webbrowser", "open_new_tab"):
        "the same support page, from the About window",
}

# Every library the package loads through ctypes. All ten are local Windows APIs;
# none of them speaks a network protocol. This is the check that closes the hole
# a module-name scan cannot see - `windll.wininet` needs no import statement.
ALLOWED_LIBRARIES = {
    "advapi32", "dwmapi", "iphlpapi", "kernel32", "ntdll", "shcore", "shell32",
    "user32", "uxtheme", "winmm",
}

# A process is the other way out of a sandbox: `curl`, `powershell -c Invoke-
# WebRequest`, `bitsadmin`. MEASURED: the shipped package spawns NOTHING today,
# so this is a floor rather than a budget. `winenv.py` imports subprocess for
# `list2cmdline`, a pure string helper, which is why the import is not the test.
# 🔴 `popen` was missing until 2026-09-03 and `os.popen("curl ...")` walked
# through - the plainest spelling of the thing this check exists to stop. The
# lesson is not "add popen": it is that a list of names is only as good as the
# person who wrote it, so the canary below carries a case for each family rather
# than trusting the list to be complete.
SPAWN_CALLS = {"run", "Popen", "call", "check_call", "check_output", "system",
               "popen", "startfile", "posix_spawn", "posix_spawnp",
               "spawnl", "spawnle", "spawnlp", "spawnv", "spawnve", "spawnvp",
               "execl", "execle", "execlp", "execv", "execve", "execvp",
               "execvpe", "fork", "forkpty"}

# An endpoint appears in the code as a string before anything calls it, so a URL
# outside these two files is an early warning. The rule is the PLACE, not a list
# of addresses, so adding a third-party component (convention 35 requires its
# source URL) does not have to touch this test.
URL_HOMES = {"beantester/appinfo.py", "beantester/legal.py"}


def _shipped():
    """Every Python file that goes into the release, repo-relative."""
    out = [LAUNCHER]
    for base, dirs, files in os.walk(PACKAGE):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        out += [os.path.join(base, f) for f in files if f.endswith(".py")]
    return sorted((os.path.relpath(p, ROOT).replace("\\", "/"), p) for p in out)


def _docstring_nodes(tree):
    """The string constants that are docstrings, by identity.

    Prose is not an endpoint. ``views.py`` explains its search syntax with
    ``http://x`` in a docstring, and a scan that cannot tell that from a
    hard-coded address would be a scan people learn to ignore.
    """
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                out.add(id(first.value))
    return out


LOADERS = ("windll", "cdll", "oledll")


def _library_name(node):
    """The ctypes library a node names, or None. Handles every loader form.

    Three spellings reach the same place and all three are read: the attribute
    chain ``ctypes.windll.kernel32``, the same chain after ``from ctypes import
    windll`` (where the base is a bare name), and the explicit
    ``ctypes.WinDLL("iphlpapi.dll")``. An alias on ``ctypes`` itself needs no
    special case - the loader attribute is what is matched, not the module name.
    """
    if isinstance(node, ast.Attribute):
        base = node.value
        if isinstance(base, ast.Attribute) and base.attr in LOADERS:
            return node.attr
        if isinstance(base, ast.Name) and base.id in LOADERS:
            return node.attr
    if isinstance(node, ast.Call):
        name = getattr(node.func, "attr", "") or getattr(node.func, "id", "")
        if name in ("WinDLL", "CDLL", "OleDLL", "LoadLibrary") and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                return first.value
    return None


def _local_names(tree):
    """What the local names in this module actually refer to.

    Returns ``(modules, symbols)``: ``modules`` maps a local name to the watched
    module it stands for (``import socket as s`` -> ``{"s": "socket"}``), and
    ``symbols`` maps a bare name to the ``(module, attribute)`` it was imported
    from (``from subprocess import run`` -> ``{"run": ("subprocess", "run")}``).

    Without this the scan only sees one spelling out of three, which is exactly
    how it looked until somebody fed it the other two.
    """
    modules, symbols = {}, {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in WATCHED_MODULES:
                    modules[alias.asname or alias.name] = top
        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".")[0]
            if top in WATCHED_MODULES:
                for alias in node.names:
                    symbols[alias.asname or alias.name] = (top, alias.name)
    return modules, symbols


def _url_scheme(text):
    """The scheme of a URL literal, or ``''``. Never raises.

    🔴 The first version did ``split("://")[0].rsplit(None, 1)[-1]`` and a string
    that is exactly ``"://"`` made it raise ``IndexError`` - so a module carrying
    that literal would have taken the whole guard down instead of reporting
    anything. A scanner that crashes is worse than one that misses: the miss is
    silent, the crash is a red build nobody can read.
    """
    head = text.split("://")[0].strip()
    if not head:
        return ""
    return head.rsplit(None, 1)[-1].lower()


def findings(source, rel):
    """Every network finding in one module: a list of ``(kind, detail, line)``.

    One function rather than five scattered loops, because the canary at the
    bottom has to be able to point the SAME code at something known-bad. A
    scanner that can only be run against the tree it was written for cannot be
    shown to work.
    """
    found = []
    tree = ast.parse(source)
    docstrings = _docstring_nodes(tree)
    modules, symbols = _local_names(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in FORBIDDEN_MODULES:
                    found.append(("import", alias.name, node.lineno))
                elif top in ("socket", "webbrowser", "subprocess"):
                    # Reported whether or not it is registered - the test decides.
                    # An import states its module whatever the local name becomes,
                    # so this is the check an alias cannot walk around.
                    found.append(("watched-import", (rel, top), node.lineno))
        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".")[0]
            if top in FORBIDDEN_MODULES:
                found.append(("import", node.module, node.lineno))
            elif top in ("socket", "webbrowser", "subprocess"):
                found.append(("watched-import", (rel, top), node.lineno))
        elif isinstance(node, ast.Call):
            func = node.func
            owner = name = None
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                owner, name = modules.get(func.value.id), func.attr
            elif isinstance(func, ast.Name) and func.id in symbols:
                owner, name = symbols[func.id]
            if owner in ("socket", "webbrowser"):
                found.append(("call", (rel, owner, name), node.lineno))
            if owner in ("subprocess", "os") and name in SPAWN_CALLS:
                found.append(("spawn", "%s.%s" % (owner, name), node.lineno))
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstrings and "://" in node.value:
                if _url_scheme(node.value) in ("http", "https", "ftp", "ws", "wss"):
                    found.append(("url", node.value[:60], node.lineno))
        library = _library_name(node)
        if library:
            found.append(("library", library.lower().removesuffix(".dll"),
                          getattr(node, "lineno", 0)))
    return found


def _scan():
    """Every finding across the shipped package, keyed by kind."""
    out = {}
    for rel, path in _shipped():
        with open(path, encoding="utf-8") as handle:
            for kind, detail, line in findings(handle.read(), rel):
                out.setdefault(kind, []).append((rel, detail, line))
    return out


# -- layer A: what the code SAYS --------------------------------------------- #
def test_the_shipped_package_imports_no_network_client():
    """Not one of the modules that exist to talk to a network is imported."""
    bad = ["%s:%d imports %s" % (rel, line, detail)
           for rel, detail, line in _scan().get("import", [])]
    check("no network client is imported by the shipped package", not bad, f"({bad})")


def test_every_socket_and_browser_use_is_a_named_exception():
    """The two modules that CAN reach out are allowed only where it is written down.

    Exact in both directions. A call with no entry fails, and an entry whose code
    has moved fails too - a permission nobody can point at any more is how an
    allowlist quietly becomes a blindfold.
    """
    used = {detail for _rel, detail, _line in _scan().get("call", [])}
    unlisted = sorted(c for c in used if c not in ALLOWED_CALLS)
    check("every socket/webbrowser call is a named exception", not unlisted,
          f"(add it to ALLOWED_CALLS with the reason, or remove it: {unlisted})")
    stale = sorted(entry for entry in ALLOWED_CALLS if entry not in used)
    check("no exception is listed for code that is gone", not stale,
          f"(remove it from ALLOWED_CALLS: {stale})")


def test_only_named_files_may_import_a_module_that_reaches_outside():
    """The alias-proof half: an import names its module whatever it calls it.

    ``import socket as s`` and ``from socket import create_connection`` both
    carry the word ``socket`` in the statement, so registering the IMPORT catches
    a new module reaching for one of these before anything has to work out what
    it did with the name afterwards. Exact in both directions, like the calls.
    """
    used = {detail for _rel, detail, _line in _scan().get("watched-import", [])}
    unlisted = sorted(i for i in used if i not in ALLOWED_IMPORTS)
    check("only named files import socket, webbrowser or subprocess", not unlisted,
          f"(add it to ALLOWED_IMPORTS with the reason: {unlisted})")
    stale = sorted(entry for entry in ALLOWED_IMPORTS if entry not in used)
    check("no import permission outlives the import", not stale,
          f"(remove it from ALLOWED_IMPORTS: {stale})")


def test_ctypes_opens_only_local_windows_libraries():
    """No network library reaches the driver layer through ctypes.

    This is the check a module-name scan cannot do: ``windll.wininet`` needs no
    import statement, so nothing about its spelling looks like networking.
    """
    seen = {detail for _rel, detail, _line in _scan().get("library", [])}
    bad = sorted(seen - ALLOWED_LIBRARIES)
    check("ctypes opens only local Windows libraries", not bad,
          f"(a library that can speak a protocol has no business here: {bad})")


def test_the_shipped_package_never_spawns_a_process():
    """No child process, so no shelling out to curl, bitsadmin or PowerShell."""
    bad = ["%s:%d %s" % (rel, line, detail)
           for rel, detail, line in _scan().get("spawn", [])]
    check("the shipped package spawns no process", not bad, f"({bad})")


def test_a_url_literal_lives_only_where_the_licence_needs_one():
    """An address in the code is an endpoint waiting for a caller.

    Allowed in exactly two files: ``appinfo.py`` holds the support page the About
    window opens, and ``legal.py`` holds the component source URLs that
    convention 35 obliges us to publish. Docstrings are exempt - prose about a
    URL is not a URL.
    """
    bad = ["%s:%d %s" % (rel, line, detail)
           for rel, detail, line in _scan().get("url", []) if rel not in URL_HOMES]
    check("a URL literal lives only in appinfo.py or legal.py", not bad, f"({bad})")


# -- layer B: what the code DOES --------------------------------------------- #
# The hook is installed BEFORE beantester is imported, so module-level work is
# covered too. It runs in a subprocess because `sys.addaudithook` has no removal
# API: installed in the pytest interpreter it would slow every later test and
# leak into all of them. `tests/gui_harness.py` runs subprocesses for the same
# class of reason.
# What it costs, so nobody has to wonder: MEASURED 2026-09-03 on a bench that
# refuses a verdict when the difference is inside the noise
# (`internal_tools/bench_audit_hook.py`, two full runs). An installed hook charges
# **~235-310 ns per audit event** - the RATIO repeated at 4.66x and 4.76x, the
# absolute did not, so the range is the honest form. This run raises 2010 events,
# about half a millisecond, and the bench REFUSED a conclusion on this workload in
# both runs: against a 1.2 s run whose own spread is 50-200 ms it cannot be seen.
# The second that `--duration 1` waits out is what this test costs, not the hook.
AUDIT_SCRIPT = """
import io, json, sys
sys.path.insert(0, {root!r})

NET = ("socket.", "urllib.", "ftplib.", "smtplib.", "imaplib.", "poplib.",
       "http.", "ssl.", "webbrowser.", "subprocess.", "os.system", "os.exec",
       "os.spawn", "os.startfile")
FORBIDDEN = {forbidden!r}
seen, libraries, imports = [], set(), set()

def hook(event, args):
    if event.startswith(NET):
        seen.append([event, repr(args)[:120]])
    elif event == "ctypes.dlopen":
        libraries.add(str(args[0]).lower().removesuffix(".dll"))
    elif event == "import":
        top = str(args[0]).split(".")[0]
        if top in FORBIDDEN:
            imports.add(str(args[0]))

sys.addaudithook(hook)

# A real run with impairment armed, through the real entry point.
from beantester.cli import run_cli
out, err = io.StringIO(), io.StringIO()
try:
    code = run_cli(["--simulate", "--loss", "10", "--latency", "50",
                    "--duration", "1"], out=out, err=err)
except SystemExit as exc:
    code = exc.code

# The one documented network primitive, exercised on purpose so the test can
# assert WHERE it goes rather than merely that it exists.
from beantester.utils import host_identity
host_identity()

print("BEGIN_JSON" + json.dumps({{"exit": code, "events": seen,
                                 "libraries": sorted(libraries),
                                 "imports": sorted(imports)}}))
"""

# What a healthy run is allowed to raise. MEASURED 2026-09-03: the CLI run on its
# own raises NOTHING, and every entry below comes from `host_identity`. The
# addresses are asserted, not just the event names - "a socket happened" would
# pass for a socket that shipped the user's traffic somewhere.
ALLOWED_EVENTS = {
    "socket.gethostname": "the machine's own name",
    "socket.__new__": "the two route probes, both SOCK_DGRAM",
    "socket.connect": "the route probes, to 8.8.8.8:80 and 2001:4860:4860::8888:80",
    "socket.gethostbyname": "the documented fallback when no route is found",
}
PROBE_ADDRESSES = ("8.8.8.8", "2001:4860:4860::8888")


def _audit_run():
    script = AUDIT_SCRIPT.format(root=ROOT, forbidden=sorted(FORBIDDEN_MODULES))
    proc = subprocess.run([sys.executable, "-c", script], cwd=ROOT, timeout=180,
                          capture_output=True, text=True, check=False)
    marker = proc.stdout.find("BEGIN_JSON")
    assert marker >= 0, (
        "the audited run produced no result\n--- stdout ---\n%s\n--- stderr ---\n%s"
        % (proc.stdout[-1500:], proc.stderr[-1500:]))
    import json
    return json.loads(proc.stdout[marker + len("BEGIN_JSON"):])


def test_a_real_run_raises_no_network_audit_event():
    """Run the CLI for real and let the interpreter report what happened.

    This is the half that sees through a computed name, a dynamic import and a
    third-party Python library, none of which the AST above can read.

    🔴 The library check is VACUOUS on the Linux leg and that is worth saying,
    because a green run there would otherwise read as proof it does not give.
    MEASURED 2026-09-03 in WSL: the same five socket events fire with the same
    destinations, so the connection half is real on both runners, but `dlopen`
    comes back EMPTY - nothing loads a Windows library on Linux. The static
    ``test_ctypes_opens_only_local_windows_libraries`` above reads source, so it
    is the half that covers this everywhere.
    """
    result = _audit_run()
    check("the audited CLI run succeeded", result["exit"] == 0, f"({result['exit']})")
    unexpected = [e for e in result["events"] if e[0] not in ALLOWED_EVENTS]
    check("no unexpected network event was raised", not unexpected, f"({unexpected})")
    check("no forbidden module was imported at runtime", not result["imports"],
          f"({result['imports']})")
    bad = sorted(set(result["libraries"]) - ALLOWED_LIBRARIES)
    check("ctypes loaded only local Windows libraries", not bad, f"({bad})")


def test_the_only_connection_goes_to_the_documented_route_probe():
    """Every ``connect`` names one of the two probe addresses, and nothing else.

    The event carries its destination, so this can say WHERE rather than "a
    socket was created" - the difference between a route lookup and an upload.
    """
    connects = [e[1] for e in _audit_run()["events"] if e[0] == "socket.connect"]
    check("something connected at all, or this test proves nothing", connects,
          "(host_identity did not run - the check would pass vacuously)")
    stray = [c for c in connects if not any(a in c for a in PROBE_ADDRESSES)]
    check("every connection goes to a documented route probe", not stray, f"({stray})")


# -- the canary: the guard has to be shown able to fail ---------------------- #
# 🔴 Every ALIAS shape below was measured walking straight through on
# 2026-09-03, which is why they are here one by one rather than as a single
# representative case: the scan read exactly one spelling out of three, and a
# canary that only ever tries the spelling the author had in mind proves nothing
# about the two they did not.
BAD_CODE = (
    ("a plain import of a network client", "import urllib.request\n", "import"),
    ("a from-import of one", "from http.client import HTTPConnection\n", "import"),
    ("a network library through ctypes",
     "import ctypes\nctypes.windll.wininet.InternetOpenW(0, 0, 0, 0, 0)\n", "library"),
    ("the same one loaded by string",
     "import ctypes\nctypes.WinDLL('winhttp')\n", "library"),
    ("the same one after from-importing the loader",
     "from ctypes import windll\nwindll.wininet.InternetOpenW(0)\n", "library"),
    ("shelling out to curl",
     "import subprocess\nsubprocess.run(['curl', 'https://x.example'])\n", "spawn"),
    ("shelling out under an alias",
     "import subprocess as sp\nsp.run(['curl', 'https://x.example'])\n", "spawn"),
    ("shelling out through a from-import",
     "from subprocess import Popen\nPopen(['curl'])\n", "spawn"),
    ("os.popen, the plainest spelling of all",
     "import os\nos.popen('curl https://x.example')\n", "spawn"),
    ("the exec family", "import os\nos.execl('/bin/sh', 'sh')\n", "spawn"),
    ("posix_spawn", "import os\nos.posix_spawn('/bin/sh', [], {})\n", "spawn"),
    ("an endpoint written into the code", "ENDPOINT = 'https://telemetry.example/v1'\n",
     "url"),
    ("a socket call in a module with no permission",
     "import socket\nsocket.create_connection(('x.example', 443))\n", "call"),
    ("the same call under an alias",
     "import socket as s\ns.create_connection(('x.example', 443))\n", "call"),
    ("the same call through a from-import",
     "from socket import create_connection\ncreate_connection(('x.example', 443))\n",
     "call"),
    ("a socket built to send with",
     "import socket\ns = socket.socket()\ns.send(b'secret')\n", "call"),
    ("and the datagram form",
     "import socket\ns = socket.socket()\ns.sendto(b'secret', ('h', 1))\n", "call"),
    ("an unregistered module importing socket at all",
     "import socket as s\n", "watched-import"),
)


def test_the_static_guard_rejects_code_it_must_reject():
    """Point the scanner at each shape it exists to catch, and require a finding.

    Every case is something this project would genuinely be sorry to ship. A
    guard that has only ever seen clean code has been shown to run, not to look
    (see ``tests/test_public_text_guard.py`` for where that lesson was paid for).
    """
    missed = []
    for label, source, kind in BAD_CODE:
        kinds = {k for k, _detail, _line in findings(source, "beantester/fake.py")}
        if kind not in kinds:
            missed.append("%s -> saw %s, wanted %s" % (label, sorted(kinds) or "nothing",
                                                       kind))
    check("the scanner catches every shape it exists to catch", not missed,
          f"({missed})")


def test_the_canary_does_not_pass_by_accident():
    """Clean code produces no finding, or the case above proves nothing.

    A scanner that flags everything would satisfy the canary and be useless, so
    the negative half is part of the same claim.
    """
    clean = ("import os\n"
             "def f(path):\n"
             '    """Read a file. Not http://example.invalid, just prose."""\n'
             "    with open(path) as handle:\n"
             "        return handle.read()\n")
    found = findings(clean, "beantester/fake.py")
    check("ordinary code raises no finding", not found, f"({found})")
