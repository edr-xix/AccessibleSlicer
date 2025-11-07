"""Install helper for AccessibleSlicer builds.

This script detects the host platform and installs the built application from the
`dist/` folder into a sensible system location. It will also check for Python
packages the project depends on (PyQt6, pyserial) and optionally install them
using pip when missing. This helps make sure the build and tools used during
development and packaging behave correctly on the builder machine.

The script supports --dry-run, --yes (no prompt), --uninstall and prints helpful
diagnostics. It requires elevated privileges to write to system locations.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import platform
import shutil
import stat
import subprocess
import sys
from pathlib import Path


APP_NAME = "AccessibleSlicer"
DIST_DIR = Path(__file__).resolve().parent / "dist"

REQUIRED_PACKAGES = {
	"pyserial": "serial",
	"PyQt6": "PyQt6",
}


def is_admin() -> bool:
	if platform.system().lower() == "windows":
		try:
			import ctypes

			return ctypes.windll.shell32.IsUserAnAdmin() != 0
		except Exception:
			return False
	else:
		try:
			return os.geteuid() == 0
		except AttributeError:
			return False


def prompt_confirm(msg: str, assume_yes: bool) -> bool:
	if assume_yes:
		print(msg + " [AUTO-YES]")
		return True
	resp = input(msg + " [y/N]: ").strip().lower()
	return resp in ("y", "yes")


def make_executable(path: Path) -> None:
	try:
		mode = path.stat().st_mode
		path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
	except Exception:
		pass


def run_pip_install(package: str) -> int:
	cmd = [sys.executable, "-m", "pip", "install", package]
	print("Running:", " ".join(cmd))
	completed = subprocess.run(cmd)
	return completed.returncode


def check_and_install_dependencies(assume_yes: bool, dry_run: bool) -> None:
	"""Ensure required Python packages are importable; install with pip if missing.

	This installs into the Python environment used to run this script (sys.executable).
	"""
	missing = []
	for pkg, module_name in REQUIRED_PACKAGES.items():
		if importlib.util.find_spec(module_name) is None:
			missing.append(pkg)

	if not missing:
		print("All required Python packages are present.")
		return

	print("Missing Python packages:", ", ".join(missing))
	if dry_run:
		print("Dry-run: would install: ", ", ".join(missing))
		return

	if not assume_yes and not prompt_confirm(f"Install missing packages via pip? ({', '.join(missing)})", assume_yes):
		print("Skipping automatic dependency installation. You may need to install them manually.")
		return

	for pkg in missing:
		print(f"Installing {pkg}...")
		rc = run_pip_install(pkg)
		if rc != 0:
			print(f"Failed to install {pkg} (pip exit code {rc}). Aborting.")
			sys.exit(rc)
	print("Dependencies installed.")


def install_windows(target_root: Path, assume_yes: bool, dry_run: bool) -> None:
	src = DIST_DIR / "windows" / APP_NAME
	if not src.exists():
		raise FileNotFoundError(f"Windows build not found in: {src}")

	dest = target_root / APP_NAME
	print(f"Installing Windows build from {src} -> {dest}")
	if dry_run:
		return

	if dest.exists():
		if not prompt_confirm(f"Destination {dest} exists — remove and replace?", assume_yes):
			print("Aborting.")
			return
		shutil.rmtree(dest)

	shutil.copytree(src, dest)
	print(f"Copied to {dest}")


def install_linux(assume_yes: bool, dry_run: bool) -> None:
	src = DIST_DIR / "linux" / APP_NAME
	if not src.exists():
		# Allow case where binary is directly in dist/linux (no folder)
		alt = DIST_DIR / "linux"
		if (alt / APP_NAME).exists():
			src = alt
		else:
			raise FileNotFoundError(f"Linux build not found in: {src}")

	dest_root = Path("/opt") / "accessible-slicer"
	print(f"Installing Linux build from {src} -> {dest_root}")
	if dry_run:
		return

	if dest_root.exists():
		if not prompt_confirm(f"Destination {dest_root} exists — remove and replace?", assume_yes):
			print("Aborting.")
			return
		shutil.rmtree(dest_root)

	shutil.copytree(src, dest_root)

	# Try to find the runnable binary
	candidate = None
	# Common: binary at root named after app
	if (dest_root / APP_NAME).exists():
		candidate = dest_root / APP_NAME
	else:
		# fallback: look for an executable file in root
		for p in dest_root.iterdir():
			if p.is_file() and os.access(p, os.X_OK):
				candidate = p
				break

	if candidate:
		make_executable(candidate)
		symlink_path = Path("/usr/local/bin") / APP_NAME
		if not symlink_path.parent.exists():
			symlink_path = Path("/bin") / APP_NAME

		if symlink_path.exists():
			symlink_path.unlink()

		os.symlink(candidate, symlink_path)
		print(f"Created symlink: {symlink_path} -> {candidate}")
	else:
		print("Warning: could not automatically find executable to link. Manual step may be required.")


def install_macos(assume_yes: bool, dry_run: bool) -> None:
	src_app = DIST_DIR / "macos" / f"{APP_NAME}.app"
	if not src_app.exists():
		raise FileNotFoundError(f"macOS build (.app) not found in: {src_app}")

	dest = Path("/Applications") / src_app.name
	print(f"Installing macOS bundle from {src_app} -> {dest}")
	if dry_run:
		return

	if dest.exists():
		if not prompt_confirm(f"Destination {dest} exists — remove and replace?", assume_yes):
			print("Aborting.")
			return
		if dest.is_dir():
			shutil.rmtree(dest)

	# copytree preserves bundle contents
	shutil.copytree(src_app, dest)

	# Create a symlink in /usr/local/bin
	exec_in_app = dest / "Contents" / "MacOS" / APP_NAME
	symlink_path = Path("/usr/local/bin") / APP_NAME
	if symlink_path.exists():
		symlink_path.unlink()
	os.symlink(exec_in_app, symlink_path)
	print(f"Created symlink: {symlink_path} -> {exec_in_app}")


def uninstall_windows(target_root: Path, assume_yes: bool, dry_run: bool) -> None:
	dest = target_root / APP_NAME
	print(f"Uninstalling Windows installation at {dest}")
	if dry_run:
		return
	if dest.exists():
		if not prompt_confirm(f"Remove {dest}?", assume_yes):
			print("Aborting.")
			return
		shutil.rmtree(dest)
		print("Removed.")
	else:
		print("Nothing to remove.")


def uninstall_linux(assume_yes: bool, dry_run: bool) -> None:
	dest_root = Path("/opt") / "accessible-slicer"
	symlink_path = Path("/usr/local/bin") / APP_NAME
	if not symlink_path.exists():
		symlink_path = Path("/bin") / APP_NAME

	print(f"Uninstalling Linux installation at {dest_root} and symlink {symlink_path}")
	if dry_run:
		return

	if symlink_path.exists():
		symlink_path.unlink()
		print(f"Removed symlink {symlink_path}")

	if dest_root.exists():
		if not prompt_confirm(f"Remove {dest_root}?", assume_yes):
			print("Aborting.")
			return
		shutil.rmtree(dest_root)
		print("Removed.")
	else:
		print("Nothing to remove.")


def uninstall_macos(assume_yes: bool, dry_run: bool) -> None:
	dest = Path("/Applications") / f"{APP_NAME}.app"
	symlink_path = Path("/usr/local/bin") / APP_NAME
	print(f"Uninstalling macOS installation at {dest} and symlink {symlink_path}")
	if dry_run:
		return

	if symlink_path.exists():
		symlink_path.unlink()
		print(f"Removed symlink {symlink_path}")

	if dest.exists():
		if not prompt_confirm(f"Remove {dest}?", assume_yes):
			print("Aborting.")
			return
		shutil.rmtree(dest)
		print("Removed.")
	else:
		print("Nothing to remove.")


def main() -> None:
	p = argparse.ArgumentParser(description="Install AccessibleSlicer build to system locations")
	p.add_argument("--yes", "-y", action="store_true", help="assume yes for prompts")
	p.add_argument("--dry-run", action="store_true", help="show what would be done without making changes")
	p.add_argument("--uninstall", action="store_true", help="remove installation instead of installing")
	p.add_argument("--target", choices=["windows", "linux", "macos", "auto"], default="auto", help="target platform (default: auto-detect)")
	p.add_argument("--no-deps", action="store_true", help="skip automatic dependency checks/install")
	args = p.parse_args()

	system = platform.system().lower()
	target = args.target
	if target == "auto":
		if system.startswith("windows"):
			target = "windows"
		elif system == "darwin":
			target = "macos"
		else:
			target = "linux"

	# Check and install Python package dependencies unless disabled
	if not args.no_deps:
		try:
			check_and_install_dependencies(args.yes, args.dry_run)
		except Exception as e:
			print(f"Dependency check/install failed: {e}")
			if not args.yes:
				print("Re-run with --yes to attempt automatic installation, or install packages manually.")
			sys.exit(1)

	if args.uninstall:
		if target == "windows":
			if not is_admin():
				print("Uninstalling on Windows requires administrative privileges. Run from an elevated PowerShell.")
				sys.exit(1)
			uninstall_windows(Path(os.environ.get("ProgramFiles", "C:\\Program Files")), args.yes, args.dry_run)
		elif target == "linux":
			if not is_admin():
				print("Uninstalling on Linux requires root. Re-run with sudo.")
				sys.exit(1)
			uninstall_linux(args.yes, args.dry_run)
		elif target == "macos":
			if not is_admin():
				print("Uninstalling on macOS requires admin privileges. Re-run with sudo.")
				sys.exit(1)
			uninstall_macos(args.yes, args.dry_run)
		return

	# Install
	if target == "windows":
		if not is_admin():
			print("Installing to Program Files requires administrative privileges. Run this script from an elevated PowerShell.")
			sys.exit(1)
		program_files = Path(os.environ.get("ProgramFiles", "C:\\Program Files"))
		install_windows(program_files, args.yes, args.dry_run)

	elif target == "linux":
		if not is_admin():
			print("Installing to /opt and creating symlinks requires root. Re-run with sudo.")
			sys.exit(1)
		install_linux(args.yes, args.dry_run)

	elif target == "macos":
		if not is_admin():
			print("Installing to /Applications requires admin privileges. Re-run with sudo.")
			sys.exit(1)
		install_macos(args.yes, args.dry_run)


if __name__ == "__main__":
	main()

