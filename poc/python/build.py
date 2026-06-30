#!/usr/bin/env python3
"""
Build script for Walksnail Ground Station standalone app.

Usage:
    python build.py              # build for current platform
    python build.py --clean      # delete dist/ build/ first
    python build.py --zip        # also create a distributable zip

Output:
    dist/WalksnailGS/            → folder (all platforms)
    dist/WalksnailGS.app         → macOS app bundle (double-click to run)
    dist/WalksnailGS-mac.zip     → macOS distributable
    dist/WalksnailGS-win.zip     → Windows distributable
"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"


def run(cmd: list[str], **kw) -> None:
    print(f"\n  $ {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, **kw)
    if result.returncode != 0:
        print(f"\n  ❌ Command failed with exit code {result.returncode}")
        sys.exit(result.returncode)


def clean() -> None:
    print("  Cleaning dist/ and build/…")
    shutil.rmtree(DIST, ignore_errors=True)
    shutil.rmtree(BUILD, ignore_errors=True)
    print("  ✓ Clean done")


def build() -> None:
    print(f"\n  Building for {platform.system()} ({platform.machine()})…")
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "walksnail.spec"],
        cwd=ROOT)


def make_zip() -> None:
    system = platform.system().lower()
    arch = platform.machine().lower()
    tag = {"darwin": "mac", "windows": "win", "linux": "linux"}.get(system, system)
    zip_name = f"WalksnailGS-{tag}-{arch}.zip"
    zip_path = DIST / zip_name

    # What to zip depends on platform
    if system == "darwin":
        source = DIST / "WalksnailGS.app"
        if not source.exists():
            print(f"  ⚠ {source} not found — zipping folder instead")
            source = DIST / "WalksnailGS"
    else:
        source = DIST / "WalksnailGS"

    print(f"\n  Creating {zip_name}…")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        if source.is_dir():
            for file in source.rglob("*"):
                if file.is_file():
                    zf.write(file, file.relative_to(DIST))
        else:
            zf.write(source, source.name)

    size_mb = zip_path.stat().st_size / 1024 / 1024
    print(f"  ✓ {zip_name} ({size_mb:.0f} MB)")
    return zip_path


def verify() -> None:
    """Quick sanity check — run the built binary with --help."""
    system = platform.system().lower()
    if system == "darwin":
        exe = DIST / "WalksnailGS" / "WalksnailGS"
    elif system == "windows":
        exe = DIST / "WalksnailGS" / "WalksnailGS.exe"
    else:
        exe = DIST / "WalksnailGS" / "WalksnailGS"

    if not exe.exists():
        print(f"  ⚠ Executable not found at {exe}, skipping verify")
        return

    print(f"\n  Verifying {exe}…")
    result = subprocess.run([str(exe), "--help"],
                            capture_output=True, text=True, timeout=30)
    if result.returncode == 0:
        print("  ✓ Binary runs correctly")
    else:
        print(f"  ⚠ Binary returned {result.returncode}")
        print(result.stderr[:500])


def print_summary() -> None:
    system = platform.system().lower()
    print("\n" + "=" * 58)
    print("  ✅  BUILD COMPLETE")
    print("=" * 58)

    if system == "darwin":
        print("""
  macOS:
    • dist/WalksnailGS.app  → drag to /Applications and open
    • dist/WalksnailGS-mac-*.zip → share this file

  First run on another Mac:
    If macOS says "unidentified developer":
    Right-click → Open → Open (once only)
""")
    elif system == "windows":
        print("""
  Windows:
    • dist\\WalksnailGS\\WalksnailGS.exe → run directly
    • dist\\WalksnailGS-win-*.zip → share this folder zipped

  First run on another PC:
    Windows Defender may warn → "More info" → "Run anyway"
    This is normal for unsigned apps.
""")
    else:
        print("""
  Linux:
    • dist/WalksnailGS/WalksnailGS → run directly
    • chmod +x dist/WalksnailGS/WalksnailGS first if needed
""")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Walksnail GS standalone app")
    parser.add_argument("--clean", action="store_true", help="Delete dist/ build/ first")
    parser.add_argument("--zip", action="store_true", help="Create distributable zip")
    parser.add_argument("--no-verify", action="store_true", help="Skip post-build verify")
    args = parser.parse_args()

    if args.clean:
        clean()

    build()

    if not args.no_verify:
        verify()

    if args.zip:
        make_zip()

    print_summary()


if __name__ == "__main__":
    main()
