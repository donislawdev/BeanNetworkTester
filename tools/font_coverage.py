"""Can this machine actually DRAW a language? Asked of fontconfig, not of pixels.

WHY IT IS ITS OWN FILE
    ``ci_gui_render.py`` imports tkinter and rewires the user-file locations the
    moment it is imported, deliberately, so no test can import it - the suite has
    to run where there is no Tk at all. The rule below is subtle enough to be
    "simplified" back into the bug by a future reader, so it lives where a test
    can reach it.

WHAT IT IS FOR
    The render check measures real font metrics. A language whose glyphs are
    missing is measured as the "missing glyph" box, and a box has a width, so
    every clipping test passes on it. A Linux runner carries no CJK font unless
    somebody installs one - which is how a green appeared for Chinese that
    nothing had earned.
"""
import subprocess

# The control query. Any machine that can run a GUI check at all has a font for
# English, so an empty answer HERE means fontconfig is not answering rather than
# that the font is missing.
CONTROL_LANG = "en"


def families(code, run=subprocess.run):
    """Font families fontconfig says cover ``code``, or None if it cannot answer.

    None is "no opinion" - no fontconfig on this machine (Windows, a stripped
    container), which is deliberately a different answer from an empty list,
    meaning "asked, and nothing covers it".
    """
    try:
        out = run(["fc-list", f":lang={code}", "family"],
                  capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return [line for line in (out.stdout or "").splitlines() if line.strip()]


def system_can_draw(code, run=subprocess.run):
    """True / False / None - and None is a real answer, not a failure.

    A "no" is only believed once the mechanism has been shown to say "yes". An
    fc-list that answers nothing for everything is fontconfig failing, not a
    machine with no fonts, and reading that as "no glyphs" would replace one
    silent lie with its opposite - every language reported unmeasured, and the
    check quietly stops checking.

    So the control is asked about an EMPTY answer only. A non-empty one has
    already proved the mechanism works, and asking twice would put a second
    process on the common path for no information at all.
    """
    found = families(code, run)
    if found is None:
        return None
    if found:
        return True
    return False if families(CONTROL_LANG, run) else None
