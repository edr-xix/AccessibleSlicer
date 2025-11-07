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


REPO_ROOT = os.path.dirname(__file__)
SRC_ENTRY = os.path.join(REPO_ROOT, 'Source', 'main.py')
APP_NAME = 'AccessibleSlicer'


def run(cmd):
    print('> ' + cmd)
    completed = subprocess.run(cmd, shell=True)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


# Executable build, one-folder, Adjust --add-data to include any non-python assets.
def build_windows():

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
