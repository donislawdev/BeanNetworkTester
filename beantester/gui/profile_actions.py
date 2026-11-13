"""The profile picker's actions: what it lists and shows, picking, saving, deleting.

Carved out of ``gui/app.py`` like ``csv_export`` and ``session_repro``: App sits on
the file-size ratchet in tests/test_code_shape.py, and asking before a profile is
replaced or deleted, and marking one the form has left, needed room it did not
have. The functions take the App, because the state is still the App's - the
current profile id (``_profile_key``), the picker's variable, the store - and the
App's methods (``save_profile``, ``select_profile``...) stay the names the page,
the smoke script and the tests call.

The current profile is an ID, never the text in the picker: preset names are
translated, and the picker may also show "(changed)" after the name. Turning the
picker's text back into an id is ``key_for``'s job and nobody else's.
"""
from .. import crashlog
from ..fields import widget_value
from ..i18n import T, field_name
from ..presets import PRESETS, preset_to_settings, resolve_preset, settings_to_preset
from ..settings import non_profile_active
from ..validators import number_or_zero
from . import dialogs
from .theme import popdown_height, popdown_width

AREA = "gui.profile_actions"
DEFAULT_PROFILE = "presets.perfect"    # the form always starts on a perfect link


def short_label(key):
    """Short form of a field label: no colon (``i18n.field_name``), and no
    parenthetical either - a comma-separated list wants the bare name."""
    return field_name(key).split("(")[0].strip().rstrip(":").strip()


def names(app):
    """Everything the picker offers: presets first, then the user's own.

    Nothing else - no group headings. The dropdown sits under the "Profiles"
    heading and every row in it is a profile, so a row that only says which
    group comes next is a row the user can pick and get nothing from.
    """
    return [T(k) for k in PRESETS] + app.profiles.names()


def label(key):
    """Displayed name of a profile id (presets are translated, own ones are not)."""
    return T(key) if key in PRESETS else str(key or "")


def _stored(app, key):
    return PRESETS.get(key) or app.profiles.get(key)


def _same(expected, typed):
    """One field: does the form still hold what the profile filled in?

    By value, not by text: "5" and "5.0" (or "5,0") are the same latency, and a
    picker that called that a change would cry wolf. A switch compares as a
    switch.
    """
    if isinstance(expected, bool):
        return bool(typed) == expected
    return number_or_zero(typed) == number_or_zero(expected)


def is_modified(app):
    """True when a field the current profile stores no longer holds its value.

    Fields a profile does not store (the target, the filter...) do not count:
    changing them leaves the link the profile describes as it was.
    """
    stored = _stored(app, app._profile_key)
    if not stored:
        return False
    return not all(_same(widget_value(setting, value), app.vars[setting].get())
                   for setting, value in preset_to_settings(stored).items()
                   if setting in app.vars)


def shown(app):
    """What the picker shows: the current profile, marked once the form left it."""
    name = label(app._profile_key)
    return T("app.profile_modified", name=name) if name and is_modified(app) else name


def key_for(app, text):
    """The picker's text -> profile id: a preset's translated name, the user's own
    name as it is, or the current profile when the text is the marked one.

    A row of the list wins over the mark: a profile of the user's own may be NAMED
    like the marked current one ("Office (changed)"), and picking that row loads it.
    The mark is never a row, so only the text left in the picker reads like it.
    """
    # asked on a pick, not kept: the names change with the language
    preset = {T(key): key for key in PRESETS}.get(text)
    if preset is not None:
        return preset
    if text and text not in app.profiles and text == shown(app):
        return app._profile_key
    return text


def refresh_shown(app):
    """Re-mark the picker after an edit. Cheap: it compares a handful of fields,
    and writes the variable only when the text actually changes."""
    text = shown(app)
    if app.profile_var.get() != text:
        app.profile_var.set(text)


def sync_widgets(app):
    """Refill the profile list, show the selection, gate the Delete button."""
    if app.profile_cb is None:
        return
    with crashlog.quiet(AREA):
        listed = names(app)      # also refreshes the label<->key lookups
        # width too, not just the row count: saving a profile is how a LONG
        # name gets into this list, and a picker that fits at build time can
        # stop fitting a keystroke later
        app.profile_cb.config(values=listed, height=popdown_height(listed),
                              width=popdown_width(listed))
    with crashlog.quiet(AREA):
        app.profile_var.set(shown(app))
    if app.btn_delete_profile is not None:
        with crashlog.quiet(AREA):
            # built-in presets and the group headings are not deletable;
            # the button used to look live and then silently do nothing
            deletable = app._profile_key in app.profiles
            app.btn_delete_profile.config(state="normal" if deletable else "disabled")


def set_key(app, key, current=None):
    """Make ``key`` the current profile AND the one remembered for next start.

    The single place that writes ``_profile_key``. It used to be written by
    each of the three paths that change the current profile, and only one of
    them (picking from the list) also remembered it - so saving a new profile,
    which is how a user ENDS UP on their own profile, left "Restore the last
    profile on startup" pointing at the preset picked before it. Persisting
    right here, not on close, is the same rule preferences follow: a
    deliberate choice must survive an unclean exit.

    ``current`` is a different current profile for THIS session only:
    deleting the loaded profile remembers the fallback for the next start but
    names no profile now (see ``delete``).
    """
    app._profile_key = key if current is None else current
    app.ui.set("profile", key)
    app.ui.persist()


def select(app, key):
    """Fill the form from a preset/profile id. Never applies by itself."""
    preset = _stored(app, key)
    if not preset:
        return
    set_key(app, key)
    for setting, value in preset_to_settings(preset).items():
        app.vars[setting].set(widget_value(setting, value))
    sync_widgets(app)
    app.form.validate_all()
    app.form.apply_overrides()
    app.on_form_changed()
    app.log(f"{T('log.loaded_profile')}: {label(key)}")
    if app.running:
        app.log(T("log.apply_needed"))


def save(app):
    # warn up front (once, contextually) when active settings fall outside the
    # profile scope, so nothing is lost silently
    try:
        extras = [short_label(key)
                  for key in non_profile_active(app._settings_from_widgets())]
    except ValueError:              # a refused field: said below, after the name
        extras = []
    if extras:
        dialogs.show_warning(
            app.root, T("dialogs.profile_scope_title"),
            T("dialogs.profile_scope_warning", fields=", ".join(extras)))
    name = dialogs.ask_string(app.root, T("dialogs.save_profile"), T("dialogs.profile_name"))
    name = (name or "").strip()
    if not name:
        return
    if resolve_preset(name) is not None:          # a built-in preset's name, any language
        dialogs.show_error(app.root, T("log.error"), T("dialogs.profile_name_taken"))
        return
    try:
        values = settings_to_preset(app._settings_from_widgets())
    except ValueError as e:
        # The message _settings_from_widgets raises names the field and its
        # range ("Field 'Loss' must be between 0 and 100"); this used to
        # throw it away and show "Values must be numbers", which named
        # neither. _start has always shown str(e) for the SAME exception from
        # the SAME call.
        dialogs.show_error(app.root, T("log.error"), str(e))
        return
    # Asked AFTER the values are known to be good: a "replace it?" answered Yes
    # and then refused for a bad field would be a question asked for nothing.
    # The keyboard starts on No - this Yes loses the profile that was there.
    if name in app.profiles and not dialogs.ask_yes_no(
            app.root, T("dialogs.profile_exists_title"),
            T("dialogs.profile_exists", name=name), careful=True):
        return
    # float() cannot be the one raising: settings_to_preset reads an already
    # validated dict, so every value it hands over is a number.
    app.profiles.set(name, {k: float(v) for k, v in values.items()})
    persist(app)
    set_key(app, name)      # saving one also SELECTS it - remember that
    sync_widgets(app)
    app.log(f"{T('log.profile_saved')}: {name}")


def delete(app):
    name = app._profile_key
    if name not in app.profiles:
        return                    # presets are not deletable (button is disabled)
    if not dialogs.ask_yes_no(app.root, T("dialogs.delete_profile_title"),
                              T("dialogs.delete_profile", name=name), careful=True):
        return
    app.profiles.delete(name)
    persist(app)
    # Remember what we fall back TO for the next start, not the name that no
    # longer exists - and name NO profile now. The form still holds the deleted
    # profile's values, and the picker read "Perfect network" over them, which
    # START then applied under that name (external review, P3-27).
    set_key(app, DEFAULT_PROFILE, current="")
    sync_widgets(app)
    app.log(f"{T('log.profile_deleted')}: {name}")


def persist(app):
    err = app.profiles.persist()
    if err:
        app.log(f"{T('log.profiles_not_saved')}: {err}")
