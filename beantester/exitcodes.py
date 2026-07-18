"""Process exit codes - the CI/CD contract of the CLI.

A build pipeline can only react to what it can distinguish, so every failure
mode gets its own code instead of the old "0 unless the engine refused to
start" behaviour (a missing scenario file used to end in a green run).

The numbers follow shell convention: 2 is argparse's own "bad usage" code and
128 + N is the code a shell reports for a process killed by signal N.
"""

OK = 0            # the session ran and every check passed
RUNTIME = 1       # the session could not run (no pydivert, driver/engine failure)
USAGE = 2         # bad command line (argparse's own exit code - do not reuse)
CONFIG = 3        # invalid settings: expression, schedule, range, preset, config file
SCENARIO = 4      # the scenario file is missing or malformed
IO = 5            # an artifact could not be written (repro report, saved config)
ASSERTION = 6     # the run finished but a --min-packets / --fail-on-no-traffic check failed
PERMISSION = 7    # Administrator rights are required and missing
INTERRUPTED = 130  # Ctrl+C  (128 + SIGINT)
TERMINATED = 143   # SIGTERM (128 + SIGTERM)

NAMES = {
    OK: "OK",
    RUNTIME: "RUNTIME",
    USAGE: "USAGE",
    CONFIG: "CONFIG",
    SCENARIO: "SCENARIO",
    IO: "IO",
    ASSERTION: "ASSERTION",
    PERMISSION: "PERMISSION",
    INTERRUPTED: "INTERRUPTED",
    TERMINATED: "TERMINATED",
}

# Rendered into --help so the contract is discoverable without the README.
HELP_TABLE = "\n".join(
    ["exit codes:"] +
    [f"  {code:<3} {NAMES[code].lower()}" for code in
     (OK, RUNTIME, USAGE, CONFIG, SCENARIO, IO, ASSERTION, PERMISSION,
      INTERRUPTED, TERMINATED)])


def name_of(code):
    """Machine-readable name of an exit code (used in JSON output)."""
    return NAMES.get(int(code), "UNKNOWN")
