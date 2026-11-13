"""What a traffic filter lets through, what a setting needs, and the line between them.

The traffic filter runs IN THE DRIVER, so a setting that needs traffic the filter
leaves out never sees a packet - "SYN drop" with "UDP only", "Download" with
"Outbound only", a port with "ICMP only". Two declarations answer it
(``filters.FILTER_ADMITS`` and ``fields.Field.needs``) and
``settings.settings_the_filter_leaves_out`` reads them.

Each half has its own guard, and neither is the code checked against itself:

* the filter declarations against the capture driver's OWN evaluator (Windows and
  Linux), with canaries that prove the comparison can fail;
* the field declarations against a hand table of cases, each one read off the gate
  in ``BeanCore.decide`` that the field is named after - with the silent cases next
  to the speaking ones, so neither "always" nor "never" passes.
"""
import itertools

from beantester import fields as F
from beantester.filters import (FILTER_ADMITS, FILTER_DEFS, ICMP, INBOUND, LOOPBACK,
                                NETWORK, OUTBOUND, PORTS, TCP, TRAITS, UDP, Admits,
                                i18n_key_for)
from beantester.i18n import T, field_name, section_name, set_language
from beantester.settings import DEFAULT_SETTINGS, settings_the_filter_leaves_out
from fakes import LANGS, check
from filter_oracle import PACKETS, evaluator

SETTING = "log.filter_skips_setting"
SCOPE = "log.filter_skips_scope"
NEEDING = tuple(f.key for f in F.FIELD_DEFS if f.needs)


def _leaves_out(filt, **settings):
    return settings_the_filter_leaves_out(dict(DEFAULT_SETTINGS, filter=filt, **settings))


# -- the filter half ------------------------------------------------------------ #
def test_every_filter_says_what_it_lets_through_and_every_need_is_a_trait():
    check("FILTER_ADMITS covers exactly the filters of FILTER_DEFS",
          set(FILTER_ADMITS) == {key for key, _, _ in FILTER_DEFS},
          f"({sorted(set(FILTER_ADMITS) ^ {key for key, _, _ in FILTER_DEFS})})")
    for key, admits in FILTER_ADMITS.items():
        check(f"filter {key!r} lets something through on every axis",
              all(admits), f"({admits})")
    for f in F.FIELD_DEFS:
        check(f"{f.key}: every need is a known trait", set(f.needs) <= TRAITS,
              f"({f.needs})")


def _views(admits):
    """The (protocol, direction, path) views a declaration promises: its product."""
    return set(itertools.product(admits.protocols, admits.directions, admits.paths))


def _admitted(evaluates, expression):
    """The (protocol, direction, path) views the driver's evaluator admits.

    Each view is asked for an IPv4 and an IPv6 packet, and both must agree: every
    filter here covers both families (tests/test_ip_family_default.py). A view the
    two answer differently comes back marked, so it can never pass for agreement.
    """
    views = set()
    for protocol, direction, path in itertools.product(
            (TCP, UDP, ICMP), (OUTBOUND, INBOUND), (NETWORK, LOOPBACK)):
        bits = (int(direction == OUTBOUND), int(path == LOOPBACK))
        answers = {evaluates(expression, raw, *bits)
                   for p, raw in PACKETS if p == protocol}
        if answers == {True}:
            views.add((protocol, direction, path))
        elif answers != {False}:
            views.add((protocol + ": one family only", direction, path))
    return views


def test_each_declaration_is_exactly_what_the_driver_admits():
    """The declaration may not promise a view the driver drops, nor leave out one
    it takes - asked of the driver's own evaluator, on the platform's own driver.

    Canaries first, so a broken evaluator or a comparison that cannot fail does not
    pass for agreement: ``false`` admits nothing, ``true`` admits all twelve views,
    and a declaration with TCP and UDP swapped must be caught.
    """
    evaluates = evaluator()
    expressions = {key: expression for key, _, expression in FILTER_DEFS}
    everything = Admits(frozenset({TCP, UDP, ICMP}), frozenset({INBOUND, OUTBOUND}),
                        frozenset({LOOPBACK, NETWORK}))
    check("canary: 'false' admits nothing", _admitted(evaluates, "false") == set())
    check("canary: 'true' admits all twelve views",
          _admitted(evaluates, "true") == _views(everything))
    wrong = FILTER_ADMITS["tcp"]._replace(protocols=frozenset({UDP}))
    check("canary: a declaration with TCP and UDP swapped is caught",
          _admitted(evaluates, expressions["tcp"]) != _views(wrong))

    for key, expression in expressions.items():
        got = _admitted(evaluates, expression)
        want = _views(FILTER_ADMITS[key])
        check(f"filter {key!r}: the declaration is what the driver admits",
              got == want, f"(driver only: {sorted(got - want)}, "
                           f"declared only: {sorted(want - got)})")


# -- the field half ------------------------------------------------------------- #
# Each row: (filter, settings) -> what it must say. Read off decide(), not off the
# declarations: the gate is named beside each group.
CASES = (
    # step 7: only TCP has a SYN
    (("udp", dict(syn_drop=50)), [(SETTING, TCP, ("syn_drop",))]),
    (("tcp", dict(syn_drop=50)), []),
    # step 4 runs only for TCP
    (("udp", dict(rst_prob=10)), [(SETTING, TCP, ("rst_prob",))]),
    (("out", dict(rst_prob=10)), []),
    # step 2 asks the port expression about a portless packet: "443" and "*" turn
    # it away, "!53" lets it through; one that does not compile says nothing
    (("ping", dict(dst_port="443")), [(SCOPE, PORTS, ("dst_port",))]),
    (("ping", dict(dst_port="*")), [(SCOPE, PORTS, ("dst_port",))]),
    (("ping", dict(dst_port="!53")), []),
    (("ping", dict(dst_port="abc")), []),
    (("tcp", dict(dst_port="443")), []),
    # step 2c, the same question; the block by address works on ICMP
    (("ping", dict(block_ip="10.0.0.1", block_port="80")),
     [(SETTING, PORTS, ("block_port",))]),
    # step 1 finds a process by its port, before any expression is asked
    (("ping", dict(target="app.exe")), [(SCOPE, PORTS, ("target",))]),
    # step 2: TCP is never part of a call, payload sizes are per protocol
    (("tcp", dict(call_media=True, payload_udp=">=0", payload_tcp="!0")),
     [(SCOPE, UDP, ("call_media", "payload_udp"))]),
    (("udp", dict(payload_tcp="0")), [(SCOPE, TCP, ("payload_tcp",))]),
    (("ping", dict(call_checks=True, call_turn_control=True)),
     [(SCOPE, UDP, ("call_checks", "call_turn_control"))]),
    # step 11: download is what comes in, upload what goes out; step 3 drops only
    # what comes in, on a flow keyed by its ports
    (("out", dict(down=100, up=100, nat_timeout=30)),
     [(SETTING, INBOUND, ("down", "nat_timeout"))]),
    (("in", dict(up=100)), [(SETTING, OUTBOUND, ("up",))]),
    (("ping", dict(nat_timeout=30)), [(SETTING, PORTS, ("nat_timeout",))]),
    # a schedule makes Download inert already, and the form says so
    (("out", dict(down=100, rate_schedule="5:100:100")), []),
    # step 2c answers only an outgoing TCP packet, and only with a block armed
    (("in", dict(block_ip="10.0.0.1", block_reject=True)),
     [(SETTING, OUTBOUND, ("block_reject",))]),
    (("udp", dict(block_ip="10.0.0.1", block_reject=True)),
     [(SETTING, TCP, ("block_reject",))]),
    (("udp", dict(block_reject=True)), []),
    # the block is ONE gate, armed by either expression (fields.GATE_ARMED_BY)
    (("udp", dict(block_port="80", block_reject=True)),
     [(SETTING, TCP, ("block_reject",))]),
    # step 2b: loopback survives both switches
    (("loopback", dict(lan_mode=True, internet_only=True)),
     [(SETTING, NETWORK, ("lan_mode", "internet_only"))]),
    (("no-loopback", dict(lan_mode=True)), []),
    # every loopback packet arrives as outbound - log.loopback_all_upload says that,
    # and a second line about the same thing would be noise
    (("loopback", dict(down=100, nat_timeout=5, target="app.exe")), []),
    # two kinds of sentence, in registry order
    (("ping", dict(dst_port="443", syn_drop=5, rst_prob=5)),
     [(SCOPE, PORTS, ("dst_port",)), (SETTING, TCP, ("syn_drop", "rst_prob"))]),
    # a filter this does not know is validation's business
    (("bogus", dict(syn_drop=50)), []),
)


def test_each_case_says_exactly_what_its_gate_in_decide_implies():
    for (filt, settings), want in CASES:
        got = _leaves_out(filt, **settings)
        check(f"{filt} {settings}: says {want}", got == want, f"(got {got})")


def test_every_field_with_needs_has_a_case_that_speaks():
    spoken = {key for _, want in CASES for _, _, keys in want for key in keys}
    check("each field that declares needs is named by at least one case",
          set(NEEDING) <= spoken, f"(missing: {sorted(set(NEEDING) - spoken)})")


# One value that puts each field in play, with what it waits on.
IN_PLAY = dict(syn_drop=1, rst_prob=1, nat_timeout=1, down=1, up=1, lan_mode=True,
               internet_only=True, target="app.exe", dst_port="443", block_port="443",
               block_reject=True, call_checks=True, call_turn_control=True,
               call_media=True, payload_udp=">=0", payload_tcp=">=0")
WAITS_ON = dict(block_reject=dict(block_ip="10.0.0.1"))


def test_every_filter_and_every_field_speak_exactly_when_a_need_is_left_out():
    """The machinery over every pair, read from the declarations: a field is named
    once when the filter leaves out one of its needs, and never otherwise.

    The CONTENT of the declarations is held by the two tests above; this one holds
    the gating and the grouping to them on all 8 x 16 pairs, which a hand table
    would not reach. "All traffic" and "All traffic except loopback" must therefore
    be silent on every field.
    """
    check("IN_PLAY covers every field that declares needs",
          set(IN_PLAY) == set(NEEDING), f"({sorted(set(IN_PLAY) ^ set(NEEDING))})")
    for filt, admits in FILTER_ADMITS.items():
        for key in NEEDING:
            got = _leaves_out(filt, **{key: IN_PLAY[key]}, **WAITS_ON.get(key, {}))
            named = [entry for entry in got if key in entry[2]]
            starved = [n for n in F.FIELDS[key].needs if not admits.lets_through(n)]
            check(f"{filt} + {key}: named iff a need is left out",
                  len(named) == (1 if starved else 0), f"(got {got})")
            if starved:
                check(f"{filt} + {key}: for the FIRST need left out",
                      named[0][1] == starved[0], f"(got {named[0]})")
    for filt in ("both", "no-loopback"):
        check(f"{filt}: silent with every field in play at once",
              _leaves_out(filt, **IN_PLAY, block_ip="10.0.0.1") == [])


def test_a_scenario_step_cannot_swap_the_filter_the_session_started_with():
    """A step naming another filter is ignored (the loader says so), and the lines
    must describe the filter the driver opened, not the one in the step."""
    from beantester import Scenario
    sc = Scenario([{"at": 0, "settings": {"filter": "udp", "syn_drop": 10}}])
    started_both = sc.settings_at(1, dict(DEFAULT_SETTINGS, filter="both"))
    check("started on 'both': the step's 'udp' leaves SYN drop nothing - not said",
          settings_the_filter_leaves_out(started_both) == [],
          f"({settings_the_filter_leaves_out(started_both)})")
    started_udp = sc.settings_at(1, dict(DEFAULT_SETTINGS, filter="udp"))
    check("started on 'udp': SYN drop from the step is named",
          settings_the_filter_leaves_out(started_udp) == [(SETTING, TCP, ("syn_drop",))],
          f"({settings_the_filter_leaves_out(started_udp)})")


# -- what a person reads ---------------------------------------------------------- #
def test_the_lines_reach_the_log_in_every_language():
    """Wired into apply_settings, and readable: every placeholder filled, the
    filter by the name on its dropdown, each field with the section it sits in."""
    from beantester import BeanEngine, apply_settings
    settings = dict(DEFAULT_SETTINGS, filter="ping", dst_port="443", syn_drop=5)
    for lang in LANGS:
        set_language(lang)
        said = []
        apply_settings(BeanEngine(), settings, said.append)
        lines = [line for line in said if T(i18n_key_for("ping")) in line]
        check(f"{lang}: two lines, one per sentence", len(lines) == 2, f"({said})")
        for line in lines:
            check(f"{lang}: no placeholder left", "{" not in line, f"({line})")
        for key, line in (("dst_port", lines[0]), ("syn_drop", lines[1])):
            field = F.FIELDS[key]
            check(f"{lang}: {key} named with its section",
                  field_name(field.label) in line
                  and section_name(F.SECTION_BY_ID[field.section].label) in line,
                  f"({line})")
        check(f"{lang}: the ports reason is given",
              T("filters.lacks_ports") in lines[0], f"({lines[0]})")


def test_every_need_a_field_declares_has_its_words_in_every_language():
    used = {need for f in F.FIELD_DEFS for need in f.needs}
    for lang in LANGS:
        set_language(lang)
        missing = [n for n in used if T("filters.lacks_" + n) == "filters.lacks_" + n]
        check(f"{lang}: a text for every need", not missing, f"({missing})")


def test_the_default_filter_is_still_the_first_and_the_new_one_sits_next_to_it():
    keys = [key for key, _, _ in FILTER_DEFS]
    check("'both' stays the default", keys[0] == "both" == DEFAULT_SETTINGS["filter"])
    check("'no-loopback' is second, beside it", keys[1] == "no-loopback", f"({keys})")
