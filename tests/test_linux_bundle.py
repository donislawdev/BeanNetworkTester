"""``tools/linux_bundle.py``: the libraries the Linux bundle takes from the system,
and the check CI runs on the bundle it built. The check is proven able to fail on
each thing it looks for (a tool that cannot fail proves nothing)."""
import os
import sys

from fakes import ROOT, check

sys.path.insert(0, os.path.join(ROOT, "tools"))

import linux_bundle                                          # noqa: E402

GOOD = ("_internal/libtk8.6.so", "_internal/libXft.so.2", "_internal/libX11.so.6",
        "_internal/pydivert/bpf/libebpfdivert.so",
        "_internal/python3.15/lib-dynload/_tkinter.cpython-315-x86_64-linux-gnu.so")


def _bundle(tmp_path, names):
    for name in names:
        path = tmp_path / "BeanNetworkTester" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x7fELF")
    return str(tmp_path / "BeanNetworkTester")


def test_a_bundle_that_keeps_to_the_list_passes(tmp_path, capsys):
    folder = _bundle(tmp_path, GOOD)
    check("nothing wrong", linux_bundle.problems(folder) == [], f"({linux_bundle.problems(folder)})")
    check("and the command says so", linux_bundle.main(["check", folder]) == 0
          and "none of them the system's own" in capsys.readouterr().out)


def test_a_bundle_carrying_the_systems_font_stack_fails(tmp_path):
    """Measured: a bundled fontconfig 2.15 rejects Arch's 2.18 configuration."""
    for name in ("libfontconfig.so.1", "libfreetype.so.6", "libexpat.so.1", "libpng16.so.16",
                 "libbrotlicommon.so.1", "libbrotlidec.so.1", "libbz2.so.1.0"):
        folder = _bundle(tmp_path / name, GOOD + (f"_internal/{name}",))
        found = linux_bundle.problems(folder)
        check(f"{name} is caught", len(found) == 1 and name in found[0], f"({found})")
        check(f"{name}: the command fails", linux_bundle.main(["check", folder]) == 1)


def test_what_the_systems_libxcb_brings_is_not_carried(tmp_path):
    """The system's libxcb needs libXau and libXdmcp (measured), so they are there."""
    for name in ("libXau.so.6", "libXdmcp.so.6", "libbsd.so.0", "libmd.so.0"):
        found = linux_bundle.problems(_bundle(tmp_path / name, GOOD + (f"_internal/{name}",)))
        check(f"{name} is caught", len(found) == 1 and "from the system" in found[0], f"({found})")


def test_modules_the_program_never_uses_are_not_carried(tmp_path):
    for name in ("python3.15/lib-dynload/_bz2.cpython-315-x86_64-linux-gnu.so",
                 "python3.15/lib-dynload/_lzma.cpython-315-x86_64-linux-gnu.so",
                 "python3.15/lib-dynload/_zstd.cpython-315-x86_64-linux-gnu.so",
                 "liblzma.so.5", "libzstd.so.1"):
        found = linux_bundle.problems(_bundle(tmp_path / name.replace("/", "_"),
                                              GOOD + (f"_internal/{name}",)))
        check(f"{name} is caught", len(found) == 1 and "never uses" in found[0], f"({found})")
    check("a module that only starts like one stays",
          not linux_bundle.not_needed("_bz2x.cpython-315.so"))


def test_a_bundle_missing_what_it_must_carry_fails(tmp_path):
    """Measured: without libXft, a system that lacks it opens no window."""
    # Written out, not read from MUST_CARRY: a part dropped from the list would
    # otherwise drop out of this test too (a mutation measured exactly that).
    for part in ("libtk", "libXft.so", "libebpfdivert.so"):
        folder = _bundle(tmp_path / part, [n for n in GOOD if part not in n])
        found = linux_bundle.problems(folder)
        check(f"no {part}: caught", found == [f"does not carry {part}"], f"({found})")
    check("no folder at all fails", linux_bundle.problems(str(tmp_path / "none")) != [])


def test_libraries_the_bundle_keeps_are_not_mistaken_for_the_systems():
    for name in ("libXft.so.2", "libX11.so.6", "libpython3.15.so.1.0", "libz.so.1",
                 "libffi.so.8"):
        check(f"{name} stays", not linux_bundle.taken_from_system(name))
    check("a path is judged by its file name",
          linux_bundle.taken_from_system("/x/_internal/libfreetype.so.6"))


def test_a_wrong_command_line_is_refused(capsys):
    check("usage", linux_bundle.main([]) == 2 and "usage" in capsys.readouterr().err)
