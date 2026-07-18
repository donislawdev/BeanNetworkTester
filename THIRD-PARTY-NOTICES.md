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

## WinDivert (`WinDivert.dll`, `WinDivert64.sys`)

* Copyright (c) basil (basil@reqrypt.org)
* Used under: **GNU Lesser General Public License, version 3 (LGPLv3)**
  (WinDivert is dual-licensed under LGPLv3 or GPLv2, at the user's choice; this
  program uses it under the LGPLv3.)
* Licence text: `licenses/WinDivert-LICENSE.txt` (contains LGPLv3, GPLv3 and GPLv2)
* Homepage: https://reqrypt.org/windivert.html
* Source code: https://github.com/basil00/WinDivert
* Shipped as: a stand-alone DLL and a stand-alone kernel driver, inside
  `_internal\pydivert\`. They are **not** compiled into `BeanNetworkTester.exe`.

**Your LGPL rights, in practice.** You may modify WinDivert and use your modified
version with this program: build (or download) an interface-compatible
`WinDivert.dll` / `WinDivert64.sys` and replace the files shipped in
`_internal\pydivert\`. The program loads them from that path at run time and will
use whatever it finds there. You may reverse engineer Bean Network Tester to the
extent necessary to debug such modifications.

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

**Your LGPL rights, in practice.** PyDivert is a pure-Python library. It is bundled
inside this application, and you may replace it with your own modified,
interface-compatible version: put your modified `pydivert` package in
`_internal\pydivert\` (Python packages there take precedence over the bundled
copy), or rebuild the application against your version. **Written offer:** for as
long as this release is distributed, the Author will supply, on request and at no
charge beyond the cost of delivery, the complete corresponding source of the
PyDivert version used in this build. Contact: https://donislawdev.com/

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
