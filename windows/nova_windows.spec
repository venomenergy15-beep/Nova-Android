# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller build spec for NOVA for Windows 7 (32-bit).

Reproduces the previous command-line build exactly:
    pyinstaller --onefile --windowed --name NOVA-Windows-7 windows/nova_windows.py
...with one addition: the Universal C Runtime (UCRT) DLLs are bundled into
the exe so it runs on Windows 7 machines that never received update KB2999226
or the Visual C++ Redistributable.

Why: Python 3.8 extension modules (_socket, _tkinter, ...) link against the
UCRT (api-ms-win-crt-*.dll -> ucrtbase.dll, plus vcruntime140.dll). That
runtime ships with Windows 10 but not with an unpatched Windows 7, so on such
a machine the exe died at startup with:
    DLL load failed while importing _socket: The parameter is incorrect.
Bundling the DLLs makes the exe self-contained: the PyInstaller bootloader
extracts them next to the app and they take precedence over the system's
(stale or missing) copies.

ucrtbase.dll itself forwards to the api-ms-win-core-*.dll API-set DLLs
(e.g. api-ms-win-core-sysinfo-l1-2-0.dll), which are also absent from an
unpatched Windows 7 — the first UCRT-bundled build fixed the _socket error
but then failed asking for one of those. So the whole api-ms-win-*.dll set
is bundled, not just the crt ones.

The DLLs are collected at build time from the runner's SysWOW64 directory
(32-bit DLLs on a 64-bit runner), falling back to System32 (32-bit runner).
Any DLL that is not present is skipped silently; if none are found the build
still succeeds and a warning is printed to the build log.
"""

import glob
import os

# Directory containing this spec file (windows/), resolved robustly whether
# the build is run from the repo root or from inside windows/.
try:
    SPEC_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:  # pragma: no cover - __file__ is normally defined
    # Fall back to locating the script relative to the working directory.
    if os.path.isfile(os.path.join('windows', 'nova_windows.py')):
        SPEC_DIR = os.path.abspath('windows')
    else:
        SPEC_DIR = os.path.abspath('.')


def _ucrt_dlls():
    """Return [(source_path, '.')] for the UCRT + API-set DLLs to bundle.

    SysWOW64 is checked first because on a 64-bit runner it holds the 32-bit
    DLLs this 32-bit build needs; System32 on such a machine holds the
    64-bit copies, which must NOT be bundled. On a 32-bit runner SysWOW64
    does not exist and System32 holds the 32-bit DLLs.
    """
    system_root = os.environ.get('SystemRoot', r'C:\Windows')
    folders = [
        os.path.join(system_root, 'SysWOW64'),
        os.path.join(system_root, 'System32'),
    ]
    # api-ms-win-*.dll covers both the crt set (api-ms-win-crt-*.dll) and
    # the core set (api-ms-win-core-*.dll) that ucrtbase.dll forwards to.
    patterns = ('api-ms-win-*.dll', 'ucrtbase.dll', 'vcruntime140.dll')
    found = []
    seen = set()
    for folder in folders:
        for pattern in patterns:
            for path in sorted(glob.glob(os.path.join(folder, pattern))):
                name = os.path.basename(path).lower()
                if name in seen:
                    continue
                seen.add(name)
                found.append((path, '.'))
    if not found:
        print('WARNING: no UCRT DLLs found under %s; '
              'the exe will not be self-contained on Windows 7' % system_root)
    else:
        print('Bundling %d UCRT/API-set DLL(s): %s'
              % (len(found), ', '.join(sorted(seen))))
    return found


block_cipher = None


a = Analysis(
    [os.path.join(SPEC_DIR, 'nova_windows.py')],
    pathex=[SPEC_DIR],
    binaries=_ucrt_dlls(),
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='NOVA-Windows-7',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
