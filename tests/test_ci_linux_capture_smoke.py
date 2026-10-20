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
