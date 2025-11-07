# AccessibleSlicer

AccessibleSlicer (A3-DS) is a small, accessible PyQt-based wrapper around PrusaSlicer’s command-line interface (CLI). It provides a simple, keyboard- and assistive-technology-friendly GUI for slicing STL files into G-code and for managing basic printer interactions (serial connection, sending G-code, and an SD card file manager mock).

The app is designed to make 3D printing workflows with PrusaSlicer more approachable for users who need an accessible interface while still leveraging the powerful slicing features provided by PrusaSlicer.

## Highlights

- Lightweight PyQt6 UI focused on accessibility.
- Uses PrusaSlicer CLI for slicing tasks (the application is a wrapper around the PrusaSlicer CLI).
- Serial communication support for sending commands to printers (via pyserial).
- SD Card Manager dialog (mocked file list in this repo) for selecting/starting prints.
- Cross-platform Python app (development and usage notes here are focused on Windows/PowerShell).

## Requirements

- Python 3.8+ (use the Python you normally run your desktop apps with).
- PyQt6
- pyserial
- PrusaSlicer (installed separately) — the application expects to call the PrusaSlicer CLI to perform slicing. Make sure PrusaSlicer is installed and its CLI binary is available on PATH, or update the app preferences to point to the PrusaSlicer executable.

Note: The program also uses standard library modules (sys, subprocess, os, shutil, time) which ship with Python.

## Install (install.py)

./install.py

1. Checks for dependencies, if not existent installs them.
2. Checks for build source; if not present in dist, it invokes build. (I might not have integrated this, so run build.py first)
3. Installs them onto your system, for windows C:\Program Files, linux, /opt/accessible-slicer with a CLI symlink, and on macOS in /Applications/AccessibleSlicer.app

## Run

Simply run it how you would any other app installed on your system.

The application will open a Qt window. Use the Printer tab to select serial port / baud rate and connect to your printer. Use the Slicer tab to pick STL files and invoke the PrusaSlicer CLI (the UI acts as a wrapper for the CLI). The SD Card Manager in this repository currently uses a mocked file list and demonstrates the flow for listing, selecting, starting, and deleting files (M20/M23/M24/M30). Serial interaction is handled by `pyserial`.

## Configuration / Preferences

- The app stores simple preferences via Qt settings. If PrusaSlicer is not on PATH, set the full path to the CLI in the preferences fields (in the Preferences tab).
- Serial port detection uses `serial.tools.list_ports` from `pyserial` — ports listed depend on the OS and what devices are connected.

## Notes on Accessibility

The UI is built with accessibility in mind: labeled controls, accessible names on some widgets, keyboard-focusable widgets, and clear text for actions. This project aims to provide a more approachable UI for people who rely on assistive technologies when using 3D printing tools.

## Development

- The main application code is in `main.py`.
- To contribute: fork the repo, create a branch, add features or fixes, and open a pull request describing the change and accessibility considerations.

Suggested small improvements you might consider implementing:
- Wire the SD Card Manager to parse real M20 responses from printers and dynamically populate files.
- Add preferences to save the full path to the PrusaSlicer CLI and example slice presets.
- Add tests for serial communication mocking and UI snapshots (integration tests for the main window).

## License

This repository does not currently include a license file. Add an appropriate license (for example, MIT) if you want to permit reuse.

## Contact / Credits

Built as a small helper/wrapper around PrusaSlicer with accessibility improvements. If you want help developing features or polishing accessibility, file an issue or open a PR.

---
Generated from repository context and project summary.
