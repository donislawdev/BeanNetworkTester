# Contributing to Bean Network Tester

Thanks for your interest! The project is a QA/dev tool that simulates poor
network conditions on Windows (WinDivert), with an engine that is fully
testable on any OS.

## Getting started

```bash
pip install --require-hashes -r requirements.txt   # runtime, pinned to exact artefacts
pip install -r requirements-dev.txt
pip install --require-hashes -r requirements-lint.txt   # ruff, mypy and diff-cover
pip install -r requirements-scan.txt   # semgrep (Linux and macOS) and pip-audit
python -m pytest tests            # full suite - no Windows, no driver, no admin rights
python smoke_gui.py               # GUI smoke with a fake tkinter
ruff check                        # F and B fail a pull request, S and ASYNC are a report
mypy                              # types, over the package
python bean_network_tester.py --simulate --loss 10 --duration 3   # CLI demo
python bean_network_tester.py --doctor                            # environment report
```

Two checks in `tests/test_cli_runtime.py` assert what the CLI does once it is allowed to
open the driver. On Windows without administrator rights they **skip themselves and say
so** - green still means green. Run the suite from an elevated prompt if you want them
executed; nothing else in it needs special rights.

The shipped build is ONE executable (`BeanNetworkTester.exe`, built from
`BeanNetworkTester.spec`) that serves both the GUI and the CLI: console subsystem,
onedir, `asInvoker`. Do not reintroduce `--noconsole` / `--onefile` / `--uac-admin`
(see the build section of the README for what each of them broke).

## Project layout

- `beantester/` - the package: `core.py` (pure decision pipeline),
  `engine.py` (threads), `settings.py`, `scenario.py`, `presets.py`,
  `filters.py`, `summary.py`, `repro.py`, `cli.py`, `i18n.py`, `gui/`.
- `bean_network_tester.py` - thin launcher kept for backward compatibility.
- `lang/` - translation files; `tests/` - pytest suite.

## Conventions (enforced by tests)

- Everything is named **BeanNetworkTester**; no references to legacy names.
- Code, comments and docstrings are in **English**, and so are commit messages and pull
  request descriptions. This repository is public and its history is permanent: a comment or
  a message cannot be unpublished, because the commit carrying it stays. Keep local paths,
  machine names, addresses and credentials out of all of them. Quote the program - interface
  text, command output, code - and not a person: a sentence from a chat or an issue is
  somebody else's words. CI checks the mechanical half of this on every pull request.
- UI texts appear in code **only as i18n keys** (`lang/<code>.json` holds the
  texts; English is the fallback). Adding a language = adding a JSON file.
- The CLI is always English and logs with the `[bean]` prefix.
- **The CLI is a CI/CD interface**: every outcome has an exit code from
  `beantester/exitcodes.py`, logs go to **stderr**, data goes to **stdout**
  (text or NDJSON). A new failure mode gets a code, a test in
  `tests/test_cli_runtime.py` and a row in the README table.
- **Fail open**: anything that can leave the WinDivert handle open must stop the
  engine instead. Covered by `tests/test_failsafe.py`.
- Presets are ordered best (top) -> worst (bottom).
- Keep `BeanCore.decide()` pure and covered by tests; new mechanisms get a
  numbered spot in the pipeline plus unit tests.
- **New functionality is merged with the test that guards it.** That is the policy, and the
  two bullets above are what it looks like in practice. It is not left to good intentions:
  `tests/test_mutation_registry.py` records which broken behaviour each test is supposed to
  catch, and CI re-breaks them to prove the test actually reddens.

## Pull requests

1. Run `python -m pytest tests` - everything must pass.
2. Run `ruff check` and `mypy` - both are gates on the pull request.
   Semgrep runs in CI and needs no local setup. On Windows it installs but does not
   scan, so run it from WSL if you want it locally.
3. Add tests for new behavior (see `tests/` for the style).
4. Update both `lang/en.json` and `lang/pl.json` when adding UI texts.
