"""
build.py — One-click build script for Air Assault
Run this file with:  python build.py
It will install all required packages and produce dist/AirAssault.exe
"""

import subprocess
import sys
import os
import shutil

# ── 0. Python version check ──────────────────────────────────────────
def check_python_version():
    major = sys.version_info.major
    minor = sys.version_info.minor
    print(f"  Python version: {major}.{minor}")
    if major == 3 and minor >= 13:
        print()
        print("  WARNING: You are running Python 3.{}.".format(minor))
        print("  pygame does not have pre-built wheels for Python 3.13+.")
        print()
        print("  Please install Python 3.12 from:")
        print("  https://www.python.org/downloads/release/python-3128/")
        print()
        print("  After installing Python 3.12, run this script again using:")
        print("    py -3.12 build.py")
        print()
        input("  Press Enter to exit...")
        sys.exit(1)

# ── 1. Packages to install before building ──────────────────────────
REQUIRED = ["pygame", "pyinstaller", "qrcode", "setuptools"]

def install(package):
    print(f"  Installing {package}...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", package,
         "--quiet", "--no-warn-script-location"],
    )
    if result.returncode != 0:
        print(f"\n  ERROR: Failed to install {package}.")
        print("  Try running manually:")
        print(f"    pip install {package}")
        input("\n  Press Enter to exit...")
        sys.exit(1)

# ── 2. Clean previous build artefacts ───────────────────────────────
def clean():
    for folder in ("build", "dist", "__pycache__"):
        if os.path.exists(folder):
            shutil.rmtree(folder)
            print(f"  Removed old {folder}/")
    for f in os.listdir("."):
        if f.endswith(".spec"):
            os.remove(f)
            print(f"  Removed old {f}")

# ── 3. Build command ─────────────────────────────────────────────────
def build():
    sep = ";" if sys.platform == "win32" else ":"
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", "AirAssault",
        "--collect-all", "pygame",
        "--collect-all", "qrcode",
        "--add-data", f"assets{sep}assets",
        "--hidden-import", "pygame",
        "--hidden-import", "pygame.locals",
        "--hidden-import", "pygame.mixer",
        "--hidden-import", "pygame.font",
        "--hidden-import", "pygame.image",
        "--hidden-import", "pygame.transform",
        "--hidden-import", "pygame.display",
        "--hidden-import", "pygame.event",
        "--hidden-import", "pygame.key",
        "--hidden-import", "pygame.mouse",
        "--hidden-import", "pygame.time",
        "--hidden-import", "pygame.sprite",
        "--hidden-import", "pygame.draw",
        "--hidden-import", "pygame.surface",
        "--hidden-import", "qrcode.image.pure",
        "t.py",
    ]
    if os.path.exists("icon.ico"):
        cmd += ["--icon", "icon.ico", "--add-data", f"icon.ico{sep}."]
    print("\n  Running PyInstaller...\n")
    result = subprocess.run(cmd)
    return result.returncode == 0


# ── Main ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 52)
    print("  Air Assault — Build Script")
    print("=" * 52)

    # Check Python version first
    print("\n[ Step 0 ] Checking Python version...")
    check_python_version()
    print("  OK.")

    # Check t.py exists
    if not os.path.exists("t.py"):
        print("\n  ERROR: t.py not found.")
        print("  Run this script from the same folder as t.py.")
        input("\n  Press Enter to exit...")
        sys.exit(1)

    # Check assets folder exists
    if not os.path.exists("assets"):
        print("\n  ERROR: assets/ folder not found.")
        print("  Make sure the assets folder is in the same folder as t.py.")
        input("\n  Press Enter to exit...")
        sys.exit(1)

    # Check icon exists
    if not os.path.exists("icon.ico"):
        print("\n  WARNING: icon.ico not found.")
        print("  The exe will build without a custom icon.")
        print("  Place icon.ico in the same folder as t.py to add one.")

    # Install packages
    print("\n[ Step 1 ] Installing required packages...")
    for pkg in REQUIRED:
        install(pkg)
    print("  Done.")

    # Clean old build
    print("\n[ Step 2 ] Cleaning old build files...")
    clean()
    print("  Done.")

    # Build
    print("\n[ Step 3 ] Building AirAssault.exe...")
    success = build()

    # Result
    print("\n" + "=" * 52)
    exe_path = os.path.join("dist", "AirAssault.exe")
    if success and os.path.exists(exe_path):
        size_mb = os.path.getsize(exe_path) / (1024 * 1024)
        print(f"  BUILD SUCCESSFUL!")
        print(f"  Output : dist/AirAssault.exe  ({size_mb:.1f} MB)")
        print(f"  Share the dist/AirAssault.exe file with players.")
    else:
        print("  BUILD FAILED.")
        print("  Check the error messages above.")
        print("  Common fixes:")
        print("    - Make sure t.py and assets/ are in the same folder")
        print("    - Try running as Administrator")
        print("    - Delete build/ and dist/ folders and try again")
    print("=" * 52)
    input("\n  Press Enter to exit...")