# A3DS: Accessible 3-D Slicer

**A3DS** is a lightweight, high-accessibility GUI wrapper built with PyQt6. It leverages the powerful **PrusaSlicer Command-Line Interface (CLI)** to provide a keyboard-friendly and screen-reader-optimized workflow for 3D printing. 

Whether you are slicing STL files into G-code or managing a printer via a serial connection, A3DS is designed to be utilitarian, straightforward, and fully accessible to users of assistive technology (NVDA, VoiceOver, JAWS, TalkBack).

## Key Features

* **Accessibility-First Design:** Fully labeled controls, ARIA-style accessible names, and a logical tab order for seamless screen reader navigation.
* **CLI Slicing Engine:** Acts as a secure wrapper for the PrusaSlicer/BambuSlicer backend—leveraging industry-standard slicing logic through a simplified interface.
* **Integrated Printer Control:** Real-time serial communication (via `pyserial`) to send manual G-code, home axes, and monitor temperatures.
* **SD Card Manager:** Support for listing, starting, and deleting files on the printer's SD card (M20/M23/M24/M30 protocols).
* **Cross-Platform Persistence:** Settings are dynamically stored in native system paths (`Application Support` on macOS, `AppData` on Windows), ensuring your configurations stay safe across app updates.

## Requirements

* **Python 3.11+**
* **Dependencies:** `PyQt6`, `pyserial`
* **Slicer Backend:** PrusaSlicer or BambuSlicer must be installed. During the first run, the **Setup Wizard** will help you locate the executable.

## Installation & Usage

### For End Users (Binary)
Download the latest zipped executable for your platform from the **Releases** section on the right side of this repository:
1.  **Windows:** Unzip the folder and run `A3DS.exe`.
2.  **macOS:** Drag `A3DS.app` to your Applications folder and open it.

### For Developers (Source)
Clone the repository and install the requirements:
```bash
git clone [https://github.com/YourUsername/A3DS.git](https://github.com/YourUsername/A3DS.git)
cd A3DS
python -m pip install PyQt6 pyserial
python A3DSv0.6.4.py
