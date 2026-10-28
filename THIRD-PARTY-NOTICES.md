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

    BeanNetworkTester.exe --license          (Windows)
    ./BeanNetworkTester --license            (Linux)

The Windows zip and the Linux `.tar.gz` carry different libraries. Each section says
which of the two carries it; one that says nothing is in both. The Linux package takes
some libraries from the system it runs on instead (fontconfig, freetype and the X
libraries libxcb needs); those are the system's own and are not shipped.

---

## WinDivert (`WinDivert64.dll`, `WinDivert64.sys`, the Windows zip)

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

## eBPFDivert (`libebpfdivert.so`, the Linux package)

* Copyright (c) Fabio Falcinelli and eBPFDivert contributors
* Used under: **GNU Lesser General Public License, version 3 or later
  (LGPL-3.0-or-later)**
  (eBPFDivert is dual-licensed under GPL-2.0-or-later or LGPL-3.0-or-later; this
  program uses it under the LGPL. It contains WinDivert's filter code, which carries
  the same dual licence.)
* Licence text: `licenses/LGPL-3.0.txt`, `licenses/GPL-3.0.txt`, `licenses/GPL-2.0.txt`
* Source code: https://github.com/ffalcinelli/ebpfdivert
* Shipped as: one library, `_internal/pydivert/bpf/libebpfdivert.so`, which comes
  with PyDivert's Linux wheel and is used unmodified. Its version is printed by
  `./BeanNetworkTester --license`. It carries libbpf, elfutils' libelf, Zstandard
  and zlib inside it (their sections are below).

**Your LGPL rights, in practice.** The library is a separate file the program loads
from that folder at run time. You may build an interface-compatible
`libebpfdivert.so` from eBPFDivert's source - with a modified libbpf, libelf,
Zstandard or zlib inside, if you like - and replace the file. You may reverse
engineer Bean Network Tester to the extent necessary to debug such modifications.

**Written offer:** for at least three years from the date of this release, the
Author will supply, on request and at no charge beyond the cost of delivery, the
complete corresponding source of the eBPFDivert version in this build, with the
libbpf and libelf it carries. The source is public at the address above. Contact:
https://donislawdev.com/

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
* The Python interpreter and standard library are embedded in the executable. In
  the Linux package the interpreter is `_internal/libpython3.*.so`.

---

## Tcl/Tk (used through Python's `tkinter`)

* Copyright (c) Regents of the University of California, Sun Microsystems Inc.,
  Scriptics Corporation, and other parties
* Used under: **Tcl/Tk licence (BSD-style)**
* Licence text: `licenses/Tcl-Tk-LICENSE.txt`
* Source code: https://www.tcl-lang.org/software/tcltk/
* Provides the graphical user interface toolkit. In the Linux package it is Tcl/Tk
  8.6 as Ubuntu 24.04 ships it (`libtcl8.6.so`, `libtk8.6.so`).

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
* In the Linux package: `libz.so.1` from Ubuntu 24.04 (zlib 1.3), and a copy
  inside `libebpfdivert.so`.

---

## libffi

* Copyright (c) 1996-2022 Anthony Green, Red Hat, Inc and others
* Used under: **MIT-style licence**
* Licence text: inside `licenses/Python-LICENSE.txt`, in CPython's section for
  incorporated software - libffi arrives with CPython and is licensed there
* Source code: https://github.com/libffi/libffi
* Ships as `libffi-8.dll`; it is what `ctypes` calls into, and this project
  reaches the WinDivert driver and several Windows APIs through `ctypes`. In the
  Linux package: `libffi.so.8` from Ubuntu 24.04 (libffi 3.4.6), through which
  `ctypes` reaches eBPFDivert.

---

## X.Org libraries (`libX11`, `libXext`, `libXft`, `libXrender`, `libXss`, the Linux package)

* Copyright: the X Consortium, The Open Group, Keith Packard and many others; each
  library's holders are listed in its own section of the licence file
* Used under: **MIT and X11-style permission notices** (permissive)
* Licence text: `licenses/X.Org-libraries.txt` - the copyright files Ubuntu 24.04
  ships with these libraries, unchanged
* Source code: https://gitlab.freedesktop.org/xorg/lib
* Ship as `_internal/libX11.so.6`, `libXext.so.6`, `libXft.so.2`, `libXrender.so.1`
  and `libXss.so.1`: libX11 1.8.7, libXext 1.3.4, libXft 2.3.6, libXrender 0.9.10 and
  libXss 1.2.3, as Ubuntu 24.04 builds them. Tk draws the window through them.

---

## libbpf (inside `libebpfdivert.so`, the Linux package)

* Copyright (c) the libbpf authors (Facebook, Isovalent and others)
* Used under: **GNU Lesser General Public License, version 2.1 (LGPL-2.1)**
  (libbpf is dual-licensed under LGPL-2.1 or BSD-2-Clause)
* Licence text: `licenses/LGPL-2.1.txt`, `licenses/libbpf-copyright.txt`
* Source code: https://github.com/libbpf/libbpf (eBPFDivert builds the version its
  source tree pins)
* What eBPFDivert loads its kernel programs with. Replacing it means rebuilding
  `libebpfdivert.so` - see eBPFDivert above.

---

## elfutils (libelf, inside `libebpfdivert.so`, the Linux package)

* Copyright (c) Red Hat, Inc. and the elfutils contributors
* Used under: **GNU Lesser General Public License, version 3 or later
  (LGPL-3.0-or-later)** (libelf is dual-licensed under LGPL-3.0-or-later or
  GPL-2.0-or-later)
* Licence text: `licenses/LGPL-3.0.txt`, `licenses/GPL-2.0.txt`,
  `licenses/elfutils-copyright.txt`
* Source code: https://sourceware.org/elfutils/
* What libbpf reads the kernel programs' object file with. Replacing it means
  rebuilding `libebpfdivert.so` - see eBPFDivert above.

---

## Zstandard (inside `libebpfdivert.so`, the Linux package)

* Copyright (c) Meta Platforms, Inc. and affiliates
* Used under: **BSD 3-Clause License** (Zstandard is dual-licensed under
  BSD-3-Clause or GPL-2.0)
* Licence text: `licenses/zstd-copyright.txt`
* Source code: https://github.com/facebook/zstd
* libelf's decompression; nothing in this program calls it directly.

---

## libtommath (the Windows zip)

* Copyright: none claimed - the authors dedicate the work to the public domain
* Used under: **the Unlicense** (a public-domain dedication)
* Licence text: `licenses/libtommath-LICENSE.txt`
* Source code: https://github.com/libtom/libtommath
* Ships as `libtommath.dll`, as part of the CPython Windows runtime. Python ships
  Tcl/Tk 9 since 3.14, and Tcl 9 links libtommath for its arbitrary-precision
  integer arithmetic. Nothing in this project calls it directly - it arrives
  because the graphical interface needs Tk.

---

## Microsoft C Runtime (`ucrtbase.dll`, `VCRUNTIME140*.dll`, `api-ms-win-*.dll`, the Windows zip)

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
reporting service, no update check and nothing that sends on its own: the traffic it
captures on your own machine never leaves the machine. Two things go out only when
you ask for them. One is a page opened in **your** browser - the support page
(`https://donislawdev.com/support/`) or the project's page on GitHub
(`https://github.com/donislawdev/BeanNetworkTester`) - when you click the button for
it yourself. The other is the **Ping** tool on the Tools tab: ICMP echo requests to
the address you type, from Start to Stop (a name you type is looked up first, as for
any program).
