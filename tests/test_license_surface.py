"""The licensing surface: ``--license``, and the texts it must actually find.

Why this file exists (measured 2026-08-01): ``legal.cli_report``, ``license_text``
and ``notices_text`` were called by NO test. What was tested is that ``LICENSE``
and ``THIRD-PARTY-NOTICES.md`` EXIST in the tree (``os.path.exists`` from the repo
root) - but the code reads them through ``resource_path()``, which is a different
resolution, and ``legal._read`` answers an ``OSError`` with an empty string.

So the failure mode was: the files ship, the paths stop resolving (a frozen build,
a renamed constant), ``--license`` prints an empty licence, and the whole suite
stays green. That is an LGPL obligation towards the holder of the BINARY failing
silently - convention 35 calls that a blocker, not a formality.

``--doctor`` had a runtime test; ``--license``, the flag with legal weight, did not.
"""
import io
import json

from beantester import appinfo, exitcodes, legal
from beantester.cli import run_cli
from fakes import check


def cli(argv):
    out, err = io.StringIO(), io.StringIO()
    code = run_cli(argv, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


# -- the texts resolve at run time, not just on disk ------------------------- #


def test_the_licence_and_notices_resolve_through_resource_path():
    """``_read`` swallows an OSError into "", so an unresolvable path is silent."""
    licence = legal.license_text()
    notices = legal.notices_text()
    check("LICENSE is readable through resource_path (not an empty fallback)",
          len(licence) > 1000, f"({len(licence)} chars)")
    check("LICENSE really is the GPL text the project claims",
          "GNU GENERAL PUBLIC LICENSE" in licence)
    check("THIRD-PARTY-NOTICES is readable through resource_path",
          len(notices) > 200, f"({len(notices)} chars)")


def test_every_shipped_component_is_named_with_a_version_and_a_source():
    """The obligation is not "a licence exists" - it is naming the exact version
    the user was given, so they can fetch that source and replace it."""
    rows = legal.component_rows()
    names = [name for name, *_ in rows]
    for required in ("WinDivert", "PyDivert", "psutil", "Python"):
        check(f"{required} is declared", required in names, f"({names})")
    for name, version, licence, url in rows:
        check(f"{name} carries a version", bool(str(version).strip()))
        check(f"{name} carries a licence", bool(str(licence).strip()))
        check(f"{name} carries a source URL", str(url).startswith("http"), f"({url})")


def test_the_report_carries_the_licence_the_components_and_the_no_telemetry_line():
    report = legal.cli_report()
    check("report opens with the licence itself",
          "GNU GENERAL PUBLIC LICENSE" in report)
    for name, version, _lic, url in legal.component_rows():
        check(f"report names {name}", name in report)
        check(f"report names the source of {name}", url in report)
    check("report states there is no telemetry (convention 36)",
          "Telemetry: none" in report, f"({report[-200:]!r})")


# -- the flag ---------------------------------------------------------------- #


def test_license_flag_prints_the_report_to_stdout_and_exits_ok():
    code, out, err = cli(["--license"])
    check("--license exits OK", code == exitcodes.OK, f"(code={code})")
    check("the report goes to STDOUT (it is data, not log)",
          "GNU GENERAL PUBLIC LICENSE" in out, f"({out[:120]!r})")
    check("nothing of it leaks into stderr", "GENERAL PUBLIC" not in err)


def test_license_flag_never_touches_the_driver():
    """A licence audit must work on a machine with no WinDivert and no admin."""
    code, out, _ = cli(["--license"])
    check("--license succeeds without a driver", code == exitcodes.OK)
    check("and without opening a session", "packets" not in out.lower())


def test_license_as_json_is_one_parsable_record_with_every_component():
    """A corporate licence audit is a script more often than a person, so the
    machine-readable shape is part of the NDJSON contract, not a nicety."""
    code, out, _ = cli(["--license", "--format", "json"])
    check("--license --format json exits OK", code == exitcodes.OK, f"(code={code})")
    lines = [l for l in out.splitlines() if l.strip()]
    check("exactly one NDJSON record", len(lines) == 1, f"({len(lines)} lines)")

    record = json.loads(lines[0])
    check("the record names itself", record.get("event") == "license", f"({record.get('event')})")
    check("it carries the project licence",
          record.get("license") == appinfo.LICENSE_NAME, f"({record.get('license')})")
    check("it states no telemetry", record.get("telemetry") is False)

    shipped = {c["name"] for c in record.get("components", [])}
    expected = {name for name, *_ in legal.COMPONENTS}
    check("every component in the registry reaches the JSON", shipped == expected,
          f"(missing={sorted(expected - shipped)}, extra={sorted(shipped - expected)})")
    for component in record["components"]:
        check(f"{component['name']} carries source + licence in JSON",
              component.get("source", "").startswith("http")
              and bool(component.get("license")), f"({component})")
