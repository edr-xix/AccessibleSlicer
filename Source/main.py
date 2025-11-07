import sys
import subprocess
import serial
import time
import os
import shutil
import platform
import json
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget, QVBoxLayout,
    QLabel, QPushButton, QFileDialog, QHBoxLayout, QTextEdit, QLineEdit,
    QCheckBox, QMessageBox, QSpinBox, QGridLayout, QGroupBox, QRadioButton, QFormLayout, QDialog,
    QKeySequenceEdit
)
from PyQt6.QtCore import QSettings, QTimer, QCoreApplication, Qt, QSize, QThread, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from pathlib import Path

# -----------------------------
# 1. CONFIGURATION CONSTANTS 🛠️
# -----------------------------
PRINTER_NAMES = ["Ender 3", "Prusa MK3S", "Custom Printer", "XYZ Printer"] 
FILAMENT_NAMES = ["PLA", "ABS", "PETG", "TPU", "Nylon"]
PRINT_QUALITIES = ["0.20 mm Standard", "0.15 mm Quality", "0.30 mm Draft", "0.05 mm Ultra Fine"]
BAUD_RATES = ["115200", "250000", "230400", "9600"]
# Note: SD_CARD_FILES is now ONLY used for mocking the initial display.
SD_CARD_FILES = ["test_cube.gcode", "vase_print.gcode", "calibration.gcode", "benchy.gcode"] 

# Dynamically list serial ports if pyserial is available
try:
    from serial.tools import list_ports
    SERIAL_PORTS = [port.device for port in list_ports.comports()] or ["No ports found"]
except ImportError:
    SERIAL_PORTS = ["COM1", "/dev/ttyUSB0", "COM3", "/dev/tty.usbmodem1234"] 
except Exception:
    SERIAL_PORTS = ["COM1", "/dev/ttyUSB0", "COM3", "/dev/tty.usbmodem1234"] 


def find_prusaslicer() -> str | None:
    """Attempt to locate a PrusaSlicer CLI executable on the host system.

    Returns the full path to the executable if found, else None.
    """
    # Try shutil.which candidates first
    candidates = ["prusa-slicer", "prusa-slicer-console", "prusa_slicer"]
    if os.name == 'nt':
        # Windows executable names
        candidates = [c + ".exe" for c in candidates] + candidates

    for c in candidates:
        p = shutil.which(c)
        if p:
            return p

    # Platform-specific typical locations
    system = platform.system().lower()
    if system.startswith('windows'):
        prog = os.environ.get('ProgramFiles', r'C:\Program Files')
        possible = [
            os.path.join(prog, 'Prusa3D', 'PrusaSlicer', 'prusa-slicer.exe'),
            os.path.join(prog, 'PrusaSlicer', 'prusa-slicer.exe'),
        ]
        for p in possible:
            if os.path.exists(p):
                return p

    elif system == 'darwin':
        app_path = '/Applications/PrusaSlicer.app/Contents/MacOS/PrusaSlicer'
        if os.path.exists(app_path):
            return app_path

    else:
        # Linux common paths
        for p in ['/usr/bin/prusa-slicer', '/usr/bin/prusa-slicer-console', '/snap/bin/prusa-slicer']:
            if os.path.exists(p):
                return p

    return None

# -----------------------------
# 2. Controller and Dialog Classes 💻
# -----------------------------

class SDCardManagerDialog(QDialog):
    """
    Accessible SD card file management. Sends M20 on initialization.
    """
    def __init__(self, parent=None, controller=None):
        super().__init__(parent)
        self.setWindowTitle("SD Card Manager")
        self.setMinimumSize(QSize(450, 350))
        self.controller = controller
        self.current_files = [] 
        self.selected_file = None
        
        layout = QVBoxLayout(self)
        
        # 1. File Selection Group (Will be populated by _load_initial_files)
        self.file_group = QGroupBox("Select File to Print/Manage")
        self.file_layout = QVBoxLayout(self.file_group)
        self.file_layout.addWidget(QLabel("Loading files..."))
        layout.addWidget(self.file_group)
        
        # 2. Actions Group (Push Buttons)
        action_hlayout = QHBoxLayout()
        self.print_btn = QPushButton("Start Print (M23/M24)")
        self.delete_btn = QPushButton("Delete File (M30)")
        self.refresh_btn = QPushButton("Refresh List (M20)")
        
        action_hlayout.addWidget(self.print_btn)
        action_hlayout.addWidget(self.delete_btn)
        action_hlayout.addWidget(self.refresh_btn)
        layout.addLayout(action_hlayout)
        
        # 3. Connection and Signals
        self.refresh_btn.clicked.connect(self._refresh_list)
        self.print_btn.clicked.connect(self._start_print)
        self.delete_btn.clicked.connect(self._delete_file)
        
        # FIX: Call the loading sequence when the dialog is initialized
        self._load_initial_files()
        
    def _load_initial_files(self):
        """Sends M20 and populates the radio button list."""
        
        # Clear existing widgets
        for i in reversed(range(self.file_layout.count())): 
            widget = self.file_layout.itemAt(i).widget()
            if widget is not None:
                widget.setParent(None)

        if self.controller and self.controller.is_connected:
            # Send M20 command (which is logged in the main console)
            self.controller.send_command("M20") 
            
            # NOTE: In a real implementation, we would wait for the M20 response
            # and parse the actual file list here. For now, we use the mock list.
            self.current_files = SD_CARD_FILES 
            
            self.file_layout.addWidget(QLabel("Files listed below (Mocked):"))

        else:
            self.current_files = []
            self.file_layout.addWidget(QLabel("Printer is disconnected. Cannot load files."))
            return

        if self.current_files:
            for file in self.current_files:
                radio = QRadioButton(file)
                radio.setAccessibleName(f"SD Card File: {file}")
                radio.toggled.connect(lambda checked, val=file: self._set_selected_file(val) if checked else None)
                self.file_layout.addWidget(radio)
            
            # Select the first file by default
            first_radio = self.file_group.findChildren(QRadioButton)[0]
            if first_radio:
                 first_radio.setChecked(True)
                 self._set_selected_file(first_radio.text())
        else:
             self.file_layout.addWidget(QLabel("No G-code files found on SD card."))

    def _set_selected_file(self, file_name):
        self.selected_file = file_name
        
    def _refresh_list(self):
        # The refresh button just re-runs the initial loading logic
        QMessageBox.information(self, "Refresh", "M20 command sent to printer. Refreshing file list...")
        self._load_initial_files()

    def _start_print(self):
        if not self.selected_file: QMessageBox.warning(self, "Error", "No file selected."); return
        if self.controller and self.controller.is_connected:
            self.controller.send_command(f"M23 {self.selected_file}")
            self.controller.send_command("M24")
            QMessageBox.information(self, "Action", f"Started print of: {self.selected_file}")
        else:
            QMessageBox.warning(self, "Error", "Printer not connected.")

    def _delete_file(self):
        if not self.selected_file: QMessageBox.warning(self, "Error", "No file selected."); return
        if self.controller and self.controller.is_connected:
            self.controller.send_command(f"M30 {self.selected_file}")
            QMessageBox.information(self, "Action", f"Sent M30 to delete: {self.selected_file} (mocked)")
        else:
            QMessageBox.warning(self, "Error", "Printer not connected.")


# -----------------------------
# 3. Main Window (A3-DS) 
# -----------------------------
# ... (PrinterController and AccessibleSlicerWindow classes remain identical to the last version) ...
class PrinterController:
    # ... (content remains identical) ...
    def __init__(self, console_output):
        self.ser = None
        self.is_connected = False
        self.console = console_output
        self.printer_status = {
            "bed_temp": "--", "bed_target": "--",
            "nozzle_temp": "--", "nozzle_target": "--",
            "fan_speed": "--", "position": "X-- Y-- Z--"
        }
    def connect(self, port, baud_rate):
        if self.is_connected: self.disconnect()
        try:
            self.ser = serial.Serial(port, int(baud_rate), timeout=1)
            time.sleep(2) 
            self.is_connected = True
            self.console.append(f"*** CONNECTED to {port} @ {baud_rate} ***")
            self._send_raw_command("M105", log_sent=False, wait_for_response=False)
            return True
        except serial.SerialException as e:
            self.console.append(f"*** CONNECTION FAILED: {e} ***")
            self.is_connected = False
            return False
            
    def disconnect(self):
        if self.ser and self.ser.is_open:
            self.ser.close()
            self.is_connected = False
            self.console.append("*** DISCONNECTED ***")
            return True
        return False
        
    def _send_raw_command(self, command, wait_for_response=True, log_sent=True):
        if not self.is_connected: return None
        full_command = command.strip() + '\n'
        try:
            self.ser.write(full_command.encode('utf-8'))
        except serial.SerialException as e:
            self.console.append(f"SERIAL WRITE ERROR: {e}")
            self.disconnect()
            return None
        
        if log_sent: self.console.append(f"SENT: {command}")
        
        if wait_for_response: return self._read_response()
        return ""
        
    def send_command(self, command, log_response=True):
        if not self.is_connected:
            self.console.append(f"ERROR: Cannot send command '{command}'. Not connected.")
            return None
            
        response = self._send_raw_command(command, wait_for_response=True)
        
        if log_response and response and ('M105' not in command):
            self.console.append("RECV:\n" + response.strip())
        return response

    def _read_response(self):
        response = ""
        if not self.ser or not self.ser.is_open: return ""
        time.sleep(0.01) 
        while self.ser.in_waiting > 0:
            try:
                line = self.ser.readline().decode('utf-8', errors='ignore').strip()
                if line: response += line + '\n'
            except Exception as e:
                QCoreApplication.instance().processEvents() 
                self.console.append(f"READ ERROR: {e}")
                break
        return response
        
    def get_status(self):
        if not self.is_connected: return self.printer_status
        self._read_response() 
        response_temp = self._send_raw_command("M105", log_sent=False)
        if response_temp:
            self.console.append("RECV (M105):\n" + response_temp.strip())
            temp_parts = response_temp.split()
            for part in temp_parts:
                if part.startswith('T:'):
                    try: current, target = part[2:].split('/'); self.printer_status["nozzle_temp"] = current; self.printer_status["nozzle_target"] = target
                    except ValueError: pass
                elif part.startswith('B:'):
                    try: current, target = part[2:].split('/'); self.printer_status["bed_temp"] = current; self.printer_status["bed_target"] = target
                    except ValueError: pass
        return self.printer_status


# -----------------------------
#  Slicing and Sending threads
# -----------------------------
class SlicingThread(QThread):
    finished_signal = pyqtSignal(int, str)  # returncode, output_path
    output_signal = pyqtSignal(str)

    def __init__(self, input_stl: str, output_gcode: str, slicer_exec: str | None = None):
        super().__init__()
        self.input_stl = input_stl
        self.output_gcode = output_gcode
        self.slicer_exec = slicer_exec

    def run(self):
        # Determine command
        cmd = None
        if self.slicer_exec:
            cmd = [self.slicer_exec, '--export-gcode', '-o', self.output_gcode, self.input_stl]
        else:
            # try common executables
            for candidate in ('prusa-slicer', 'prusa-slicer-console', 'prusa_slicer'):
                if shutil.which(candidate):
                    cmd = [candidate, '--export-gcode', '-o', self.output_gcode, self.input_stl]
                    break

        if cmd is None:
            self.output_signal.emit('PrusaSlicer CLI not found. Please set the path in the Slicer tab.')
            self.finished_signal.emit(1, '')
            return

        # Run command and stream output
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        except Exception as e:
            self.output_signal.emit(f'Failed to run slicer: {e}')
            self.finished_signal.emit(1, '')
            return

        # Read stdout lines and emit
        if proc.stdout:
            for line in proc.stdout:
                self.output_signal.emit(line.rstrip())

        proc.wait()
        self.finished_signal.emit(proc.returncode, self.output_gcode if proc.returncode == 0 else '')


class SendingThread(QThread):
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal()

    def __init__(self, gcode_path: str, controller: PrinterController):
        super().__init__()
        self.gcode_path = gcode_path
        self.controller = controller

    def run(self):
        try:
            with open(self.gcode_path, 'r', encoding='utf-8', errors='ignore') as fh:
                lines = fh.readlines()
        except Exception:
            self.finished_signal.emit()
            return

        total = len(lines)
        if total == 0:
            self.finished_signal.emit()
            return

        sent = 0
        for i, raw in enumerate(lines):
            line = raw.strip()
            if not line:
                continue
            # Write raw to serial if connected
            try:
                if self.controller and self.controller.is_connected and self.controller.ser and self.controller.ser.is_open:
                    try:
                        self.controller.ser.write((line + '\n').encode('utf-8'))
                    except Exception:
                        # if direct write fails, try controller method
                        self.controller._send_raw_command(line, wait_for_response=False)
                # simple pacing
                time.sleep(0.005)
            except Exception:
                pass

            sent += 1
            pct = int((sent / total) * 100)
            self.progress_signal.emit(pct)

        self.finished_signal.emit()


class AccessibleSlicerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("A3-DS (Accessible 3D Slicer) - Final Version")
        self.resize(850, 600)
        self.selected_printer = PRINTER_NAMES[0]
        self.selected_filament = FILAMENT_NAMES[0]
        self.selected_quality = PRINT_QUALITIES[0]
        self.selected_port = SERIAL_PORTS[0]
        self.selected_baud = BAUD_RATES[0]
        self.real_time_updates = True 
        self.update_interval = 2000
        self._setup_ui()
        self.printer_controller = PrinterController(self.console_output)
        self._connect_signals()
        self._load_preferences()
        self._update_slicer_labels()
        self._update_connection_toggle(self.printer_controller.is_connected) 
        self._update_button_states()
        self.status_timer = QTimer(self)
        self.status_timer.setInterval(self.update_interval) 
        self.status_timer.timeout.connect(self._update_status)
        self.status_timer.start()
        
    def _setup_ui(self):
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.tabs.addTab(self._create_slicer_tab(), "&Slicer") 
        self.tabs.addTab(self._create_printer_tab(), "&Printer")
        self.tabs.addTab(self._create_preferences_tab(), "Pr&eferences")

    def _create_radio_selection_group(self, title, options, state_key, max_height=None):
        group = QGroupBox(title)
        vlayout = QVBoxLayout(group)
        for option in options:
            radio = QRadioButton(option)
            radio.setAccessibleName(f"Select {title}: {option}")
            radio.toggled.connect(lambda checked, val=option, key=state_key: self._handle_profile_selection(key, val) if checked else None)
            vlayout.addWidget(radio)
        vlayout.setSpacing(5)
        vlayout.setContentsMargins(10, 15, 10, 10)
        if max_height: group.setMaximumHeight(max_height)
        return group
        
    def _create_slicer_tab(self):
        # Build the full Slicer tab UI
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Top: current selections summary
        summary_group = QGroupBox("Current Slicer Profile")
        summary_layout = QHBoxLayout(summary_group)
        self.current_printer_label = QLabel(self.selected_printer)
        self.current_filament_label = QLabel(self.selected_filament)
        self.current_quality_label = QLabel(self.selected_quality)
        summary_layout.addWidget(QLabel("Printer:"))
        summary_layout.addWidget(self.current_printer_label)
        summary_layout.addSpacing(10)
        summary_layout.addWidget(QLabel("Filament:"))
        summary_layout.addWidget(self.current_filament_label)
        summary_layout.addSpacing(10)
        summary_layout.addWidget(QLabel("Quality:"))
        summary_layout.addWidget(self.current_quality_label)
        layout.addWidget(summary_group)

        # File selection
        file_hlayout = QHBoxLayout()
        self.file_btn = QPushButton("Select STL File")
        self.file_btn.setAccessibleName("Select STL file to slice")
        self.selected_file_label = QLabel("No file selected")
        file_hlayout.addWidget(self.file_btn)
        file_hlayout.addWidget(self.selected_file_label)
        layout.addLayout(file_hlayout)

        # Slicer executable path and options
        slicer_group = QGroupBox("Slicer / Output")
        slicer_layout = QHBoxLayout(slicer_group)
        self.slicer_path_line = QLineEdit()
        self.slicer_path_line.setPlaceholderText("Path to PrusaSlicer CLI (optional)")
        self.slicer_path_line.setAccessibleName("PrusaSlicer CLI path")
        self.slice_btn = QPushButton("Slice (PrusaSlicer)")
        self.slice_btn.setEnabled(False)
        slicer_layout.addWidget(self.slicer_path_line)
        slicer_layout.addWidget(self.slice_btn)
        layout.addWidget(slicer_group)

        # Actions: export and send
        actions_h = QHBoxLayout()
        self.export_btn = QPushButton("Export G-code")
        self.export_btn.setEnabled(False)
        self.send_btn = QPushButton("Send to Printer")
        self.send_btn.setEnabled(False)
        actions_h.addWidget(self.export_btn)
        actions_h.addWidget(self.send_btn)
        layout.addLayout(actions_h)

        # Status and console output
        self.status_label = QLabel("")
        layout.addWidget(self.status_label)
        layout.addWidget(QLabel("Slicing Console Output:"))
        self.slicer_console = QTextEdit()
        self.slicer_console.setReadOnly(True)
        layout.addWidget(self.slicer_console)

        # Internal state
        self._selected_stl = None
        self._last_gcode = None

        # Connections
        self.file_btn.clicked.connect(self._select_file)
        self.slice_btn.clicked.connect(self._start_slice)
        self.export_btn.clicked.connect(self._export_gcode)
        self.send_btn.clicked.connect(self._send_gcode)

        return tab

    def _select_file(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Select STL file", os.path.expanduser("~"), "STL Files (*.stl);;All Files (*)")
        if not fn:
            return
        self._selected_stl = fn
        self.selected_file_label.setText(os.path.basename(fn))
        self.slice_btn.setEnabled(True)

    def _start_slice(self):
        if not getattr(self, '_selected_stl', None):
            QMessageBox.warning(self, "No file", "Please select an STL file first.")
            return

        slicer_exec = self.slicer_path_line.text().strip()
        out_dir = os.path.dirname(self._selected_stl)
        base = os.path.splitext(os.path.basename(self._selected_stl))[0]
        output_gcode = os.path.join(out_dir, base + ".gcode")

        self.slice_btn.setEnabled(False)
        self.status_label.setText("Slicing...")
        self.slicer_console.clear()

        self._slicing_thread = SlicingThread(self._selected_stl, output_gcode, slicer_exec if slicer_exec else None)
        self._slicing_thread.output_signal.connect(self._append_slicer_output)
        self._slicing_thread.finished_signal.connect(self._on_slice_finished)
        self._slicing_thread.start()

    def _append_slicer_output(self, text: str):
        self.slicer_console.append(text)

    def _on_slice_finished(self, returncode: int, out_path: str):
        self.slice_btn.setEnabled(True)
        if returncode == 0 and out_path:
            self.status_label.setText(f"Slicing complete: {out_path}")
            self._last_gcode = out_path
            self.export_btn.setEnabled(True)
            self.send_btn.setEnabled(self.printer_controller.is_connected)
            self.slicer_console.append(f"G-code saved to: {out_path}")
        else:
            self.status_label.setText("Slicing failed — see console")

    def _export_gcode(self):
        if not self._last_gcode or not os.path.exists(self._last_gcode):
            QMessageBox.warning(self, "No G-code", "No generated G-code available to export.")
            return
        fn, _ = QFileDialog.getSaveFileName(self, "Export G-code", os.path.expanduser("~"), "G-code Files (*.gcode);;All Files (*)")
        if not fn:
            return
        try:
            shutil.copy(self._last_gcode, fn)
            QMessageBox.information(self, "Exported", f"G-code exported to {fn}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export: {e}")

    def _send_gcode(self):
        if not self._last_gcode or not os.path.exists(self._last_gcode):
            QMessageBox.warning(self, "No G-code", "No generated G-code to send.")
            return
        if not self.printer_controller.is_connected:
            QMessageBox.warning(self, "Not connected", "Please connect to a printer first.")
            return

        self.send_btn.setEnabled(False)
        self._sending_thread = SendingThread(self._last_gcode, self.printer_controller)
        self._sending_thread.progress_signal.connect(lambda v: self.status_label.setText(f"Sending... {v}%"))
        self._sending_thread.finished_signal.connect(lambda: (self.status_label.setText("Send complete"), self.send_btn.setEnabled(True)))
        self._sending_thread.start()

    def _create_printer_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        conn_group = QGroupBox("Printer Connection & USB/Serial Management")
        conn_hlayout = QHBoxLayout()
        self.port_group = self._create_radio_selection_group("Serial Port", SERIAL_PORTS, 'port', max_height=150)
        conn_hlayout.addWidget(self.port_group)
        self.baud_group = self._create_radio_selection_group("Baud Rate", BAUD_RATES, 'baud', max_height=150)
        conn_hlayout.addWidget(self.baud_group)
        conn_group.setLayout(conn_hlayout)
        layout.addWidget(conn_group)
        action_hlayout = QHBoxLayout()
        self.toggle_connect_btn = QPushButton("Connect")
        self.sd_manager_btn = QPushButton("SD Card Manager")
        self.sd_manager_btn.setAccessibleName("Open SD Card File List and Controls")
        action_hlayout.addWidget(self.toggle_connect_btn)
        action_hlayout.addWidget(self.sd_manager_btn)
        layout.addLayout(action_hlayout)
        status_group = QGroupBox("Current Status")
        status_layout = QFormLayout(status_group)
        self.temp_label = QLabel("Nozzle: -- / -- °C")
        self.bed_label = QLabel("Bed: -- / -- °C")
        self.position_label = QLabel("Position: X-- Y-- Z--")
        status_layout.addRow("Nozzle/Target:", self.temp_label)
        status_layout.addRow("Bed/Target:", self.bed_label)
        status_layout.addRow("Current Position:", self.position_label)
        layout.addWidget(status_group)
        command_group = QGroupBox("Send Manual G-code")
        command_hlayout = QHBoxLayout(command_group)
        self.send_command_line = QLineEdit()
        self.send_command_line.setPlaceholderText("Enter G-code command (e.g., G1 X100 Y100, M104 S200)")
        self.send_command_line.setAccessibleName("Manual G-code Command Input")
        self.send_command_btn = QPushButton("Send Command")
        command_hlayout.addWidget(self.send_command_line)
        command_hlayout.addWidget(self.send_command_btn)
        layout.addWidget(command_group)
        layout.addWidget(QLabel("\nConsole Output:"))
        self.console_output = QTextEdit()
        self.console_output.setReadOnly(True)
        self.console_output.setAccessibleName("Printer Communication Console")
        layout.addWidget(self.console_output)
        layout.addStretch(1)
        return tab
    
    def _create_preferences_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Slicer CLI path
        slicer_group = QGroupBox("Slicer / CLI")
        slicer_layout = QFormLayout(slicer_group)
        self.slicer_path_line = QLineEdit()
        self.slicer_path_line.setPlaceholderText("Path to PrusaSlicer CLI (optional)")
        slicer_layout.addRow("PrusaSlicer CLI:", self.slicer_path_line)
        layout.addWidget(slicer_group)

        # Theme selection
        theme_group = QGroupBox("Appearance")
        theme_layout = QHBoxLayout(theme_group)
        from PyQt6.QtWidgets import QComboBox
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Classic (Fusion)", "Dark Modern"])
        self.theme_combo.setAccessibleName("Select application theme")
        theme_layout.addWidget(QLabel("Theme:"))
        theme_layout.addWidget(self.theme_combo)
        layout.addWidget(theme_group)

        # Shortcut preferences
        shortcuts_group = QGroupBox("Keyboard Shortcuts")
        shortcuts_layout = QFormLayout(shortcuts_group)
        # Defaults: Ctrl+S, Ctrl+Shift+S, Ctrl+E
        self.keyseq_slice = QKeySequenceEdit()
        self.keyseq_send = QKeySequenceEdit()
        self.keyseq_export = QKeySequenceEdit()
        shortcuts_layout.addRow("Slice (default Ctrl+S):", self.keyseq_slice)
        shortcuts_layout.addRow("Send to printer (default Ctrl+Shift+S):", self.keyseq_send)
        shortcuts_layout.addRow("Export G-code (default Ctrl+E):", self.keyseq_export)
        layout.addWidget(shortcuts_group)

        # Preferences actions
        actions_layout = QHBoxLayout()
        self.save_prefs_btn = QPushButton("Save Preferences")
        actions_layout.addStretch(1)
        actions_layout.addWidget(self.save_prefs_btn)
        layout.addLayout(actions_layout)

        # Wire up
        self.save_prefs_btn.clicked.connect(self._save_preferences)
        self.theme_combo.currentTextChanged.connect(self._on_theme_changed)
        # When shortcut edits change, update live
        self.keyseq_slice.keySequenceChanged.connect(lambda seq: self._update_shortcut('slice', seq))
        self.keyseq_send.keySequenceChanged.connect(lambda seq: self._update_shortcut('send', seq))
        self.keyseq_export.keySequenceChanged.connect(lambda seq: self._update_shortcut('export', seq))

        return tab

    def _on_theme_changed(self, theme_name: str):
        self.apply_theme(theme_name)

    def _update_shortcut(self, which: str, seq: QKeySequence):
        # Store temporarily in widget; full save happens on Save Preferences
        # Also apply immediately
        seq_str = seq.toString()
        settings = QSettings()
        settings.setValue(f'shortcuts/{which}', seq_str)
        # apply
        self._setup_shortcuts()

    def apply_theme(self, theme_name: str):
        app = QApplication.instance()
        if not app:
            return
        if theme_name == "Dark Modern":
            # Simple dark stylesheet — modern-ish
            dark_qss = """
            QWidget { background: #2b2b2b; color: #e6e6e6; }
            QLineEdit, QTextEdit { background: #3c3f41; color: #e6e6e6; }
            QPushButton { background: #4b6eaf; color: white; border-radius: 4px; padding: 6px; }
            QPushButton:hover { background: #5b7ecf; }
            QGroupBox { border: 1px solid #3c3f41; margin-top: 6px; }
            QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 3px 0 3px; }
            QTabWidget::pane { border: 0; }
            """
            app.setStyle("Fusion")
            app.setStyleSheet(dark_qss)
        else:
            # Classic / Fusion — clear stylesheet
            app.setStyle("Fusion")
            app.setStyleSheet("")

    def _save_preferences(self):
        settings = QSettings()
        settings.setValue('slicer/cli_path', self.slicer_path_line.text())
        settings.setValue('appearance/theme', self.theme_combo.currentText())
        # Save shortcuts
        settings.setValue('shortcuts/slice', self.keyseq_slice.keySequence().toString())
        settings.setValue('shortcuts/send', self.keyseq_send.keySequence().toString())
        settings.setValue('shortcuts/export', self.keyseq_export.keySequence().toString())
        settings.sync()
        QMessageBox.information(self, "Preferences", "Preferences saved.")
        # Apply shortcuts on save
        self._setup_shortcuts()

    def _load_preferences(self):
        settings = QSettings()
        cli = settings.value('slicer/cli_path', '') or ''
        theme = settings.value('appearance/theme', 'Classic (Fusion)') or 'Classic (Fusion)'

        # User data JSON next to executable
        try:
            app_dir = Path(sys.argv[0]).resolve().parent
        except Exception:
            app_dir = Path('.').resolve()
        user_json = app_dir / 'user_data.json'

        if not user_json.exists():
            # First run: try to auto-detect PrusaSlicer
            found = find_prusaslicer()
            if found:
                cli = found
                settings.setValue('slicer/cli_path', cli)
                try:
                    user_json.write_text(json.dumps({'prusa_slicer_path': cli}, indent=2))
                except Exception:
                    pass
                QMessageBox.information(self, "PrusaSlicer detected", f"PrusaSlicer found at {found} and will be used.")
            else:
                QMessageBox.warning(self, "PrusaSlicer not found", "PrusaSlicer CLI could not be automatically detected. Please set it in Preferences.")
        else:
            try:
                data = json.loads(user_json.read_text())
                if data.get('prusa_slicer_path') and not cli:
                    cli = data.get('prusa_slicer_path')
            except Exception:
                pass

        self.slicer_path_line.setText(cli)
        # Set theme combo safely
        idx = self.theme_combo.findText(theme)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        # Apply theme immediately
        self.apply_theme(theme)
        # Load shortcuts (or defaults)
        slice_key = settings.value('shortcuts/slice', 'Ctrl+S') or 'Ctrl+S'
        send_key = settings.value('shortcuts/send', 'Ctrl+Shift+S') or 'Ctrl+Shift+S'
        export_key = settings.value('shortcuts/export', 'Ctrl+E') or 'Ctrl+E'
        try:
            self.keyseq_slice.setKeySequence(QKeySequence(slice_key))
            self.keyseq_send.setKeySequence(QKeySequence(send_key))
            self.keyseq_export.setKeySequence(QKeySequence(export_key))
        except Exception:
            pass
        # Apply shortcuts
        self._setup_shortcuts()

    def _setup_shortcuts(self):
        settings = QSettings()
        slice_key = settings.value('shortcuts/slice', 'Ctrl+S') or 'Ctrl+S'
        send_key = settings.value('shortcuts/send', 'Ctrl+Shift+S') or 'Ctrl+Shift+S'
        export_key = settings.value('shortcuts/export', 'Ctrl+E') or 'Ctrl+E'

        # Create or update QShortcut objects
        try:
            if hasattr(self, 'shortcut_slice') and self.shortcut_slice:
                self.shortcut_slice.setKey(QKeySequence(slice_key))
            else:
                self.shortcut_slice = QShortcut(QKeySequence(slice_key), self)
                self.shortcut_slice.activated.connect(self._start_slice)

            if hasattr(self, 'shortcut_send') and self.shortcut_send:
                self.shortcut_send.setKey(QKeySequence(send_key))
            else:
                self.shortcut_send = QShortcut(QKeySequence(send_key), self)
                self.shortcut_send.activated.connect(self._send_gcode)

            if hasattr(self, 'shortcut_export') and self.shortcut_export:
                self.shortcut_export.setKey(QKeySequence(export_key))
            else:
                self.shortcut_export = QShortcut(QKeySequence(export_key), self)
                self.shortcut_export.activated.connect(self._export_gcode)
        except Exception:
            # Safe fallback: ignore shortcut setup errors
            pass

    def _update_status(self):
        if self.printer_controller.is_connected and self.real_time_updates:
            status = self.printer_controller.get_status()
            self.temp_label.setText(f"Nozzle: {status['nozzle_temp']} / {status['nozzle_target']} °C")
            self.bed_label.setText(f"Bed: {status['bed_temp']} / {status['bed_target']} °C")
            self.position_label.setText(f"Position: {status['position']}")
        elif not self.printer_controller.is_connected:
             self.temp_label.setText("Nozzle: -- / -- °C")
             self.bed_label.setText("Bed: -- / -- °C")
             self.position_label.setText("Position: X-- Y-- Z--")
             
    def toggle_connection(self):
        if self.printer_controller.is_connected: self.disconnect_printer()
        else: self.connect_printer()

    def connect_printer(self):
        port = self.selected_port
        baud = self.selected_baud
        success = self.printer_controller.connect(port, baud)
        self._update_connection_toggle(success)

    def disconnect_printer(self):
        success = self.printer_controller.disconnect()
        self._update_connection_toggle(not success)
        self._update_status()

    def _update_connection_toggle(self, is_connected):
        if is_connected:
            self.toggle_connect_btn.setText("Disconnect")
            self.toggle_connect_btn.setStyleSheet("background-color: lightcoral;")
            self.toggle_connect_btn.setAccessibleName("Click to Disconnect the printer")
            self.port_group.setEnabled(False)
            self.baud_group.setEnabled(False)
        else:
            self.toggle_connect_btn.setText("Connect")
            self.toggle_connect_btn.setStyleSheet("background-color: lightgreen;")
            self.toggle_connect_btn.setAccessibleName("Click to Connect to the printer")
            self.port_group.setEnabled(True)
            self.baud_group.setEnabled(True)
            
    def open_sd_manager(self):
        """FIX: This method only opens the dialog, which then handles the M20 command."""
        if not self.printer_controller.is_connected:
            QMessageBox.warning(self, "Connection Required", "Please connect to the printer before accessing the SD Card Manager.")
            return
        dialog = SDCardManagerDialog(self, controller=self.printer_controller)
        dialog.exec()
        
    def send_manual_command(self):
        command = self.send_command_line.text().strip()
        if not command: return
        self.printer_controller.send_command(command)
        self.send_command_line.clear()

    def _connect_signals(self):
        self.toggle_connect_btn.clicked.connect(self.toggle_connection)
        self.send_command_btn.clicked.connect(self.send_manual_command)
        self.send_command_line.returnPressed.connect(self.send_manual_command)
        self.sd_manager_btn.clicked.connect(self.open_sd_manager)
        
    
    def _handle_profile_selection(self, profile_type, value): pass
    def _update_button_states(self): pass
    def _update_slicer_labels(self): pass


# -----------------------------
# 4. Run Application
# -----------------------------
if __name__ == "__main__": # just a side note, why __name__ == "__main__"? I don't get it.
    QCoreApplication.setOrganizationName("A3-DS")
    QCoreApplication.setApplicationName("Prefs")
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    font = app.font()
    font.setPointSize(font.pointSize() + 1)
    app.setFont(font)

    window = AccessibleSlicerWindow()
    window.show()
    sys.exit(app.exec())