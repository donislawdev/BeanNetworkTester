# Internal changelog

Technical, developer-facing history for Bean Network Tester. This file is NOT shipped to
users - the user-facing log is `CHANGELOG.md`. Keep entries technical: which
modules/registries were touched, decisions, format migrations, CI changes, and NEW TESTS.
This is the one place we record added tests (file/test name + what it guards). Entries may
reference conventions (for example "convention 24") and code symbols.

The format follows [Keep a Changelog](https://keepachangelog.com/); versions follow SemVer.
Entries go under `[Unreleased]`; the owner closes a version by setting `VERSION.txt` (never
bump the version here). Plain hyphen only, no em/en dashes (convention 33).

Breaking changes must be visible at a glance: a change that breaks a public contract (CLI
flags, exit codes, the NDJSON schema, on-disk file formats, or the facade's public API) gets
a `### BREAKING` section placed FIRST in that version, and each such line is prefixed with
`**BREAKING:**`. A breaking change also requires a version bump by the owner (convention 34).

## [0.3.0]

### GUI fix: a widened throughput chart crept into its new window instead of filling it

- **`App._reconcile_chart_len` now zero-pads when GROWING** (new `App._resized_hist(hist, n)`).
  Two paths build the history and only one padded: `__init__` creates
  `deque([0] * n, maxlen=n)`, while the reconcile did `deque(hist, maxlen=n)` - correct when
  shrinking (the deque drops the oldest itself), but on a grow it left `len` at the OLD value
  and only raised `maxlen`.
- **Why it was visible:** `chart.draw_throughput_chart` labels the X axis from
  `len(down_hist) * sample_interval_s`, so raising `chart_seconds` from ~20 s to 250 s left the
  axis reading "-28 s" and counting up one sample per `TICK_MS`, ~4 minutes to fill, while
  `stats._throughput_title` reads the preference directly and said 250 immediately - breaking
  the invariant its own docstring promises ("never drifts from the live X-axis label"). The
  series is also drawn across the full plot width (`x = i / (len - 1)`), so the horizontal
  scale crept with every tick. `chart.py` and `stats.py` are unchanged: with `len == maxlen`
  restored as an invariant, both are already right.
- Tests: `test_prefs.py::test_a_resized_chart_spans_its_whole_window_at_once` (len matches the
  window after growing AND shrinking, newest sample stays newest, padding lands on the left).
  Verified to fail on the pre-fix code with `(171, 357)`. The existing
  `test_chart_history_length_follows_the_preference` asserted `maxlen` only, which was correct
  throughout - the bug lived in `len`, which is what the axis is computed from.

### GUI: dark mode for the parts Windows draws itself (system menu, menu frames)

- **New `theme.apply_dark_app_mode()`**, called once from the top of
  `theme.apply_dark_titlebar` (module flag `_app_mode_applied`, one attempt per process).
  Piggy-backed there deliberately: `App`, every `PanelWindow` in the registry and `dialogs.py`
  already call `apply_dark_titlebar`, so no window can ask for a dark frame and still get a
  white system menu - and no caller needed changing.
- **Why a second mechanism at all:** `DWMWA_USE_IMMERSIVE_DARK_MODE` is a PER-WINDOW attribute
  and only covers the DWM-drawn frame. The system menu (title-bar icon / Alt+Space) and the
  frame user32 puts around a classic `tk.Menu` popup follow a PROCESS-WIDE flag in undocumented
  `uxtheme` exports instead, which nothing in the package was setting - so every window had a
  white system menu, and the Connections context menu kept the light rim noted in convention 41
  ("Tk reaches the entries but not the system-drawn frame").
- **Implementation:** `uxtheme` ordinals 135 (`SetPreferredAppMode`, `AllowDarkModeForApp` on
  1809) and 136 (`FlushMenuThemes`). `ForceDark` (2), not `AllowDark` (1): the UI is dark
  unconditionally, so following the system theme would leave a light menu for a user running
  Windows in light mode. The flush is required - the menu theme is cached per process and is
  already light by the time we get here. Gated on `sys.getwindowsversion().build >= 17763`
  (first build with these exports), wrapped in `crashlog.note` (convention 30): the exports are
  undocumented, and the worst case on failure is the light menu we had before.
- Side effect, accepted by the owner: the native `filedialog` pickers render dark now. They stay
  native on purpose (see the `dialogs.py` docstring) and dark is the consistent look.
- **No test guard.** This is pixels painted by the OS outside the widget tree - the tkinter
  fake cannot observe it and `tools/ci_gui_render.py` only sees the client area. Verified by
  render on Windows 11 build 26200 (convention 41: check live, not from the code).

### GUI fixes: truncated About text, a button left highlighted, and a render check that lied

- **`panels/about.py` uses `labels.wrapping_label` for every prose line** (author, copyright,
  licence, licence terms, the no-telemetry line, the third-party heading). A plain `ttk.Label`
  never wraps - it is CUT at the frame edge - and the helper written for exactly this was not
  being used here. `pad` is `2 * 12 + 16`: the `padx` on both sides plus the few pixels a wrapped
  `ttk.Label` requests on top of its `wraplength` (measured against the render check, not
  guessed - at `pad=30` the widest wrapped line still overhung by 12 px).
- **`App._release_focus()`, called from `App.open_window`.** ttk gives a button keyboard focus
  when it is clicked and `theme.py` paints `focus` exactly like `active` (both -> `BTN_HOVER` +
  `ACC` border), so closing a window handed focus back to the button that opened it and it kept
  looking hovered. Focus goes to the toplevel instead, and the invoking widget's `active`/`focus`
  flags are cleared - the same remedy `theme.unhighlight_combobox` applies to a readonly combobox.
- **`tools/ci_gui_render.py` now FAILS on a truncated label** instead of filing every clipped
  label under "it probably wraps". The split is `wraplength > 0` -> note (it re-wraps), no
  `wraplength` -> `TRUNCATED LABEL`, which is a real defect. This check had been printing the two
  About lines as harmless notes for as long as they had been broken.
- **The render check also opens EVERY window in the `WINDOWS` registry** (it only ever opened
  About), and runs against an **empty user state** - `UiStateStore`/`ProfileStore` are pointed at
  a temp dir like `tests/gui_harness.py` does. It was reading the developer's own
  `bean_network_tester_ui.json`, so the `--lang en` pass rendered whatever language that file
  remembered (the "en" run was reporting Polish strings), and a saved geometry could have hidden
  the very clipping the check exists to find.
- **`tests/fake_tk.py`** models keyboard focus (`FOCUS`, `focus_set`/`focus_get`) and ttk state
  flags (`W.states`, `state(["!active"])` sets/clears; `Root.state()` still answers `"normal"`,
  since a toplevel's `state()` is the window state, not ttk flags).
- **Tests:** `tests/test_windows.py::test_opening_a_window_takes_the_highlight_off_the_button_that_opened_it`
  and `::test_every_prose_label_in_the_about_window_can_wrap`. Both were confirmed to fail against
  the pre-fix code, and the render check was confirmed to report `2 truncated label(s)` on it.

### GUI: focus is a ring, hover is a fill (they used to be the same picture)

- **`gui/theme.py`: every `("focus", <colour>)` entry that duplicated the style's `("active",
  <colour>)` is gone** (`TButton`, `Accent`, `Stop`, `Dirty`, `Help`, `Donate`, `Section`,
  `Gear`). Hover keeps the fill; focus is drawn by clam's **`Button.focus` element** through
  `focuscolor` (`focusthickness=1`, `focussolid=True` on `TButton`, inherited by the derived
  styles; the coloured buttons keep their own ink colour, because an accent ring on an
  accent-blue button is invisible). Measured, not assumed: at thickness 1 the ring costs no
  space (a button is 82x31 either way) and at 3 it grows to 86x35 - which is why this one
  number is not `scaled()`.
- **`tools/ci_gui_render.py` fails when a style paints `focus` and `active` the same.** The
  styles it checks come from two places, neither hand-kept: the widgets actually on screen, plus
  every name `theme.py` configures or maps (regex over the module source) - `Stop.TButton` only
  exists while a capture runs and `Dirty.TButton` only while the form is dirty, so a screen walk
  alone missed exactly the styles nobody looks at. Against the pre-fix theme it reports all 8
  offending styles; after the fix, none.
- Theme module docstring gained the rule as a third invariant, next to "no hard pixels" and
  "a disabled widget must look disabled". This is the other half of the "button left
  highlighted" fix above: that one stops focus LANDING on the button, this one stops focus from
  being painted as hover in the first place.

### GUI fix: a tooltip covered the whole row, not the text

- **A tooltip belongs to a WIDGET, so a label packed `fill`/`expand` shows its bubble over the
  blank space next to the sentence.** Measured on real Tk at 1366x768: `App.summary` was **508 px
  wider and 17 px taller than its own text** (it filled the fixed-height summary strip), so the
  bubble fired over empty header background nowhere near the line it explains. Same shape, smaller
  numbers, on the two `wrapping_label` scope notes (`pages/stats.py` 118 px, `pages/conns.py`).
- **Fix:** pack them to their content - `App.summary` -> `side="left", anchor="nw"`, both scope
  notes -> `anchor="w"` instead of `fill="x"`. A `wrapping_label` does NOT need `fill` to wrap:
  `labels.bind_wraplength` follows the PARENT's `<Configure>`, so the wrap width is unchanged.
- **Test:** `tests/test_gui_layout.py::test_a_tooltip_never_covers_empty_space` - walks all three
  pages and fails on any LEAF widget that has a tooltip, carries `text`, no `command`, and is
  packed with `fill`/`expand`. Containers are exempt on purpose (a stat tile or a `LabelFrame`
  with a tooltip does answer for everything inside it), and so are entries/comboboxes/buttons,
  where the whole box is the control. Confirmed to report all three offenders before the fix.

### GUI: the profile picker is a ttk.Combobox again (convention 41)

- **`gui/pages/control.py::_build_profiles`: `ttk.Menubutton` + `tk.Menu` -> `ttk.Combobox`**
  (readonly, no named style - the shared `TCombobox` look), bound to
  `App.on_profile_selected` (`unhighlight_combobox` + `load_selected_profile`), i.e. exactly
  how the traffic filter is built in `form.py`. The menu was introduced so group headings
  could be rendered non-pickable, but the headings had already been dropped from the menu, so
  all it still bought was a dropdown that could not be made to match: **on Windows a `tk.Menu`
  is a native Win32 popup**, so its frame (a light system border), its width (no `-width`
  option, so it is sized to the longest label instead of to the button) and the highlight on
  the current entry are outside Tk's reach - no amount of styling closes that gap.
- **Group headings dropped entirely** (owner's decision, convention 41: every row in a list
  must DO something). `App.profile_names()` is now `presets + own profiles`, full stop;
  `App._profile_separators` and the snap-back branch in `App.load_selected_profile` are gone,
  `_is_reserved_profile_name` is down to the preset check (a user profile may now be called
  "Presets"), and the `profiles.presets_separator` / `profiles.mine_separator` keys are
  deleted from `lang/en.json` + `lang/pl.json`. `smoke_gui.py`'s separator check is replaced
  by one asserting the picker offers presets then own profiles and nothing else.
- **Removed:** `App._rebuild_profile_menu`, `App._post_profile_menu` (a workaround for the
  Menubutton's post-on-mouse-down toggle - a combobox has no such problem), the
  `App.profile_menu` attribute, the `Profile.TMenubutton` layout/configure/map and the bare
  `TMenubutton` styles in `gui/theme.py`, and the `like_combobox` parameter of
  `theme.style_menu` (context menus were its only other caller). `App.profile_mb` ->
  `App.profile_cb`.
- **`theme.popdown_height(values)`** (+ `POPDOWN_ROWS = 20`) is now the single source for the
  "a list that fits must not spawn the popdown scrollbar" rule, used by the profile picker,
  the traffic filter (`form.py`) and the language box (`panels/settings.py`), which each had
  their own `height=len(...)`. The profile list is the only one the user can grow without
  limit, hence the cap at ttk's own default rather than a dropdown taller than the screen.
  `App._sync_profile_widgets` now refills `values=`/`height=` instead of rebuilding a menu.
- **Tests:** `test_gui_release_fixes.py::test_profile_menu_has_no_indicator_gutter` and
  `::test_profile_picker_uses_the_combobox_field_style` (both about the retired Menubutton)
  replaced by `::test_profile_picker_is_the_same_widget_as_the_traffic_filter`, which checks
  the built widget (readonly, no style override, `values` == `profile_names()`, `height` ==
  item count) AND greps `gui/pages/control.py` for `Menubutton`/`tk.Menu(`, so the imitation
  cannot come back.
- **PROJECT_NOTES convention 41** rewritten with two lessons: same role -> same widget (do not
  imitate a sibling widget with styles - the imitation has a ceiling that is invisible in the
  code), and every row in a list must do something. The stale "405 keys per lang file" figure
  in the repo-structure section (really 465) was replaced by the command that counts them -
  a number copied out of its source file drifts, which is exactly what convention "one fact,
  one source" is about.

### GUI fix: "restore the last profile" ignored the user's own profiles

- **`App._set_profile_key(key)` is now the single writer of `_profile_key`** (`gui/app.py`).
  Three paths change the current profile - `select_profile`, `save_profile`, `delete_profile` -
  but only the first also wrote `ui["profile"]`, the key the `restore_profile` preference reads
  on startup. Since **saving** is how a user ends up on their own profile, the preference
  restored the preset picked before the save; picking an own profile from the list already
  worked, which is why this looked like "it does not work for custom profiles". `delete_profile`
  now remembers the fallback (`DEFAULT_PROFILE`) instead of the deleted name.
- **The key is persisted on the spot** (`ui.persist()` inside `_set_profile_key`), the rule
  `set_pref` already follows: a deliberate user choice must survive an unclean exit, unlike
  session state written in `on_close`. One small atomic write per profile change.
- **`App.__init__` keeps a plain `self._profile_key = DEFAULT_PROFILE`** (commented): routing it
  through `_set_profile_key` would write the default into `ui.json` before
  `_restore_last_profile` reads the remembered one.
- **`_restore_last_profile` clears a dead pointer**: a name that resolves to neither a preset nor
  a stored profile (deleted by hand, `profiles.json` quarantined as corrupt, removed by another
  instance) is still ignored without an error, but `ui["profile"]` is reset so the file stops
  carrying a ghost.
- **Test:** `tests/test_prefs.py::test_restore_last_profile_covers_the_users_own_profiles` -
  save remembers, delete falls back, a vanished profile is ignored AND forgotten.

### Docs: intro wording and third-party links

- **README intro (EN + PL)** reworded: leads with the product name (branding + the auto-snippet),
  compares to Clumsy/NetLimiter by what the tool *does* rather than by the driver - NetLimiter does
  not use WinDivert, and the old phrasing implied it did - and names WinDivert **via PyDivert**, both
  linked.
- **Third-party section (EN + PL):** each named component now links to its homepage/source
  (WinDivert, PyDivert, psutil, CPython, Tcl/Tk, PyInstaller).

### CI: one run per commit

- **`ci.yml` `push` trigger scoped to `master`.** With `on: [push, pull_request]` a branch that
  had an open PR ran the whole matrix twice (a `push` event and a `pull_request` event; the
  concurrency group only dedupes within one event). Now feature branches run once via their PR,
  and `master` runs on push (after a merge). Halves the Actions runs on PR branches.

### Relicense: GPLv3

- **Relicensed from the proprietary Bean Network Tester License to the GNU GPL v3.** `LICENSE` is
  now the verbatim GPLv3 text (byte-identical to `licenses/GPL-3.0.txt`, so GitHub detects it and
  the copyleft terms actually apply). Touchpoints updated in one pass: `appinfo.LICENSE_NAME` and
  `COPYRIGHT` (dropped "All rights reserved"), the `pyproject` classifier
  (`Other/Proprietary` -> `OSI Approved :: GNU General Public License v3 (GPLv3)`),
  `about.license_terms` in `lang/en.json` + `lang/pl.json`, the License and third-party sections of
  both READMEs (removed the "closed source" line), and the `THIRD-PARTY-NOTICES.md` header. Exe
  metadata (`.spec` LegalCopyright) and the About window follow automatically via the `appinfo`
  constants. No version bump (owner closes the version).
- **Test:** `tests/test_version_and_release.py` - `test_license_is_not_mit_anymore` rewritten as
  `test_license_is_gplv3` (asserts the verbatim GPLv3 text is present and the old "may not be sold"
  wording is gone); `test_no_mit_references_left_in_metadata` renamed to
  `test_no_stale_license_references_in_metadata` (also asserts the Proprietary classifier is gone
  and the GPLv3 classifier is present).

### Docs: English README is now the default

- **Swapped the README language default.** `README.en.md` (English) is now `README.md` - the file
  GitHub renders on the project page - and the Polish text moved to `README.pl.md`. Cross-links at
  the top/bottom of each file updated to point at the new names; `pyproject.readme` now points at
  `README.md`.
- **Tests:** `tests/test_readme_guards.py` and `tests/test_cli_docs.py` - `READMES` tuple and the
  per-language pipeline guards retargeted (`test_english_readme_pipeline_matches_core_decide` reads
  `README.md`; `test_polish_readme_pipeline_keeps_lan_and_blocking` reads `README.pl.md`). No new
  tests, same guarantees against the new filenames.

### CI: release workflow and GitHub repo furniture

- **New `.github/workflows/release.yml`.** Tag push `v*` -> assert the tag matches
  `VERSION.txt`, build the onedir exe from `BeanNetworkTester.spec`,
  smoke it, zip it as `BeanNetworkTester-<tag>-windows-x64.zip`, write `SHA256SUMS.txt` (the
  checksum the README tells users to verify), and publish a GitHub Release via the preinstalled
  `gh` (job token, `contents: write` scoped to the workflow; no third-party action). A
  `v<version>-rc.N` (or `-beta.N` / `-alpha.N`) tag publishes as a GitHub Pre-release; a plain
  `v<version>` tag as Latest. The tag's base version must equal `VERSION.txt`. `ci.yml` is
  unchanged.
- **Repo furniture:** `SECURITY.md` (private vulnerability reporting, tool-specific scope),
  `.github/FUNDING.yml` (Sponsor button -> the project support page),
  `.github/ISSUE_TEMPLATE/` (bug-report + feature-request forms tailored to the tool: version,
  Windows, GUI/CLI/simulate, elevation, `--doctor`; plus `config.yml` disabling blank issues and
  linking support + security advisories), and `PULL_REQUEST_TEMPLATE.md` (checklist keyed to the
  project conventions: tests, both lang files, both changelogs, Conventional Commits, no bump).
- `dependabot.yml` already covered `pip` + `github-actions` - left as is.

### Repo: line endings, code of conduct, README badges

- **`.gitattributes`** pins text files to LF (`* text=auto eol=lf`; `*.png` / `*.ico` binary),
  ending the "LF -> CRLF" checkout churn on Windows and giving the Linux/Windows CI runners
  identical bytes. `git add --renormalize` was a no-op (the repo already stored LF), so no
  content changed.
- **`CODE_OF_CONDUCT.md`** (Contributor Covenant 2.1) completes the GitHub community profile;
  README, LICENSE, CONTRIBUTING, SECURITY and the issue/PR templates were already present.
- **README badges** in both languages (CI status, latest release, downloads, GPLv3, Windows).

### Repo: release-note grouping, downloads script, WinDivert link

- **`.github/release.yml`** groups the auto-generated release notes by PR label
  (New features / Bug fixes / Performance / Documentation / CI / Other) instead of one
  flat list.
- **`tools/downloads.py`** prints per-release, per-asset GitHub download counts via the
  public API (stdlib only, no token). The README downloads badge shows the same total live.
- **README (EN + PL):** the first WinDivert mention now links to its homepage
  (`reqrypt.org/windivert.html`).
- CodeQL and `dependency-review-action` are deferred to just after the repo goes public
  (both need a public repo or GitHub Advanced Security); steps are in the Doc repo runbook.

### Docs: README polish for the public repo

- Table of contents is now **expanded by default** (removed the `<details>` fold) in both READMEs.
- Added a **Contributing** section linking `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` and `SECURITY.md`.
- Added a short **AI-assisted-workflow disclosure** to the Author section.
- Section order left intact - a full read confirmed it was already logical and public-ready, so no
  reshuffle (would have been churn against the guards for no reader benefit).

### GUI: Settings window

- **New "surface" split of the field registry.** `fields.Section` gains `surface`
  (default `"control"`); the `tables` section is marked `surface="settings"`. Added views
  `CONTROL_SECTIONS` / `SETTINGS_SECTIONS`. The Control page and the Settings window are now
  both renderers of one registry: a new preference is one entry with `surface="settings"` and
  it renders itself (widget, label, unit, live validation) - no second code path. `row_limit`
  (still `ui_only`, convention 37) is the first field to move.
- **`gui/form.py::ControlForm` takes `sections=`** (defaults to `CONTROL_SECTIONS`); all its
  `SECTIONS` loops now read `self._sections`. `SECTION_BY_ID` stays a full lookup. The Control
  page passes the default; the Settings window passes `SETTINGS_SECTIONS`. Shared `app.vars`
  keep both forms in sync (a config-file load updates the Settings entry live).
- **New window `gui/panels/settings.py` (`SettingsWindow`, ID `settings`)** via the window
  registry (convention 25): language combobox (bound to the App's `lang_var`, locked mid-session
  like before) + `ControlForm(sections=SETTINGS_SECTIONS)`. Registered in `panels/__init__.py`.
- **`gui/app.py`**: header language combobox+label replaced by a gear button opening the
  Settings window (`Gear.TButton` in `theme.py`, icon from new `icon.make_gear_icon`, pure
  `PhotoImage.put`, DPI-scaled). `lang_var` / `_lang_name2code` still built in `_build_ui`
  (smoke and `_switch_language` depend on them); `lang_cb` is now owned by the Settings window
  (set on build, `None` on close). `_sync_running_ui` skips `lang_cb` when `None`.
- New i18n keys (both files): `windows.settings`, `buttons.settings`, `tips.settings`.
- `theme.apply_dark_titlebar` now forces a non-client repaint (`SetWindowPos` SWP_FRAMECHANGED)
  after setting the DWM attribute, and `windows.PanelWindow.open` re-asserts it once the window
  is mapped: a Toplevel shown without being activated (opened while the main window keeps focus)
  used to keep a white title bar until first click. Fixes it for every registered window.
- Dead-entry cleanup: `gui/app.py::FIRST_RUN_COLLAPSED` no longer lists `"tables"` (that section
  is settings-surface, rendered `collapsible=False`, so the collapse hint did nothing).
- Tests: `test_windows.py::test_settings_window_holds_the_language_box_and_the_view_fields`
  (row_limit renders in Settings, not on the Control page; no Control field leaks in; language
  box owned + rebound across a language switch + dropped on close). Updated
  `test_gui_layout.py::test_stop_button_and_language_picker_reflect_the_session` and
  `test_gui_release_fixes.py::test_short_dropdowns_do_not_spawn_a_popdown_scrollbar` to open the
  Settings window before asserting on `lang_cb` (it left the header). Added
  `test_windows.py::test_settings_sections_render_open_and_do_not_touch_collapse_state` (the
  clobber guard: two ControlForms must not fight over `app.collapsed_sections`) and, in
  `test_field_registry.py`, `test_sections_split_cleanly_by_surface` +
  `test_ui_only_fields_live_on_the_settings_surface` (convention 42 / 37 invariants).

### GUI preferences (ui.json-backed)

- **New `gui/prefs.py`** - a small preference registry *separate* from `fields.FIELD_DEFS`.
  `Pref(kind=NUMBER|BOOL|ACTION)`; `PREFS` + `PREF_GROUPS`. These persist in `*_ui.json` under
  `pref.<key>` (never in a traffic config file, never a CLI flag). `App.pref(key)` reads+validates,
  `App.set_pref(key, v)` writes through and persists immediately (a preference must survive an
  unclean exit). `SettingsWindow` renders the groups (numbers with live `parse_number` validation,
  checkbuttons, and an action button). See convention 42 for the two-kind model (registry
  `surface="settings"` field vs a `Pref`).
- Wired behaviours in `gui/app.py`:
  - `chart_seconds` -> `App.chart_samples()` (seconds / tick period) sizes the throughput deques;
    `_reconcile_chart_len()` resizes them live in `_sample()` (keeps the most recent samples).
  - `log_lines` -> `_append_log_line` trims `_log_lines` and the Text widget to the preference
    (with a +100 hysteresis so it is not an every-line reslice); the rebuild-restore uses it too.
  - `confirm_close` -> `on_close` only prompts when the switch is on.
  - `restore_profile` -> `_restore_last_profile()` (startup only, never on a language rebuild)
    refills the form from the saved `ui.json` "profile"; `select_profile` now persists that key.
    Fills the form only, never auto-applies (convention 15).
  - `reset_ui_layout()` (the `reset_layout` action) clears geometry / page / collapsed / sorts /
    sash and the `window.*` geometries back to `ui_state.DEFAULTS`, then recentres and rebuilds.
  Note: driver cleanup on exit was NOT added - `driver.release_on_exit` (called from `on_close`)
  already unloads the driver when a run loaded it, so a toggle would only disable useful behaviour.
- `gui/app.py::FIRST_RUN_COLLAPSED` unchanged here; `README.md`/`README.en.md` project layout lists
  `prefs.py`. New i18n keys (both files, and both files re-sorted to the documented key order):
  `prefs.*` (labels/units/hints/groups), `tips.chart_seconds|log_lines|confirm_close|restore_profile|reset_layout`,
  `dialogs.reset_layout_title|body`, `log.layout_reset`.
- Tests: `tests/test_prefs.py` - registry (every pref grouped once; all texts resolve in en+pl;
  `coerce` clamps/falls back), accessors (round-trip + persistence), and each wired behaviour
  (chart resize, log trim, confirm-close honoured, restore-on-start fills only when enabled,
  reset-layout forgets window state). Extended
  `test_windows.py::test_settings_window_holds_the_language_box_and_the_view_fields` to assert the
  pref widgets render.

### Startup / performance

- `bean_network_tester.py`: the launcher facade now resolves the GUI (`App`, `Tooltip`,
  `add_tooltip`, `make_bean_icon`) LAZILY via a module `__getattr__` (PEP 562), mirroring
  `beantester/gui/__init__.py`, instead of an eager `from beantester.gui import App` at module
  load. Importing the launcher no longer pulls in `tkinter` or the `gui/` package. This matters
  on the GUI-launch path: with `asInvoker` + `winenv.elevate_self` (convention 19) a non-admin
  start spawns a second elevated process, and the doomed pre-elevation process used to import
  all of `gui/` (and Tk) for nothing before relaunching. Verified: `import bean_network_tester`
  leaves `tkinter` out of `sys.modules` until `App` is first accessed; `_HAS_TK` is still
  exposed (computed lazily). Guard `test_launcher_compat.py` stays green (it asserts the
  engine/CLI API surface, not GUI symbols).

- `gui/app.py`: START/STOP no longer block the Tk main thread. The blocking parts - the psutil
  target resolution + `engine.start()` (WinDivert driver load, ~0.5-1 s) and `engine.stop()`
  (worker-thread joins) - now run on a short-lived worker via `_begin_transition(kind, work)`.
  The worker leaves `(kind, err)` on a new `self._ui_queue`; `_tick` drains it (`_drain_ui_queue`)
  and applies the result on the main thread (`_finish_start` / `_finish_stop`), exactly like the
  log queue and the target-warning handoff (convention 26 - no widget touch off the main thread).
  While in flight, `self._transition` is `"starting"`/`"stopping"`; the button keeps showing
  START/STOP with NO transitional label (owner UX decision: the work is normally milliseconds -
  measured driver open ~6 ms on a warm driver - and a second click is a no-op while a transition
  is set, so there is nothing to relabel or disable). `_poll_transition` re-arms via
  `root.after(30 ms)` so the button flips as soon as the worker finishes instead of on the next
  `_tick` (the fake-tk `after` never fires, so tests drive it through `_settle_transition`).
  `_refresh_start_enabled` early-returns during a transition, and the `_on_engine_stopped` trigger
  in `_tick` is gated on `_transition is None` so a mid-stop tick does not fire it early. `on_close` sets
  `self._closing` before `engine.stop()`; a start finishing after that does not resurrect the UI,
  and `engine.stop()` still serialises on the engine's `_stop_lock`, so no divert can leak
  (fail-open, convention 20). `_settle_transition()` (join worker + drain) lets a headless test
  drive the async path deterministically.

### Engine / filters

- New `drop_shutdown` counter (`engine.py`). `BeanEngine.stop()` records `len(self._heap)`
  before clearing the delay queue, so packets captured but never injected (parked in the queue at
  STOP) are accounted for instead of vanishing from the seen/delivered/dropped balance. Seeded in
  `reset_stats`; bumped once under `_slock` after releasing `_cv` (the cv->slock order matches
  `_enqueue`). Flows into the NDJSON summary `counters` automatically - `cli.py` builds
  `counters=stats_snapshot()` AFTER `engine.stop()`. NOT added to the per-interval `sample` record
  (only ever nonzero at STOP). Additive to the NDJSON schema (a new key; existing keys unchanged),
  so NOT a `### BREAKING` change - same as earlier counter additions (`drop_rate`, `drop_block`).

- New `loopback` traffic filter: one entry in `filters.py::FILTER_DEFS`
  (`loopback and (ip or ipv6) and (tcp or udp or icmp or icmpv6)`). Combobox order and
  `--filter` choices derive from the registry, so no GUI/CLI code changed; i18n key
  `filters.loopback` added to both lang files; both READMEs' filter prose + `--filter` row updated.
  Covered by the existing `test_presets_filters.py::test_every_filter_covers_ipv4_and_ipv6`.
  Confirmed on real WinDivert (elevated Windows run): `--filter loopback --latency 200` took
  `ping 127.0.0.1` RTT from <1 ms to ~408 ms avg (200 ms each direction) and the packet counter
  tracked the loopback traffic, so WinDivert captures and reinjects 127.0.0.1/::1 correctly.

### GUI

- `drop_shutdown` shown in the live counters grid: entry in `gui/pages/stats.py::STAT_ROWS`
  (after `drop_overflow`) plus the key added to the hardcoded tuple in `refresh_counters`; i18n
  keys `stats.shutdown_dropped` + `tips.stat_shutdown` in both lang files. Label/tip deliberately
  reassuring, because it is routinely nonzero on any stop that used latency or a speed limit
  (packets were queued, not lost in transit). CSV column `dropped_at_stop` added to
  `App.CSV_COLUMNS` (every `drop_*` counter has a friendly `dropped_*` name).

- `tips.stat_corrupted` reworded (both lang files). `corrupted` counts successful payload
  bit-flips only: `BeanCore.corrupt_packet` returns False for a payload-less packet (bare ACK)
  and the engine never bumps the counter, so on real TCP traffic it trails the configured
  corruption percentage. The tooltip now says so. Behaviour unchanged - correct, since there is
  no payload to corrupt.

- Per-field "?" help sheet generalised beyond filter expressions. `fields.Field` gained
  `help_title` / `help_body` (i18n keys, default ""); `gui/form.py::ControlForm._place_one`
  renders the existing `Help.TButton` for any field declaring `help_body` (new `_show_field_help`,
  opens `dialogs.show_help`), in an `elif` after the `kind == EXPR` branch. Hover shows the field's
  own `tip`, a click opens the sheet. The `buffer` field now declares
  `dialogs.buffer_help` / `dialogs.buffer_help_title` (new keys in `lang/en.json` + `lang/pl.json`).
  `settings.DEFAULT_SETTINGS["buffer"]` changed 2000 -> 1000 ms (rate-limiter link buffer,
  `BeanCore.buffer_s`): not a public contract (no test asserts the default; `--buffer` and
  `core.set_buffer` unchanged). Chosen after a measurement sweep - delivered rate is accurate at
  every buffer and under sustained overload loss converges regardless, so the buffer only trades
  added latency against onset-of-loss; 1000 ms halves worst-case added latency and tracks sub-2 s
  schedule steps. Both READMEs updated.

- Control-page jitter on START/STOP: `form.py::ControlForm` no longer `pack`/`pack_forget`s the
  per-section override/lock note. The label is packed ONCE at build time (in `_place_fields`) and
  kept mapped; `apply_overrides` now only sets its `text` ("" when idle). An empty `ttk.Label`
  reserves the same one-line height as a full one (measured), so the section height is constant and
  the scrolled form stops reflowing/jumping when the `fields.locked_running` note appears at START.
  Guard already present: `test_gui_layout.py::test_schedule_overrides_greys_the_constant_limits`
  asserts the note text is `""` when idle (unchanged by this fix).

- Profile picker styling (`theme.py`, `pages/control.py`): `Profile.TMenubutton` now uses the flat
  `Menubutton.indicator` arrow inside `Combobox.field` instead of `Combobox.downarrow`. clam draws
  the downarrow as a bordered, sunken button (a lighter `BORDER`/#39404e box) which read as a
  "white arrow" next to the flat traffic-filter combobox; the indicator is a bare triangle.
  `style_menu(menu, like_combobox=True)` paints the profile dropdown on `FIELD` (matching the
  `*TCombobox*Listbox` popdown colour) instead of the `BG2` card colour; context menus keep `BG2`.

- Connections avg column: extracted `views.avg_packet_bytes(c)` (rounds `bytes / max(1, packets)`)
  and routed BOTH `conns.py::_render` and `App.export_connections_csv` through it. They had
  duplicated the formula and diverged - the table rounded (`f"{avg:.0f}"`), the CSV floored
  (`bytes // packets`), so 767.5 B/pkt read 768 on screen and 767 in the file. Tests:
  `test_views.py::test_avg_packet_bytes_rounds_like_the_table` and
  `test_conns_export.py::test_export_connections_csv_avg_matches_the_table_rounding`.

- Session average throughput: extracted `rates.average_kbps(total_bytes, elapsed_s)` (pure) and
  used it in `pages/stats.py`; the figure was computed inline from a MB value already rounded to
  two decimals, now it divides the full-precision byte count. Test:
  `test_gui_helpers.py::test_average_kbps_is_total_bytes_over_elapsed`.

- Release-polish pass (bug fixes + UI cleanup):

- Running-state chrome: `App._sync_running_ui` now also sets the window title
  (`APP_NAME` + `T("app.title.running")` tag) and swaps `root.iconphoto` between an idle and a
  running icon. Both flow through the ONE place already called after every start/stop and every
  language-switch rebuild, so the tag/icon never desync (same reason status/filter live there).
  `gui/icon.py`: `make_bean_icon(active=)` stamps a red recording dot (`_put_dot`); `_running_variant`
  copies the idle PhotoImage (keeps a user `bean.png`'s art) and stamps the dot, falling back to a
  drawn active bean. `apply_window_icon` now returns `(idle, running)`; `App` keeps both refs
  (`_icon_idle`/`_icon_running`) so Tk does not GC them. New i18n key `app.title.running`
  (en `"● RUNNING"`, pl `"● DZIAŁA"`). CLI is untouched (GUI-only, `test_layering` still holds).
  Test: `test_gui_state.py::test_language_switch_keeps_running_state` now asserts the title carries
  the tag while running and reverts to bare `APP_NAME` on stop.

- Release-polish pass (bug fixes + UI cleanup):
  - Native crash capture is now armed LAZILY (`crashlog.arm_native`), not at launch:
    `install(native=True)` only records intent (`_arm_wanted`) and registers
    `atexit(_cleanup_native)`; it no longer opens the file. `BeanEngine._start_locked` calls
    `crashlog.arm_native()` right after `driver.mark_driver_used()` - the one moment a native
    crash becomes possible (real WinDivert loaded), so `--simulate`/tests never arm it. faulthandler
    must hold its file open before a hard crash, so it cannot be created purely on-demand, but this
    means opening the GUI leaves NO `crashes/` folder. `_cleanup_native` (atexit) closes the stream,
    removes the empty `native-crash.txt` and `os.rmdir`s an empty `crashes/`; a real segfault skips
    atexit so a genuine report survives. `reset()` clears the new native flags for test isolation.
    DEBUG-severity records still persist (owner decision).
  - Profile picker (`gui/app.py`, `gui/pages/control.py`): the `Menubutton` is now posted
    explicitly via `App._post_profile_menu` bound to `<Button-1>` (returns `"break"`), fixing the
    intermittent press/release toggle where the dropdown reopened shut. `_rebuild_profile_menu` was
    simplified to a plain `add_command` list (presets, `add_separator`, then user profiles): the
    disabled group-heading entries rendered as muddy "blurry" text and the selected-item tick (both
    the native radiobutton indicator and a hand-drawn glyph) looked wrong, so both are gone - the
    current profile shows on the button via `textvariable`. The `profiles.presets_separator`/
    `mine_separator` i18n keys are kept (still used by `profile_names`/`_profile_separators` for the
    reserved-name guard), just no longer shown in the menu.
  - Connections tint (`gui/pages/conns.py`, `gui/theme.py`): `_tag_of` is an instance method gated
    on `_scope_active` and the flow's CURRENT scope (see the dropdown/scope pass below), so the
    "impaired" tag never floods when no target narrows.
    `CONN_COLORS["impaired"]` switched from a muddy `background` to an amber `foreground`.
  - `SortableTree._on_select` (`gui/widgets/sortable_tree.py`) drops blank-slot iids from the
    widget selection (re-`selection_set`/`selection_remove`), so a click below the last real row
    no longer leaves an empty row visibly selected.
  - Chart (`gui/chart.py`): new `_axis_label(value, peak)` gives adaptive precision (int >=10,
    1 dp >=1, else 2 dp) so an idle `peak=1` axis no longer collapses to "0 0 0 1 1"; five Y
    ticks only when `ph >= scaled(70)`, otherwise two (floor + peak). i18n `frames.throughput`
    caption "~80 s" -> "~84 s" to match the axis (120 samples x 0.7 s).
  - Windows (`gui/windows.py`): `PanelWindow.open` now sets `maxsize` (`_max_size` = `SIZE *
    MAX_FACTOR` clamped by `scaling.max_window_size`) and calls `theme.disable_maximize`, so every
    registered window is capped and non-maximisable like the main window (convention 25, updated
    in PROJECT_NOTES).

- Tooltips are suppressed while a Tk grab is held (`gui/tooltip.py`): new `_grab_active(widget)`
  guards the shared `_show_bubble`, so a field's bubble no longer draws over an open combobox
  popdown (the list the user just opened). Detection uses the raw `grab current` Tcl call - the
  ttk popdown is a Tcl-only window, so `Misc.grab_current`/`_nametowidget` raises on it;
  `grab_current()` stays as a fallback for the test double (no `.tk`). Same pattern as
  `WheelDispatcher._popdown_open`. Silence goes through `crashlog.quiet` (convention 30), not
  `except: pass`. Modal dialogs also grab but carry no tooltips and block background hover events,
  so nothing regresses.

- Dropdown/combobox polish pass (screenshot-driven, on the Connections/Control pages):
  - Scenario dialog (`gui/app.py::load_scenario`) passes `initialdir=paths.scenarios_dir()`; new
    `paths.scenarios_dir()` resolves the bundled `scenarios/` via `_resource_bases()` (same pattern
    as `lang_dir`), so it points at `_MEIPASS`/`_internal` when frozen. Single source for the path.
  - `theme.unhighlight_combobox` now also hands focus to the widget's `master` after a pick: a
    readonly combobox kept keyboard focus after a mouse selection, so the accent focus ring
    (`TCombobox` map `bordercolor=[("focus", ACC)]`) lingered as a stuck highlight. Applies to the
    traffic filter (`form.py::_on_choice`) and the language picker (`app.py`). Silence via
    `crashlog.quiet` (convention 30).
  - Readonly comboboxes get `height=len(values)` (`form.py` CHOICE field, `app.py` language picker):
    a list that fits no longer spawns the popdown scrollbar, which renders as a light `SCROLL_BG`
    bar over the near-black listbox. Confirmed by pixel probe: the bar was the themed scrollbar
    (#3a4150), not an unstyled one - it just should not appear for a 6-item list.
  - `_rebuild_profile_menu` (`app.py`) adds `hidemargin=True` to every `add_command`: tk.Menu
    reserved an indicator gutter for the check/radio tick that was removed, leaving a stray indent.
  - Profile picker now uses `Profile.TMenubutton` (`gui/theme.py`, applied in `gui/pages/control.py`):
    a custom layout that borrows the combobox's own `Combobox.field` + `Combobox.downarrow` elements
    (label from `Menubutton.label`), so it renders pixel-identical to a readonly combobox while still
    posting the grouped menu. The bare `TMenubutton` looked flat next to the traffic filter.

- Live targeting scope for the Connections view (`core.py`, `engine.py`, `gui/pages/conns.py`):
  new read-only `BeanCore.in_scope(local_port, remote_ip, remote_port)` mirrors `decide` steps 1-2
  (process + destination gates) under the core lock, plus `BeanCore.targeting_active()`; both
  delegated by `BeanEngine.in_scope_now` / `targeting_active`. The connections page recomputes a
  row's scope from the CURRENT target (`_in_scope`, called for visible rows only via
  `SortableTree.repaint`) for both the scope column and the "impaired" tag, instead of reading the
  flow's stored `scoped` (which was the LAST packet's decision - an idle flow kept a stale flag, so
  a firefox row stayed highlighted after the target was narrowed to chrome). `_build_model` now
  returns `scope_active = engine.targeting_active()` (one lock) in place of the old O(n)
  `any(scoped) and any(not scoped)` snapshot scan.

- Tooltips can advertise a keyboard shortcut (`gui/tooltip.py`, wired in `gui/app.py`): new
  `tooltip_text(key, shortcut)` appends `[F5]`-style bracket line (no translatable word -> no i18n
  key); `add_tooltip(widget, key, shortcut=)` uses it and stores the `Tooltip` on the widget
  (`_bnt_tooltip`) for tests. Wired to START/STOP (`F5`), Apply (`Ctrl+Enter`), Save (`Ctrl+S`),
  Load (`Ctrl+O`). New convention 40 in PROJECT_NOTES.

- Statistics -> Session panel now shows host identity: computer name + private IPv4/IPv6
  (`gui/pages/stats.py` `SESSION_ROWS` + `refresh_session`). Backed by a new pure helper
  `utils.host_identity() -> (hostname, ipv4, ipv6)` built on `utils._route_source_ip(family,
  probe)`, a connected-UDP-socket route lookup that puts NO packet on the wire (never
  disturbs capture) and degrades to `"-"` when a family has no route. Deliberately NOT added
  to the repro report or the NDJSON schema (privacy - the tool sends no data anywhere). New
  i18n keys `session.host`, `session.private_ipv4`, `session.private_ipv6` in both langs.
  New test `tests/test_core.py::test_host_identity` (asserts a 3-tuple of non-empty strings).
- Connections table split traffic into `down`/`up`/total (`gui/pages/conns.py`,
  `views.py`). The engine already recorded `bytes_in`/`bytes_out` per flow in `_log_conn`;
  this is presentation-only, nothing touches the capture thread. `views.DERIVED` gained
  `down` (`bytes_in`/1024) and `up` (`bytes_out`/1024) and both are in the numeric sort set;
  the existing `kb` column id is kept as the TOTAL column (unchanged semantics, only the
  label/tooltip), so the persisted default sort (`ui_state.py` `conn_sort=kb`) and its guard
  (`test_validators_settings.py`) keep working with no migration. New i18n keys `conns.down`,
  `conns.up`, `tips.col_down`, `tips.col_up` in both langs; `conns.kb`/`tips.col_kb` reworded.
- Connection table gained the per-flow columns backed by the engine work above:
  `pid`, `scoped` ("impaired?"), `dropped`, plus derived `avg` (`gui/pages/conns.py`,
  `views.py`). `views.DERIVED` gained `avg` (`bytes`/`packets`) and `scoped` (1/0 so the
  column sorts numerically); `dropped`/`pid` added to the numeric sort set. The search
  predicate was extracted to `views._filter_connections`/`_connection_blob` (one source), so
  the new `views.traffic_totals(conns, query, proc_map)` sums download/upload/total bytes
  over the SAME filtered set - computed in the worker (`_build_model`) over the whole filtered
  set, not the limited `shown`, and shown in a footer label (`conns.totals`). In-scope rows
  carry a `tag_of` -> `theme.CONN_COLORS["impaired"]` highlight. The `_render` tuple grew to
  15 values to match COLUMNS (guarded so it cannot drift). New i18n keys `conns.pid`,
  `conns.scoped`, `conns.dropped`, `conns.avg`, `conns.yes`, `conns.no`, `conns.totals`,
  `tips.col_pid`/`col_scoped`/`col_dropped`/`col_avg` in both langs.
- Connection-table CSV export: `App.export_connections_csv` (`gui/app.py`), button on
  `gui/pages/conns.py`. Reuses `views.filter_sort_connections` with the page's current
  `conn_query`/`conn_sort` and `limit=0` (the display row-limit is a render cap, not part
  of the export), so the file mirrors the visible order over the whole filtered set. Raw
  byte columns (`download_bytes`/`upload_bytes`/`total_bytes` = `bytes_in`/`bytes_out`/`bytes`)
  rather than the table's KB. Atomic overwrite (tmp + `os.replace`) to a snapshot file
  `paths.CONNECTIONS_CSV_FILE` (also exported from the package `__init__`), not an append
  log like the stats CSV. New i18n keys `buttons.export_conns`, `tips.export_conns`,
  `log.conns_saved_to` in both langs. `CONN_CSV_HEADER` now MIRRORS the table's columns:
  added `pid`, `impaired` ("yes"/"no", English like the headers - the CSV is
  language-independent), `dropped` and `avg_bytes`, so the export no longer lagged the new
  columns.

### Engine / core

- Blocking (firewall). New pipeline step 2c in `core.decide()` (documented in the module
  docstring), placed AFTER the targeting gate next to LAN mode, so a process/destination
  target scopes it. `BeanCore` gained `block_active`/`block_ip`/`block_port` + two matchers
  and `set_block(active, ip, port)` (mirrors `set_dest`); the gate is `block_ip_matcher OR
  block_port_matcher` where each side takes part only when the matcher is non-empty (an empty
  `Matcher` is falsy and would otherwise match everything - that is the OR skip-empty rule, and
  the reason blocking is NOT modelled as AND like destination targeting). Drops carry
  `reason="block"`, `scoped=True`. Two registry fields `block_ip`/`block_port` (`fields.py`,
  section `block`, kinds `KIND_IP`/`KIND_INT`+`PORT_BOUNDS`, flags `--block-ip`/`--block-port`)
  - so `MATCH_FIELDS`, `build_matchers`, form, live validation and profile scope derive
  themselves. `settings.py`: `DEFAULT_SETTINGS` gained `block_ip`/`block_port`, `apply_settings`
  calls `engine.set_block` (tolerant `try/except` like destination), `setting_expression`
  normalises `block_port`. `engine.py`: counter `drop_block` in `st`, `_bump` map entry, and a
  `set_block` delegate. Surfaced additively (no contract break): CSV column `dropped_block`
  (`gui/app.py::CSV_COLUMNS`), live stat row `stats.block_cut` (`gui/pages/stats.py`), one-line
  `summary.block`, NDJSON `sample.drop_block` and the `[bean]` text line, repro metric
  `blocked`, and the reproduce command (`repro.settings_to_cli` emits `--block-ip`/`--block-port`
  - it is a hand-maintained emitter, not registry-driven, so a missing field silently drops from
  the copy-paste repro command; guarded by the round-trip test below). New i18n keys `frames.block`, `tips.block`, `stats.block_cut`, `tips.stat_block`,
  `summary.block` in both langs; field labels reuse `fields.ip`/`fields.port`.

- Per-flow impairment bookkeeping behind the upcoming "impaired?"/"dropped" connection
  columns. `core.Decision` gained `scoped: bool = True`; the three targeting early-returns
  (process step 1, destination ip/port step 2) now pass `scoped=False`, so `scoped` marks
  whether a packet cleared the targeting gate - i.e. the flow is in scope for impairment, not
  merely observed. Every impairment path (loss, LAN, rst, nat, flap, mtu, syn, rate) keeps
  `scoped=True`. Zero added cost: same early returns. In `engine.py`, `_log_conn` now records
  `dropped` (per-flow drop count), `scoped` (latest packet's scope) and `pid`
  (`_pid_for` -> `portmap.pid_for`, resolved once at flow creation like the process name); the
  connection dict carries `dropped`/`scoped`/`pid`. The capture loop was REORDERED so
  `core.decide()` runs before `_log_conn` (decide reads none of the connection log, so the
  order is free) - one lock acquisition still records the packet plus its drop/scope. No new
  O(n) work on the capture thread. These fields flow through `connections_snapshot` into the
  repro report automatically (additive, backward-compatible).

- Bounded link buffer for the speed limit: `buffer` field (`fields.py::FIELD_DEFS`, section
  `speed_limit`, flag `--buffer`, default 2000 ms, 0 = unbounded). The token bucket can no
  longer run unbounded ahead; offered load above the cap is dropped once the buffer fills,
  which bounds the added latency to ~`buffer` ms and lets a mid-session cap increase take
  effect within that window. New counter `drop_rate` (CSV `dropped_rate_limit`), kept
  separate from `drop_flap`, from loss, and from the queue's own `drop_overflow`. A sub-byte/s
  cap now floors at 1 B/s instead of rounding to 0 ("unlimited").
- RST injection and SYN dropping are exercised off Windows: `--simulate` now carries a real
  TCP/UDP/ICMP protocol mix and the RST packet is built through the traffic source, so
  `rst_sent` moves in tests and simulation instead of only on Windows with WinDivert.

### Tests

- `tests/test_engine.py::test_packets_queued_at_stop_are_counted_as_drop_shutdown`: a 60 s latency
  parks 200 packets in the delay queue; after `stop()` it asserts `drop_shutdown == 200`, nothing
  delivered, and `seen == delivered + drop_shutdown` (the balance closes to the end of the session).

- `tests/test_gui_layout.py`: `test_only_filter_expressions_get_the_syntax_cheat_sheet` renamed to
  `test_fields_with_a_help_sheet_get_the_question_mark_button` and now asserts `buffer` is present
  in `ControlForm.helps` alongside the five expression fields (guards the generalised "?" help
  wiring from `Field.help_body`).

- `tests/test_failsafe.py::test_start_and_stop_run_off_the_ui_thread`: a slow `engine.start`/
  `engine.stop` (0.4 s sleep) proves `_start()`/`_stop()` return in < 0.2 s (do not block the UI
  thread), the button keeps showing START/STOP with no transitional label, and
  `_settle_transition()` drives the async result to `running` True/False.
  `test_the_gui_starts_the_session_with_its_duration` gained the matching `_settle_transition()`
  call now that start is asynchronous.

- Release-polish pass:
  - `tests/test_crashlog.py`: `test_launch_creates_no_crash_folder_until_a_capture_arms_it` and
    `test_arm_native_is_a_noop_when_native_was_not_requested` guard the lazy `arm_native`; plus
    `test_cleanup_removes_the_empty_native_file_and_dir` and `test_cleanup_keeps_a_non_empty_native_file`
    for `_cleanup_native` (empty file + empty dir removed on clean exit; a written report is preserved).
  - `tests/test_virtual_tables.py::test_clicking_a_blank_slot_selects_nothing` guards the
    `_on_select` blank-slot fix (clicking a blank slot clears it; a real+blank click keeps only
    the real key). `tests/fake_tk.py` `Treeview` gained `selection_remove`.
  - `tests/test_windows.py::test_a_window_is_dark_and_hidden_before_it_is_shown` gained a
    `maxsize` assertion (every window is capped, not just given a minsize).
  - `tests/test_gui_release_fixes.py::test_tooltip_is_suppressed_while_a_dropdown_is_open` guards
    the tooltip grab-guard: `_grab_active` is false with no grab, true after `grab_set()`, and
    `_show_bubble` returns `None` (short-circuits before rendering) while a grab is held.
  - `tests/test_gui_release_fixes.py`: `test_short_dropdowns_do_not_spawn_a_popdown_scrollbar`
    (filter/language comboboxes carry `height == len(values)`),
    `test_profile_menu_has_no_indicator_gutter` (every profile `add_command` has `hidemargin`),
    `test_scenario_dialog_defaults_to_the_bundled_scenarios_dir` (`paths.scenarios_dir()` exists and
    is named `scenarios`), `test_shortcut_buttons_advertise_their_key` (START/Apply tooltips carry
    `F5`/`Ctrl+Enter`), `test_profile_picker_uses_the_combobox_field_style` (Menubutton uses
    `Profile.TMenubutton`). Combobox focus-drop (#7) verified live on real Tk, not in the fake
    (fake `focus_set` is a no-op).
  - `tests/test_conns_columns.py::test_connection_columns_tag_and_footer` rewritten for live scope:
    it sets `engine.core.set_target(True, {5000})` and gives the out-of-scope svchost row a STALE
    `scoped=True`, asserting the column and tag follow the current target (svchost -> "no", no tag)
    rather than the stored flag.
- Blocking: `tests/test_core.py` gained six tests for pipeline step 2c - block by IP drops
  matching only (reason `block`, `scoped=True`), block by port ignores an empty IP field (the
  OR skip-empty rule), IP and port combine with OR (not AND like destination targeting), block
  sits after the process-targeting gate (a non-target flow passes even when its destination is
  on the block list), inactive block passes everything, and a malformed expression raises
  `ValueError`. `block_ip`/`block_port` added to `IMPAIRMENT_OFF` and `drop_block` to
  `DAMAGE_COUNTERS` in `tests/test_passthrough.py` (a new default-harm field would otherwise slip
  through). Registry-guard sets updated for the two new expression fields:
  `test_field_registry.py`, `test_settings_config_scenario.py` (MATCH_FIELDS view),
  `test_gui_layout.py` (filter fields get the syntax cheat sheet), and the hand-written fake
  engine in `test_cli_runtime.py` gained a `set_block` stub.
  `test_summary_repro_views.py::test_settings_to_cli_roundtrip` extended with `block_ip`/
  `block_port` so the reproduce command is proven to round-trip them.
- Engine and settings coverage: `test_engine.py::test_block_integration` (block drops matching
  IP and port through a real `BeanEngine`+`FakeDivert`, `drop_block == 2`, OR of the two
  fields); `test_settings_config_scenario.py` gained `test_apply_settings_bad_expression_disables_blocking`
  (tolerant path), `test_apply_settings_with_block_expressions`, `test_scenario_block_step_applies_and_clears`,
  and extends `test_apply_settings_maps_engine`, `test_config_roundtrip_keeps_expressions` and
  `test_validate_settings_rejects_bad_expressions` with block fields; `test_summary_repro_views.py::test_summary_shows_blocking`.
- `scenarios/blocked-endpoint.json` shipped (loops a backend/API outage via `block_ip` on a
  TEST-NET-3 range, then clears it) - auto-validated by `test_shipped_scenarios.py`.
- `tests/test_conns_columns.py` - drives the real `ConnsPage` on fake-tk: the 15-column
  render tuple lines up with COLUMNS, `pid`/`scoped`/`dropped` cells render, the in-scope row
  gets the `impaired` tag and the observed-only row does not, and the footer sums the filtered
  traffic. `tests/test_views.py` gained `test_traffic_totals_sum_filtered_bytes` (footer sum
  honours the search), `test_derived_avg_and_scoped` and `test_sort_by_every_new_numeric_column`
  (down/up/dropped/pid each actually order the table). `tests/test_conns_export.py` now also
  covers the connection export's new columns (pid/impaired/dropped/avg_bytes) and adds
  `test_export_csv_stats_appends_then_rotates_on_a_column_change` - the FIRST test of the stats
  CSV export at all (append, and the roll-aside-on-header-change branch).
- `tests/test_core.py::test_decision_scoped_reflects_targeting` - `Decision.scoped` is False
  only when process/destination targeting excludes the packet, True with no targeting, on a
  matching target, and on an impairment drop (LAN). `tests/test_engine.py::test_connection_records_scope_and_dropped`
  - with targeting on one port and 100% loss, only the targeted flow is `scoped` and counts
  its `dropped`; the other is merely observed; every row carries a `pid` field.
- `tests/test_engine.py::test_lan_mode_integration` strengthened: now also feeds an INBOUND
  packet from a public `src_addr`, so LAN mode is proven to cut the internet both ways
  (`remote_ip` = `dst_addr` outbound / `src_addr` inbound), not only outbound. Expected
  `drop_lan` 2 -> 3, with a LAN-bound packet still passing.
- `tests/test_conns_export.py` - guards `App.export_connections_csv`: the CSV header, the
  raw `download_bytes`/`upload_bytes`/`total_bytes` split, sort order carried into the file,
  the atomic overwrite leaving no `.tmp`, and that the current search narrows the export.
  First test to exercise a CSV export at all (the stats export was never covered).
- `tests/test_bandwidth_buffer.py` - bounded queueing delay (added latency capped by
  `buffer`), recovery after a mid-session rate increase, `drop_rate` counting on a full
  buffer, and the legacy unbounded behaviour. Locks in the fix for the old token bucket that
  ran seconds ahead at a low rate and swallowed every later high-rate step.
- Reminder (convention "new impairment"): every traffic-damaging field must also be added to
  `IMPAIRMENT_OFF` in `tests/test_passthrough.py`, or a harmful default slips through unseen.

### Build / packaging

- `BeanNetworkTester.spec`: two size trims, neither touching startup or runtime (onedir does not
  unpack at launch - PROJECT_NOTES "performance > size").
  (1) Drop Tcl's bundled IANA timezone database (`_tcl_data/tzdata`) and msgcat catalogs
  (`_tcl_data/msgs`, `_tk_data/msgs`) from `a.datas` after Analysis - the tool uses Python's
  `time` (never Tcl `[clock]`) and its own `lang/*.json` i18n, so ~750 files were dead weight.
  (2) `excludes` now also drops `ssl`, `_ssl`, `_hashlib` -> OpenSSL (libcrypto ~6 MB + libssl
  ~1.3 MB) is no longer collected. The app has no network TLS (convention 36: no telemetry) and
  `import bean_network_tester` never pulls in `ssl`; its only hashing is crashlog's sha1
  fingerprint, and `hashlib` falls back to the built-in `_sha1` module when `_hashlib` is absent
  (verified: `sys.modules['_hashlib']=None; hashlib.sha1(...)` still works on this CPython, and
  `_sha1` is built into python314.dll, not a separate excluded .pyd).
  Measured `dist/BeanNetworkTester/_internal`: 1020 -> 262 files, 27.9 -> 19.2 MB. Encodings are
  KEPT (Tk needs them). Verified on the rebuilt exe: `--version`, `--simulate --loss 10
  --duration 2` (exit 0), and the GUI window opens; `libcrypto*`/`libssl*`/`_hashlib*`/`_ssl*` are
  absent from `_internal`.

### CI / tooling

- `.github/workflows/ci.yml`: pinned actions moved to their Node 24 majors
  (`checkout@v5`, `setup-python@v6`, `upload-artifact@v6`); fixed the coverage-artifact name
  (`matrix.python` -> `matrix.python-version`, previously empty and colliding across the two
  Python versions); added `concurrency` (cancel superseded runs), least-privilege
  `permissions: contents: read`, per-job `timeout-minutes`, a weekly `schedule` run (catches
  drift in unpinned `pydivert`/`psutil`), and `CHANGELOG.md` to the required-release-files
  check. New headed GUI render check under Xvfb (`tools/ci_gui_render.py`) that builds the
  real Tk `App` at 1366x768 in both languages and fails on truncated key widgets - catches
  layout regressions the fake-tk smoke cannot see.
- `.github/dependabot.yml`: weekly updates for the `github-actions` and `pip` ecosystems.

## [0.2.0] - 2026-07 - first public release

First tagged release. See `CHANGELOG.md` for the user-facing summary. Internally this is the
package-refactor baseline: the pure decision core (`core.py`), the threaded engine
(`engine.py`), the field/filter/exit-code/preset/window/page registries as single sources of
truth, the virtualized tables, and the pytest suite (engine, i18n, CLI, fail-safe, property
based, concurrency chaos, GUI on the fake-tk harness).
