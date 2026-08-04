## What and why

<!-- What does this change do, and why? Link any related issue, e.g. "Fixes #123". -->

## Checklist

- [ ] `python -m pytest tests` passes locally.
- [ ] New behaviour has tests (see `tests/` for the style).
- [ ] UI text goes through i18n keys, with **both** `lang/en.json` and `lang/pl.json` updated.
- [ ] User-facing changes noted in `CHANGELOG.md`, under `[Unreleased]`.
- [ ] Commits follow Conventional Commits (`type(scope): summary`).
- [ ] No version bump - the owner closes a version via `VERSION.txt`.
- [ ] **Written for a public audience.** This repository is public, and so is
      everything in it: code comments, commit messages and this description are
      readable by anyone, forever, including in the history after an edit. So:
      English throughout, no local file paths or machine names, no personal data
      of any kind, no credentials, and every comment explains itself rather than
      pointing at a document only the maintainers can open.
- [ ] **Quotes the program, not a person.** Interface text, command output and
      code are evidence and belong here. A sentence from a chat, an email or an
      issue thread is somebody else's words: say what was found, not who said
      it. Translating it first does not change that.
- [ ] Any new dependency, DLL, font or bundled asset has a licence compatible
      with the GPLv3, an entry in `THIRD-PARTY-NOTICES.md`, its full licence text
      in `licenses/` and a row in `beantester/legal.py`.
