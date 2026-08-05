"""Files written by RELEASED versions must still open in the version after them.

Why this exists
---------------
`test_settings_config_scenario.py::test_every_file_this_tool_writes_still_loads`
writes with today's code and reads with today's code. Its own docstring says it
"holds by construction today" - and it does, which is why it cannot see the thing
that actually breaks for a user: a file written LAST YEAR, opened by the build
they just installed.

The on-disk formats are named FROZEN contracts in the project notes (profile,
config file, scenario, `*_ui.json`, CSV). Nothing was holding an old file against
a new reader, and this is not a hypothetical class - `ProfileStore._clean`
carries a fix for exactly it: profiles written before `buffer` entered the
profile scope would have been zero-filled, and 0 there means an UNBOUNDED queue,
so the fill would have turned an old profile into the runaway token bucket the
bounded buffer exists to prevent.

The corpus
----------
`tests/data/legacy/<tag>/` holds files produced by CHECKING OUT that release and
running its own writers - not by hand, because the question is what old code
really wrote. Each directory carries a `MANIFEST.json` naming the tag.

Adding a release means adding a directory; this file needs no edit, because
everything below iterates the corpus. That is deliberate: a guard that must be
extended by hand is a guard that stops covering the newest thing first.
"""
import json
import os

from fakes import check

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(HERE, "data", "legacy")


def releases():
    if not os.path.isdir(CORPUS):
        return []
    return sorted(name for name in os.listdir(CORPUS)
                  if os.path.isdir(os.path.join(CORPUS, name)))


def test_the_corpus_is_not_empty():
    """A scanner that finds nothing passes every check it makes.

    The same trap `test_the_repository_scanners_actually_read_files` guards for
    the repo scanners: without this, deleting the corpus would turn every test
    below into a silent pass.
    """
    found = releases()
    check("legacy corpus: at least two released versions are kept",
          len(found) >= 2, "(%s)" % ", ".join(found) or "(empty)")


def test_a_config_file_from_every_release_still_loads():
    """Missing keys must fall back to defaults, not be rejected.

    The loader is deliberately STRICT about a key it does not recognise (a
    misspelled setting is an error, not a silent default). This is the other
    direction, and the one an upgrade actually hits: a file written before a
    setting existed simply does not mention it.
    """
    from beantester import DEFAULT_SETTINGS, load_config_file

    for tag in releases():
        path = os.path.join(CORPUS, tag, "config.json")
        if not os.path.exists(path):
            continue
        loaded = load_config_file(path)
        check("%s: its config file still loads" % tag,
              set(loaded) == set(DEFAULT_SETTINGS),
              "(missing %s, unexpected %s)"
              % (sorted(set(DEFAULT_SETTINGS) - set(loaded)),
                 sorted(set(loaded) - set(DEFAULT_SETTINGS))))
        # The values the user chose must survive, not merely the key set.
        with open(path, encoding="utf-8") as handle:
            written = json.load(handle)
        for key in ("loss", "latency", "down", "dst_ip", "dst_port", "target"):
            if key not in written:
                continue
            # Numbers are normalised on the way in (7 becomes 7.0) and that is
            # the loader working, not drifting - so compare by VALUE, and only
            # fall back to text for the expression fields.
            try:
                same = float(loaded[key]) == float(written[key])
            except (TypeError, ValueError):
                same = str(loaded[key]) == str(written[key])
            check("%s: config keeps %s across the upgrade" % (tag, key), same,
                  "(%r -> %r)" % (written[key], loaded[key]))


def test_a_profile_from_every_release_still_loads_with_its_own_defaults():
    """And an absent field falls back to THAT FIELD'S default, never to zero.

    This is the documented failure: `buffer` defaults to 1000 ms and 0 means an
    unbounded queue, so a blanket zero-fill silently rearms the exact behaviour
    the bounded buffer was added to stop.
    """
    from beantester.fields import PROFILE_FIELDS
    from beantester.gui.profiles import ProfileStore
    from beantester.settings import DEFAULT_SETTINGS

    # PROFILE_FIELDS is a tuple of KEYS, and the defaults live in
    # DEFAULT_SETTINGS - the Field objects do not carry one.
    defaults = {key: DEFAULT_SETTINGS[key] for key in PROFILE_FIELDS
                if key in DEFAULT_SETTINGS}
    for tag in releases():
        path = os.path.join(CORPUS, tag, "profiles.json")
        if not os.path.exists(path):
            continue
        store = ProfileStore(path)
        check("%s: its profiles still load" % tag, bool(store.names()),
              "(%s, problem=%r)" % (sorted(store.names()), store.problem))
        with open(path, encoding="utf-8") as handle:
            written = json.load(handle)
        for name in store.names():
            values = store.get(name)
            absent = [key for key in defaults if key not in written.get(name, {})]
            zeroed = [key for key in absent
                      if key in values and float(values[key]) == 0.0
                      and float(defaults[key]) != 0.0]
            check("%s/%s: a field the file omits keeps its own default"
                  % (tag, name), not zeroed, "(zero-filled: %s)" % zeroed)


def test_a_saved_window_state_from_every_release_still_loads():
    """`*_ui.json` is a frozen format too, and it is the one a user never sees
    until the window opens in the wrong place."""
    from beantester.gui.ui_state import UiStateStore

    for tag in releases():
        path = os.path.join(CORPUS, tag, "ui.json")
        if not os.path.exists(path):
            continue
        store = UiStateStore(path)
        with open(path, encoding="utf-8") as handle:
            written = json.load(handle)
        for key in ("geometry", "page", "language"):
            if key in written:
                check("%s: window state keeps %s" % (tag, key),
                      store.get(key) == written[key],
                      "(%r -> %r)" % (written[key], store.get(key)))


def test_a_repro_command_from_every_release_still_parses():
    """A repro command is what a user pastes from an old bug report.

    It is the one artefact here that travels between PEOPLE, so a flag that
    stopped being accepted breaks somebody else's reproduction, not their own
    settings.
    """
    from beantester.cli import build_arg_parser

    for tag in releases():
        path = os.path.join(CORPUS, tag, "repro-command.txt")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as handle:
            command = handle.read().strip()
        argv = _split_command(command)
        try:
            build_arg_parser().parse_args(argv)
            ok, detail = True, ""
        except SystemExit as exc:
            ok, detail = False, "(argparse rejected it: %s)" % exc
        check("%s: its repro command still parses" % tag, ok, detail)


def _split_command(command):
    """Drop the program name, honour the quoting `settings_to_cli_string` adds."""
    import shlex

    parts = shlex.split(command, posix=False)
    argv = []
    for part in parts[2:] if len(parts) > 1 and parts[0] == "python" else parts[1:]:
        argv.append(part.strip('"'))
    return argv
