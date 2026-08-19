# What a review of this repository has to know

This file is the reviewer's briefing. It is copied to `CLAUDE.md` on the CI runner before
the review runs, because the maintainer's own `CLAUDE.md` is not in the repository - it
lives in a private notes repo and a runner never sees it. Without this file the review
arrives with no idea what this project holds itself to and spends its findings on textbook
advice that is already handled.

Everything below is already visible in `CONTRIBUTING.md` and the READMEs. Nothing private
belongs here: this file is public and permanent, like every other file in a public repo.

## What the tool is

Bean Network Tester simulates poor network conditions on Windows - latency, packet loss,
jitter, bandwidth limits, dropped connections - so a developer can see how their program
behaves on a bad link. It has a GUI and a CLI, and it works by loading the WinDivert kernel
driver and mangling packets in flight.

Two consequences worth carrying into every review:

- **It runs on the machine it is testing.** A change that widens what gets intercepted can
  take the user's own network down with it. Impairment must always be narrow - a target
  process, address or port - and bounded by a duration.
- **It ships a kernel driver to strangers.** Supply chain, signatures and pinned bytes are
  not paperwork here; they are the product.

## Rules that a reviewer should treat as blocking

1. **Flat hyphen only.** No em dash, no en dash, anywhere in the repository - code,
   comments, docs, changelogs. A test enforces it.
2. **Everything in git is English.** Commit messages, pull request titles and bodies. Quote
   the program - interface text, command output, code - and never a person: a sentence from
   a conversation is somebody else's words, and a public commit cannot be unpublished. No
   local paths, machine names, addresses or tokens, in comments either.
3. **Anything visible from outside goes in the changelog.** `CHANGELOG.md` for users,
   `CHANGELOG-INTERNAL.md` for maintainers; a GUI change counts as visible. Entries go under
   `[Unreleased]`, and `VERSION.txt` is never bumped in a pull request.
4. **Never break traffic globally.** A real interception needs a narrow target
   (`--target` / `--dst-ip` / `--dst-port`) and a short `--duration`. `--loss` or `--latency`
   with no target is a defect, not a default.
5. **Fail open.** Anything that could leave the WinDivert handle open must stop the engine
   instead. Traffic is released on failure, never held.
6. **New behaviour arrives with the test that guards it.** A new failure mode gets an exit
   code, a test and a README row. A new mechanism in the decision pipeline gets unit tests.
   A test that cannot fail is worse than no test.

## Contracts that changes must not break silently

- **The CLI is a CI/CD interface.** Every outcome has an exit code from
  `beantester/exitcodes.py`. Logs go to stderr, data goes to stdout, as text or NDJSON.
  Changing a code, a stream or the NDJSON schema is a breaking change.
- **UI text lives in `lang/<code>.json`, never in code.** Code carries i18n keys. A new key
  goes into `lang/en.json` **and** `lang/pl.json` in the same change, or the other language
  falls back silently.
- **`BeanCore.decide()` stays pure.** It is the decision pipeline and it is covered
  position by position.
- **Presets are ordered best at the top, worst at the bottom.**
- **The project website's page addresses are a contract.** The site is published; names on
  its pages come from the language files, not typed by hand.

## What CI already enforces, so a review need not

ruff (bug shapes, dead code, a measured complexity ceiling), mypy, semgrep, CodeQL, a
coverage gate on the whole repository plus 80 percent on the lines a pull request changes,
a mutation registry that re-breaks each guarded behaviour to prove its test reddens, a
licence gate on new dependencies, a weekly dependency audit, and a check that commit
messages and the pull request body obey rule 2. Every action is pinned to a commit SHA and
no `${{ }}` is ever interpolated into a `run:` script.

Findings that repeat one of those are noise. The valuable finding is the one no gate can
see: a wrong answer, a broken edge case, a contract quietly changed, a test that passes for
the wrong reason, a comment that no longer matches the code beneath it.

## How to write a finding here

Say what breaks, with the input or state that breaks it. "This could be clearer" is not a
finding; "with `--duration 0` this loops forever, and no test covers it" is. If a rule above
is broken, name the rule. If nothing is wrong, say so plainly rather than filling the space.
