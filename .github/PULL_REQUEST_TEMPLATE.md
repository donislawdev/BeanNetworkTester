## What and why

<!-- What does this change do, and why? Link any related issue, e.g. "Fixes #123". -->

## Checklist

- [ ] `python -m pytest tests` passes locally.
- [ ] New behaviour has tests (see `tests/` for the style).
- [ ] UI text goes through i18n keys, with **both** `lang/en.json` and `lang/pl.json` updated.
- [ ] User-facing changes noted in `CHANGELOG.md`; technical ones and new tests in `CHANGELOG-INTERNAL.md`, under `[Unreleased]`.
- [ ] Commits follow Conventional Commits (`type(scope): summary`).
- [ ] No version bump - the owner closes a version via `VERSION.txt`.
