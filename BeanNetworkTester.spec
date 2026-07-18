# BeanNetworkTester.spec - build with:  pyinstaller BeanNetworkTester.spec
#
# Four deliberate choices, each of them a bug fix:
#
# 1. console=True (NOT --noconsole).
#    A GUI-subsystem exe has no stdout/stderr, and cmd.exe/PowerShell do not
#    even WAIT for it - a CI step could never read its output nor its exit code.
#    The one binary therefore lives in the console subsystem and the GUI detaches
#    from the console at startup (winenv.detach_console), so a double-click does
#    not leave a black window behind.
#
# 2. onedir (COLLECT), NOT --onefile.
#    pydivert ships WinDivert.dll + WinDivert64.sys. With --onefile they were
#    unpacked into %TEMP%\_MEIxxxxx on every start and the KERNEL loaded the
#    driver from there - so the kernel kept an open handle on the .sys file and
#    the temp directory could not be deleted (not by the app, not by the user,
#    not until a reboot). Shipping a folder keeps the driver at a stable path
#    next to the exe.
#
# 3. uac_admin=False (asInvoker).
#    requireAdministrator always spawns a NEW elevated process: the caller's
#    pipes and exit code are lost, which breaks CI - and --simulate needs no
#    admin at all. The GUI asks for elevation itself (winenv.elevate_self) and
#    the CLI fails fast with exit code 7 (PERMISSION) when it needs rights it
#    does not have.
# 4. version_info.
#    Without it the exe's Properties -> Details sheet is EMPTY: no product name,
#    no author, no version. A tool that asks for Administrator rights had better
#    be able to say who wrote it. The number itself comes from VERSION.txt (via
#    appinfo) - never edit a version literal here.
#
# 5. The legal files travel WITH the program.
#    LICENSE, THIRD-PARTY-NOTICES.md and licenses/ are bundled so the GUI ("About")
#    and "--license" can show them from any copy of the app. build.py additionally
#    places human-readable copies NEXT TO the exe: PyInstaller 6 puts datas inside
#    _internal/, and a licence nobody can find is a licence nobody reads.
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs
from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo,
                                                 StringStruct, StringTable,
                                                 VarFileInfo, VarStruct,
                                                 VSVersionInfo)

sys.path.insert(0, os.path.abspath("."))
from beantester.appinfo import (APP_NAME, AUTHOR, COPYRIGHT, EXE_NAME,
                                VERSION_FILE, __version__)

if __version__ == "0.0.0":
    raise SystemExit("BeanNetworkTester.spec: VERSION.txt is missing or malformed "
                     "(expected x.y.z). Refusing to build an exe with no version.")

_v = tuple(int(part) for part in __version__.split(".")[:3]) + (0,)

version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=_v, prodvers=_v, mask=0x3F, flags=0x0, OS=0x40004,
                      fileType=0x1, subtype=0x0),
    kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("CompanyName", AUTHOR),
            StringStruct("FileDescription", f"{APP_NAME} - poor network conditions simulator"),
            StringStruct("FileVersion", __version__),
            StringStruct("InternalName", "BeanNetworkTester"),
            StringStruct("LegalCopyright", COPYRIGHT),
            StringStruct("OriginalFilename", EXE_NAME),
            StringStruct("ProductName", APP_NAME),
            StringStruct("ProductVersion", __version__),
        ])]),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)

datas = [("lang", "lang"), (VERSION_FILE, "."), ("LICENSE", "."),
         ("THIRD-PARTY-NOTICES.md", "."), ("licenses", "licenses"),
         ("scenarios", "scenarios")]
for icon in ("bean.png", "bean.ico"):
    if os.path.exists(icon):
        datas.append((icon, "."))

# WinDivert.dll / WinDivert64.sys live inside the pydivert package
datas += collect_data_files("pydivert")
binaries = collect_dynamic_libs("pydivert")

a = Analysis(
    ["bean_network_tester.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=["pydivert", "psutil"],
    hookspath=[],
    runtime_hooks=[],
    # ssl/_ssl/_hashlib pull in OpenSSL (libcrypto ~6 MB + libssl ~1.3 MB). The app
    # has ZERO network TLS (convention 36: no telemetry) - `import bean_network_tester`
    # never touches `ssl` - and its only hashing is crashlog's sha1 fingerprint, which
    # `hashlib` computes via the built-in `_sha1` module when `_hashlib` is absent
    # (verified). Dropping them is ~7 MB off the release at no runtime cost.
    excludes=["pytest", "ssl", "_ssl", "_hashlib"],
    noarchive=False,
)

# Performance > size (PROJECT_NOTES): a trim may only shrink the release footprint,
# never touch startup or runtime. onedir does NOT unpack at launch, so dropping
# files does not speed startup - it only makes the folder next to the exe smaller.
# Tcl bundles the full IANA timezone database (_tcl_data/tzdata, ~600 files) and its
# own msgcat message catalogs (_tcl_data/msgs, _tk_data/msgs). This tool uses
# Python's time (never Tcl's [clock]) and its own i18n (lang/*.json), so those ~750
# files are dead weight. Encodings are KEPT (Tk needs them). OpenSSL (libcrypto/libssl)
# is dropped via the Analysis `excludes` above - see the note there.
_TCL_CRUFT = ("_tcl_data/tzdata/", "_tcl_data/msgs/", "_tk_data/msgs/")
a.datas = [d for d in a.datas
           if not any(part in d[0].replace("\\", "/") for part in _TCL_CRUFT)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,          # onedir
    name="BeanNetworkTester",
    icon="bean.ico" if os.path.exists("bean.ico") else None,
    console=True,                   # the CLI must have stdout/stderr and an exit code
    uac_admin=False,                # asInvoker - the app elevates itself when needed
    version=version_info,           # exe Properties -> Details (author, version)
    debug=False,
    strip=False,
    upx=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="BeanNetworkTester",       # dist\BeanNetworkTester\BeanNetworkTester.exe
)
