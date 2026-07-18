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
