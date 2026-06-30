# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Walksnail Ground Station.

Bundles:
  - FastAPI + uvicorn (web server)
  - PyAV + FFmpeg dylibs/DLLs (RTSP decode)
  - OpenCV + its FFmpeg dylibs (JPEG encode)
  - NumPy
  - walksnail_client package
  - web/static/ (SPA frontend)

Build:
    pyinstaller walksnail.spec

Output:
    dist/WalksnailGS/          (folder with the app)
    dist/WalksnailGS.app       (macOS — after building on Mac)
    dist/WalksnailGS.exe       (Windows — after building on Windows)
"""

import os
import sys
from pathlib import Path
import site

# ── Locate installed packages ──────────────────────────────────────────────
site_pkgs = Path(site.getsitepackages()[0])

def pkg(name):
    p = site_pkgs / name
    if p.exists():
        return str(p)
    raise FileNotFoundError(f"Package not found: {name} in {site_pkgs}")


# ── Hidden imports needed for dynamic loading ──────────────────────────────
HIDDEN = [
    # uvicorn dynamic imports
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    # FastAPI / starlette
    "fastapi",
    "starlette.routing",
    "starlette.staticfiles",
    "starlette.responses",
    "starlette.websockets",
    "websockets",
    "websockets.legacy",
    "websockets.legacy.server",
    # PyAV
    "av",
    "av.audio",
    "av.video",
    "av.codec",
    "av.container",
    # OpenCV
    "cv2",
    # Standard library async
    "asyncio",
    "email.mime.text",
    "email.mime.multipart",
]

# ── Data files (non-Python resources to bundle) ───────────────────────────
datas = []

# SPA frontend
static_dir = Path("walksnail_client/web/static")
datas.append((str(static_dir), "static"))

# av FFmpeg shared libraries (macOS: .dylibs, Windows: .dlls)
av_dir = site_pkgs / "av"
if (av_dir / ".dylibs").exists():
    datas.append((str(av_dir / ".dylibs"), "av/.dylibs"))
if (av_dir / ".libs").exists():
    datas.append((str(av_dir / ".libs"), "av/.libs"))
# Windows: av ships DLLs in the package root
for dll in av_dir.glob("*.dll"):
    datas.append((str(dll), "av"))

# cv2 shared libraries
cv2_dir = site_pkgs / "cv2"
if (cv2_dir / ".dylibs").exists():
    datas.append((str(cv2_dir / ".dylibs"), "cv2/.dylibs"))
if (cv2_dir / ".libs").exists():
    datas.append((str(cv2_dir / ".libs"), "cv2/.libs"))
for dll in cv2_dir.glob("*.dll"):
    datas.append((str(dll), "cv2"))

# h11 (uvicorn dependency)
h11_dir = site_pkgs / "h11"
if h11_dir.exists():
    datas.append((str(h11_dir), "h11"))

# anyio (starlette dependency)
anyio_dir = site_pkgs / "anyio"
if anyio_dir.exists():
    datas.append((str(anyio_dir), "anyio"))


# ── Analysis ───────────────────────────────────────────────────────────────
a = Analysis(
    ["app_launcher.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=HIDDEN,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Things we don't need in the bundle
        "tkinter",
        "matplotlib",
        "PIL",
        "scipy",
        "pandas",
        "IPython",
        "notebook",
        "jupyter",
        "pytest",
        "test",
        "tests",
        "unittest",
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

# ── EXE / App bundle ───────────────────────────────────────────────────────
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WalksnailGS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,          # Keep console so user sees the server URL
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon="assets/icon.icns",  # uncomment when you have an icon
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="WalksnailGS",
)

# macOS: wrap in a .app bundle
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="WalksnailGS.app",
        # icon="assets/icon.icns",
        bundle_identifier="com.walksnail.groundstation",
        info_plist={
            "CFBundleShortVersionString": "0.1.0",
            "CFBundleVersion": "0.1.0",
            "NSHighResolutionCapable": True,
            "LSUIElement": False,   # show in Dock
        },
    )
