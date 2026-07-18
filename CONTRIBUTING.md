# Contributing to Bean Network Tester

Thanks for your interest! The project is a QA/dev tool that simulates poor
network conditions on Windows (WinDivert), with an engine that is fully
testable on any OS.

## Getting started

```bash
pip install -r requirements-dev.txt
python -m pytest tests            # full suite (no Windows/admin needed)
python smoke_gui.py               # GUI smoke with a fake tkinter
python bean_network_tester.py --simulate --loss 10 --duration 3   # CLI demo
python bean_network_tester.py --doctor                            # environment report
```

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
- Code, comments and docstrings are in **English**.
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

## Pull requests

1. Run `python -m pytest tests` - everything must pass.
2. Add tests for new behavior (see `tests/` for the style).
3. Update both `lang/en.json` and `lang/pl.json` when adding UI texts.
