"""The Filter tester's verdict is the one a session gives the same value.

The tester (``nettools.exprtest.evaluate``) reaches the matcher through the field
registry and ``Matcher.explain``; a session through ``settings.apply_settings``,
``core.compile_endpoint`` and ``BeanCore.decide``, and for a process through
``ProcessTargeting.refresh``. ``tests/test_matchers_properties.py`` holds
``explain`` to ``matches``. This holds the two ROADS to each other, over a grid of
expressions and values per field, because what can differ is what each road does
around the matcher: how the text is trimmed, what an empty field means, which form
of an address the packet carries.

Found on its first run (2026-11-04): an empty Blocked IP or Blocked port read
"Matches" in the tester, and a session blocks nothing by an empty block field.
"""
import random

import pytest

from beantester.core import BeanCore
from beantester.fields import expression_fields
from beantester.i18n import set_language
from beantester.nettools.exprtest import MATCH, NO_MATCH, evaluate
from beantester.settings import DEFAULT_SETTINGS, apply_settings
from beantester.targeting import ProcessTargeting

LOCAL_PORT = 50000
OTHER_IP, OTHER_PORT = "192.0.2.10", 443          # the half of the packet not tested

IPS = ("", "  ", "10.0.0.0/16, !10.0.5.0/24", "!10.0.0.0/8", "192.168.1.*",
       "10.0.0.1-10.0.0.9", "re:^10[.]", "fd00::/16", "*", "fd00::1, 10.0.0.1",
       "!fd00::/16", "2001:db8::1", " 10.0.5.7 ")
IP_VALUES = ("10.0.5.7", "10.0.1.1", "192.168.1.20", "fd00::5", "FD00:0::5", "8.8.8.8",
             "::ffff:10.0.0.1", "10.0.0.5", "2001:0db8::0001")
PORTS = ("", "443", "80, 443", "1000-2000", ">1024", "!53", "<1024, !80", "*", "0",
         "65535", " 443 ")
PORT_VALUES = ("0", "53", "80", "443", "1500", "65535", "1024", "1025")
PROCESSES = ("", "chrome", "chrome, !chromedriver", "re:^py", "1234", ">1000", "*",
             "!chrome", "Chrome.EXE", "*.exe", " chrome ")
# Always with a pid: the owner of a socket always has one, so a name alone is a
# question only the tester can be asked.
OWNERS = (("chrome.exe", "1234"), ("chromedriver.exe", "77"), ("python3", "5000"),
          ("svchost.exe", "999"), ("CHROME.EXE", "4321"), ("chrome", "1001"))

GRID = {"dst_ip": (IPS, IP_VALUES), "block_ip": (IPS, IP_VALUES),
        "dst_port": (PORTS, PORT_VALUES), "block_port": (PORTS, PORT_VALUES),
        "target": (PROCESSES, OWNERS)}


class _Table:
    """One process, owning ``LOCAL_PORT`` - the read surface ``ProcessTargeting`` asks."""

    def __init__(self, pid, name):
        self.pid, self.name = pid, name

    def name_of(self, pid, cheap=False):
        return self.name if pid == self.pid else ""

    def ancestors(self, pid, depth=8):
        return []

    def snapshot(self):
        return {LOCAL_PORT: self.pid}

    def pid_for(self, port):
        return self.pid if port == LOCAL_PORT else None

    def refresh(self, now=None, force=False):
        return False

    def created_of(self, pid):
        return None


class _Engine(BeanCore):
    """The core, with the engine's one hook targeting needs: ``target_for``."""

    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    def target_for(self, matcher):
        return ProcessTargeting(matcher, table=_Table(*self.owner))

    def targeting(self):
        return None


def session_takes(field, expression, value, pid=""):
    """Does a session with ``expression`` in ``field`` aim at, or block, this packet?"""
    owner = (int(pid or 1), value if field == "target" else "other")
    engine = _Engine(owner)
    apply_settings(engine, {**DEFAULT_SETTINGS, field: expression})
    ip = value if field.endswith("_ip") else OTHER_IP
    port = int(value) if field.endswith("_port") else OTHER_PORT
    decision = engine.decide(100, True, LOCAL_PORT, 0.0, random.Random(0), remote_ip=ip,
                             remote_port=port, is_tcp=True)
    return decision.reason == "block" if field.startswith("block") else decision.scoped


def pairs(field):
    expressions, values = GRID[field]
    for expression in expressions:
        for value in values:
            name, pid = value if isinstance(value, tuple) else (value, "")
            yield expression, name, pid


@pytest.fixture(autouse=True)
def _english():
    set_language("en")


def test_the_grid_covers_every_expression_field():
    assert set(GRID) == {field.key for field in expression_fields()}


@pytest.mark.parametrize("field", sorted(GRID))
def test_the_tester_answers_what_a_session_does_with_the_same_value(field):
    differ, verdicts = [], set()
    for expression, value, pid in pairs(field):
        verdict = evaluate(field, expression, value, pid)
        verdicts.add(verdict.state)
        session = session_takes(field, expression, value, pid)
        if (verdict.state == MATCH) != session:
            differ.append(f"{expression!r} with {value!r}/{pid!r}: tester {verdict.state}, "
                          f"session {'takes' if session else 'leaves'} it")
    # Every value in the grid is readable, so every verdict is an answer about the pair,
    # and the grid holds both answers - one that held only "no" would pass a session
    # that takes nothing.
    assert verdicts == {MATCH, NO_MATCH}, verdicts
    assert not differ, f"{len(differ)} disagree:\n" + "\n".join(differ[:12])
