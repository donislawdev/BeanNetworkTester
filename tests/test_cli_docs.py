"""Docs guard: the README CLI tables must match the real argument parser.

Every ``--flag`` the parser defines has to be documented in BOTH READMEs, and
neither README may list an app ``--flag`` the parser does not have. This is the
cheapest way to stop the CLI reference from drifting as flags come and go: add a
flag to ``cli.py`` without documenting it (or leave a removed one in the README)
and this test goes red.

Flags are read from the parser via AST (the source of truth) and from the
READMEs by taking only backtick-wrapped ``--tokens`` (so link anchors like
``#...--ip--port`` are not mistaken for flags).

``IGNORE`` holds tokens that legitimately appear in the READMEs but are not app
flags: argparse's built-in ``--help`` and the PyInstaller build flags mentioned
in the "Building an .exe" section.
"""
import ast
import os
import re

from fakes import ROOT, check

IGNORE = {"--help", "--noconfirm", "--noconsole", "--onefile", "--uac-admin"}
READMES = ("README.md", "README.pl.md")


def _parser_flags():
    src = open(os.path.join(ROOT, "beantester", "cli.py"), encoding="utf-8").read()
    flags = set()
    for node in ast.walk(ast.parse(src)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"):
            for arg in node.args:
                if (isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                        and arg.value.startswith("--")):
                    flags.add(arg.value)
    return flags


def _documented_flags(readme):
    text = open(os.path.join(ROOT, readme), encoding="utf-8").read()
    return set(re.findall(r"`(--[a-z][a-z0-9-]+)", text))


def test_every_parser_flag_is_documented_in_both_readmes():
    real = _parser_flags()
    for readme in READMES:
        missing = sorted(real - _documented_flags(readme))
        check(f"{readme} documents every CLI flag", not missing,
              f"(undocumented: {missing})")


def test_no_stale_app_flags_in_readmes():
    real = _parser_flags()
    for readme in READMES:
        stale = sorted(_documented_flags(readme) - real - IGNORE)
        check(f"{readme} lists no flag the parser lacks", not stale,
              f"(stale: {stale})")


def test_no_semicolons_in_the_help_a_user_reads():
    """Conventions 1b and 33: people do not write semicolons in ordinary prose.

    ``lang/*.json`` has been guarded since the day 21 tooltips were found to have
    drifted (``test_i18n.py::test_no_semicolons_in_ui_text``). The CLI's help is
    the same kind of prose read by the same kind of person, and nothing looked at
    it - six had accumulated by the time anybody did.

    Read off the PARSER, not off the source: a help string added anywhere, by any
    future refactor, is covered without this test knowing where it was written.
    ``description`` and ``epilog`` come along because they are prose too, and the
    epilog carries the exit-code table users actually script against.

    No exception list. A semicolon is syntax inside a filter expression, a shell
    line or JSON - none of which live in ``help=`` today, and the convention says
    the exception is for code, not for prose ABOUT code. If a help string ever
    genuinely needs one, this test is where that argument gets made.
    """
    import beantester.cli as cli_module
    parser = cli_module.build_arg_parser()
    helps = [a for a in parser._actions if a.help]
    # The canary from test_repo_conventions: a scan that reads nothing satisfies
    # every rule ever written and looks like a guard that works.
    check("CLI help: the scan actually read the parser", len(helps) >= 30,
          f"({len(helps)} help strings)")
    offenders = sorted("/".join(a.option_strings) or a.dest
                       for a in helps if ";" in a.help)
    check(f"CLI help: no semicolons in help= ({len(helps)} read)",
          not offenders, f"({offenders})")
    for name in ("description", "epilog"):
        text = getattr(parser, name, None) or ""
        check(f"CLI help: no semicolons in the parser {name}",
              ";" not in text)


def test_help_opens_with_examples_and_not_with_a_wall_of_usage():
    """clig.dev: show the common cases first, then the reference.

    MEASURED before this: 24 lines of generated usage listing about fifty flags,
    then one sentence, then the flags again in full. The first thing anyone wants
    from a tool that size is a line to copy, and it was below the fold - as was
    the error message on a typo, which argparse prints under the same block.

    Asserts ORDER, not wording: the examples have to arrive before the flag list,
    or this is decoration.
    """
    import beantester.cli as cli_module
    text = cli_module.build_arg_parser().format_help()
    check("--help: has an examples section", "Examples:" in text)
    first_block = text.split("\n\n")[0].splitlines()
    check("--help: the usage block is one line, not fifty flags",
          first_block[0].startswith("usage:") and len(first_block) == 1,
          f"({len(first_block)} lines: {first_block[0]!r})")
    check("--help: examples come before the flag list",
          text.index("Examples:") < text.index("--simulate  "),
          "(the reference is above the worked cases)")
    examples = text.split("Examples:")[1].split("options:")[0]
    for flag in ("--simulate", "--target", "--duration", "--format json"):
        check(f"--help: an example actually uses {flag}", flag in examples)
