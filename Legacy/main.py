import sys
import subprocess
import serial
import time
import os
import shutil
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget, QVBoxLayout,
    QLabel, QPushButton, QFileDialog, QHBoxLayout, QTextEdit, QLineEdit,
    QCheckBox, QMessageBox, QSpinBox, QGridLayout, QGroupBox, QRadioButton, QFormLayout, QDialog
)
from PyQt6.QtCore import QSettings, QTimer, QCoreApplication, Qt, QSize

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
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.current_printer_label = QLabel(self.selected_printer)
        self.current_filament_label = QLabel(self.selected_filament)
        self.current_quality_label = QLabel(self.selected_quality)
        self.file_btn = QPushButton()
        self.slice_btn = QPushButton()
        self.export_btn = QPushButton()
        self.send_btn = QPushButton()
        self.selected_file_label = QLabel("No file selected")
        self.status_label = QLabel("")
        return tab

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
        self.printer_group = self._create_radio_selection_group("Printer", PRINTER_NAMES, 'printer')
        self.filament_group = self._create_radio_selection_group("Filament", FILAMENT_NAMES, 'filament')
        self.quality_group = self._create_radio_selection_group("Quality", PRINT_QUALITIES, 'quality')
        self.slicer_path_line = QLineEdit()
        self.printer_ini_path_line = QLineEdit()
        self.filament_ini_path_line = QLineEdit()
        self.quality_ini_path_line = QLineEdit()
        self.real_time_checkbox = QCheckBox()
        self.update_interval_spinbox = QSpinBox()
        self.save_prefs_btn = QPushButton()
        return tab

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
        
    def _load_preferences(self): pass
    def _handle_profile_selection(self, profile_type, value): pass
    def _update_button_states(self): pass
    def _update_slicer_labels(self): pass


# -----------------------------
# 4. Run Application
# -----------------------------
if __name__ == "__main__":
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