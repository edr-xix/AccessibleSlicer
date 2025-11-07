"""
Helper to run PyInstaller with recommended options for this project.

Notes:
- PyInstaller must be installed in the environment used to build.
- Building for each operating system should be done on the respective OS for best results.
- This script uses a conservative one-folder build which often handles PyQt6 resources better; change to --onefile if you prefer a single binary.
"""
import argparse
import os
import platform
import shlex
import subprocess
import sys
import time
import stat
import signal
import ctypes
from shutil import rmtree


REPO_ROOT = os.path.dirname(__file__)
SRC_ENTRY = os.path.join(REPO_ROOT, 'Source', 'main.py')
APP_NAME = 'AccessibleSlicer'


def run(cmd):
    print('> ' + cmd)
    completed = subprocess.run(cmd, shell=True)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def _clear_readonly_and_rmtree(path: str):
    """Attempt to remove a directory tree, clearing readonly flags and retrying.

    This helps when DLLs or files have readonly attributes. If a file is locked
    by a running process, deletion will still fail; the caller should ensure the
    process is stopped first.
    """
    def _onerror(func, p, exc_info):
        # Try to clear read-only attribute and retry
        try:
            os.chmod(p, stat.S_IWRITE)
        except Exception:
            pass
        try:
            func(p)
        except Exception:
            pass

    # Try a few times with short sleeps to allow handles to close
    for attempt in range(3):
        try:
            if os.path.exists(path):
                rmtree(path, onerror=_onerror)
            return True
        except Exception:
            time.sleep(0.5)
    return False

# Executable build, one-folder, Adjust --add-data to include any non-python assets.
def build_windows():
    # Remove previous dist folder safely
    dist_path = os.path.join(REPO_ROOT, 'dist', 'windows', APP_NAME)
    if os.path.exists(dist_path):
        ok = _clear_readonly_and_rmtree(dist_path)
        if not ok:
            print(f"WARNING: Could not fully remove {dist_path}. Please ensure the app is not running and remove it manually.")

    cmd = (
        f"python -m PyInstaller --noconfirm --clean --windowed --name {APP_NAME} "
        f"--add-data \"{os.path.join(REPO_ROOT, 'Source', 'config.json')};.\" "
        f"--distpath dist/windows --workpath build/windows --specpath build/windows_spec "
        f"\"{SRC_ENTRY}\""
    )
    run(cmd)

# Create Linux executable, can't test this since I'm on windows.
def build_linux():
    cmd = (
        f"python -m PyInstaller --noconfirm --clean --windowed --name {APP_NAME} "
        f"--add-data \"{os.path.join(REPO_ROOT, 'Source', 'config.json')}:.;\" "
        f"--distpath dist/linux --workpath build/linux --specpath build/linux_spec "
        f"\"{SRC_ENTRY}\""
    )
    run(cmd)


# Create macOS .app bundle, can't test this since I'm on windows.
def build_macos():
    cmd = (
        f"python -m PyInstaller --noconfirm --clean --windowed --name {APP_NAME} "
        f"--add-data \"{os.path.join(REPO_ROOT, 'Source', 'config.json')}:.;\" "
        f"--distpath dist/macos --workpath build/macos --specpath build/macos_spec "
        f"\"{SRC_ENTRY}\""
    )
    run(cmd)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--target', choices=['windows', 'linux', 'macos'], required=True)
    args = parser.parse_args()

    host = platform.system().lower()
    print('Host platform detected:', host)

    if args.target == 'macos' and host != 'darwin':
        print('ERROR: macOS builds must be run on macOS (darwin).')
        sys.exit(2)
    if args.target == 'windows' and host not in ('windows', 'darwin', 'linux'): # Allow building on Windows; warn for cross-platform attempts.
        print('WARNING: Building for Windows is typically done on Windows for best results.')

    if args.target == 'windows':
        build_windows()
    elif args.target == 'linux':
        build_linux()
    elif args.target == 'macos':
        build_macos()


if __name__ == '__main__':
    main()
