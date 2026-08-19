# What a review of this repository has to know

The maintainer's own `CLAUDE.md` is not part of this repository, so a CI runner checks out
a tree without it. This file is the public stand-in: it is copied to `CLAUDE.md` for the
length of a review run. Nothing private belongs here, and nothing in it is new - every rule
below is already stated in `CONTRIBUTING.md` or the READMEs.

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
   `[Unreleased]`, a user-facing entry is capped at 100 words, and `VERSION.txt` is never
   bumped in a pull request.
4. **Never break traffic globally.** A real interception needs a narrow target
   (`--target` / `--dst-ip` / `--dst-port`) and a short `--duration`. `--loss` or `--latency`
   with no target is a defect, not a default.
5. **Fail open.** Anything that could leave the WinDivert handle open must stop the engine
   instead. Traffic is released on failure, never held.
6. **New behaviour arrives with the test that guards it.** A new failure mode gets an exit
   code, a test and a README row. A new mechanism in the decision pipeline gets unit tests.

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

## Where this project's bugs actually come from

This is not a guess. `tests/test_mutation_registry.py` records every behaviour that has been
broken on purpose to prove its test catches it, and the entries cluster. Look here first.

1. 🔴 **A guard that cannot fail.** The single most valuable finding available in this
   repository, and no linter can see it. An assertion that would also pass over an empty
   set, a collector that returns nothing, a walk rooted at a directory that does not exist
   on a runner, a search pattern that quietly stops matching - each looks like coverage and
   is coverage of nothing. **A new test that would still pass with the behaviour removed is
   a finding.** Ask of every added assertion: what input makes this red?
2. **A sentence that stops agreeing with the state it describes.** A note, tooltip, chart
   caption, log line or warning has to be derived from the state, never from a nearby proxy
   that is usually the same. Past defects of exactly this shape: an unbounded run judged
   bounded, a session that becomes unbounded and says nothing, a filter of pure exclusions
   passing as a target. Numbers and the words beside them must come from one source.
3. **Lifecycle and ordering around targeting.** The largest group by far. A socket that
   arrives while a rebuild is in flight, a process adopted and then never re-judged, a
   pending entry nobody drains, a failure on one item that kills the thread handling the
   rest. Any change here deserves the question "what happens if this arrives during that".
4. **Tables and their column registry drifting apart.** A header describing its neighbour
   once a column is hidden, a count that includes hidden columns, a row marked by colour
   alone, a number left touching the text beside it. If a change touches columns, check the
   registry, the header, the tooltip and the export together.
5. **Empty and just-changed states.** An empty table that renders as a blank rectangle, an
   unsearched table blaming a search nobody made. The first and last iteration are where
   this code breaks, not the middle.

Two more things a diff hides:

- **The fake tkinter has blind spots.** The suite drives a stand-in for Tk with one widget
  class, no style validation and no geometry. Changes to styles, geometry or column mapping
  are therefore **not** covered by the tests that appear to cover them, and deserve a closer
  read than their green suite suggests.
- **One platform is not both.** The suite runs on Linux and Windows. A symbol, a keysym or a
  path habit named after one system can raise on the other, and "checked locally" here means
  "checked on Windows".

## What a complete pull request looks like here

The change, the guard that catches its absence, an entry in the mutation registry when it
guards a behaviour, and the changelog lines. **A pull request that adds behaviour with no
guard is itself a finding**, and so is one that changes behaviour without touching the prose
that describes it - the READMEs describe current state, and drift there is invisible.

## What CI already enforces, so a review need not

ruff, mypy, semgrep and CodeQL; a coverage gate on the repository plus 80 percent on the
lines a pull request changes; the mutation registry; a licence gate on new dependencies; a
weekly dependency audit; and a check that commit messages and the pull request body obey
rule 2. Every action is pinned to a commit SHA and no `${{ }}` reaches a `run:` script.

**A finding that repeats one of those is noise.** The valuable finding is the one no gate can
see.

## What not to propose

- **A new dependency.** This project ships a kernel driver and pins its dependencies by
  artefact hash; adding one is a deliberate decision with a licence gate in front of it, not
  a review suggestion.
- **A broad refactor.** Judge the change that is here.
- **Style already settled by the linter**, or anything the section above covers.

## How to write a finding

Say what breaks, with the input or state that breaks it. "This could be clearer" is not a
finding; "with `--duration 0` this loops forever, and no test covers it" is. If a rule above
is broken, name the rule. If nothing is wrong, say so plainly rather than filling the space.
