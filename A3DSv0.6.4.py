import sys
import os
import json
import subprocess
import tempfile
import shutil
import re
import time
import platform

# PyQt Imports
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QMessageBox, QDialog, 
    QTextEdit, QRadioButton, QButtonGroup, QGroupBox, QSpinBox, 
    QDoubleSpinBox, QFormLayout, QTabWidget, QCheckBox, QComboBox,
    QLineEdit, QStackedWidget, QScrollArea, QProgressBar
)
from PyQt6.QtGui import QAction
from PyQt6.QtCore import QTimer, Qt, QThread, pyqtSignal

# --- CONSTANTS ---
APP_NAME = "A3DS"
FULL_NAME = "Accessible 3-D Slicer"
APP_VERSION = "v0.6.4"

# --- UNIVERSAL SETTINGS PATH LOGIC ---
# Ensures settings persist correctly when running as a bundled application
def get_settings_path():
    app_id = "A3DS"
    if platform.system() == "Windows":
        base_path = os.environ.get("APPDATA", os.path.expanduser("~"))
    elif platform.system() == "Darwin":  # macOS
        base_path = os.path.expanduser("~/Library/Application Support")
    else:  # Linux
        base_path = os.path.expanduser("~/.config")
    
    config_dir = os.path.join(base_path, app_id)
    if not os.path.exists(config_dir):
        os.makedirs(config_dir)
        
    return os.path.join(config_dir, "a3ds_settings.json")

SETTINGS_FILE = get_settings_path()

# --- RELEASE NOTES ---
RELEASE_NOTES = f"""
<h2>Welcome to {APP_NAME} {APP_VERSION}</h2>
<p><b>Public Release Backend Update:</b></p>
<ul>
    <li><b>Universal Hardware Support:</b> Removed hardcoded Ender 3 offsets. All start/end sequences now calculate moves based on your Setup Wizard parameters.</li>
    <li><b>Settings Persistence:</b> Fixed the bug where settings would reset on macOS bundles.</li>
    <li><b>3MF Export:</b> Retained toggle for Bambu Lab/Prusa project files.</li>
    <li><b>Hardened Security:</b> Secure temp file handling and subprocess isolation.</li>
    <li><b>UI Integrity:</b> All accessible layouts, tabs, and the SD Manager remain untouched.</li>
</ul>
<p><i>Developers: Elwin Rivera & Gemini 3.0</i></p>
"""

# Serial Imports
try:
    import serial
    from serial.tools import list_ports
    def get_serial_ports():
        ports = [port.device for port in list_ports.comports()]
        return ports if ports else ["No ports found"]
except ImportError:
    def get_serial_ports(): return ["/dev/tty.usbserial", "COM3"]

# Defaults
DEFAULTS = {
    "gcode_flavor": "marlin", 
    "bed_x": 220,
    "bed_y": 220,
    "bed_z": 250,
    "nozzle_size": 0.4,
    "filament_diam": 1.75,
    "serial_port": "",
    "baud_rate": "115200",
    "poll_interval_idle": 2,   
    "poll_interval_print": 10, 
    "disconnect_on_sd": 0,     
    "use_relative_e": 0,
    "retract_len": 5.0,
    "retract_min_travel": 2.0, 
    "travel_speed": 150,
    "perimeter_speed": 40,
    "first_layer_speed": 20,
    "material": "PLA",
    "infill_density": 20,
    "layer_height": 0.20,
    "temp_nozzle": 205,
    "temp_bed": 60,
    "fan_speed": 100,
    "brim_width": 5,
    "support_gap": 0.25,
    "support_spacing_organic": 3.0,
    "support_spacing_grid": 2.5,
    "scale_percent": 100.0,
    "elefant_foot_comp": 0.0,
    "seam_position": "aligned",
    "wipe_on_retract": 0,
    "last_run_version": "" 
}

MATERIALS = {
    "PLA":   {"nozzle": 205, "bed": 60,  "fan": 100},
    "PETG":  {"nozzle": 240, "bed": 80,  "fan": 50},
    "ABS":   {"nozzle": 250, "bed": 100, "fan": 0},
    "ASA":   {"nozzle": 260, "bed": 110, "fan": 0},
    "TPU":   {"nozzle": 230, "bed": 0,   "fan": 100},
    "Nylon": {"nozzle": 250, "bed": 70,  "fan": 0},
    "PC":    {"nozzle": 270, "bed": 110, "fan": 0}
}

BAUD_RATES = ["115200", "250000", "230400", "9600"]

# --- ACCESSIBLE CONTROLS ---
class AccessSpinBox(QSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.lineEdit().setAccessibleName(self.accessibleName())
    def setAccessibleName(self, name):
        super().setAccessibleName(name)
        self.lineEdit().setAccessibleName(name)

class AccessDoubleSpinBox(QDoubleSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.lineEdit().setAccessibleName(self.accessibleName())
    def setAccessibleName(self, name):
        super().setAccessibleName(name)
        self.lineEdit().setAccessibleName(name)

# --- HELPER WINDOWS ---
class ReleaseNotesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"What's New in {APP_NAME}")
        self.setGeometry(200, 200, 500, 400)
        layout = QVBoxLayout()
        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.text.setHtml(RELEASE_NOTES)
        layout.addWidget(self.text)
        btn = QPushButton("Awesome!")
        btn.clicked.connect(self.accept)
        layout.addWidget(btn); self.setLayout(layout)

class LogWindow(QDialog):
    def __init__(self, log_text, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Debug Logs")
        self.setGeometry(200, 200, 600, 400)
        layout = QVBoxLayout()
        self.text_area = QTextEdit()
        self.text_area.setReadOnly(True)
        self.text_area.setText(log_text)
        layout.addWidget(self.text_area)
        btn = QPushButton("Close")
        btn.clicked.connect(self.accept)
        layout.addWidget(btn); self.setLayout(layout)

class ParameterDialog(QDialog):
    def __init__(self, current_params, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setGeometry(150, 150, 500, 700)
        self.params = current_params
        
        layout = QVBoxLayout()
        self.tabs = QTabWidget()
        
        # TAB 1: Connection
        tab_con = QWidget()
        con_layout = QFormLayout()
        
        grp_port = QGroupBox("USB Port")
        self.v_port = QVBoxLayout()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.sw = QWidget()
        self.sl = QVBoxLayout(self.sw)
        self.bg_port = QButtonGroup()
        
        self.sl.addStretch()
        self.sw.setLayout(self.sl)
        scroll.setWidget(self.sw)
        self.v_port.addWidget(scroll)
        grp_port.setLayout(self.v_port)
        con_layout.addRow(grp_port)

        grp_baud = QGroupBox("Baud Rate")
        v_baud = QVBoxLayout()
        scroll_baud = QScrollArea()
        scroll_baud.setWidgetResizable(True)
        sw_baud = QWidget()
        sl_baud = QVBoxLayout(sw_baud)
        self.bg_baud = QButtonGroup()
        
        current_baud = self.params.get("baud_rate", "115200")
        for i, b in enumerate(BAUD_RATES):
            r = QRadioButton(b)
            self.bg_baud.addButton(r, i)
            sl_baud.addWidget(r)
            if b == current_baud: r.setChecked(True)
            
        sl_baud.addStretch()
        sw_baud.setLayout(sl_baud)
        scroll_baud.setWidget(sw_baud)
        v_baud.addWidget(scroll_baud)
        grp_baud.setLayout(v_baud)
        con_layout.addRow(grp_baud)
        
        grp_poll = QGroupBox("Monitoring Speeds")
        l_poll = QFormLayout()
        
        self.spin_poll_idle = AccessSpinBox()
        self.spin_poll_idle.setRange(1, 60)
        self.spin_poll_idle.setAccessibleName("Idle Update Frequency")
        self.spin_poll_idle.setValue(int(self.params.get("poll_interval_idle", 2)))
        self.spin_poll_idle.setSuffix(" sec")
        l_poll.addRow("Idle (Manual Control):", self.spin_poll_idle)
        
        self.spin_poll_print = AccessSpinBox()
        self.spin_poll_print.setRange(1, 60)
        self.spin_poll_print.setAccessibleName("Printing Update Frequency")
        self.spin_poll_print.setValue(int(self.params.get("poll_interval_print", 10)))
        self.spin_poll_print.setSuffix(" sec")
        l_poll.addRow("Printing (Active):", self.spin_poll_print)
        
        grp_poll.setLayout(l_poll)
        con_layout.addRow(grp_poll)
        
        btn_refresh = QPushButton("Rescan Ports")
        btn_refresh.clicked.connect(self.refresh_ports)
        con_layout.addRow("", btn_refresh)
        tab_con.setLayout(con_layout)
        self.tabs.addTab(tab_con, "Connection")

        # TAB 2: Material
        tab_mat = QWidget()
        mat_layout = QVBoxLayout()
        
        grp_mat = QGroupBox("Material Defaults")
        lay_mat = QVBoxLayout()
        self.bg_mat = QButtonGroup()
        
        self.rad_pla = QRadioButton("PLA")
        self.rad_petg = QRadioButton("PETG")
        self.rad_abs = QRadioButton("ABS")
        self.rad_asa = QRadioButton("ASA")
        self.rad_tpu = QRadioButton("TPU")
        self.rad_nylon = QRadioButton("Nylon")
        self.rad_pc = QRadioButton("PC")
        self.rad_custom = QRadioButton("Custom / Exotic")
        
        self.bg_mat.addButton(self.rad_pla, 1)
        self.bg_mat.addButton(self.rad_petg, 2)
        self.bg_mat.addButton(self.rad_abs, 3)
        self.bg_mat.addButton(self.rad_asa, 4)
        self.bg_mat.addButton(self.rad_tpu, 5)
        self.bg_mat.addButton(self.rad_nylon, 6)
        self.bg_mat.addButton(self.rad_pc, 7)
        self.bg_mat.addButton(self.rad_custom, 8)
        
        lay_mat.addWidget(self.rad_pla)
        lay_mat.addWidget(self.rad_petg)
        lay_mat.addWidget(self.rad_abs)
        lay_mat.addWidget(self.rad_asa)
        lay_mat.addWidget(self.rad_tpu)
        lay_mat.addWidget(self.rad_nylon)
        lay_mat.addWidget(self.rad_pc)
        lay_mat.addWidget(self.rad_custom)
        grp_mat.setLayout(lay_mat)
        mat_layout.addWidget(grp_mat)
        
        self.bg_mat.buttonToggled.connect(self.on_mat_toggle)

        form_mat = QFormLayout()
        self.spin_nozzle_temp = AccessSpinBox()
        self.spin_nozzle_temp.setRange(0, 350)
        self.spin_nozzle_temp.setAccessibleName("Nozzle Temperature")
        self.spin_nozzle_temp.setValue(self.params.get("temp_nozzle", 205))
        form_mat.addRow("Nozzle Temp:", self.spin_nozzle_temp)
        
        self.spin_bed_temp = AccessSpinBox()
        self.spin_bed_temp.setRange(0, 120)
        self.spin_bed_temp.setAccessibleName("Bed Temperature")
        self.spin_bed_temp.setValue(self.params.get("temp_bed", 60))
        form_mat.addRow("Bed Temp:", self.spin_bed_temp)
        
        mat_layout.addLayout(form_mat)
        mat_layout.addStretch()
        tab_mat.setLayout(mat_layout)
        self.tabs.addTab(tab_mat, "Material")

        # TAB 3: Quality
        tab_qual = QWidget()
        v_qual = QVBoxLayout()
        
        grp_noz = QGroupBox("Nozzle Size (mm)")
        l_noz = QVBoxLayout()
        self.bg_noz = QButtonGroup()
        
        self.rad_n02 = QRadioButton("0.2 mm")
        self.rad_n04 = QRadioButton("0.4 mm")
        self.rad_n06 = QRadioButton("0.6 mm")
        self.rad_n08 = QRadioButton("0.8 mm")
        self.rad_n10 = QRadioButton("1.0 mm")
        self.rad_ncus = QRadioButton("Custom")
        
        self.bg_noz.addButton(self.rad_n02, 1)
        self.bg_noz.addButton(self.rad_n04, 2)
        self.bg_noz.addButton(self.rad_n06, 3)
        self.bg_noz.addButton(self.rad_n08, 4)
        self.bg_noz.addButton(self.rad_n10, 5)
        self.bg_noz.addButton(self.rad_ncus, 6)
        
        l_noz.addWidget(self.rad_n02)
        l_noz.addWidget(self.rad_n04)
        l_noz.addWidget(self.rad_n06)
        l_noz.addWidget(self.rad_n08)
        l_noz.addWidget(self.rad_n10)
        l_noz.addWidget(self.rad_ncus)
        
        self.spin_nozzle_custom = AccessDoubleSpinBox()
        self.spin_nozzle_custom.setRange(0.1, 2.0)
        self.spin_nozzle_custom.setSingleStep(0.1)
        self.spin_nozzle_custom.setValue(0.4)
        l_noz.addWidget(self.spin_nozzle_custom)
        self.spin_nozzle_custom.hide()
        
        grp_noz.setLayout(l_noz)
        self.bg_noz.buttonToggled.connect(self.on_nozzle_toggle)
        v_qual.addWidget(grp_noz)

        grp_adv = QGroupBox("Advanced Surface Quality")
        l_adv = QVBoxLayout()
        
        form_adv = QFormLayout()
        self.spin_layer = AccessDoubleSpinBox()
        self.spin_layer.setRange(0.05, 0.8)
        self.spin_layer.setSingleStep(0.01)
        self.spin_layer.setValue(self.params.get("layer_height", 0.20))
        form_adv.addRow("Layer Height:", self.spin_layer)
        
        self.spin_infill = AccessSpinBox()
        self.spin_infill.setRange(0, 100)
        self.spin_infill.setValue(self.params.get("infill_density", 20))
        form_adv.addRow("Infill %:", self.spin_infill)
        
        self.spin_ele = AccessDoubleSpinBox()
        self.spin_ele.setRange(0.0, 1.0)
        self.spin_ele.setSingleStep(0.05)
        self.spin_ele.setValue(self.params.get("elefant_foot_comp", 0.0))
        self.spin_ele.setAccessibleName("Elephant Foot Compensation")
        form_adv.addRow("Elephant Foot Comp (mm):", self.spin_ele)
        
        l_adv.addLayout(form_adv)
        
        grp_seam = QGroupBox("Seam Position")
        v_seam = QVBoxLayout()
        self.bg_seam = QButtonGroup()
        
        self.rad_seam_aligned = QRadioButton("Aligned (Recommended)")
        self.rad_seam_nearest = QRadioButton("Nearest")
        self.rad_seam_rear = QRadioButton("Rear")
        self.rad_seam_random = QRadioButton("Random")
        
        self.bg_seam.addButton(self.rad_seam_aligned, 1)
        self.bg_seam.addButton(self.rad_seam_nearest, 2)
        self.bg_seam.addButton(self.rad_seam_rear, 3)
        self.bg_seam.addButton(self.rad_seam_random, 4)
        
        v_seam.addWidget(self.rad_seam_aligned)
        v_seam.addWidget(self.rad_seam_nearest)
        v_seam.addWidget(self.rad_seam_rear)
        v_seam.addWidget(self.rad_seam_random)
        grp_seam.setLayout(v_seam)
        l_adv.addWidget(grp_seam)
        
        saved_seam = self.params.get("seam_position", "aligned")
        if saved_seam == "aligned": self.rad_seam_aligned.setChecked(True)
        elif saved_seam == "nearest": self.rad_seam_nearest.setChecked(True)
        elif saved_seam == "rear": self.rad_seam_rear.setChecked(True)
        elif saved_seam == "random": self.rad_seam_random.setChecked(True)
        else: self.rad_seam_aligned.setChecked(True)

        self.chk_wipe = QCheckBox("Wipe on Retract")
        self.chk_wipe.setChecked(bool(self.params.get("wipe_on_retract", 0)))
        l_adv.addWidget(self.chk_wipe)
        
        grp_adv.setLayout(l_adv)
        v_qual.addWidget(grp_adv)
        
        v_qual.addStretch()
        tab_qual.setLayout(v_qual)
        self.tabs.addTab(tab_qual, "Quality")

        # TAB 4: Retraction
        tab_ret = QWidget()
        v_ret = QVBoxLayout()
        v_ret.addWidget(QLabel("Prevents jamming/clicking on detailed prints."))
        
        form_ret = QFormLayout()
        self.spin_ret_len = AccessDoubleSpinBox()
        self.spin_ret_len.setRange(0, 20.0)
        self.spin_ret_len.setSingleStep(0.1)
        self.spin_ret_len.setAccessibleName("Retraction Length")
        self.spin_ret_len.setValue(self.params.get("retract_len", 5.0))
        form_ret.addRow("Length (mm):", self.spin_ret_len)
        
        self.spin_min_travel = AccessDoubleSpinBox()
        self.spin_min_travel.setRange(0, 10.0)
        self.spin_min_travel.setSingleStep(0.1)
        self.spin_min_travel.setAccessibleName("Minimum Travel")
        self.spin_min_travel.setValue(self.params.get("retract_min_travel", 2.0))
        form_ret.addRow("Min Travel (mm):", self.spin_min_travel)
        
        v_ret.addLayout(form_ret)
        v_ret.addStretch()
        tab_ret.setLayout(v_ret)
        self.tabs.addTab(tab_ret, "Retraction")

        # TAB 5: About
        tab_about = QWidget()
        about_layout = QVBoxLayout()
        title = QLabel(f"{APP_NAME} {APP_VERSION}")
        title.setStyleSheet("font-weight: bold; font-size: 16px;")
        about_layout.addWidget(title)
        sub = QLabel(f"{FULL_NAME}")
        sub.setStyleSheet("font-size: 14px; margin-bottom: 10px;")
        about_layout.addWidget(sub)
        
        credit = QLabel("Developers:\n- Elwin Rivera\n- Gemini 3.0")
        credit.setStyleSheet("font-style: italic;")
        about_layout.addWidget(credit)
        
        about_layout.addSpacing(10)
        lbl_notes = QLabel("Release Notes:")
        lbl_notes.setStyleSheet("font-weight: bold;")
        about_layout.addWidget(lbl_notes)
        
        self.txt_notes = QTextEdit()
        self.txt_notes.setReadOnly(True)
        self.txt_notes.setHtml(RELEASE_NOTES)
        about_layout.addWidget(self.txt_notes)
        
        tab_about.setLayout(about_layout)
        self.tabs.addTab(tab_about, "About")

        self.tabs.currentChanged.connect(self.update_dialog_title)
        layout.addWidget(self.tabs)
        
        btn_box = QHBoxLayout()
        btn_save = QPushButton("Save Settings")
        btn_save.clicked.connect(self.save_values)
        btn_save.setDefault(True)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_cancel)
        btn_box.addWidget(btn_save)
        layout.addLayout(btn_box)
        self.setLayout(layout)
        
        # Initial State Loading
        curr_mat = self.params.get("material", "PLA")
        if curr_mat == "PLA": self.rad_pla.setChecked(True)
        elif curr_mat == "PETG": self.rad_petg.setChecked(True)
        elif curr_mat == "ABS": self.rad_abs.setChecked(True)
        elif curr_mat == "ASA": self.rad_asa.setChecked(True)
        elif curr_mat == "TPU": self.rad_tpu.setChecked(True)
        elif curr_mat == "Nylon": self.rad_nylon.setChecked(True)
        elif curr_mat == "PC": self.rad_pc.setChecked(True)
        else: self.rad_custom.setChecked(True)
        
        ns = self.params.get("nozzle_size", 0.4)
        if ns == 0.2: self.rad_n02.setChecked(True)
        elif ns == 0.4: self.rad_n04.setChecked(True)
        elif ns == 0.6: self.rad_n06.setChecked(True)
        elif ns == 0.8: self.rad_n08.setChecked(True)
        elif ns == 1.0: self.rad_n10.setChecked(True)
        else:
            self.rad_ncus.setChecked(True)
            self.spin_nozzle_custom.setValue(float(ns))

        self.refresh_ports() 

    def update_dialog_title(self, index):
        tab_name = self.tabs.tabText(index)
        self.setWindowTitle(f"Settings - {tab_name}")

    def on_mat_toggle(self, btn, checked):
        if not checked: return
        mat_name = btn.text().split(" ")[0]
        if mat_name in MATERIALS:
            p = MATERIALS[mat_name]
            self.spin_nozzle_temp.setValue(p["nozzle"])
            self.spin_bed_temp.setValue(p["bed"])

    def on_nozzle_toggle(self, btn, checked):
        if not checked: return
        if self.rad_ncus.isChecked():
            self.spin_nozzle_custom.show()
            self.spin_nozzle_custom.setFocus()
        else:
            self.spin_nozzle_custom.hide()

    def refresh_ports(self):
        for i in reversed(range(self.sl.count())): 
            w = self.sl.itemAt(i).widget()
            if w: w.setParent(None)
        
        ports = get_serial_ports()
        current_port = self.params.get("serial_port", "")
        
        for i, p in enumerate(ports):
            r = QRadioButton(p)
            self.bg_port.addButton(r, i)
            self.sl.addWidget(r)
            if p == current_port: r.setChecked(True)
            elif i == 0 and not current_port: r.setChecked(True)
        self.sl.addStretch()

    def save_values(self):
        if self.rad_pla.isChecked(): m = "PLA"
        elif self.rad_petg.isChecked(): m = "PETG"
        elif self.rad_abs.isChecked(): m = "ABS"
        elif self.rad_asa.isChecked(): m = "ASA"
        elif self.rad_tpu.isChecked(): m = "TPU"
        elif self.rad_nylon.isChecked(): m = "Nylon"
        elif self.rad_pc.isChecked(): m = "PC"
        else: m = "Custom"
        
        self.params["material"] = m
        self.params["temp_nozzle"] = self.spin_nozzle_temp.value()
        self.params["temp_bed"] = self.spin_bed_temp.value()
        self.params["layer_height"] = self.spin_layer.value()
        self.params["infill_density"] = self.spin_infill.value()
        self.params["elefant_foot_comp"] = self.spin_ele.value()
        
        if self.rad_seam_aligned.isChecked(): self.params["seam_position"] = "aligned"
        elif self.rad_seam_nearest.isChecked(): self.params["seam_position"] = "nearest"
        elif self.rad_seam_rear.isChecked(): self.params["seam_position"] = "rear"
        elif self.rad_seam_random.isChecked(): self.params["seam_position"] = "random"
        
        self.params["wipe_on_retract"] = 1 if self.chk_wipe.isChecked() else 0
        nid = self.bg_noz.checkedId()
        if nid == 1: self.params["nozzle_size"] = 0.2
        elif nid == 2: self.params["nozzle_size"] = 0.4
        elif nid == 3: self.params["nozzle_size"] = 0.6
        elif nid == 4: self.params["nozzle_size"] = 0.8
        elif nid == 5: self.params["nozzle_size"] = 1.0
        else: self.params["nozzle_size"] = self.spin_nozzle_custom.value()
        
        self.params["retract_len"] = self.spin_ret_len.value()
        self.params["retract_min_travel"] = self.spin_min_travel.value()
        self.params["poll_interval_idle"] = self.spin_poll_idle.value()
        self.params["poll_interval_print"] = self.spin_poll_print.value()
        
        if self.bg_port.checkedButton():
            self.params["serial_port"] = self.bg_port.checkedButton().text()
        if self.bg_baud.checkedButton():
            self.params["baud_rate"] = self.bg_baud.checkedButton().text()
            
        self.accept()

# --- SETUP WIZARD ---
class SetupWizard(QDialog):
    def __init__(self, user_params, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} Setup Wizard")
        self.setGeometry(150, 150, 600, 700)
        self.params = user_params
        self.paths = {"slicer": ""}
        self.layout = QVBoxLayout()
        self.stack = QStackedWidget()
        
        # PAGE 1: APP
        self.page1 = QWidget()
        l1 = QVBoxLayout()
        l1.addWidget(QLabel("Step 1: Locate PrusaSlicer App"))
        self.btn_slicer = QPushButton("Find App...")
        self.btn_slicer.clicked.connect(self.locate_slicer)
        l1.addWidget(self.btn_slicer)
        l1.addStretch()
        self.page1.setLayout(l1)
        self.stack.addWidget(self.page1)

        # PAGE 2: HARDWARE
        self.page2 = QWidget()
        l2 = QVBoxLayout()
        l2.addWidget(QLabel("Step 2: Hardware"))
        
        grp_flav = QGroupBox("Firmware (USB & Slicer)")
        lf = QVBoxLayout()
        self.bg_flav = QButtonGroup()
        self.rad_marlin = QRadioButton("Marlin (Ender 3, Prusa, etc.)")
        self.rad_klipper = QRadioButton("Klipper")
        self.rad_reprap = QRadioButton("RepRap")
        self.bg_flav.addButton(self.rad_marlin, 1)
        self.bg_flav.addButton(self.rad_klipper, 2)
        self.bg_flav.addButton(self.rad_reprap, 3)
        lf.addWidget(self.rad_marlin)
        lf.addWidget(self.rad_klipper)
        lf.addWidget(self.rad_reprap)
        
        flav = self.params.get("gcode_flavor", "marlin")
        if flav == "klipper": self.rad_klipper.setChecked(True)
        elif flav == "reprap": self.rad_reprap.setChecked(True)
        else: self.rad_marlin.setChecked(True)
        
        grp_flav.setLayout(lf)
        l2.addWidget(grp_flav)
        
        grp_bed = QGroupBox("Bed Size (mm)")
        lb = QFormLayout()
        self.spin_bed_x = AccessSpinBox()
        self.spin_bed_x.setRange(50, 1000)
        self.spin_bed_x.setValue(220)
        lb.addRow("X (Width):", self.spin_bed_x)
        self.spin_bed_y = AccessSpinBox()
        self.spin_bed_y.setRange(50, 1000)
        self.spin_bed_y.setValue(220)
        lb.addRow("Y (Depth):", self.spin_bed_y)
        self.spin_bed_z = AccessSpinBox()
        self.spin_bed_z.setRange(50, 1000)
        self.spin_bed_z.setValue(250)
        lb.addRow("Z (Height):", self.spin_bed_z)
        grp_bed.setLayout(lb)
        l2.addWidget(grp_bed)
        
        grp_noz = QGroupBox("Nozzle Size")
        lnoz = QVBoxLayout()
        self.bg_noz = QButtonGroup()
        self.rad_02 = QRadioButton("0.2 mm")
        self.rad_04 = QRadioButton("0.4 mm")
        self.rad_06 = QRadioButton("0.6 mm")
        self.rad_08 = QRadioButton("0.8 mm")
        self.rad_10 = QRadioButton("1.0 mm")
        self.rad_ncus = QRadioButton("Custom")
        
        self.bg_noz.addButton(self.rad_02, 1)
        self.bg_noz.addButton(self.rad_04, 2)
        self.bg_noz.addButton(self.rad_06, 3)
        self.bg_noz.addButton(self.rad_08, 4)
        self.bg_noz.addButton(self.rad_10, 5)
        self.bg_noz.addButton(self.rad_ncus, 6)
        
        lnoz.addWidget(self.rad_02)
        lnoz.addWidget(self.rad_04)
        lnoz.addWidget(self.rad_06)
        lnoz.addWidget(self.rad_08)
        lnoz.addWidget(self.rad_10)
        lnoz.addWidget(self.rad_ncus)
        
        self.spin_nozzle_custom = AccessDoubleSpinBox()
        self.spin_nozzle_custom.setRange(0.1, 2.0)
        self.spin_nozzle_custom.setValue(0.4)
        lnoz.addWidget(self.spin_nozzle_custom)
        self.spin_nozzle_custom.hide()
        
        self.bg_noz.buttonToggled.connect(self.on_nozzle_toggle)
        self.rad_04.setChecked(True)
        grp_noz.setLayout(lnoz)
        l2.addWidget(grp_noz)
        
        l2.addStretch()
        self.page2.setLayout(l2)
        self.stack.addWidget(self.page2)

        # PAGE 3: CONNECTION
        self.page3 = QWidget()
        l3 = QVBoxLayout()
        l3.addWidget(QLabel("Step 3: Connection"))
        
        grp_usb = QGroupBox("USB Port")
        lusb = QVBoxLayout()
        self.scroll_usb = QScrollArea()
        self.scroll_usb.setWidgetResizable(True)
        self.sw_usb = QWidget()
        self.sl_usb = QVBoxLayout(self.sw_usb)
        self.bg_port = QButtonGroup()
        
        self.sl_usb.addStretch()
        self.sw_usb.setLayout(self.sl_usb)
        self.scroll_usb.setWidget(self.sw_usb)
        lusb.addWidget(self.scroll_usb)
        
        btn_refresh_p = QPushButton("Refresh Ports")
        btn_refresh_p.clicked.connect(self.refresh_ports_wiz)
        lusb.addWidget(btn_refresh_p)
        
        grp_usb.setLayout(lusb)
        l3.addWidget(grp_usb)

        grp_baud = QGroupBox("Baud Rate")
        lbaud = QVBoxLayout()
        scroll_baud = QScrollArea()
        scroll_baud.setWidgetResizable(True)
        sw_b = QWidget()
        sl_b = QVBoxLayout(sw_b)
        self.bg_baud = QButtonGroup()
        for i, baud in enumerate(BAUD_RATES):
            r = QRadioButton(baud)
            self.bg_baud.addButton(r, i)
            sl_b.addWidget(r)
            if baud == "115200": r.setChecked(True)
        sl_b.addStretch()
        sw_b.setLayout(sl_b)
        scroll_baud.setWidget(sw_b)
        lbaud.addWidget(scroll_baud)
        grp_baud.setLayout(lbaud)
        l3.addWidget(grp_baud)

        grp_conn_set = QGroupBox("Connection Settings")
        l_cset = QFormLayout()
        self.wiz_poll_idle = AccessSpinBox()
        self.wiz_poll_idle.setRange(1, 60)
        self.wiz_poll_idle.setValue(2)
        l_cset.addRow("Idle Rate:", self.wiz_poll_idle)
        self.wiz_poll_print = AccessSpinBox()
        self.wiz_poll_print.setRange(1, 60)
        self.wiz_poll_print.setValue(10)
        l_cset.addRow("Printing Rate:", self.wiz_poll_print)
        grp_conn_set.setLayout(l_cset)
        l3.addWidget(grp_conn_set)
        
        self.page3.setLayout(l3)
        self.stack.addWidget(self.page3)

        # PAGE 4: SAFETY
        self.page4 = QWidget()
        l4 = QVBoxLayout()
        l4.addWidget(QLabel("Step 4: Safety & Retraction"))
        grp_math = QGroupBox("Extrusion")
        lm = QVBoxLayout()
        self.bg_math = QButtonGroup()
        self.rad_abs = QRadioButton("Absolute (Safe)")
        self.rad_rel = QRadioButton("Relative")
        self.bg_math.addButton(self.rad_abs, 0)
        self.bg_math.addButton(self.rad_rel, 1)
        lm.addWidget(self.rad_abs); lm.addWidget(self.rad_rel)
        self.rad_abs.setChecked(True)
        grp_math.setLayout(lm)
        l4.addWidget(grp_math)
        
        grp_ret = QGroupBox("Retraction")
        lr = QFormLayout()
        self.spin_ret_len = AccessDoubleSpinBox()
        self.spin_ret_len.setRange(0, 20)
        self.spin_ret_len.setValue(5.0)
        lr.addRow("Length (mm):", self.spin_ret_len)
        self.spin_min_travel = AccessDoubleSpinBox()
        self.spin_min_travel.setRange(0, 10.0)
        self.spin_min_travel.setValue(2.0)
        lr.addRow("Min Travel (mm):", self.spin_min_travel)
        grp_ret.setLayout(lr)
        l4.addWidget(grp_ret)
        l4.addStretch()
        self.page4.setLayout(l4)
        self.stack.addWidget(self.page4)

        # PAGE 5: SPEED
        self.page5 = QWidget()
        l5 = QVBoxLayout()
        l5.addWidget(QLabel("Step 5: Speeds"))
        form_spd = QFormLayout()
        self.spin_first = AccessSpinBox()
        self.spin_first.setRange(10, 100); self.spin_first.setValue(20)
        form_spd.addRow("First Layer:", self.spin_first)
        self.spin_walls = AccessSpinBox()
        self.spin_walls.setRange(10, 300); self.spin_walls.setValue(40)
        form_spd.addRow("Walls:", self.spin_walls)
        self.spin_travel = AccessSpinBox()
        self.spin_travel.setRange(50, 500); self.spin_travel.setValue(150)
        form_spd.addRow("Travel:", self.spin_travel)
        l5.addLayout(form_spd)
        l5.addStretch()
        self.page5.setLayout(l5)
        self.stack.addWidget(self.page5)

        # PAGE 6: DEFAULTS
        self.page6 = QWidget()
        l6 = QVBoxLayout()
        l6.addWidget(QLabel("Step 6: Printing Defaults"))
        grp_def = QGroupBox("Common Settings")
        ldef = QVBoxLayout()
        ldef.addWidget(QLabel("Material:"))
        self.bg_def_mat = QButtonGroup()
        mats = ["PLA", "PETG", "ABS", "ASA", "TPU", "Nylon", "PC", "Custom"]
        for i, m in enumerate(mats, 1):
            r = QRadioButton(m)
            self.bg_def_mat.addButton(r, i)
            ldef.addWidget(r)
            if m == "PLA": r.setChecked(True)
        
        self.bg_def_mat.buttonToggled.connect(self.on_wiz_mat_toggle)
        form_def = QFormLayout()
        self.wiz_temp_nozzle = AccessSpinBox()
        self.wiz_temp_nozzle.setRange(0, 350); self.wiz_temp_nozzle.setValue(205)
        form_def.addRow("Nozzle Temp:", self.wiz_temp_nozzle)
        self.wiz_temp_bed = AccessSpinBox()
        self.wiz_temp_bed.setRange(0, 120); self.wiz_temp_bed.setValue(60)
        form_def.addRow("Bed Temp:", self.wiz_temp_bed)
        ldef.addLayout(form_def)
        
        self.wiz_infill = AccessSpinBox()
        self.wiz_infill.setRange(0, 100); self.wiz_infill.setValue(20)
        ldef.addWidget(QLabel("Infill (%):")); ldef.addWidget(self.wiz_infill)
        self.wiz_layer = AccessDoubleSpinBox()
        self.wiz_layer.setRange(0.05, 0.4); self.wiz_layer.setValue(0.20)
        ldef.addWidget(QLabel("Layer Height (mm):")); ldef.addWidget(self.wiz_layer)
        
        grp_def.setLayout(ldef)
        l6.addWidget(grp_def); l6.addStretch()
        self.page6.setLayout(l6)
        self.stack.addWidget(self.page6)

        self.layout.addWidget(self.stack)
        nav_layout = QHBoxLayout()
        self.btn_back = QPushButton("Exit Setup")
        self.btn_back.clicked.connect(self.go_back)
        self.btn_next = QPushButton("Next")
        self.btn_next.clicked.connect(self.go_next)
        self.btn_next.setDefault(True)
        self.btn_next.setEnabled(False)
        nav_layout.addWidget(self.btn_back); nav_layout.addWidget(self.btn_next)
        self.layout.addLayout(nav_layout)
        self.setLayout(self.layout)
        self.refresh_ports_wiz()

    def locate_slicer(self):
        fname, _ = QFileDialog.getOpenFileName(self, "Locate PrusaSlicer", "/Applications", "Applications (*.app);;Executables (*.exe)")
        if fname:
            self.paths["slicer"] = fname
            self.btn_slicer.setText(f"Found: {os.path.basename(fname)}")
            self.btn_next.setEnabled(True); self.btn_next.setFocus()

    def refresh_ports_wiz(self):
        for i in reversed(range(self.sl_usb.count())): 
            w = self.sl_usb.itemAt(i).widget()
            if w: w.setParent(None)
        ports = get_serial_ports()
        for i, port in enumerate(ports):
            r = QRadioButton(port)
            self.bg_port.addButton(r, i); self.sl_usb.addWidget(r)
            if i == 0: r.setChecked(True)
        self.sl_usb.addStretch()

    def on_nozzle_toggle(self, btn, checked):
        if not checked: return
        if self.rad_ncus.isChecked():
            self.spin_nozzle_custom.show(); self.spin_nozzle_custom.setFocus()
        else: self.spin_nozzle_custom.hide()

    def on_wiz_mat_toggle(self, btn, checked):
        if not checked: return
        mat_name = btn.text().split(" ")[0]
        if mat_name in MATERIALS:
            p = MATERIALS[mat_name]
            self.wiz_temp_nozzle.setValue(p["nozzle"])
            self.wiz_temp_bed.setValue(p["bed"])

    def go_next(self):
        idx = self.stack.currentIndex()
        if idx < 5: 
            self.stack.setCurrentIndex(idx + 1)
            self.btn_back.setText("Back")
            if idx == 4: self.btn_next.setText("Finish")
        else:
            self.save_all(); self.accept()

    def go_back(self):
        idx = self.stack.currentIndex()
        if idx == 0: self.reject()
        else:
            self.stack.setCurrentIndex(idx - 1)
            self.btn_next.setText("Next")
            if idx == 1: self.btn_back.setText("Exit Setup")

    def save_all(self):
        fid = self.bg_flav.checkedId()
        self.params["gcode_flavor"] = "marlin" if fid == 1 else "klipper" if fid == 2 else "reprap"
        self.params["bed_x"] = self.spin_bed_x.value()
        self.params["bed_y"] = self.spin_bed_y.value()
        self.params["bed_z"] = self.spin_bed_z.value()
        
        nid = self.bg_noz.checkedId()
        sizes = {1:0.2, 2:0.4, 3:0.6, 4:0.8, 5:1.0}
        self.params["nozzle_size"] = sizes.get(nid, self.spin_nozzle_custom.value())

        if self.bg_port.checkedButton(): self.params["serial_port"] = self.bg_port.checkedButton().text()
        if self.bg_baud.checkedButton(): self.params["baud_rate"] = self.bg_baud.checkedButton().text()
        
        self.params["poll_interval_idle"] = self.wiz_poll_idle.value()
        self.params["poll_interval_print"] = self.wiz_poll_print.value()
        self.params["use_relative_e"] = self.bg_math.checkedId()
        self.params["retract_len"] = self.spin_ret_len.value()
        self.params["retract_min_travel"] = self.spin_min_travel.value()
        self.params["first_layer_speed"] = self.spin_first.value()
        self.params["perimeter_speed"] = 40
        self.params["travel_speed"] = 150
        
        self.params["material"] = "PLA"
        self.params["infill_density"] = self.wiz_infill.value()
        self.params["layer_height"] = self.wiz_layer.value()
        self.params["temp_nozzle"] = self.wiz_temp_nozzle.value()
        self.params["temp_bed"] = self.wiz_temp_bed.value()
        self.params["fan_speed"] = 100

# --- PRINTER LOGIC ---
class PrinterController:
    def __init__(self, console_output):
        self.ser = None
        self.is_connected = False
        self.console = console_output
        self.firmware_type = "marlin"
        self.status = {"bed_temp": "--", "bed_target": "--", "nozzle_temp": "--", "nozzle_target": "--", "position": "X-- Y-- Z--"}
        self.temp_regex = re.compile(r"T:([0-9\.]+) /([0-9\.]+) B:([0-9\.]+) /([0-9\.]+)")
        self.pos_regex = re.compile(r"X:([0-9\.\-]+)\s+Y:([0-9\.\-]+)\s+Z:([0-9\.\-]+)")
    
    def set_firmware(self, fw_type):
        self.firmware_type = fw_type.lower()
        self.console.append(f"Firmware Protocol set to: {self.firmware_type}")

    def connect(self, port, baud):
        if self.is_connected: self.disconnect()
        try:
            self.ser = serial.Serial()
            self.ser.port = port
            self.ser.baudrate = int(baud)
            self.ser.timeout = 1
            self.ser.dtr = False 
            self.ser.rts = False
            self.ser.open()
            time.sleep(2)
            self.is_connected = True
            self.console.append(f"*** CONNECTED to {port} ***")
            return True
        except Exception as e:
            self.console.append(f"*** CONNECTION FAILED: {e} ***")
        return False
            
    def disconnect(self):
        if self.ser and self.ser.is_open: self.ser.close()
        self.is_connected = False
        self.console.append("*** DISCONNECTED ***")
        return True
        
    def send_command(self, cmd, log=True):
        if not self.is_connected: return None
        clean_cmd = "".join(filter(lambda x: x.isprintable(), cmd.strip()))
        try:
            self.ser.write((clean_cmd + '\n').encode('utf-8'))
            if log and 'M105' not in clean_cmd: self.console.append(f"SENT: {clean_cmd}")
            time.sleep(0.1)
            if self.ser.in_waiting:
                resp = self.ser.read(self.ser.in_waiting).decode('utf-8', errors='ignore')
                if log and 'M105' not in clean_cmd: self.console.append(f"RECV: {resp.strip()}")
                return resp
        except Exception as e: 
            self.console.append(f"ERROR: {e}")
            self.disconnect()
        return None
        
    def read_buffer(self):
        if not self.is_connected: return ""
        try:
            if self.ser.in_waiting:
                return self.ser.read(self.ser.in_waiting).decode('utf-8', errors='ignore')
        except: pass
        return ""

    def get_status(self):
        if not self.is_connected: return self.status
        r = self.send_command("M105", log=False)
        if r:
            m = self.temp_regex.search(r)
            if m: 
                self.status["nozzle_temp"]=m.group(1); self.status["nozzle_target"]=m.group(2)
                self.status["bed_temp"]=m.group(3); self.status["bed_target"]=m.group(4)
        r = self.send_command("M114", log=False)
        if r:
            m = self.pos_regex.search(r)
            if m: self.status["position"] = f"X{m.group(1)} Y{m.group(2)} Z{m.group(3)}"
        return self.status

class SDCardManagerDialog(QDialog):
    def __init__(self, parent=None, controller=None):
        super().__init__(parent)
        self.setWindowTitle("SD Card Manager")
        self.controller = controller
        self.resize(500, 600)
        self.layout = QVBoxLayout(self)
        self.parent_window = parent 
        
        self.file_group = QGroupBox("Files on SD Card")
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True)
        self.sw = QWidget(); self.file_layout = QVBoxLayout(self.sw)
        self.scroll.setWidget(self.sw)
        self.file_group_layout = QVBoxLayout(); self.file_group_layout.addWidget(self.scroll)
        self.file_group.setLayout(self.file_group_layout); self.layout.addWidget(self.file_group)

        self.lbl_status = QLabel("Ready"); self.layout.addWidget(self.lbl_status)
        btn_layout = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh List"); self.refresh_btn.clicked.connect(self.start_refresh)
        btn_layout.addWidget(self.refresh_btn)
        self.del_btn = QPushButton("Delete File"); self.del_btn.setStyleSheet("color: red"); self.del_btn.clicked.connect(self.delete_file)
        btn_layout.addWidget(self.del_btn); self.layout.addLayout(btn_layout)
        self.print_btn = QPushButton("Start Print from SD"); self.print_btn.clicked.connect(self.start_print)
        self.layout.addWidget(self.print_btn)
        
        self.selected_file = None
        self.wait_timer = QTimer(); self.wait_timer.setSingleShot(True); self.wait_timer.timeout.connect(self.finish_refresh)
        self.start_refresh()

    def start_refresh(self):
        for i in reversed(range(self.file_layout.count())): 
            w = self.file_layout.itemAt(i).widget()
            if w: w.setParent(None)
        if not self.controller.is_connected:
            self.file_layout.addWidget(QLabel("Not Connected")); return
        self.refresh_btn.setEnabled(False); self.del_btn.setEnabled(False)
        self.lbl_status.setText("Listing files... Waiting 5s...")
        self.controller.send_command("M21"); self.controller.send_command("M20")
        self.wait_timer.start(5000)

    def finish_refresh(self):
        resp = self.controller.read_buffer()
        self.lbl_status.setText("List Updated.")
        self.refresh_btn.setEnabled(True); self.del_btn.setEnabled(True)
        found = False
        if resp:
            for line in resp.splitlines():
                line = line.strip()
                if not line or line.startswith("Begin") or line.startswith("End"): continue
                parts = line.split()
                if not parts: continue
                fname = parts[0]
                if os.path.splitext(fname)[1].lower() in [".gcode", ".gco", ".g"]:
                    r = QRadioButton(line)
                    r.toggled.connect(lambda c, f=fname: self.set_file(f) if c else None)
                    self.file_layout.addWidget(r); found = True
        if not found: self.file_layout.addWidget(QLabel("No G-code files found."))
        self.file_layout.addStretch()

    def set_file(self, f): self.selected_file = f
    def delete_file(self):
        if self.selected_file and QMessageBox.question(self, "Confirm", f"Delete {self.selected_file}?") == QMessageBox.StandardButton.Yes:
            self.controller.send_command(f"M30 {self.selected_file}")
            self.start_refresh()

    def start_print(self):
        if self.selected_file:
            self.controller.send_command(f"M23 {self.selected_file}")
            self.controller.send_command("M24")
            if self.parent_window.params.get("disconnect_on_sd", 0) == 1:
                self.controller.disconnect()
            else:
                self.parent_window.set_polling_mode("print")
            self.accept()

class SlicingThread(QThread):
    finished_sig = pyqtSignal(int, str, str) 
    def __init__(self, cmd):
        super().__init__()
        self.cmd = cmd
    def run(self):
        try:
            proc = subprocess.run(self.cmd, capture_output=True, text=True, check=False)
            self.finished_sig.emit(proc.returncode, self.cmd[-1], proc.stdout + proc.stderr)
        except Exception as e:
            self.finished_sig.emit(1, "", str(e))

# --- MAIN WINDOW ---
class CombinedWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.resize(900, 700)
        self.params = DEFAULTS.copy()
        self.slicer_exe = ""
        self.model_path = ""
        self.last_gcode = ""
        self.ctl = None
        self.is_printing = False
        self.initUI()
        QTimer.singleShot(100, self.check_setup)

    def initUI(self):
        menubar = self.menuBar()
        view = menubar.addMenu('&View')
        log_act = QAction('&Show Debug Logs', self); log_act.setShortcut('Ctrl+L')
        log_act.triggered.connect(self.show_logs); view.addAction(log_act)
        
        settings = menubar.addMenu('&Settings')
        conf_act = QAction('&Configure Defaults...', self); conf_act.setShortcut('Ctrl+P')
        conf_act.triggered.connect(self.open_config); settings.addAction(conf_act)
        wiz_act = QAction('&Run Setup Wizard...', self); wiz_act.triggered.connect(self.run_wizard)
        settings.addAction(wiz_act)

        self.tabs = QTabWidget(); self.setCentralWidget(self.tabs)
        self.tabs.addTab(self.create_slicer_tab(), "Slicer")
        self.tabs.addTab(self.create_printer_tab(), "Printer Control")
        self.tabs.currentChanged.connect(self.update_main_title)

    def update_main_title(self, index):
        self.setWindowTitle(f"{self.tabs.tabText(index)} - {APP_NAME} {APP_VERSION}")

    def create_slicer_tab(self):
        tab = QWidget(); layout = QVBoxLayout(tab)
        layout.addWidget(QLabel("1. Select Model"))
        self.btn_file = QPushButton("Select STL/3MF/OBJ..."); self.btn_file.clicked.connect(self.select_file)
        layout.addWidget(self.btn_file)
        self.lbl_file = QLabel("No file selected"); layout.addWidget(self.lbl_file)
        
        grp_scale = QGroupBox("Model Adjustments")
        l_scale = QFormLayout(); self.spin_scale = AccessDoubleSpinBox()
        self.spin_scale.setRange(1.0, 1000.0); self.spin_scale.setValue(100.0); self.spin_scale.setSuffix("%")
        l_scale.addRow("Scale (%):", self.spin_scale); grp_scale.setLayout(l_scale); layout.addWidget(grp_scale)
        
        grp = QGroupBox("2. Modifiers"); l_mod = QVBoxLayout()
        self.chk_brim = QCheckBox("Add Brim"); self.chk_brim.toggled.connect(self.toggle_slice_btn)
        self.chk_supp = QCheckBox("Add Supports"); self.chk_supp.toggled.connect(self.on_supp_toggle)
        self.chk_3mf = QCheckBox("Export as 3MF Project")
        self.chk_3mf.setAccessibleDescription("Wraps the mesh and settings into a 3MF file for Bambu/Prusa printers instead of standard G-code.")
        l_mod.addWidget(self.chk_brim); l_mod.addWidget(self.chk_supp); l_mod.addWidget(self.chk_3mf)
        grp.setLayout(l_mod); layout.addWidget(grp)
        
        self.grp_style = QGroupBox("Support Style"); l_sty = QVBoxLayout(); self.bg_style = QButtonGroup()
        self.rad_org = QRadioButton("Organic Trees"); self.rad_org.setChecked(True)
        self.rad_grid = QRadioButton("Grid Blocks"); self.bg_style.addButton(self.rad_org, 1); self.bg_style.addButton(self.rad_grid, 2)
        l_sty.addWidget(self.rad_org); l_sty.addWidget(self.rad_grid); self.grp_style.setLayout(l_sty)
        layout.addWidget(self.grp_style); self.grp_style.hide()
        
        layout.addSpacing(20)
        self.btn_slice = QPushButton("Slice and Save G-code"); self.btn_slice.clicked.connect(self.start_slice)
        layout.addWidget(self.btn_slice); self.slice_log = ""
        return tab

    def create_printer_tab(self):
        tab = QWidget(); layout = QVBoxLayout(tab)
        l_act = QHBoxLayout()
        self.btn_con = QPushButton("Connect"); self.btn_con.clicked.connect(self.toggle_connect)
        self.btn_sd = QPushButton("SD Card Manager"); self.btn_sd.clicked.connect(self.open_sd)
        self.btn_estop = QPushButton("EMERGENCY STOP"); self.btn_estop.setStyleSheet("background-color: red; color: white")
        self.btn_estop.clicked.connect(lambda: self.ctl.send_command("M112"))
        l_act.addWidget(self.btn_con); l_act.addWidget(self.btn_sd); l_act.addWidget(self.btn_estop); layout.addLayout(l_act)
        
        grp_pos = QGroupBox("Axis Positions"); l_pos = QVBoxLayout(); self.lbl_pos = QLabel("X: --  Y: --  Z: --")
        l_pos.addWidget(self.lbl_pos); grp_pos.setLayout(l_pos); layout.addWidget(grp_pos)
        
        grp_temp = QGroupBox("Temperature"); l_temp = QFormLayout()
        self.lbl_noz = QLabel("Nozzle: -- / --"); self.lbl_bed = QLabel("Bed: -- / --")
        l_temp.addRow("Nozzle:", self.lbl_noz); l_temp.addRow("Bed:", self.lbl_bed)
        grp_temp.setLayout(l_temp); layout.addWidget(grp_temp)
        
        l_cmd = QHBoxLayout(); self.line_cmd = QLineEdit(); self.line_cmd.setPlaceholderText("Enter G-code (e.g., G28)")
        self.btn_send = QPushButton("Send"); self.btn_send.clicked.connect(self.send_manual)
        l_cmd.addWidget(self.line_cmd); l_cmd.addWidget(self.btn_send); layout.addLayout(l_cmd)
        
        layout.addWidget(QLabel("Console Output:")); self.console = QTextEdit(); self.console.setReadOnly(True)
        layout.addWidget(self.console); self.ctl = PrinterController(self.console)
        self.timer = QTimer(); self.timer.timeout.connect(self.update_status)
        return tab

    def check_setup(self):
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, 'r') as f:
                    data = json.load(f)
                self.slicer_exe = data.get("slicer", "")
                self.params.update(data.get("params", {}))
                self.ctl.set_firmware(self.params.get("gcode_flavor", "marlin"))
                if self.params.get("last_run_version", "") != APP_VERSION:
                    ReleaseNotesDialog(self).exec()
                    self.params["last_run_version"] = APP_VERSION; self.save_settings()
                if not self.slicer_exe: self.run_wizard()
            except: self.run_wizard()
        else:
            self.run_wizard()

    def run_wizard(self):
        wiz = SetupWizard(self.params, self)
        if wiz.exec():
            self.slicer_exe = wiz.paths["slicer"]
            self.params["last_run_version"] = APP_VERSION; self.save_settings()
            self.ctl.set_firmware(self.params.get("gcode_flavor", "marlin"))

    def open_config(self):
        if ParameterDialog(self.params, self).exec(): self.save_settings()

    def save_settings(self):
        try:
            with open(SETTINGS_FILE, 'w') as f: json.dump({"slicer": self.slicer_exe, "params": self.params}, f)
        except: pass

    def select_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select Model", "", "Supported Models (*.stl *.obj *.3mf)")
        if f:
            if not f.lower().endswith((".stl", ".obj", ".3mf")):
                QMessageBox.critical(self, "Error", "Invalid file type."); return
            self.model_path = f; self.lbl_file.setText(os.path.basename(f)); self.chk_brim.setFocus()

    def toggle_slice_btn(self): 
        if self.sender().hasFocus(): self.btn_slice.setFocus()

    def on_supp_toggle(self, c): 
        self.grp_style.setVisible(c)
        if c: QTimer.singleShot(100, self.rad_org.setFocus)
        else: self.btn_slice.setFocus()

    def start_slice(self):
        if not self.slicer_exe or not self.model_path: 
            QMessageBox.warning(self, "Error", "Missing file or slicer."); return
        
        p = self.params; scale_factor = self.spin_scale.value() / 100.0
        
        # Universal Scaling Logic for Purge and Presentation
        safe_x = float(p['bed_x']) * 0.05
        safe_y = float(p['bed_y']) * 0.05
        safe_z = 2.0
        present_y = float(p['bed_y']) * 0.95
        
        config_text = f"""
gcode_flavor = {p['gcode_flavor']}
bed_shape = 0x0,{p['bed_x']}x0,{p['bed_x']}x{p['bed_y']},0x{p['bed_y']}
max_print_height = {p.get('bed_z', 250)}
nozzle_diameter = {p['nozzle_size']}
filament_diameter = {p.get('filament_diam', 1.75)}
use_relative_e_distances = {p['use_relative_e']}
travel_speed = {p['travel_speed']}
perimeter_speed = {p['perimeter_speed']}
first_layer_speed = {p['first_layer_speed']}
retract_length = {p['retract_len']}
retract_before_travel = {p['retract_min_travel']}
temperature = {p['temp_nozzle']}
bed_temperature = {p['temp_bed']}
layer_height = {p['layer_height']}
fill_density = {p['infill_density']}%
elefant_foot_compensation = {p['elefant_foot_comp']}
seam_position = {p['seam_position']}
wipe = {p['wipe_on_retract']}
brim_width = {p['brim_width'] if self.chk_brim.isChecked() else 0}
"""
        if self.chk_supp.isChecked():
            style = "organic" if self.bg_style.checkedId() == 1 else "grid"
            config_text += f"\nsupport_material = 1\nsupport_material_style = {style}"
        else: config_text += "\nsupport_material = 0"

        config_text += f"""
start_gcode = G28 ; Home axes\\nG1 Z{safe_z} F3000\\nG1 X{safe_x} Y{safe_y} F5000\\nM109 S[temperature]\\nM190 S[bed_temperature]
end_gcode = M104 S0\\nM140 S0\\nG91\\nG1 E-1 F2700\\nG1 Z10\\nG90\\nG1 X0 Y{present_y}\\nM84
"""

        if self.chk_3mf.isChecked():
            out_f, _ = QFileDialog.getSaveFileName(self, "Save 3MF Project", f"{os.path.splitext(os.path.basename(self.model_path))[0]}.3mf", "3MF Project (*.3mf)")
        else:
            out_f, _ = QFileDialog.getSaveFileName(self, "Save G-code", f"{os.path.splitext(os.path.basename(self.model_path))[0]}.gcode", "G-code (*.gcode)")
        
        if not out_f: return

        try:
            fd, cfg_path = tempfile.mkstemp(suffix=".ini", text=True)
            with os.fdopen(fd, 'w') as tmp:
                tmp.write(config_text)
        except Exception as e: 
            QMessageBox.critical(self, "Error", f"Failed to create secure config: {e}"); return

        action_flag = "--export-3mf" if self.chk_3mf.isChecked() else "--slice"
        cmd = [self.slicer_exe, "--load", cfg_path, "--scale", str(scale_factor), action_flag, self.model_path, "--output", out_f]
        
        self.btn_slice.setEnabled(False); self.btn_slice.setText("Working...")
        self.slicer_thread = SlicingThread(cmd)
        self.slicer_thread.finished_sig.connect(self.on_slice_done)
        self.slicer_thread.start(); self.temp_cfg = cfg_path

    def on_slice_done(self, code, path, log):
        self.btn_slice.setEnabled(True); self.btn_slice.setText("Slice and Save G-code")
        self.slice_log = log
        if os.path.exists(self.temp_cfg): os.remove(self.temp_cfg)
        if code == 0: QMessageBox.information(self, "Success", "Operation Complete!")
        else: QMessageBox.warning(self, "Failed", "Operation failed. Check debug logs.")

    def show_logs(self): LogWindow(self.slice_log, self).exec()

    def set_polling_mode(self, mode):
        self.timer.stop()
        interval = int(self.params.get("poll_interval_print" if mode == "print" else "poll_interval_idle", 2)) * 1000
        self.timer.start(interval)

    def toggle_connect(self):
        if self.ctl.is_connected:
            self.ctl.disconnect(); self.btn_con.setText("Connect"); self.timer.stop(); self.reset_labels()
        else:
            port = self.params.get("serial_port", "")
            if not port: QMessageBox.warning(self, "Error", "No port selected."); return
            if self.ctl.connect(port, self.params.get("baud_rate", "115200")):
                self.btn_con.setText("Disconnect"); self.set_polling_mode("idle")

    def reset_labels(self):
        self.lbl_noz.setText("Nozzle: -- / --"); self.lbl_bed.setText("Bed: -- / --"); self.lbl_pos.setText("X: --  Y: --  Z: --")

    def update_status(self):
        s = self.ctl.get_status()
        self.lbl_noz.setText(f"Nozzle: {s['nozzle_temp']} / {s['nozzle_target']}")
        self.lbl_bed.setText(f"Bed: {s['bed_temp']} / {s['bed_target']}")
        self.lbl_pos.setText(f"{s['position']}")

    def send_manual(self):
        self.ctl.send_command(self.line_cmd.text()); self.line_cmd.clear()

    def open_sd(self):
        if not self.ctl.is_connected: QMessageBox.warning(self, "Error", "Not connected."); return
        self.timer.stop()
        SDCardManagerDialog(self, self.ctl).exec()
        if self.ctl.is_connected: self.set_polling_mode("idle")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    w = CombinedWindow(); w.show()
    sys.exit(app.exec())