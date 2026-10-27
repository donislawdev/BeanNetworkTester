"""What this system offers the tools that need an operating system's own API.

The ONE reader of "does this platform have it" for every Tools tab tool and every
row-menu entry whose work is a call only one system makes. Before it, each tool
answered for itself and each answered differently: Adapters, Proxy and TCP health
asked their module's ``supported()`` and carried their own sentence for the answer;
Ping had a ``supported()`` that nothing read, and Reset had none. Measured on Linux
(2026-10-20, Ubuntu 26.04 and WSL, ``internal_tools`` probes ``2026-10-20-linux-gui``):
every ping came back "failed" with code -1, a reset ended in an ``AttributeError``
recorded as a fault, and the Adapters tab was two blank tables - the sentence it had
for this case was never drawn. Each of those is the same defect: a second reader of
one fact, gone stale. The next tool written against a Windows API would have joined
them, and nobody would have seen it before a Linux user did.

So the question is asked here and nowhere else:

* the Tools page builds a tool's panel only when ``why_not(tool.needs)`` is ``None``
  and otherwise one shared "not available on this system" panel
  (``gui/pages/toolbox.py``) - the owner's decision for Linux: a tool the system
  lacks stays VISIBLE and says so;
* a row menu greys out the entry whose tool this system lacks.

The answer comes from the module that holds the API, through its ``supported()``,
looked up at the moment of the question - not stored at import - so a test that
stands a module's ``supported`` in sees the gate follow it, and a new module needs
one line here. ``tests/test_capabilities.py`` holds the other end: every module that
loads a Windows DLL is either named here or listed there with the reason it gates
itself.

``reason`` is an i18n key: Windows only for now. A tool ported to Linux may still be
missing on one system or another, and then its module says why in its own words
(``why_not()``, asked when it is there): Ping, the first one, needs the ping socket
for the user's group or sudo (``icmp.why_not``). Reset on Linux needs a kernel built
with ``CONFIG_INET_DIAG_DESTROY`` (WSL's is not); it has no words of its own, because
its only reader is a row menu, which greys the entry out - the README says why. TCP
health on Linux needs a kernel that lists TCP sockets through sock_diag (every one
measured does); without it the shared words are said.
"""
from types import ModuleType
from typing import NamedTuple, Optional

from . import adapters, icmp, proxy, tcpestats, tcpreset

NOT_HERE = "tools.not_here"


class Capability(NamedTuple):
    name: str
    module: ModuleType      # its supported() answers
    reason: str = NOT_HERE  # i18n key: what a tool without it says


CAPABILITIES = {c.name: c for c in (
    Capability("ping", icmp),
    Capability("adapters", adapters),
    Capability("proxy", proxy),
    Capability("tcp_health", tcpestats),
    Capability("tcp_reset", tcpreset),
)}


def available(name):
    """Does this system offer ``name``? ``""`` - a tool that needs nothing - always does.

    An unknown name raises ``KeyError``: a typo in a registry must not read as "this
    system lacks it", which would hide a tool on every platform without a word.
    """
    if not name:
        return True
    return bool(CAPABILITIES[name].module.supported())


def why_not(name) -> Optional[str]:
    """``None`` when ``name`` is available, else the i18n key of what to say instead:
    the module's own words for this system when it has them, or the shared ones."""
    if available(name):
        return None
    capability = CAPABILITIES[name]
    own = getattr(capability.module, "why_not", None)
    return (own() if own else None) or capability.reason
