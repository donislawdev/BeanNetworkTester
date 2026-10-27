"""The proxy row of the Adapters tool (``beantester/nettools/proxy.py``): Learn's proxy
list grammar, which entry may be offered to the Control page, hidden passwords, the
details and the report. Pure functions over ``proxy.Reading`` - no window, no system."""
import json
import os

from beantester.nettools import proxy
from beantester.nettools.adapters import Words
from beantester.proxy import MachineProxy, Reading, UserProxy, Variable
from fakes import ROOT, check

NOTHING = Reading(UserProxy(False, "", "", ""), "", MachineProxy("", ""), "", (), "")
EVERYTHING = Reading(
    UserProxy(True, "http://user:pw@192.0.2.20/proxy.pac?token=abc",
              "http=192.0.2.10:8080;https=proxy.example.com:8443", "<local>;*.example.com"), "",
    MachineProxy("192.0.2.30:3128", "<local>"), "",
    (Variable("HTTP_PROXY", "http://user:secret@192.0.2.40:8080", "user", replaces=True),
     Variable("HTTPS_PROXY", "http://proxy.example.com:8443", "machine"),
     Variable("NO_PROXY", "localhost,.example.com", "user")), "")
FAILED = Reading(None, "OSError: user part", None, "OSError: machine part", (),
                 "OSError: env part")


def test_a_proxy_list_is_split_the_way_learn_writes_it():
    """``([<scheme>=][<scheme>"://"]<server>[":"<port>])``, separated by semicolons or
    whitespace (WINHTTP_PROXY_INFO, Remarks)."""
    check("semicolons, spaces and both", proxy.entries("a:1;b:2 c:3; d:4") ==
          ["a:1", "b:2", "c:3", "d:4"], f"({proxy.entries('a:1;b:2 c:3; d:4')})")
    check("nothing is no entries", proxy.entries("") == [] and proxy.entries(None) == [])
    cases = {
        "192.0.2.10:8080": ("192.0.2.10", "192.0.2.10"),
        "http=192.0.2.10:8080": ("192.0.2.10", "192.0.2.10"),
        "https=proxy.example.com:8443": ("proxy.example.com", ""),
        "socks=192.0.2.12:1080": ("192.0.2.12", "192.0.2.12"),
        "http://192.0.2.10:8080": ("192.0.2.10", "192.0.2.10"),
        "http=http://192.0.2.10:8080/": ("192.0.2.10", "192.0.2.10"),
        "[2001:db8::1]:8080": ("2001:db8::1", "2001:db8::1"),
        "http=[2001:db8::1]:3128": ("2001:db8::1", "2001:db8::1"),
        "2001:db8::1": ("2001:db8::1", "2001:db8::1"),
        "http://user:p=w@192.0.2.40:8080": ("192.0.2.40", "192.0.2.40"),
        "proxy.example.com": ("proxy.example.com", ""),
        "[2001:db8::1": ("", ""),
    }
    for entry, (host, address) in cases.items():
        got = (proxy.host_of(entry), proxy.address_of(entry))
        check(f"{entry}: its server, and an address only for an IP", got == (host, address),
              f"({got})")


def test_a_password_never_survives_and_the_report_drops_a_query():
    check("one URL", proxy.masked("http://user:secret@192.0.2.40:8080") ==
          "http://***@192.0.2.40:8080")
    two = proxy.masked("http=http://a:b@h1:1;https=https://c@h2:2")
    check("every URL in a list", two == "http=http://***@h1:1;https=https://***@h2:2", f"({two})")
    check("nothing to hide is left alone", proxy.masked("192.0.2.10:8080") == "192.0.2.10:8080")
    cases = {
        "no scheme, as a variable often holds it": (
            "user:secret@192.0.2.40:8080", "***@192.0.2.40:8080"),
        "a scheme= without //": ("http=user:secret@192.0.2.40:8080", "http=***@192.0.2.40:8080"),
        "the second entry of a list": (
            "http=192.0.2.10:8080;https=user:secret@h2:2", "http=192.0.2.10:8080;https=***@h2:2"),
        "entries split by whitespace": (
            "192.0.2.10:8080 user:secret@h2:2", "192.0.2.10:8080 ***@h2:2"),
        "an @ in the password, in a URL": (
            "http://user:p@ss@192.0.2.40:8080", "http://***@192.0.2.40:8080"),
        "an @ in the password, no scheme": ("user:p@ss@192.0.2.40:8080", "***@192.0.2.40:8080"),
        "an = in the password": ("user:pa=ss@192.0.2.40:8080", "***@192.0.2.40:8080"),
        "an IPv6 server": (
            "http://user:secret@[2001:db8::1]:8080", "http://***@[2001:db8::1]:8080"),
        "an @ in a setup script's query is no password": (
            "http://192.0.2.20/proxy.pac?u=a@b", "http://192.0.2.20/proxy.pac?u=a@b"),
        "nor one in its path": (
            "http://192.0.2.20/x@y/proxy.pac", "http://192.0.2.20/x@y/proxy.pac"),
        "a bypass list is left alone": ("*.example.com;<local>;10.*", "*.example.com;<local>;10.*"),
    }
    for name, (value, shown) in cases.items():
        got = proxy.masked(value)
        check(name, got == shown, f"({got})")
    report = proxy.for_report("http://u:p@192.0.2.20/proxy.pac?token=abc#frag")
    check("the report: no password, no query, no fragment",
          report == "http://***@192.0.2.20/proxy.pac", f"({report})")


def test_the_row_says_in_use_not_set_or_could_not_be_read():
    cases = {"nothing": (NOTHING, "not_set"), "everything": (EVERYTHING, "in_use"),
             "the parts failed": (FAILED, "unreadable"),
             "detection alone": (NOTHING._replace(user=UserProxy(True, "", "", "")), "in_use"),
             "only NO_PROXY": (NOTHING._replace(env=(Variable("NO_PROXY", "x", "user"),)),
                               "not_set"),
             "only the machine's": (NOTHING._replace(machine=MachineProxy("192.0.2.30:1", "")),
                                    "in_use"),
             "a part failed, another is set": (
                 NOTHING._replace(user=None, env=(Variable("ALL_PROXY", "h:1", "machine"),)),
                 "in_use")}
    for name, (reading, state) in cases.items():
        got = proxy.state_words(reading)
        check(name, got == Words(f"tools.adapters.proxy.state.{state}"), f"({got})")
    check("the address column: the account's first server",
          proxy.first_server(EVERYTHING) == "192.0.2.10")
    check("else the machine's", proxy.first_server(
        NOTHING._replace(machine=MachineProxy("proxy.example.com:3128", ""))) == "proxy.example.com")
    check("else nothing", proxy.first_server(NOTHING) == "" and proxy.first_server(FAILED) == "")


def _keys(words):
    return tuple(w.key if isinstance(w, Words) else w for w in words)


def test_the_details_say_what_each_setting_is_and_offer_only_addresses():
    rows = {d.key: d for d in proxy.details(EVERYTHING)}
    check("in reading order", list(rows) == [
        "detect", "script", "server|0", "server|1", "bypass", "winhttp|0", "winhttp_bypass",
        "env|HTTP_PROXY", "env|HTTPS_PROXY", "env|NO_PROXY"], f"({list(rows)})")
    check("detection is explained", _keys(rows["detect"].note) ==
          ("tools.adapters.proxy.note.detect",))
    check("the script's password is hidden on screen too",
          rows["script"].value == "http://***@192.0.2.20/proxy.pac?token=abc", rows["script"])
    check("an IP server is offered", rows["server|0"].address == "192.0.2.10")
    check("a named one is not, and says why", rows["server|1"].address == "" and
          _keys(rows["server|1"].note) == ("tools.adapters.proxy.note.goes_here",
                                           "tools.adapters.proxy.note.name"), rows["server|1"])
    check("<local> is explained", _keys(rows["bypass"].note) == ("tools.adapters.proxy.note.local",)
          and rows["bypass"].value == "<local>, *.example.com")
    check("the services' proxy is offered too", rows["winhttp|0"].address == "192.0.2.30"
          and "tools.adapters.proxy.note.services" in _keys(rows["winhttp|0"].note))
    http = rows["env|HTTP_PROXY"]
    check("a variable: masked, its scope, that it replaces, who reads it",
          http.value == "http://***@192.0.2.40:8080" and http.address == "192.0.2.40"
          and _keys(http.note) == ("tools.adapters.proxy.note.this_account",
                                   "tools.adapters.proxy.note.replaces",
                                   "tools.adapters.proxy.note.readers",
                                   "tools.adapters.proxy.note.masked"), http)
    check("NO_PROXY is what goes around, never a place to send the impairments",
          rows["env|NO_PROXY"].address == "" and "tools.adapters.proxy.note.no_proxy"
          in _keys(rows["env|NO_PROXY"].note), rows["env|NO_PROXY"])
    around = proxy.details(NOTHING._replace(env=(Variable("NO_PROXY", "192.0.2.50", "user"),)))
    check("not even when it holds a bare address", around[-1].address == "", around[-1])
    bare = proxy.details(NOTHING._replace(
        env=(Variable("HTTP_PROXY", "user:secret@192.0.2.40:8080", "machine"),)))[-1]
    check("a variable with no scheme: masked, said so, and still offered",
          bare.value == "***@192.0.2.40:8080" and bare.address == "192.0.2.40"
          and "tools.adapters.proxy.note.masked" in _keys(bare.note), bare)
    empty = {d.key: d for d in proxy.details(NOTHING)}
    check("nothing set: one row each, saying none", list(empty) ==
          ["detect", "script", "server", "winhttp", "env"], f"({list(empty)})")
    failed = {d.key: d for d in proxy.details(FAILED)}
    check("a part that failed: one row with why", list(failed) == ["user", "winhttp", "env"]
          and failed["user"].note == ("OSError: user part",), f"({failed})")


def test_the_report_hides_passwords_and_says_none_or_why():
    lines = proxy.report_lines(EVERYTHING)
    text = "\n".join(lines)
    check("no password, no token", "pw" not in text and "secret" not in text
          and "token" not in text, text)
    check("three lines: the account, the services, the variables", lines == [
        "proxy, this account: detect automatically yes, setup script "
        "http://***@192.0.2.20/proxy.pac, server http=192.0.2.10:8080;https=proxy.example.com:8443,"
        " bypass <local>;*.example.com",
        "proxy for services (WinHTTP): 192.0.2.30:3128, bypass <local>",
        "proxy variables: HTTP_PROXY=http://***@192.0.2.40:8080 (user), "
        "HTTPS_PROXY=http://proxy.example.com:8443 (machine), NO_PROXY=localhost,.example.com (user)"],
        f"({lines})")
    check("nothing set says none", proxy.report_lines(NOTHING) == [
        "proxy, this account: detect automatically no, setup script none, server none, bypass none",
        "proxy for services (WinHTTP): none", "proxy variables: none"],
        f"({proxy.report_lines(NOTHING)})")
    check("a failure says why", proxy.report_lines(FAILED) == [
        "proxy, this account: could not be read (OSError: user part)",
        "proxy for services (WinHTTP): could not be read (OSError: machine part)",
        "proxy variables: could not be read (OSError: env part)"])
    check("report() is the lines", proxy.report(EVERYTHING) == text)
    bare = proxy.report_lines(NOTHING._replace(
        env=(Variable("ALL_PROXY", "user:secret@192.0.2.40:1080", "user"),)))
    check("a variable with no scheme loses its password too",
          bare[-1] == "proxy variables: ALL_PROXY=***@192.0.2.40:1080 (user)", f"({bare})")


def test_the_tool_reads_through_the_binding_on_windows_and_linux():
    class Native:                   # what proxy._Native answers, without a system
        def user(self):
            return UserProxy(True, "", "", "")

        def machine(self):
            return MachineProxy("", "")

        def env(self):
            return (Variable("NO_PROXY", "localhost", "user"),)
    got = proxy.read(Native())
    check("the binding's three parts, handed over whole", got == Reading(
        UserProxy(True, "", "", ""), "", MachineProxy("", ""), "",
        (Variable("NO_PROXY", "localhost", "user"),), ""), f"({got})")
    import sys
    check("read on Windows and Linux, like the adapters",
          proxy.supported() == sys.platform.startswith(("win", "linux")))


def test_every_word_the_row_can_say_is_in_every_language():
    readings = (NOTHING, EVERYTHING, FAILED)
    keys = {"tools.adapters.proxy.row", "tools.adapters.kind.proxy"}
    for reading in readings:
        keys.add(proxy.state_words(reading).key)
        for detail in proxy.details(reading):
            for part in (detail.item, detail.value, *detail.note):
                if isinstance(part, Words):
                    keys.add(part.key)
    keys |= {f"tools.adapters.proxy.state.{s}" for s in ("in_use", "not_set", "unreadable")}
    for lang in ("en", "pl", "zh"):
        with open(os.path.join(ROOT, "lang", f"{lang}.json"), encoding="utf-8") as handle:
            texts = json.load(handle)
        missing = sorted(k for k in keys if not texts.get(k))
        check(f"{lang}: every word has a text", not missing, f"({missing})")
