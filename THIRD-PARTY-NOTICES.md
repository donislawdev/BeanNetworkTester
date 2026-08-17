# Third-Party Notices

Bean Network Tester is free software licensed under the **GNU General Public
License, version 3** (see `LICENSE`), but it does not stand on its own: it ships
and uses components written by other people, under their own licences. This file
names every one of them, says which licence it is used under, and tells you where
to get its source code. The full licence texts are in the `licenses/` directory
next to the program.

Nothing in the Bean Network Tester licence limits your rights under any of the
licences below. Where they conflict, the licence below wins for that component.

To see the exact versions bundled in the copy you are holding, run:

    BeanNetworkTester.exe --license

---

## WinDivert (`WinDivert64.dll`, `WinDivert64.sys`)

* Copyright (c) basil (basil@reqrypt.org)
* Used under: **GNU Lesser General Public License, version 3 (LGPLv3)**
  (WinDivert is dual-licensed under LGPLv3 or GPLv2, at the user's choice; this
  program uses it under the LGPLv3.)
* Licence text: `licenses/WinDivert-LICENSE.txt` (contains LGPLv3, GPLv3 and GPLv2)
* Homepage: https://reqrypt.org/windivert.html
* Source code: https://github.com/basil00/WinDivert
* Shipped as: a stand-alone DLL and a stand-alone kernel driver, in
  `_internal\pydivert\windivert_dll\`. They are **not** compiled into
  `BeanNetworkTester.exe`.

**Your LGPL rights, in practice.** You may modify WinDivert and use your modified
version with this program: build (or download) an interface-compatible
`WinDivert64.dll` / `WinDivert64.sys` and replace the two files in
`_internal\pydivert\windivert_dll\`. The program loads them from that folder at
run time and will use whatever it finds there. You may reverse engineer Bean
Network Tester to the extent necessary to debug such modifications.

**Where the folder is.** `_internal` sits next to `BeanNetworkTester.exe`. That the
libraries are separate files you can swap, rather than code melted into the
executable, is the reason this program is built as a folder and not as a single
file: it is what makes the paragraph above something you can actually do.

**Driver signing.** The `WinDivert64.sys` driver shipped here is the official,
digitally signed build from the WinDivert project. If you replace it with a driver
you compiled yourself, Windows will refuse to load it unless it is signed (or the
machine is in test-signing mode). That is a Windows requirement, not ours.

---

## PyDivert

* Copyright (c) Fabio Falcinelli and PyDivert contributors
* Used under: **GNU Lesser General Public License, version 3 or later
  (LGPL-3.0-or-later)**
  (PyDivert is dual-licensed under LGPL-3.0-or-later or GPL-2.0-or-later, at the
  user's choice; this program uses it under the LGPL.)
* Licence text: `licenses/PyDivert-LICENSE.txt`, `licenses/LGPL-3.0.txt`,
  `licenses/GPL-3.0.txt`, `licenses/GPL-2.0.txt`
* Homepage / source code: https://github.com/ffalcinelli/pydivert
* Released source of the exact version used in this build:
  `https://pypi.org/project/pydivert/<version>/#files` (the version is printed by
  `BeanNetworkTester.exe --license`)
* PyDivert is used **unmodified**.

**Your LGPL rights, in practice.** PyDivert is a pure-Python library, and its code
is compiled into `BeanNetworkTester.exe` rather than left on disk beside it. That
matters for how you replace it, so here is the accurate answer rather than the
convenient one: **dropping a modified `pydivert` package into `_internal\` does
not work.** The copy inside the executable wins, and it wins quietly - the
replaced module even reports the path you put your files at, so it looks like it
was picked up when it was not. (Measured against a frozen build, 2026-08-04.)

What does work, and what the licence entitles you to:

* **Rebuild this application against your version.** The complete source of Bean
  Network Tester is public at https://github.com/donislawdev/BeanNetworkTester
  under the GPLv3, and the build is one command (`pyinstaller
  BeanNetworkTester.spec`). Install your modified PyDivert into the build
  environment and the result uses it.
* **Or run it from source**, where PyDivert is an ordinary installed package and
  replacing it needs nothing but `pip install`.

**Written offer:** for at least three years from the date of this release, the
Author will supply, on request and at no charge beyond the cost of delivery, the
complete corresponding source of the PyDivert version used in this build. You do
not need to take up that offer to get it - the released source of the exact
version is linked above. Contact: https://donislawdev.com/

---

## psutil

* Copyright (c) 2009, Jay Loden, Dave Daeschler, Giampaolo Rodola
* Used under: **BSD 3-Clause License**
* Licence text: `licenses/psutil-LICENSE.txt`
* Source code: https://github.com/giampaolo/psutil
* Used unmodified. Bean Network Tester uses it to resolve process names and, on
  non-Windows platforms and in tests, socket tables.

---

## Python (CPython)

* Copyright (c) 2001-2026 Python Software Foundation. All Rights Reserved.
* Used under: **PSF License Agreement**
* Licence text: `licenses/Python-LICENSE.txt`
* Source code: https://www.python.org/downloads/source/
* The Python interpreter and standard library are embedded in the executable.

---

## Tcl/Tk (used through Python's `tkinter`)

* Copyright (c) Regents of the University of California, Sun Microsystems Inc.,
  Scriptics Corporation, and other parties
* Used under: **Tcl/Tk licence (BSD-style)**
* Licence text: `licenses/Tcl-Tk-LICENSE.txt`
* Source code: https://www.tcl-lang.org/software/tcltk/
* Provides the graphical user interface toolkit.

---

## PyInstaller (bootloader)

* Copyright (c) 2010-2023, PyInstaller Development Team;
  Copyright (c) 2005-2009, Giovanni Bajo; based on previous work under
  copyright (c) 2002 McMillan Enterprises, Inc.
* Used under: **GPL 2.0 or later, with the PyInstaller bootloader exception**,
  which explicitly permits using PyInstaller to build and distribute
  non-free (proprietary) programs.
* Licence text: `licenses/PyInstaller-COPYING.txt`
* Source code: https://github.com/pyinstaller/pyinstaller
* Only the PyInstaller bootloader is part of the shipped executable.

---

## zlib

* Copyright (C) 1995-2024 Jean-loup Gailly and Mark Adler
* Used under: **zlib licence** (permissive)
* Licence text: `licenses/zlib-LICENSE.txt`
* Source code: https://www.zlib.net/
* Ships as `zlib1.dll` beside the executable, as part of the CPython Windows
  runtime. `--license` reports the version the build links against; note that it
  can read `1.3.1.zlib-ng`, because the `zlib` MODULE is built against zlib-ng
  while the DLL itself is genuine zlib. Both are under this licence.

---

## libffi

* Copyright (c) 1996-2022 Anthony Green, Red Hat, Inc and others
* Used under: **MIT-style licence**
* Licence text: inside `licenses/Python-LICENSE.txt`, in CPython's section for
  incorporated software - libffi arrives with CPython and is licensed there
* Source code: https://github.com/libffi/libffi
* Ships as `libffi-8.dll`; it is what `ctypes` calls into, and this project
  reaches the WinDivert driver and several Windows APIs through `ctypes`.

---

## libtommath

* Copyright: none claimed - the authors dedicate the work to the public domain
* Used under: **the Unlicense** (a public-domain dedication)
* Licence text: `licenses/libtommath-LICENSE.txt`
* Source code: https://github.com/libtom/libtommath
* Ships as `libtommath.dll`, as part of the CPython Windows runtime. Python 3.14
  ships Tcl/Tk 9.0, and Tcl 9 links libtommath for its arbitrary-precision
  integer arithmetic. Nothing in this project calls it directly - it arrives
  because the graphical interface needs Tk.

---

## Microsoft C Runtime (`ucrtbase.dll`, `VCRUNTIME140*.dll`, `api-ms-win-*.dll`)

* Copyright (c) Microsoft Corporation
* Used under: **Microsoft's redistributable terms** for the Visual C++ runtime
  and the Universal CRT, which permit shipping these files alongside an
  application
* Licence text: not bundled - Microsoft distributes the terms rather than a text
  to include; see the link below
* Terms: https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files
* These arrive with the CPython Windows runtime, not from this project directly.
  They are the C runtime the interpreter and its extension modules are built
  against.
* It is a larger set than it looks: **42 files, more than half the bundle by
  count** - `ucrtbase.dll`, `VCRUNTIME140.dll`, `VCRUNTIME140_1.dll` and 39
  `api-ms-win-core-*` / `api-ms-win-crt-*` ApiSet stubs (version 10.0.26100.8249,
  Microsoft Corporation). The stubs are easy to mistake for Windows itself rather
  than for something shipped alongside the program, which is exactly why they are
  named here.

---

## Artwork and everything else

The application icon, the drawn-in-code widgets (the checkbox indicator, the bean
icon fallback), the theme, the translations and all remaining source code are the
work of the Author and are covered by `LICENSE`. No third-party icon set, font or
artwork is bundled: the interface uses the fonts already installed on the system.

## Telemetry

None. Bean Network Tester does not phone home. It contains no analytics, no crash
reporting service, no update check and no network client of any kind: the only
network traffic it touches is the traffic it is capturing on your own machine, and
that data never leaves the machine. The only outbound connection the program can
ever make is opening `https://donislawdev.com/` in **your** browser, and only when
you click the support button yourself.
