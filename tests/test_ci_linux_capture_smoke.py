"""The Linux capture smoke must be able to FAIL - its judges, proven on made-up rounds.

``tools/ci_linux_capture_smoke.py`` runs a real capture only on a Linux runner as
root, so on every other machine nothing would ever show that its verdicts can go
red. Its judges are pure for exactly this: each one here is fed the measurement
of a broken session and must say so, and the clean one must pass.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

import ci_linux_capture_smoke as smoke                    # noqa: E402
from fakes import check                                    # noqa: E402

FAST = [0.2] * 12
HELD = [100.6] * 12


def test_a_session_that_did_its_job_passes():
    check("latency: added where aimed, nowhere else, gone after",
          smoke.judge_latency(FAST, HELD, FAST, FAST) == [])
    check("loss: the target silent, the bystander answering",
          smoke.judge_loss([None] * 6, [0.2] * 6) == [])


def test_every_broken_latency_session_is_named():
    cases = {
        "no latency added": (FAST, FAST, FAST, FAST, "during"),
        "only one direction delayed": (FAST, [50.4] * 12, FAST, FAST, "during"),
        "the bystander delayed too": (FAST, HELD, HELD, FAST, "bystander"),
        "latency left behind": (FAST, HELD, FAST, HELD, "after"),
        "a machine too slow to tell": (HELD, HELD, FAST, FAST, "before"),
        "the target stopped answering": (FAST, [None] * 12, FAST, FAST, "during"),
        "nothing measured at all": (FAST, [], FAST, FAST, "during"),
    }
    for name, (before, during, bystander, after, phase) in cases.items():
        failures = smoke.judge_latency(before, during, bystander, after)
        check(f"{name}: failed, naming {phase}",
              any(f.startswith(phase) for f in failures), f"({failures})")


def test_every_broken_loss_session_is_named():
    check("the target still answering is a failure",
          any("target" in f for f in smoke.judge_loss([0.2] * 6, [0.2] * 6)))
    check("one answer is enough to fail",
          any("target" in f for f in smoke.judge_loss([None] * 5 + [0.2], [0.2] * 6)))
    check("the bystander lost too is a failure",
          any("bystander" in f for f in smoke.judge_loss([None] * 6, [None, 0.2, 0.2, 0.2, 0.2, 0.2])))
    check("no bystander measured is a failure",
          any("bystander" in f for f in smoke.judge_loss([None] * 6, [])))


def ping(kind, rtts):
    return {"kind": kind, "rtts": rtts}


def test_every_broken_ping_through_a_session_is_named():
    fast, held = [0] * 6, [100] * 6
    good = (ping("raw", fast), ping("raw", held), ping("dgram", held), ping("dgram", fast))
    check("both sockets carried the latency, fast around it", smoke.judge_ping(*good) == [])
    cases = {
        "the raw socket never tried (the ping socket refused)":
            ((ping(None, []),) + good[1:], "ping before"),
        "the ping socket never taken once allowed": (good[:2] + (ping("raw", held),) + good[3:],
                                                     "ping dgram"),
        "a ping the session did not reach": (good[:1] + (ping("raw", fast),) + good[2:],
                                             "ping raw"),
        "one direction delayed": (good[:2] + (ping("dgram", [50] * 6),) + good[3:], "ping dgram"),
        "latency left behind": (good[:3] + (ping("dgram", held),), "ping after"),
        "a machine too slow to tell": ((ping("raw", held),) + good[1:], "ping before"),
        "no answers": (good[:1] + (ping("raw", [None] * 6),) + good[2:], "ping raw"),
        "nothing measured": (good[:3] + ({},), "ping after"),
    }
    for name, (got, phase) in cases.items():
        failures = smoke.judge_ping(*got)
        check(f"{name}: failed, naming {phase}", any(f.startswith(phase) for f in failures),
              f"({failures})")


def test_every_broken_reset_is_named():
    plain = {"outcome": "reset", "client": smoke.ECONNABORTED, "far": "reset"}
    impaired = {"outcome": "reset", "client": smoke.ECONNABORTED, "far": "nothing"}
    stale = {"found": 1, "stale": "gone", "listener": "alive"}
    check("a reset that did its job passes", smoke.judge_reset(plain, impaired, stale) == [])
    cases = {
        "nothing reset": ((dict(plain, outcome="gone"), impaired, stale), "plain reset"),
        "the program heard nothing": ((dict(plain, client=None), impaired, stale), "plain reset"),
        "the far end got no reset": ((dict(plain, far="nothing"), impaired, stale), "plain reset"),
        "the reset got through --loss 100": ((plain, dict(impaired, far="reset"), stale),
                                             "reset under loss"),
        "no reset under the session": ((plain, dict(impaired, outcome="failed"), stale),
                                       "reset under loss"),
        "a session that never ran": ((plain, {}, stale), "reset under loss"),
        "the connection not in the list": ((plain, impaired, dict(stale, found=0)), "stale"),
        "a gone connection read as reset": ((plain, impaired, dict(stale, stale="reset")), "stale"),
        "the listener taken": ((plain, impaired, dict(stale, listener="ConnectionRefusedError")),
                               "stale"),
        "nothing measured": ((plain, impaired, {}), "stale"),
    }
    for name, (got, phase) in cases.items():
        failures = smoke.judge_reset(*got)
        check(f"{name}: failed, naming {phase}", any(f.startswith(phase) for f in failures),
              f"({failures})")


def _adapters_seen():
    """What the Adapters phase reads in a namespace that came out right."""
    def link(index, name, state, flags, kind="ether", mac="02:00:00:00:00:0a", mtu=1500):
        return {"ifindex": index, "ifname": name, "operstate": state, "flags": flags,
                "link_type": kind, "address": mac, "mtu": mtu}
    addr = [{"ifname": "lo", "addr_info": [{"local": "127.0.0.1", "prefixlen": 8}]},
            {"ifname": "bntci-d", "addr_info": [
                {"local": smoke.LEASED, "prefixlen": 24, "dynamic": True},
                {"local": smoke.DEPRECATED, "prefixlen": 24, "dynamic": True,
                 "deprecated": True}]},
            {"ifname": "bntci-b", "addr_info": [
                {"local": smoke.DUPLICATE6, "prefixlen": 64, "tentative": True,
                 "dadfailed": True}]},
            # the end that answers for it: in use there (measured on the VM)
            {"ifname": "bntci-a", "addr_info": [{"local": smoke.DUPLICATE6, "prefixlen": 64}]}]
    return {
        "product": [
            {"name": "lo", "index": 1, "status": 1, "mtu": 65536, "mac": "",
             "addresses": [["127.0.0.1", 8, smoke.ORIGIN_WELL_KNOWN, smoke.DAD_PREFERRED]]},
            {"name": "bntci-d", "index": 2, "status": 1, "mtu": 1500, "mac": "02:00:00:00:00:0a",
             "addresses": [[smoke.LEASED, 24, smoke.ORIGIN_DHCP, smoke.DAD_PREFERRED],
                           [smoke.DEPRECATED, 24, smoke.ORIGIN_DHCP, smoke.DAD_DEPRECATED]]},
            {"name": "bntci-b", "index": 3, "status": 1, "mtu": 1500, "mac": "02:00:00:00:00:0a",
             "addresses": [[smoke.DUPLICATE6, 64, 1, smoke.DAD_DUPLICATE]]},
            {"name": "bntci-a", "index": 4, "status": 1, "mtu": 1500, "mac": "02:00:00:00:00:0a",
             "addresses": [[smoke.DUPLICATE6, 64, 1, smoke.DAD_PREFERRED]]}],
        "internet": 2,
        "link": [link(1, "lo", "UNKNOWN", ["LOOPBACK", "UP", "LOWER_UP"], "loopback",
                      "00:00:00:00:00:00", 65536),
                 link(2, "bntci-d", "UNKNOWN", ["BROADCAST", "NOARP", "UP", "LOWER_UP"]),
                 link(3, "bntci-b", "UP", ["BROADCAST", "MULTICAST", "UP", "LOWER_UP"]),
                 link(4, "bntci-a", "UP", ["BROADCAST", "MULTICAST", "UP", "LOWER_UP"])],
        "addr": addr,
        "route": [{"dst": "8.8.8.8", "dev": "bntci-d"}],
    }


def test_every_broken_adapters_reading_is_named():
    from beantester import adapters
    check("the phase's numbers are the module's", (
        smoke.ORIGIN_WELL_KNOWN, smoke.ORIGIN_DHCP, smoke.ORIGIN_ROUTER, smoke.ORIGIN_LEASE,
        smoke.DAD_TENTATIVE, smoke.DAD_DUPLICATE, smoke.DAD_DEPRECATED, smoke.DAD_PREFERRED,
        smoke.STATUS_UP) == (adapters.ORIGIN_WELL_KNOWN, adapters.ORIGIN_DHCP,
                             adapters.ORIGIN_ROUTER, adapters.LEASE, adapters.DAD_TENTATIVE,
                             adapters.DAD_DUPLICATE, adapters.DAD_DEPRECATED,
                             adapters.DAD_PREFERRED, adapters.STATUS_UP))
    seen = _adapters_seen()
    check("a reading that matches ip passes",
          smoke.judge_adapters(seen, "here", states=True) == [], f"({smoke.judge_adapters(seen, 'here', states=True)})")

    def broken(change):
        copy = _adapters_seen()
        change(copy)
        return smoke.judge_adapters(copy, "here", states=True)
    product = lambda s, name: next(a for a in s["product"] if a["name"] == name)  # noqa: E731
    cases = {
        "an adapter missing": lambda s: s["product"].pop(),
        "a wrong MTU": lambda s: product(s, "lo").update(mtu=1500),
        "a MAC written another way": lambda s: product(s, "bntci-b").update(
            mac="02-00-00-00-00-0A"),
        "UNKNOWN with its link read as down": lambda s: product(s, "bntci-d").update(status=4),
        "an address missing": lambda s: product(s, "lo").update(addresses=[]),
        "a duplicate read as in use": lambda s: product(s, "bntci-b")["addresses"][0].__setitem__(
            3, smoke.DAD_PREFERRED),
        "a lease read as set by hand": lambda s: product(s, "bntci-d")["addresses"][0].__setitem__(
            2, 1),
        "the wrong way out": lambda s: s.update(internet=3),
        "nothing listed": lambda s: s.update(product=[]),
    }
    for name, change in cases.items():
        failures = broken(change)
        check(f"{name}: failed, naming the adapters", any(f.startswith("adapters here")
                                                         for f in failures), f"({failures})")
    other = _adapters_seen()
    product(other, "lo")["addresses"][0][3] = smoke.DAD_DEPRECATED
    check("a DAD state ip does not show, on a machine with no states required",
          any("DAD state" in f for f in smoke.judge_adapters(other, "here")),
          f"({smoke.judge_adapters(other, 'here')})")
    calm = _adapters_seen()
    product(calm, "bntci-b")["addresses"][0][3] = smoke.DAD_PREFERRED
    calm["addr"][2]["addr_info"][0] = {"local": smoke.DUPLICATE6, "prefixlen": 64}
    check("without the states the namespace was given, the phase cannot pass",
          any("not seen as a duplicate" in f
              for f in smoke.judge_adapters(calm, "here", states=True)))
    check("on this machine as it is, no state is required",
          smoke.judge_adapters(calm, "here") == [])


def test_a_machine_that_cannot_run_it_skips_and_ci_turns_that_into_a_failure(capsys):
    check("not Linux", smoke.skip_reason("win32", 0, True) == "not Linux")
    check("not root", "root" in smoke.skip_reason("linux", 1000, True))
    check("no library", "libebpfdivert" in smoke.skip_reason("linux", 0, False))
    check("a ready machine runs it", smoke.skip_reason("linux", 0, True) is None)
    check("a skip exits 0", smoke.main([], environment=("linux", 1000, True)) == 0)
    check("and says SKIP out loud", "SKIP" in capsys.readouterr().out)
    check("--require: the same machine is a failure",
          smoke.main(["--require"], environment=("linux", 1000, True)) == 1)
    check("and says FAIL", "FAIL" in capsys.readouterr().out)
