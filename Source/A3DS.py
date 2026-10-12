import sys
import os
import json
import subprocess
import tempfile
import re
import time
import platform
import urllib.request
import urllib.error
import ssl
import ftplib
import threading
import queue
import zipfile

# PyQt Imports
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QMessageBox, QDialog,
    QTextEdit, QRadioButton, QButtonGroup, QGroupBox, QSpinBox,
    QDoubleSpinBox, QFormLayout, QTabWidget, QCheckBox, QComboBox,
    QLineEdit, QStackedWidget, QScrollArea
)
from PyQt6.QtGui import QAction
from PyQt6.QtCore import QTimer, Qt, QThread, pyqtSignal

# --- CONSTANTS ---
APP_NAME = "A3DS"
FULL_NAME = "Accessible 3-D Slicer"
APP_VERSION = "v0.7.0"
UPDATE_URL = "https://api.github.com/repos/edr-xix/AccessibleSlicer/releases/latest"

# --- UNIVERSAL SETTINGS PATH LOGIC ---
def get_settings_path():
    app_id = "A3DS"
    if platform.system() == "Windows":
        base_path = os.environ.get("APPDATA", os.path.expanduser("~"))
    elif platform.system() == "Darwin":  # macOS
        base_path = os.path.expanduser("~/Library/Application Support")
    else:  # Linux
        base_path = os.path.expanduser("~/.config")

    config_dir = os.path.join(base_path, app_id)
    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, "a3ds_settings.json")

SETTINGS_FILE = get_settings_path()

# --- RELEASE NOTES ---
RELEASE_NOTES = f"""
<h2>Welcome to {APP_NAME} {APP_VERSION}</h2>
<p><b>Bambu Lab network control:</b></p>
<ul>
    <li><b>New Setup Wizard step:</b> choose USB or Bambu Lab (network). Bambu setup asks for the printer's IP address, serial number and Access Code, and has a Test Connection button.</li>
    <li><b>Printer Control tab:</b> live temperatures and print progress, pause, resume, stop, chamber light, print speed, and sending G-code lines.</li>
    <li><b>Printer Files:</b> upload, list, delete and start files on a Bambu printer over the network.</li>
    <li><b>Settings:</b> new Bambu Lab tab (after Connection).</li>
</ul>
<p><b>Fixes:</b></p>
<ul>
    <li>Settings dialog no longer resets your temperatures to the material defaults every time it opens.</li>
    <li>Setup Wizard now saves your Walls and Travel speeds and your chosen material (they were ignored before).</li>
    <li>G-code start and end sequences now set extruder mode, heat the bed first, turn the fan off at the end, and use your first layer temperatures and fan speed.</li>
    <li>SD Card Manager no longer loses part of the file list.</li>
    <li>macOS: choosing PrusaSlicer.app now runs the program inside the bundle.</li>
    <li>Update checks now verify the server's certificate.</li>
    <li>Settings are saved safely and are only readable by you.</li>
</ul>
<p><i>Developers: Elwin Rivera, Gemini 3.0 &amp; Claude</i></p>
"""

# Serial Imports
NO_PORT_MARKERS = ("No ports found", "pyserial not installed")
try:
    import serial
    from serial.tools import list_ports
    def get_serial_ports():
        ports = [port.device for port in list_ports.comports()]
        return ports if ports else ["No ports found"]
except ImportError:
    serial = None
    def get_serial_ports(): return ["pyserial not installed"]

# MQTT import (Bambu Lab)
try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

# Defaults
DEFAULTS = {
    "printer_type": "usb",   # "usb" or "bambu"
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
    "last_run_version": "",
    "check_updates_on_startup": 1,
    # Bambu Lab (LAN)
    "bambu_ip": "",
    "bambu_serial": "",
    "bambu_access_code": "",
    "bambu_model": "",
    "bambu_use_ams": 0,
    "bambu_timelapse": 0,
    "bambu_bed_leveling": 1,
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

# Bambu Lab models and their build volumes (X, Y, Z in mm). None = leave bed size alone.
BAMBU_MODELS = [
    ("P1P", (256, 256, 256)),
    ("P1S", (256, 256, 256)),
    ("X1 / X1 Carbon", (256, 256, 256)),
    ("A1", (256, 256, 256)),
    ("A1 mini", (180, 180, 180)),
    ("Other Bambu Lab model", None),
]

BAMBU_STATE_NAMES = {
    "IDLE": "Idle", "PREPARE": "Preparing", "RUNNING": "Printing",
    "PAUSE": "Paused", "FINISH": "Finished", "FAILED": "Failed", "SLICING": "Preparing",
}


# --- HELPERS ---
def valid_host(text):
    """True for an IPv4 address or a plain hostname."""
    return bool(text) and len(text) <= 253 and re.fullmatch(r"[A-Za-z0-9.\-]+", text) is not None


def resolve_slicer_executable(path):
    """On macOS the user picks PrusaSlicer.app, which is a folder. Run the program inside it."""
    if path and path.lower().rstrip("/").endswith(".app") and os.path.isdir(path):
        macos_dir = os.path.join(path, "Contents", "MacOS")
        if os.path.isdir(macos_dir):
            candidates = sorted(
                f for f in os.listdir(macos_dir)
                if os.path.isfile(os.path.join(macos_dir, f)) and os.access(os.path.join(macos_dir, f), os.X_OK)
            )
            for preferred in ("PrusaSlicer", "prusa-slicer"):
                if preferred in candidates:
                    return os.path.join(macos_dir, preferred)
            if candidates:
                return os.path.join(macos_dir, candidates[0])
    return path


def load_settings_file():
    """Returns the saved settings dict, or None if missing/unreadable."""
    if not os.path.exists(SETTINGS_FILE):
        return None
    try:
        with open(SETTINGS_FILE, 'r') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def write_settings_file(slicer, params):
    """Atomic write; the file holds the Bambu access code, so keep it private."""
    directory = os.path.dirname(SETTINGS_FILE)
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump({"slicer": slicer, "params": params}, f, indent=2)
        if platform.system() != "Windows":
            os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, SETTINGS_FILE)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def make_ssl_context():
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx.load_verify_locations(certifi.where())
    except Exception:
        pass
    return ctx


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()


def clear_radio_group(group, layout):
    for b in list(group.buttons()):
        group.removeButton(b)
    clear_layout(layout)


def build_start_gcode(p, safe_x, safe_y, safe_z):
    e_mode = "M83" if int(p.get('use_relative_e', 0)) else "M82"
    lines = [
        "G90", e_mode, "G28", "G92 E0",
        f"M140 S{p['temp_bed']}", f"M104 S{p['temp_nozzle']}",
        f"G1 Z{safe_z} F3000", f"G1 X{safe_x:.1f} Y{safe_y:.1f} F5000",
        f"M190 S{p['temp_bed']}", f"M109 S{p['temp_nozzle']}",
    ]
    return "\\n".join(lines)


def build_end_gcode(p, present_y):
    lines = [
        "M104 S0", "M140 S0", "M107",
        "M83", "G1 E-1 F2700",
        "G91", "G1 Z10 F3000", "G90",
        f"G1 X0 Y{present_y:.1f} F5000",
    ]
    if not int(p.get('use_relative_e', 0)):
        lines.append("M82")
    lines.append("M84")
    return "\\n".join(lines)


def fmt_minutes(m):
    try:
        m = int(m)
    except (TypeError, ValueError):
        return "--"
    if m < 60:
        return f"{m} min"
    return f"{m // 60} hr {m % 60} min"


def fmt_temp(v):
    try:
        return f"{float(v):.1f}"
    except (TypeError, ValueError):
        return "--"


# --- UPDATE LOGIC THREAD ---
class UpdateChecker(QThread):
    finished = pyqtSignal(dict)
    def run(self):
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) A3DS-Updater',
                'Accept': 'application/vnd.github.v3+json'
            }
            req = urllib.request.Request(UPDATE_URL, headers=headers)
            with urllib.request.urlopen(req, timeout=10, context=make_ssl_context()) as response:
                data = json.loads(response.read().decode())
                self.finished.emit(data)
        except urllib.error.HTTPError as e:
            self.finished.emit({"error": f"HTTP {e.code}"})
        except Exception as e:
            self.finished.emit({"error": str(e)})

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


# --- BAMBU LAB (LAN) ---
class ImplicitFTPS(ftplib.FTP_TLS):
    """Bambu printers use implicit FTPS on port 990 (TLS from the first byte)."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sock = None

    @property
    def sock(self):
        return self._sock

    @sock.setter
    def sock(self, value):
        if value is not None and not isinstance(value, ssl.SSLSocket):
            value = self.context.wrap_socket(value, server_hostname=self.host)
        self._sock = value

    def ntransfercmd(self, cmd, rest=None):
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        if self._prot_p:
            conn = self.context.wrap_socket(conn, server_hostname=self.host)
        return conn, size


class BambuController:
    """Talks to a Bambu Lab printer in LAN mode.
    Status and commands: MQTT over TLS on port 8883 (user 'bblp', password = Access Code).
    File transfer: implicit FTPS on port 990.
    MQTT callbacks run on a background thread, so they never touch the GUI; they put
    messages in a queue that the main window drains with drain_log()."""

    MQTT_PORT = 8883
    FTP_PORT = 990
    CONNECT_TIMEOUT = 12.0
    PUSHALL_INTERVAL = 30.0
    SPEEDS = ["Silent", "Standard", "Sport", "Ludicrous"]   # levels 1..4

    def __init__(self, client_factory=None):
        self._factory = client_factory or self._default_factory
        self.client = None
        self.state = "disconnected"   # disconnected, connecting, connected, reconnecting, failed
        self.error = ""
        self.ip = ""
        self.serial = ""
        self.access_code = ""
        self.report = {}
        self.lock = threading.Lock()
        self.log_queue = queue.Queue()
        self._seq = 0
        self._started = 0.0
        self._last_pushall = 0.0
        self._user_disconnect = False

    # --- plumbing ---
    @staticmethod
    def _default_factory(client_id):
        if mqtt is None:
            raise RuntimeError("The paho-mqtt package is not installed. Install it with: pip install paho-mqtt")
        try:
            return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        except AttributeError:
            return mqtt.Client(client_id=client_id)

    def log(self, msg):
        self.log_queue.put(msg)

    def drain_log(self):
        out = []
        while True:
            try:
                out.append(self.log_queue.get_nowait())
            except queue.Empty:
                return out

    def next_seq(self):
        self._seq += 1
        return str(self._seq)

    @property
    def topic_report(self):
        return f"device/{self.serial}/report"

    @property
    def topic_request(self):
        return f"device/{self.serial}/request"

    def is_active(self):
        return self.state in ("connecting", "connected", "reconnecting")

    def is_connected(self):
        return self.state == "connected"

    @staticmethod
    def _rc_ok(rc):
        if hasattr(rc, "is_failure"):
            return not rc.is_failure
        try:
            return int(rc) == 0
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _rc_text(rc):
        text = str(rc)
        low = text.lower()
        if "authorized" in low or "bad user" in low or text.strip() == "5" or text.strip() == "4":
            return "The printer refused the login. Check the Access Code (it changes when you toggle LAN mode on the printer)."
        return f"The printer refused the connection ({text})."

    # --- connection ---
    def connect_async(self, ip, serial_number, access_code):
        ip, serial_number, access_code = ip.strip(), serial_number.strip(), access_code.strip()
        if not valid_host(ip):
            raise ValueError("The printer IP address is missing or not valid.")
        if not serial_number or not re.fullmatch(r"[A-Za-z0-9]+", serial_number):
            raise ValueError("The printer serial number is missing or not valid (letters and numbers only).")
        if not access_code:
            raise ValueError("The Access Code is missing.")
        self.disconnect(quiet=True)
        self.ip, self.serial, self.access_code = ip, serial_number, access_code
        with self.lock:
            self.report = {}
        self.error = ""
        self._user_disconnect = False
        self.state = "connecting"
        self._started = time.time()
        try:
            client = self._factory(f"a3ds-{os.getpid()}-{int(time.time())}")
            client.username_pw_set("bblp", access_code)
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE      # printers use a self-signed certificate
            client.tls_set_context(ctx)
            client.on_connect = self._on_connect
            client.on_disconnect = self._on_disconnect
            client.on_message = self._on_message
            try:
                client.reconnect_delay_set(1, 10)
            except Exception:
                pass
            self.client = client
            client.connect_async(ip, self.MQTT_PORT, keepalive=30)
            client.loop_start()
        except Exception as e:
            self.state = "failed"
            self.error = str(e)
            self._teardown()
            return
        self.log(f"Connecting to Bambu printer at {ip}...")

    def poll_state(self):
        """Call regularly from the GUI thread. Applies the connect timeout."""
        if self.state == "connecting" and time.time() - self._started > self.CONNECT_TIMEOUT:
            self._teardown()
            self.state = "failed"
            self.error = (f"Could not reach the printer at {self.ip} within {int(self.CONNECT_TIMEOUT)} seconds. "
                          "Check the IP address, that this computer is on the same network, and that LAN mode is on.")
        return self.state

    def _teardown(self):
        c, self.client = self.client, None
        if c is not None:
            try:
                c.disconnect()
            except Exception:
                pass
            try:
                c.loop_stop()
            except Exception:
                pass

    def disconnect(self, quiet=False):
        was_active = self.is_active()
        self._user_disconnect = True
        self._teardown()
        self.state = "disconnected"
        if was_active and not quiet:
            self.log("*** DISCONNECTED ***")

    def _on_connect(self, client, userdata, flags, rc, *extra):
        if self._rc_ok(rc):
            try:
                client.subscribe(self.topic_report)
            except Exception as e:
                self.log(f"ERROR: could not subscribe: {e}")
            self.error = ""
            self.state = "connected"
            self.log(f"*** CONNECTED to Bambu printer {self.serial} ***")
            self.request_full_status(force=True)
        else:
            self.error = self._rc_text(rc)
            self.state = "failed"
            self.log(f"*** CONNECTION FAILED: {self.error} ***")

    def _on_disconnect(self, client, userdata, *args):
        rc = args[1] if len(args) >= 2 else (args[0] if args else 0)
        if self._user_disconnect or self.state in ("failed", "disconnected"):
            return
        self.state = "reconnecting"
        self.log(f"*** CONNECTION LOST ({rc}); retrying... ***")

    def _on_message(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode("utf-8", errors="ignore"))
        except ValueError:
            return
        if not isinstance(data, dict):
            return
        pr = data.get("print")
        if isinstance(pr, dict):
            result = pr.get("result")
            if result and result != "success":
                self.log(f"PRINTER REJECTED '{pr.get('command')}': {pr.get('reason') or result}")
            with self.lock:
                self.report.setdefault("print", {}).update(pr)

    # --- sending ---
    def publish(self, payload):
        if self.state != "connected" or self.client is None:
            return False
        try:
            self.client.publish(self.topic_request, json.dumps(payload), qos=0)
            return True
        except Exception as e:
            self.log(f"ERROR: {e}")
            return False

    def request_full_status(self, force=False):
        now = time.time()
        if not force and now - self._last_pushall < self.PUSHALL_INTERVAL:
            return False
        self._last_pushall = now
        return self.publish({"pushing": {"sequence_id": self.next_seq(), "command": "pushall"}})

    def maybe_pushall(self):
        return self.request_full_status(force=False)

    def send_gcode(self, text):
        lines = [l.strip() for l in text.replace("\r", "\n").split("\n") if l.strip()]
        lines = ["".join(ch for ch in l if ch.isprintable()) for l in lines]
        lines = [l for l in lines if l]
        if not lines:
            return False
        ok = self.publish({"print": {"sequence_id": self.next_seq(), "command": "gcode_line",
                                     "param": "\n".join(lines) + "\n"}})
        if ok:
            self.log(f"SENT: {'; '.join(lines)}")
        return ok

    def _simple_print_cmd(self, command, label):
        ok = self.publish({"print": {"sequence_id": self.next_seq(), "command": command}})
        if ok:
            self.log(f"SENT: {label}")
        return ok

    def pause(self):  return self._simple_print_cmd("pause", "Pause print")
    def resume(self): return self._simple_print_cmd("resume", "Resume print")
    def stop(self):   return self._simple_print_cmd("stop", "Stop print")

    def set_light(self, on):
        ok = self.publish({"system": {"sequence_id": self.next_seq(), "command": "ledctrl",
                                      "led_node": "chamber_light", "led_mode": "on" if on else "off",
                                      "led_on_time": 500, "led_off_time": 500,
                                      "loop_times": 0, "interval_time": 0}})
        if ok:
            self.log(f"SENT: Chamber light {'on' if on else 'off'}")
        return ok

    def set_speed(self, level):
        if level not in (1, 2, 3, 4):
            return False
        ok = self.publish({"print": {"sequence_id": self.next_seq(), "command": "print_speed", "param": str(level)}})
        if ok:
            self.log(f"SENT: Print speed {self.SPEEDS[level - 1]}")
        return ok

    def start_file(self, remote_name, use_ams=False, timelapse=False, bed_leveling=True, plate=1):
        if not re.fullmatch(r"[A-Za-z0-9._\-]+", remote_name or ""):
            self.log("ERROR: file name has unsupported characters")
            return False
        low = remote_name.lower()
        if low.endswith(".3mf"):
            payload = {"print": {
                "sequence_id": self.next_seq(), "command": "project_file",
                "param": f"Metadata/plate_{int(plate)}.gcode",
                "project_id": "0", "profile_id": "0", "task_id": "0", "subtask_id": "0",
                "subtask_name": remote_name, "url": f"file:///sdcard/{remote_name}",
                "timelapse": bool(timelapse), "bed_type": "auto", "bed_leveling": bool(bed_leveling),
                "flow_cali": False, "vibration_cali": True, "layer_inspect": False,
                "use_ams": bool(use_ams)}}
        elif low.endswith((".gcode", ".gco", ".g")):
            payload = {"print": {"sequence_id": self.next_seq(), "command": "gcode_file",
                                 "param": f"/sdcard/{remote_name}"}}
        else:
            self.log("ERROR: only .3mf and .gcode files can be printed")
            return False
        ok = self.publish(payload)
        if ok:
            self.log(f"SENT: Start print {remote_name}")
        return ok

    # --- reading ---
    def snapshot(self):
        with self.lock:
            p = dict(self.report.get("print", {}))
        light = None
        for item in p.get("lights_report", []) or []:
            if isinstance(item, dict) and item.get("node") == "chamber_light":
                light = (item.get("mode") == "on")
        raw_state = str(p.get("gcode_state", "")) if p else ""
        spd = p.get("spd_lvl")
        try:
            spd = int(spd)
        except (TypeError, ValueError):
            spd = None
        try:
            err = int(p.get("print_error") or 0)
        except (TypeError, ValueError):
            err = 0
        return {
            "nozzle_temp": fmt_temp(p.get("nozzle_temper")),
            "nozzle_target": fmt_temp(p.get("nozzle_target_temper")),
            "bed_temp": fmt_temp(p.get("bed_temper")),
            "bed_target": fmt_temp(p.get("bed_target_temper")),
            "chamber_temp": fmt_temp(p.get("chamber_temper")),
            "raw_state": raw_state,
            "state": BAMBU_STATE_NAMES.get(raw_state, raw_state.title() if raw_state else "--"),
            "file": str(p.get("subtask_name") or p.get("gcode_file") or "--"),
            "percent": p.get("mc_percent"),
            "layer": p.get("layer_num"),
            "total_layers": p.get("total_layer_num"),
            "remaining": fmt_minutes(p.get("mc_remaining_time")) if p.get("mc_remaining_time") is not None else "--",
            "speed_level": spd,
            "light": light,
            "error": err,
        }

    # --- FTPS ---
    def _ftps(self):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ftp = ImplicitFTPS(context=ctx, timeout=20)
        ftp.connect(self.ip, self.FTP_PORT)
        ftp.login("bblp", self.access_code)
        ftp.prot_p()
        return ftp

    def ftps_list(self):
        ftp = self._ftps()
        try:
            names = ftp.nlst()
        finally:
            try:
                ftp.close()
            except Exception:
                pass
        keep = [os.path.basename(n) for n in names if n.lower().endswith((".3mf", ".gcode", ".gco"))]
        return sorted(set(keep), key=str.lower)

    @staticmethod
    def safe_remote_name(local_path):
        base = os.path.basename(local_path)
        return re.sub(r"[^A-Za-z0-9._\-]", "_", base)

    def ftps_remote_size(self, name):
        ftp = self._ftps()
        try:
            ftp.voidcmd("TYPE I")
            return ftp.size(name)
        finally:
            try:
                ftp.close()
            except Exception:
                pass

    def ftps_upload(self, local_path, progress_cb=None):
        name = self.safe_remote_name(local_path)
        total = os.path.getsize(local_path)
        sent = [0]

        def cb(block):
            sent[0] += len(block)
            if progress_cb and total:
                progress_cb(min(100, int(sent[0] * 100 / total)))

        ftp = self._ftps()
        try:
            with open(local_path, "rb") as fh:
                try:
                    ftp.storbinary(f"STOR {name}", fh, blocksize=64 * 1024, callback=cb)
                except (TimeoutError, ssl.SSLError, EOFError):
                    # Some firmware closes the data channel without a clean TLS goodbye.
                    # Treat it as success only if the whole file really arrived.
                    if self.ftps_remote_size(name) != total:
                        raise
        finally:
            try:
                ftp.close()
            except Exception:
                pass
        if progress_cb:
            progress_cb(100)
        return name

    def ftps_delete(self, name):
        ftp = self._ftps()
        try:
            ftp.delete(name)
        finally:
            try:
                ftp.close()
            except Exception:
                pass


class BambuFileWorker(QThread):
    done = pyqtSignal(str, bool, object)
    progress = pyqtSignal(int)
    def __init__(self, controller, op, arg=None):
        super().__init__()
        self.controller = controller
        self.op = op
        self.arg = arg
    def run(self):
        try:
            if self.op == "list":
                result = self.controller.ftps_list()
            elif self.op == "upload":
                result = self.controller.ftps_upload(self.arg, progress_cb=self.progress.emit)
            elif self.op == "delete":
                self.controller.ftps_delete(self.arg)
                result = self.arg
            else:
                raise ValueError("Unknown operation")
            self.done.emit(self.op, True, result)
        except Exception as e:
            self.done.emit(self.op, False, str(e) or e.__class__.__name__)


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

        # TAB 1b: Bambu Lab
        tab_bam = QWidget()
        v_bam = QVBoxLayout()

        grp_type = QGroupBox("Printer Connection Type")
        l_type = QVBoxLayout()
        self.bg_ptype = QButtonGroup()
        self.rad_type_usb = QRadioButton("USB cable (Marlin, Klipper, RepRap)")
        self.rad_type_bambu = QRadioButton("Bambu Lab over the network (LAN)")
        self.bg_ptype.addButton(self.rad_type_usb, 1)
        self.bg_ptype.addButton(self.rad_type_bambu, 2)
        l_type.addWidget(self.rad_type_usb)
        l_type.addWidget(self.rad_type_bambu)
        grp_type.setLayout(l_type)
        v_bam.addWidget(grp_type)
        if self.params.get("printer_type", "usb") == "bambu":
            self.rad_type_bambu.setChecked(True)
        else:
            self.rad_type_usb.setChecked(True)

        grp_net = QGroupBox("Bambu Lab Network Details")
        f_net = QFormLayout()
        self.edit_bip = QLineEdit(self.params.get("bambu_ip", ""))
        self.edit_bip.setAccessibleName("Printer IP Address")
        f_net.addRow("IP Address:", self.edit_bip)
        self.edit_bser = QLineEdit(self.params.get("bambu_serial", ""))
        self.edit_bser.setAccessibleName("Printer Serial Number")
        f_net.addRow("Serial Number:", self.edit_bser)
        self.edit_bcode = QLineEdit(self.params.get("bambu_access_code", ""))
        self.edit_bcode.setAccessibleName("Access Code")
        self.edit_bcode.setEchoMode(QLineEdit.EchoMode.Password)
        f_net.addRow("Access Code:", self.edit_bcode)
        self.chk_show_code = QCheckBox("Show access code")
        self.chk_show_code.toggled.connect(
            lambda on: self.edit_bcode.setEchoMode(QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        f_net.addRow("", self.chk_show_code)
        grp_net.setLayout(f_net)
        v_bam.addWidget(grp_net)

        grp_bopt = QGroupBox("Bambu Print Options")
        l_bopt = QVBoxLayout()
        self.chk_ams = QCheckBox("Use AMS")
        self.chk_ams.setChecked(bool(self.params.get("bambu_use_ams", 0)))
        self.chk_timelapse = QCheckBox("Record timelapse")
        self.chk_timelapse.setChecked(bool(self.params.get("bambu_timelapse", 0)))
        self.chk_level = QCheckBox("Auto bed leveling before print")
        self.chk_level.setChecked(bool(self.params.get("bambu_bed_leveling", 1)))
        l_bopt.addWidget(self.chk_ams); l_bopt.addWidget(self.chk_timelapse); l_bopt.addWidget(self.chk_level)
        grp_bopt.setLayout(l_bopt)
        v_bam.addWidget(grp_bopt)

        lbl_bnote = QLabel("Find the IP address and Access Code on the printer's screen under Network. "
                           "The serial number is under Device info.")
        lbl_bnote.setWordWrap(True)
        v_bam.addWidget(lbl_bnote)
        v_bam.addStretch()
        tab_bam.setLayout(v_bam)
        self.tabs.addTab(tab_bam, "Bambu Lab")

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

        # TAB 5: Updates (Release Notes Moved Here)
        tab_update = QWidget()
        up_layout = QVBoxLayout()
        l_up_head = QHBoxLayout()
        self.lbl_up_status = QLabel("Current Version: " + APP_VERSION)
        self.btn_up_check = QPushButton("Check Now")
        self.btn_up_check.clicked.connect(self.trigger_update_check)
        l_up_head.addWidget(self.lbl_up_status)
        l_up_head.addWidget(self.btn_up_check)
        up_layout.addLayout(l_up_head)

        self.chk_auto_up = QCheckBox("Check automatically on startup")
        self.chk_auto_up.setChecked(bool(self.params.get("check_updates_on_startup", 1)))
        up_layout.addWidget(self.chk_auto_up)

        up_layout.addSpacing(10)
        up_layout.addWidget(QLabel("Release Notes:"))
        self.txt_up_notes = QTextEdit()
        self.txt_up_notes.setReadOnly(True)
        self.txt_up_notes.setHtml(RELEASE_NOTES)
        up_layout.addWidget(self.txt_up_notes)
        tab_update.setLayout(up_layout)
        self.tabs.addTab(tab_update, "Updates")

        # TAB 6: About
        tab_about = QWidget()
        about_layout = QVBoxLayout()
        title = QLabel(f"{APP_NAME} {APP_VERSION}")
        title.setStyleSheet("font-weight: bold; font-size: 16px;")
        about_layout.addWidget(title)
        sub = QLabel(f"{FULL_NAME}")
        sub.setStyleSheet("font-size: 14px; margin-bottom: 10px;")
        about_layout.addWidget(sub)

        credit = QLabel("Developers:\n- Elwin Rivera\n- Gemini 3.0\n- Claude")
        credit.setStyleSheet("font-style: italic;")
        about_layout.addWidget(credit)

        about_layout.addStretch()
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
        # Connect AFTER the initial selection, otherwise opening this dialog
        # overwrites the saved temperatures with the material defaults.
        self.bg_mat.buttonToggled.connect(self.on_mat_toggle)

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

    def trigger_update_check(self):
        self.btn_up_check.setEnabled(False)
        self.lbl_up_status.setText("Connecting...")
        self.up_thread = UpdateChecker()
        self.up_thread.finished.connect(self.on_up_finished)
        self.up_thread.start()

    def on_up_finished(self, data):
        self.btn_up_check.setEnabled(True)
        if "error" in data:
            self.lbl_up_status.setText(f"Error: {data['error']}")
            return
        latest = data.get("tag_name", APP_VERSION)
        body = data.get("body", "No release notes found on GitHub.")
        self.txt_up_notes.setPlainText(body)
        if latest != APP_VERSION:
            self.lbl_up_status.setText(f"Update Found: {latest}")
            if QMessageBox.question(self, "Update", f"New version {latest} found. View release?") == QMessageBox.StandardButton.Yes:
                import webbrowser
                webbrowser.open(data.get("html_url", ""))
        else:
            self.lbl_up_status.setText(f"Up to date: {APP_VERSION}")

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
        keep = self.bg_port.checkedButton().text() if self.bg_port.checkedButton() else ""
        clear_radio_group(self.bg_port, self.sl)

        ports = get_serial_ports()
        current_port = keep or self.params.get("serial_port", "")

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

        # Bambu Lab details are checked before anything is saved
        use_bambu = self.rad_type_bambu.isChecked()
        bip = self.edit_bip.text().strip()
        bser = self.edit_bser.text().strip()
        bcode = self.edit_bcode.text().strip()
        if use_bambu:
            problem = ""
            if not valid_host(bip): problem = "The printer IP address is missing or not valid."
            elif not re.fullmatch(r"[A-Za-z0-9]+", bser): problem = "The printer serial number is missing or not valid."
            elif not bcode: problem = "The Access Code is missing."
            if problem:
                QMessageBox.warning(self, "Bambu Lab Settings", problem + "\nFill these in on the Bambu Lab tab, or choose USB.")
                return
        self.params["printer_type"] = "bambu" if use_bambu else "usb"
        self.params["bambu_ip"] = bip
        self.params["bambu_serial"] = bser
        self.params["bambu_access_code"] = bcode
        self.params["bambu_use_ams"] = 1 if self.chk_ams.isChecked() else 0
        self.params["bambu_timelapse"] = 1 if self.chk_timelapse.isChecked() else 0
        self.params["bambu_bed_leveling"] = 1 if self.chk_level.isChecked() else 0

        self.params["material"] = m
        if m in MATERIALS:
            self.params["fan_speed"] = MATERIALS[m]["fan"]
        self.params["temp_nozzle"] = self.spin_nozzle_temp.value()
        self.params["temp_bed"] = self.spin_bed_temp.value()
        self.params["layer_height"] = self.spin_layer.value()
        self.params["infill_density"] = self.spin_infill.value()
        self.params["elefant_foot_comp"] = self.spin_ele.value()
        self.params["check_updates_on_startup"] = 1 if self.chk_auto_up.isChecked() else 0

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

        if self.bg_port.checkedButton() and self.bg_port.checkedButton().text() not in NO_PORT_MARKERS:
            self.params["serial_port"] = self.bg_port.checkedButton().text()
        if self.bg_baud.checkedButton():
            self.params["baud_rate"] = self.bg_baud.checkedButton().text()

        self.accept()

# --- SETUP WIZARD ---
class SetupWizard(QDialog):
    PAGE_TITLES = {
        "slicer": "Locate PrusaSlicer App",
        "type": "Printer Type",
        "hardware": "Hardware",
        "usb": "Connection",
        "bambu": "Bambu Lab Connection",
        "safety": "Safety & Retraction",
        "speed": "Speeds",
        "defaults": "Printing Defaults",
    }

    def __init__(self, user_params, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} Setup Wizard")
        self.setGeometry(150, 150, 600, 700)
        self.params = user_params
        self.paths = {"slicer": getattr(parent, "slicer_exe", "") or ""}
        self.main_layout = QVBoxLayout()
        self.stack = QStackedWidget()
        self.page_index = {}
        self.title_labels = {}
        self.pos = 0
        self.order = []
        self.bambu_rel_set = False
        self.bmodel_applied = False

        def add_page(name, widget):
            self.page_index[name] = self.stack.addWidget(widget)

        def title_label(name):
            lbl = QLabel(self.PAGE_TITLES[name])
            self.title_labels[name] = lbl
            return lbl

        # PAGE 1: APP
        self.page1 = QWidget()
        l1 = QVBoxLayout()
        l1.addWidget(title_label("slicer"))
        self.btn_slicer = QPushButton("Find App...")
        self.btn_slicer.clicked.connect(self.locate_slicer)
        l1.addWidget(self.btn_slicer)
        l1.addStretch()
        self.page1.setLayout(l1)
        add_page("slicer", self.page1)

        # PAGE 1b: PRINTER TYPE
        self.page_type = QWidget()
        lt = QVBoxLayout()
        lt.addWidget(title_label("type"))
        grp_ptype = QGroupBox("How does this computer talk to your printer?")
        lpt = QVBoxLayout()
        self.bg_ptype = QButtonGroup()
        self.rad_type_usb = QRadioButton("USB cable (Marlin, Klipper, RepRap)")
        self.rad_type_bambu = QRadioButton("Bambu Lab over the network (LAN)")
        self.bg_ptype.addButton(self.rad_type_usb, 1)
        self.bg_ptype.addButton(self.rad_type_bambu, 2)
        lpt.addWidget(self.rad_type_usb)
        lpt.addWidget(self.rad_type_bambu)
        grp_ptype.setLayout(lpt)
        lt.addWidget(grp_ptype)
        if self.params.get("printer_type", "usb") == "bambu":
            self.rad_type_bambu.setChecked(True)
        else:
            self.rad_type_usb.setChecked(True)
        lt.addStretch()
        self.page_type.setLayout(lt)
        add_page("type", self.page_type)

        # PAGE 2: HARDWARE
        self.page2 = QWidget()
        l2 = QVBoxLayout()
        l2.addWidget(title_label("hardware"))

        self.grp_flav = QGroupBox("Firmware (USB & Slicer)")
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

        self.grp_flav.setLayout(lf)
        l2.addWidget(self.grp_flav)

        self.grp_bmodel = QGroupBox("Bambu Lab Model")
        lbm = QVBoxLayout()
        self.bg_bmodel = QButtonGroup()
        saved_model = self.params.get("bambu_model", "")
        for i, (label, _size) in enumerate(BAMBU_MODELS):
            r = QRadioButton(label)
            self.bg_bmodel.addButton(r, i)
            lbm.addWidget(r)
            if label == saved_model:
                r.setChecked(True)
        if self.bg_bmodel.checkedButton() is None:
            self.bg_bmodel.button(0).setChecked(True)
        self.grp_bmodel.setLayout(lbm)
        l2.addWidget(self.grp_bmodel)
        self.grp_bmodel.hide()

        grp_bed = QGroupBox("Bed Size (mm)")
        lb = QFormLayout()
        self.spin_bed_x = AccessSpinBox()
        self.spin_bed_x.setRange(50, 1000)
        self.spin_bed_x.setValue(int(self.params.get("bed_x", 220)))
        lb.addRow("X (Width):", self.spin_bed_x)
        self.spin_bed_y = AccessSpinBox()
        self.spin_bed_y.setRange(50, 1000)
        self.spin_bed_y.setValue(int(self.params.get("bed_y", 220)))
        lb.addRow("Y (Depth):", self.spin_bed_y)
        self.spin_bed_z = AccessSpinBox()
        self.spin_bed_z.setRange(50, 1000)
        self.spin_bed_z.setValue(int(self.params.get("bed_z", 250)))
        lb.addRow("Z (Height):", self.spin_bed_z)
        grp_bed.setLayout(lb)
        l2.addWidget(grp_bed)
        self.bg_bmodel.buttonToggled.connect(self.on_bmodel_toggle)

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
        ns = self.params.get("nozzle_size", 0.4)
        if ns == 0.2: self.rad_02.setChecked(True)
        elif ns == 0.6: self.rad_06.setChecked(True)
        elif ns == 0.8: self.rad_08.setChecked(True)
        elif ns == 1.0: self.rad_10.setChecked(True)
        elif ns == 0.4: self.rad_04.setChecked(True)
        else:
            self.rad_ncus.setChecked(True)
            self.spin_nozzle_custom.setValue(float(ns))
        grp_noz.setLayout(lnoz)
        l2.addWidget(grp_noz)

        l2.addStretch()
        self.page2.setLayout(l2)
        add_page("hardware", self.page2)

        # PAGE 3: CONNECTION (USB)
        self.page3 = QWidget()
        l3 = QVBoxLayout()
        l3.addWidget(title_label("usb"))

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
        saved_baud = str(self.params.get("baud_rate", "115200"))
        for i, baud in enumerate(BAUD_RATES):
            r = QRadioButton(baud)
            self.bg_baud.addButton(r, i)
            sl_b.addWidget(r)
            if baud == saved_baud: r.setChecked(True)
        if self.bg_baud.checkedButton() is None:
            self.bg_baud.buttons()[0].setChecked(True)
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
        self.wiz_poll_idle.setValue(int(self.params.get("poll_interval_idle", 2)))
        l_cset.addRow("Idle Rate:", self.wiz_poll_idle)
        self.wiz_poll_print = AccessSpinBox()
        self.wiz_poll_print.setRange(1, 60)
        self.wiz_poll_print.setValue(int(self.params.get("poll_interval_print", 10)))
        l_cset.addRow("Printing Rate:", self.wiz_poll_print)
        grp_conn_set.setLayout(l_cset)
        l3.addWidget(grp_conn_set)

        self.page3.setLayout(l3)
        add_page("usb", self.page3)

        # PAGE 3b: CONNECTION (BAMBU LAB)
        self.page_bambu = QWidget()
        lbam = QVBoxLayout()
        lbam.addWidget(title_label("bambu"))
        lbl_intro = QLabel("On the printer: turn on LAN Mode (Settings, WLAN or Network). "
                           "The IP address and Access Code are shown on that same screen. "
                           "The serial number is under Device info. "
                           "Newer firmware may also need Developer Mode turned on before it accepts commands.")
        lbl_intro.setWordWrap(True)
        lbam.addWidget(lbl_intro)

        grp_bnet = QGroupBox("Printer Network Details")
        fb = QFormLayout()
        self.wiz_bip = QLineEdit(self.params.get("bambu_ip", ""))
        self.wiz_bip.setAccessibleName("Printer IP Address")
        fb.addRow("IP Address:", self.wiz_bip)
        self.wiz_bser = QLineEdit(self.params.get("bambu_serial", ""))
        self.wiz_bser.setAccessibleName("Printer Serial Number")
        fb.addRow("Serial Number:", self.wiz_bser)
        self.wiz_bcode = QLineEdit(self.params.get("bambu_access_code", ""))
        self.wiz_bcode.setAccessibleName("Access Code")
        self.wiz_bcode.setEchoMode(QLineEdit.EchoMode.Password)
        fb.addRow("Access Code:", self.wiz_bcode)
        self.wiz_show_code = QCheckBox("Show access code")
        self.wiz_show_code.toggled.connect(
            lambda on: self.wiz_bcode.setEchoMode(QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        fb.addRow("", self.wiz_show_code)
        grp_bnet.setLayout(fb)
        lbam.addWidget(grp_bnet)

        self.btn_test_bambu = QPushButton("Test Connection")
        self.btn_test_bambu.clicked.connect(self.test_bambu)
        lbam.addWidget(self.btn_test_bambu)
        lbam.addStretch()
        self.page_bambu.setLayout(lbam)
        add_page("bambu", self.page_bambu)
        self.test_ctl = None
        self.test_timer = QTimer()
        self.test_timer.timeout.connect(self.check_test_result)

        # PAGE 4: SAFETY
        self.page4 = QWidget()
        l4 = QVBoxLayout()
        l4.addWidget(title_label("safety"))
        grp_math = QGroupBox("Extrusion")
        lm = QVBoxLayout()
        self.bg_math = QButtonGroup()
        self.rad_abs = QRadioButton("Absolute (Safe)")
        self.rad_rel = QRadioButton("Relative")
        self.bg_math.addButton(self.rad_abs, 0)
        self.bg_math.addButton(self.rad_rel, 1)
        lm.addWidget(self.rad_abs); lm.addWidget(self.rad_rel)
        if int(self.params.get("use_relative_e", 0)): self.rad_rel.setChecked(True)
        else: self.rad_abs.setChecked(True)
        grp_math.setLayout(lm)
        l4.addWidget(grp_math)

        grp_ret = QGroupBox("Retraction")
        lr = QFormLayout()
        self.spin_ret_len = AccessDoubleSpinBox()
        self.spin_ret_len.setRange(0, 20)
        self.spin_ret_len.setValue(float(self.params.get("retract_len", 5.0)))
        lr.addRow("Length (mm):", self.spin_ret_len)
        self.spin_min_travel = AccessDoubleSpinBox()
        self.spin_min_travel.setRange(0, 10.0)
        self.spin_min_travel.setValue(float(self.params.get("retract_min_travel", 2.0)))
        lr.addRow("Min Travel (mm):", self.spin_min_travel)
        grp_ret.setLayout(lr)
        l4.addWidget(grp_ret)
        l4.addStretch()
        self.page4.setLayout(l4)
        add_page("safety", self.page4)

        # PAGE 5: SPEED
        self.page5 = QWidget()
        l5 = QVBoxLayout()
        l5.addWidget(title_label("speed"))
        form_spd = QFormLayout()
        self.spin_first = AccessSpinBox()
        self.spin_first.setRange(10, 100); self.spin_first.setValue(int(self.params.get("first_layer_speed", 20)))
        form_spd.addRow("First Layer:", self.spin_first)
        self.spin_walls = AccessSpinBox()
        self.spin_walls.setRange(10, 300); self.spin_walls.setValue(int(self.params.get("perimeter_speed", 40)))
        form_spd.addRow("Walls:", self.spin_walls)
        self.spin_travel = AccessSpinBox()
        self.spin_travel.setRange(50, 500); self.spin_travel.setValue(int(self.params.get("travel_speed", 150)))
        form_spd.addRow("Travel:", self.spin_travel)
        l5.addLayout(form_spd)
        l5.addStretch()
        self.page5.setLayout(l5)
        add_page("speed", self.page5)

        # PAGE 6: DEFAULTS
        self.page6 = QWidget()
        l6 = QVBoxLayout()
        l6.addWidget(title_label("defaults"))
        grp_def = QGroupBox("Common Settings")
        ldef = QVBoxLayout()
        ldef.addWidget(QLabel("Material:"))
        self.bg_def_mat = QButtonGroup()
        mats = ["PLA", "PETG", "ABS", "ASA", "TPU", "Nylon", "PC", "Custom"]
        saved_mat = self.params.get("material", "PLA")
        if saved_mat not in mats: saved_mat = "Custom"
        for i, m in enumerate(mats, 1):
            r = QRadioButton(m)
            self.bg_def_mat.addButton(r, i)
            ldef.addWidget(r)
            if m == saved_mat: r.setChecked(True)

        form_def = QFormLayout()
        self.wiz_temp_nozzle = AccessSpinBox()
        self.wiz_temp_nozzle.setRange(0, 350); self.wiz_temp_nozzle.setValue(int(self.params.get("temp_nozzle", 205)))
        form_def.addRow("Nozzle Temp:", self.wiz_temp_nozzle)
        self.wiz_temp_bed = AccessSpinBox()
        self.wiz_temp_bed.setRange(0, 120); self.wiz_temp_bed.setValue(int(self.params.get("temp_bed", 60)))
        form_def.addRow("Bed Temp:", self.wiz_temp_bed)
        ldef.addLayout(form_def)
        # Connected after the initial values are in place so saved temperatures survive.
        self.bg_def_mat.buttonToggled.connect(self.on_wiz_mat_toggle)

        self.wiz_infill = AccessSpinBox()
        self.wiz_infill.setRange(0, 100); self.wiz_infill.setValue(int(self.params.get("infill_density", 20)))
        ldef.addWidget(QLabel("Infill (%):")); ldef.addWidget(self.wiz_infill)
        self.wiz_layer = AccessDoubleSpinBox()
        self.wiz_layer.setRange(0.05, 0.4); self.wiz_layer.setValue(float(self.params.get("layer_height", 0.20)))
        ldef.addWidget(QLabel("Layer Height (mm):")); ldef.addWidget(self.wiz_layer)

        grp_def.setLayout(ldef)
        l6.addWidget(grp_def); l6.addStretch()
        self.page6.setLayout(l6)
        add_page("defaults", self.page6)

        self.main_layout.addWidget(self.stack)
        nav_layout = QHBoxLayout()
        self.btn_back = QPushButton("Exit Setup")
        self.btn_back.clicked.connect(self.go_back)
        self.btn_next = QPushButton("Next")
        self.btn_next.clicked.connect(self.go_next)
        self.btn_next.setDefault(True)
        self.btn_next.setEnabled(False)
        nav_layout.addWidget(self.btn_back); nav_layout.addWidget(self.btn_next)
        self.main_layout.addLayout(nav_layout)
        self.setLayout(self.main_layout)
        self.refresh_ports_wiz()

        if self.paths["slicer"]:
            self.btn_slicer.setText(f"Found: {os.path.basename(self.paths['slicer'])}")
        self.show_page(0)

    # --- page flow ---
    def page_order(self):
        middle = "bambu" if self.rad_type_bambu.isChecked() else "usb"
        return ["slicer", "type", "hardware", middle, "safety", "speed", "defaults"]

    def show_page(self, pos):
        self.order = self.page_order()
        self.pos = max(0, min(pos, len(self.order) - 1))
        name = self.order[self.pos]
        for i, n in enumerate(self.order, 1):
            self.title_labels[n].setText(f"Step {i}: {self.PAGE_TITLES[n]}")
        self.stack.setCurrentIndex(self.page_index[name])
        self.btn_back.setText("Exit Setup" if self.pos == 0 else "Back")
        self.btn_next.setText("Finish" if self.pos == len(self.order) - 1 else "Next")
        self.btn_next.setEnabled(bool(self.paths["slicer"]) if name == "slicer" else True)
        is_bambu = self.rad_type_bambu.isChecked()
        if name == "hardware":
            self.grp_flav.setVisible(not is_bambu)
            self.grp_bmodel.setVisible(is_bambu)
            if is_bambu and not self.bmodel_applied:
                self.bmodel_applied = True
                if not self.params.get("bambu_model", ""):
                    self.on_bmodel_toggle(self.bg_bmodel.checkedButton(), True)
        if name == "safety" and is_bambu and not self.bambu_rel_set:
            self.rad_rel.setChecked(True)   # Bambu printers use relative extrusion
            self.bambu_rel_set = True

    def go_next(self):
        name = self.order[self.pos]
        if name == "bambu" and not self.validate_bambu():
            return
        if self.pos < len(self.order) - 1:
            self.show_page(self.pos + 1)
        else:
            self.save_all(); self.accept()

    def go_back(self):
        if self.pos == 0: self.reject()
        else: self.show_page(self.pos - 1)

    def validate_bambu(self):
        ip = self.wiz_bip.text().strip()
        ser = self.wiz_bser.text().strip()
        code = self.wiz_bcode.text().strip()
        problem = ""
        if not valid_host(ip): problem = "Enter the printer's IP address."
        elif not re.fullmatch(r"[A-Za-z0-9]+", ser): problem = "Enter the printer's serial number (letters and numbers only)."
        elif not code: problem = "Enter the printer's Access Code."
        if problem:
            QMessageBox.warning(self, "Bambu Lab Connection", problem)
            return False
        return True

    # --- slicer / ports ---
    def locate_slicer(self):
        fname, _ = QFileDialog.getOpenFileName(self, "Locate PrusaSlicer", "/Applications", "Applications (*.app);;Executables (*.exe);;All Files (*)")
        if fname:
            self.paths["slicer"] = fname
            self.btn_slicer.setText(f"Found: {os.path.basename(fname)}")
            self.btn_next.setEnabled(True); self.btn_next.setFocus()

    def refresh_ports_wiz(self):
        keep = self.bg_port.checkedButton().text() if self.bg_port.checkedButton() else self.params.get("serial_port", "")
        clear_radio_group(self.bg_port, self.sl_usb)
        ports = get_serial_ports()
        chosen = False
        for i, port in enumerate(ports):
            r = QRadioButton(port)
            self.bg_port.addButton(r, i); self.sl_usb.addWidget(r)
            if port == keep:
                r.setChecked(True); chosen = True
        if not chosen and self.bg_port.buttons():
            self.bg_port.buttons()[0].setChecked(True)
        self.sl_usb.addStretch()

    def on_nozzle_toggle(self, btn, checked):
        if not checked: return
        if self.rad_ncus.isChecked():
            self.spin_nozzle_custom.show(); self.spin_nozzle_custom.setFocus()
        else: self.spin_nozzle_custom.hide()

    def on_bmodel_toggle(self, btn, checked):
        if not checked: return
        size = BAMBU_MODELS[self.bg_bmodel.id(btn)][1]
        if size:
            self.spin_bed_x.setValue(size[0])
            self.spin_bed_y.setValue(size[1])
            self.spin_bed_z.setValue(size[2])

    def on_wiz_mat_toggle(self, btn, checked):
        if not checked: return
        mat_name = btn.text().split(" ")[0]
        if mat_name in MATERIALS:
            p = MATERIALS[mat_name]
            self.wiz_temp_nozzle.setValue(p["nozzle"])
            self.wiz_temp_bed.setValue(p["bed"])

    # --- Bambu connection test ---
    def test_bambu(self):
        if not self.validate_bambu():
            return
        if mqtt is None:
            QMessageBox.warning(self, "Test Connection",
                                "The paho-mqtt package is not installed, so network control is unavailable.\n"
                                "Install it with: pip install paho-mqtt")
            return
        self.test_ctl = BambuController()
        try:
            self.test_ctl.connect_async(self.wiz_bip.text(), self.wiz_bser.text(), self.wiz_bcode.text())
        except ValueError as e:
            QMessageBox.warning(self, "Test Connection", str(e))
            self.test_ctl = None
            return
        self.btn_test_bambu.setEnabled(False)
        self.btn_test_bambu.setText("Testing...")
        self.test_timer.start(250)

    def check_test_result(self):
        if self.test_ctl is None:
            self.test_timer.stop(); return
        state = self.test_ctl.poll_state()
        if state in ("connecting", "reconnecting"):
            return
        self.test_timer.stop()
        ctl, self.test_ctl = self.test_ctl, None
        self.btn_test_bambu.setEnabled(True)
        self.btn_test_bambu.setText("Test Connection")
        if state == "connected":
            ctl.disconnect(quiet=True)
            QMessageBox.information(self, "Test Connection", "Success! The printer accepted the connection.")
        else:
            err = ctl.error or "The connection failed."
            ctl.disconnect(quiet=True)
            QMessageBox.warning(self, "Test Connection", err)

    def done(self, result):
        # make sure a half-finished test does not keep running after the wizard closes
        self.test_timer.stop()
        if self.test_ctl is not None:
            self.test_ctl.disconnect(quiet=True)
            self.test_ctl = None
        super().done(result)

    def save_all(self):
        is_bambu = self.rad_type_bambu.isChecked()
        self.params["printer_type"] = "bambu" if is_bambu else "usb"

        fid = self.bg_flav.checkedId()
        if is_bambu:
            self.params["gcode_flavor"] = "marlin2"
        else:
            self.params["gcode_flavor"] = "marlin" if fid == 1 else "klipper" if fid == 2 else "reprap"
        self.params["bed_x"] = self.spin_bed_x.value()
        self.params["bed_y"] = self.spin_bed_y.value()
        self.params["bed_z"] = self.spin_bed_z.value()

        nid = self.bg_noz.checkedId()
        sizes = {1: 0.2, 2: 0.4, 3: 0.6, 4: 0.8, 5: 1.0}
        self.params["nozzle_size"] = sizes.get(nid, self.spin_nozzle_custom.value())

        if is_bambu:
            self.params["bambu_ip"] = self.wiz_bip.text().strip()
            self.params["bambu_serial"] = self.wiz_bser.text().strip()
            self.params["bambu_access_code"] = self.wiz_bcode.text().strip()
            self.params["bambu_model"] = self.bg_bmodel.checkedButton().text() if self.bg_bmodel.checkedButton() else ""
        else:
            if self.bg_port.checkedButton() and self.bg_port.checkedButton().text() not in NO_PORT_MARKERS:
                self.params["serial_port"] = self.bg_port.checkedButton().text()
            if self.bg_baud.checkedButton(): self.params["baud_rate"] = self.bg_baud.checkedButton().text()

        self.params["poll_interval_idle"] = self.wiz_poll_idle.value()
        self.params["poll_interval_print"] = self.wiz_poll_print.value()
        self.params["use_relative_e"] = self.bg_math.checkedId()
        self.params["retract_len"] = self.spin_ret_len.value()
        self.params["retract_min_travel"] = self.spin_min_travel.value()
        self.params["first_layer_speed"] = self.spin_first.value()
        self.params["perimeter_speed"] = self.spin_walls.value()
        self.params["travel_speed"] = self.spin_travel.value()

        mat_btn = self.bg_def_mat.checkedButton()
        mat = mat_btn.text() if mat_btn else "PLA"
        self.params["material"] = mat
        self.params["fan_speed"] = MATERIALS[mat]["fan"] if mat in MATERIALS else self.params.get("fan_speed", 100)
        self.params["infill_density"] = self.wiz_infill.value()
        self.params["layer_height"] = self.wiz_layer.value()
        self.params["temp_nozzle"] = self.wiz_temp_nozzle.value()
        self.params["temp_bed"] = self.wiz_temp_bed.value()

# --- PRINTER LOGIC (USB) ---
class PrinterController:
    def __init__(self, console_output):
        self.ser = None
        self.is_connected = False
        self.console = console_output
        self.firmware_type = "marlin"
        self.capture = None   # when a list, everything received is also appended here
        self.status = {"bed_temp": "--", "bed_target": "--", "nozzle_temp": "--", "nozzle_target": "--", "position": "X-- Y-- Z--"}
        self.temp_regex = re.compile(r"T:([0-9\.]+) /([0-9\.]+) B:([0-9\.]+) /([0-9\.]+)")
        self.pos_regex = re.compile(r"X:([0-9\.\-]+)\s+Y:([0-9\.\-]+)\s+Z:([0-9\.\-]+)")
        self.ok_regex = re.compile(r"(?m)^ok\b")

    def set_firmware(self, fw_type):
        self.firmware_type = fw_type.lower()
        self.console.append(f"Firmware Protocol set to: {self.firmware_type}")

    def connect(self, port, baud):
        if self.is_connected: self.disconnect()
        if serial is None:
            self.console.append("*** CONNECTION FAILED: the pyserial package is not installed (pip install pyserial) ***")
            return False
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
        was = self.is_connected
        self.is_connected = False
        if was: self.console.append("*** DISCONNECTED ***")
        return True

    def _read_available(self):
        if self.ser and self.ser.in_waiting:
            text = self.ser.read(self.ser.in_waiting).decode('utf-8', errors='ignore')
            if self.capture is not None: self.capture.append(text)
            return text
        return ""

    def send_command(self, cmd, log=True):
        if not self.is_connected: return None
        clean_cmd = "".join(filter(lambda x: x.isprintable(), cmd.strip()))
        if not clean_cmd: return None
        try:
            self.ser.write((clean_cmd + '\n').encode('utf-8'))
            if log and 'M105' not in clean_cmd: self.console.append(f"SENT: {clean_cmd}")
            time.sleep(0.1)
            resp = self._read_available()
            # give the printer a little longer to finish its "ok" line
            deadline = time.time() + 0.4
            while not self.ok_regex.search(resp) and time.time() < deadline:
                time.sleep(0.02)
                resp += self._read_available()
            if resp and log and 'M105' not in clean_cmd: self.console.append(f"RECV: {resp.strip()}")
            return resp or None
        except Exception as e:
            self.console.append(f"ERROR: {e}")
            self.disconnect()
        return None

    def read_buffer(self):
        if not self.is_connected: return ""
        try:
            return self._read_available()
        except Exception:
            pass
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
        self.main_layout = QVBoxLayout(self)
        self.parent_window = parent

        self.file_group = QGroupBox("Files on SD Card")
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True)
        self.sw = QWidget(); self.file_layout = QVBoxLayout(self.sw)
        self.scroll.setWidget(self.sw)
        self.file_group_layout = QVBoxLayout(); self.file_group_layout.addWidget(self.scroll)
        self.file_group.setLayout(self.file_group_layout); self.main_layout.addWidget(self.file_group)

        self.lbl_status = QLabel("Ready"); self.main_layout.addWidget(self.lbl_status)
        btn_layout = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh List"); self.refresh_btn.clicked.connect(self.start_refresh)
        btn_layout.addWidget(self.refresh_btn)
        self.del_btn = QPushButton("Delete File"); self.del_btn.setStyleSheet("color: red"); self.del_btn.clicked.connect(self.delete_file)
        btn_layout.addWidget(self.del_btn); self.main_layout.addLayout(btn_layout)
        self.print_btn = QPushButton("Start Print from SD"); self.print_btn.clicked.connect(self.start_print)
        self.main_layout.addWidget(self.print_btn)

        self.selected_file = None
        self.file_buttons = QButtonGroup(self)
        self.wait_timer = QTimer(); self.wait_timer.setSingleShot(True); self.wait_timer.timeout.connect(self.finish_refresh)
        self.start_refresh()

    def start_refresh(self):
        clear_radio_group(self.file_buttons, self.file_layout)
        self.selected_file = None
        if not self.controller.is_connected:
            self.file_layout.addWidget(QLabel("Not Connected")); return
        self.refresh_btn.setEnabled(False); self.del_btn.setEnabled(False)
        self.lbl_status.setText("Listing files... Waiting 5s...")
        self.controller.capture = []
        self.controller.send_command("M21"); self.controller.send_command("M20")
        self.wait_timer.start(5000)

    def finish_refresh(self):
        self.controller.read_buffer()
        resp = "".join(self.controller.capture or [])
        self.controller.capture = None
        self.lbl_status.setText("List Updated.")
        self.refresh_btn.setEnabled(True); self.del_btn.setEnabled(True)
        found = False
        seen = set()
        for line in resp.splitlines():
            line = line.strip()
            if not line or line.startswith("Begin") or line.startswith("End"): continue
            parts = line.split()
            if not parts: continue
            fname = parts[0]
            if fname in seen: continue
            if os.path.splitext(fname)[1].lower() in [".gcode", ".gco", ".g"]:
                seen.add(fname)
                r = QRadioButton(line)
                self.file_buttons.addButton(r)
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

    def done(self, result):
        self.wait_timer.stop()
        self.controller.capture = None
        super().done(result)


class BambuFilesDialog(QDialog):
    """Same layout idea as the SD Card Manager, but the files live on the Bambu printer."""
    def __init__(self, parent, controller):
        super().__init__(parent)
        self.setWindowTitle("Bambu Printer Files")
        self.controller = controller
        self.parent_window = parent
        self.resize(500, 650)
        self.worker = None
        self.selected_file = None
        self.main_layout = QVBoxLayout(self)

        self.file_group = QGroupBox("Files on Printer")
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True)
        self.sw = QWidget(); self.file_layout = QVBoxLayout(self.sw)
        self.scroll.setWidget(self.sw)
        fgl = QVBoxLayout(); fgl.addWidget(self.scroll)
        self.file_group.setLayout(fgl); self.main_layout.addWidget(self.file_group)
        self.file_buttons = QButtonGroup(self)

        grp_opt = QGroupBox("Print Options")
        lo = QVBoxLayout()
        self.chk_ams = QCheckBox("Use AMS"); self.chk_ams.setChecked(bool(parent.params.get("bambu_use_ams", 0)))
        self.chk_time = QCheckBox("Record timelapse"); self.chk_time.setChecked(bool(parent.params.get("bambu_timelapse", 0)))
        self.chk_level = QCheckBox("Auto bed leveling before print"); self.chk_level.setChecked(bool(parent.params.get("bambu_bed_leveling", 1)))
        lo.addWidget(self.chk_ams); lo.addWidget(self.chk_time); lo.addWidget(self.chk_level)
        grp_opt.setLayout(lo); self.main_layout.addWidget(grp_opt)

        self.lbl_status = QLabel("Ready"); self.main_layout.addWidget(self.lbl_status)
        row1 = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh List"); self.refresh_btn.clicked.connect(self.start_refresh)
        self.upload_btn = QPushButton("Upload File..."); self.upload_btn.clicked.connect(self.upload_file)
        row1.addWidget(self.refresh_btn); row1.addWidget(self.upload_btn)
        self.main_layout.addLayout(row1)
        self.del_btn = QPushButton("Delete File"); self.del_btn.setStyleSheet("color: red"); self.del_btn.clicked.connect(self.delete_file)
        self.main_layout.addWidget(self.del_btn)
        self.print_btn = QPushButton("Start Print"); self.print_btn.clicked.connect(self.start_print)
        self.main_layout.addWidget(self.print_btn)
        self.close_btn = QPushButton("Close"); self.close_btn.clicked.connect(self.accept)
        self.main_layout.addWidget(self.close_btn)

        self.start_refresh()

    def set_busy(self, busy, text=None):
        for b in (self.refresh_btn, self.upload_btn, self.del_btn, self.print_btn):
            b.setEnabled(not busy)
        if text: self.lbl_status.setText(text)

    def run_worker(self, op, arg=None):
        self.worker = BambuFileWorker(self.controller, op, arg)
        self.worker.done.connect(self.on_worker_done)
        self.worker.progress.connect(self.on_progress)
        self.worker.start()

    def start_refresh(self):
        clear_radio_group(self.file_buttons, self.file_layout)
        self.selected_file = None
        if not self.controller.is_connected():
            self.file_layout.addWidget(QLabel("Not Connected")); return
        self.set_busy(True, "Listing files...")
        self.run_worker("list")

    def on_progress(self, pct):
        self.lbl_status.setText(f"Uploading... {pct}%")

    def on_worker_done(self, op, ok, payload):
        self.set_busy(False)
        if not ok:
            self.lbl_status.setText("Failed.")
            QMessageBox.warning(self, "Printer Files", f"The {op} did not work:\n{payload}")
            if op != "list": self.start_refresh()
            return
        if op == "list":
            clear_radio_group(self.file_buttons, self.file_layout)
            if not payload:
                self.file_layout.addWidget(QLabel("No print files found."))
            for name in payload:
                r = QRadioButton(name)
                self.file_buttons.addButton(r)
                r.toggled.connect(lambda c, f=name: self.set_file(f) if c else None)
                self.file_layout.addWidget(r)
            self.file_layout.addStretch()
            self.lbl_status.setText(f"List Updated. {len(payload)} file(s).")
        elif op == "upload":
            self.lbl_status.setText(f"Uploaded {payload}.")
            self.start_refresh()
        elif op == "delete":
            self.lbl_status.setText(f"Deleted {payload}.")
            self.start_refresh()

    def set_file(self, f): self.selected_file = f

    def upload_file(self):
        start_dir = os.path.dirname(self.parent_window.last_gcode) if self.parent_window.last_gcode else ""
        path, _ = QFileDialog.getOpenFileName(self, "Choose a file to upload", start_dir, "Print files (*.3mf *.gcode *.gco)")
        if not path: return
        if path.lower().endswith(".3mf"):
            has_plate = False
            try:
                if zipfile.is_zipfile(path):
                    with zipfile.ZipFile(path) as zf:
                        has_plate = any(n.startswith("Metadata/plate_") and n.endswith(".gcode") for n in zf.namelist())
            except Exception:
                pass
            if not has_plate:
                if QMessageBox.question(self, "Not a sliced Bambu file",
                        "This 3MF does not contain sliced G-code for a Bambu printer (for example, a project exported "
                        "by this app's 'Export as 3MF Project' option). The printer will not be able to print it.\n\n"
                        "Upload anyway?") != QMessageBox.StandardButton.Yes:
                    return
        self.set_busy(True, "Uploading... 0%")
        self.run_worker("upload", path)

    def delete_file(self):
        if self.selected_file and QMessageBox.question(self, "Confirm", f"Delete {self.selected_file} from the printer?") == QMessageBox.StandardButton.Yes:
            self.set_busy(True, "Deleting...")
            self.run_worker("delete", self.selected_file)

    def start_print(self):
        name = self.selected_file
        if not name:
            QMessageBox.warning(self, "Start Print", "Select a file first."); return
        if not self.controller.is_connected():
            QMessageBox.warning(self, "Start Print", "Not connected."); return
        if name.lower().endswith((".gcode", ".gco", ".g")):
            if QMessageBox.question(self, "Raw G-code",
                    "Plain G-code from PrusaSlicer does not include Bambu's own startup, calibration or AMS steps, "
                    "and its temperatures and speeds are not tuned for your printer. "
                    "Watch the first layers closely.\n\nContinue?") != QMessageBox.StandardButton.Yes:
                return
        if QMessageBox.question(self, "Start Print",
                f"Start printing {name}?\nMake sure the build plate is clear.") != QMessageBox.StandardButton.Yes:
            return
        ok = self.controller.start_file(name, use_ams=self.chk_ams.isChecked(),
                                        timelapse=self.chk_time.isChecked(), bed_leveling=self.chk_level.isChecked())
        if ok:
            self.parent_window.set_polling_mode("print")
            self.accept()
        else:
            QMessageBox.warning(self, "Start Print", "The command could not be sent.")

    def done(self, result):
        if self.worker is not None and self.worker.isRunning():
            self.worker.wait(3000)
        super().done(result)


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
        self.pending_out = ""
        self.temp_cfg = ""
        self.slice_log = ""
        self.ctl = None
        self.bambu = BambuController()
        self.is_printing = False
        self.poll_mode = "idle"
        self.conn_started_ui = False
        self._last_bstate = None
        self._last_berror = 0
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
        self.apply_printer_type()

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
        layout.addWidget(self.btn_slice)
        return tab

    def create_printer_tab(self):
        tab = QWidget(); layout = QVBoxLayout(tab)
        l_act = QHBoxLayout()
        self.btn_con = QPushButton("Connect"); self.btn_con.clicked.connect(self.toggle_connect)
        self.btn_sd = QPushButton("SD Card Manager"); self.btn_sd.clicked.connect(self.open_sd)
        self.btn_estop = QPushButton("EMERGENCY STOP"); self.btn_estop.setStyleSheet("background-color: red; color: white")
        self.btn_estop.clicked.connect(self.emergency_stop)
        l_act.addWidget(self.btn_con); l_act.addWidget(self.btn_sd); l_act.addWidget(self.btn_estop); layout.addLayout(l_act)

        self.grp_pos = QGroupBox("Axis Positions"); l_pos = QVBoxLayout(); self.lbl_pos = QLabel("X: --  Y: --  Z: --")
        l_pos.addWidget(self.lbl_pos); self.grp_pos.setLayout(l_pos); layout.addWidget(self.grp_pos)

        grp_temp = QGroupBox("Temperature"); l_temp = QFormLayout()
        self.lbl_noz = QLabel("Nozzle: -- / --"); self.lbl_bed = QLabel("Bed: -- / --")
        l_temp.addRow("Nozzle:", self.lbl_noz); l_temp.addRow("Bed:", self.lbl_bed)
        grp_temp.setLayout(l_temp); layout.addWidget(grp_temp)

        # Bambu Lab only: print status and controls
        self.grp_bstat = QGroupBox("Print Status"); l_bst = QVBoxLayout()
        self.lbl_bstate = QLabel("Status: --"); self.lbl_bfile = QLabel("File: --")
        self.lbl_bprog = QLabel("Progress: --"); self.lbl_blayer = QLabel("Layer: -- / --")
        self.lbl_beta = QLabel("Time Remaining: --"); self.lbl_bchamber = QLabel("Chamber: --")
        for w in (self.lbl_bstate, self.lbl_bfile, self.lbl_bprog, self.lbl_blayer, self.lbl_beta, self.lbl_bchamber):
            l_bst.addWidget(w)
        self.grp_bstat.setLayout(l_bst); layout.addWidget(self.grp_bstat)

        self.grp_bctl = QGroupBox("Bambu Controls"); l_bct = QVBoxLayout()
        row = QHBoxLayout()
        self.btn_bpause = QPushButton("Pause Print"); self.btn_bpause.clicked.connect(self.bambu_pause)
        self.btn_bresume = QPushButton("Resume Print"); self.btn_bresume.clicked.connect(self.bambu_resume)
        self.btn_bstop = QPushButton("Stop Print"); self.btn_bstop.clicked.connect(self.bambu_stop)
        row.addWidget(self.btn_bpause); row.addWidget(self.btn_bresume); row.addWidget(self.btn_bstop)
        l_bct.addLayout(row)
        self.btn_blight = QPushButton("Turn Chamber Light On"); self.btn_blight.clicked.connect(self.bambu_toggle_light)
        l_bct.addWidget(self.btn_blight)
        f_spd = QFormLayout()
        self.combo_bspeed = QComboBox(); self.combo_bspeed.addItems(BambuController.SPEEDS)
        self.combo_bspeed.setCurrentIndex(1)
        self.combo_bspeed.setAccessibleName("Print Speed")
        self.combo_bspeed.activated.connect(self.bambu_set_speed)
        f_spd.addRow("Print Speed:", self.combo_bspeed)
        l_bct.addLayout(f_spd)
        self.grp_bctl.setLayout(l_bct); layout.addWidget(self.grp_bctl)
        self.bambu_light_on = None

        l_cmd = QHBoxLayout(); self.line_cmd = QLineEdit(); self.line_cmd.setPlaceholderText("Enter G-code (e.g., G28)")
        self.line_cmd.setAccessibleName("G-code command")
        self.line_cmd.returnPressed.connect(self.send_manual)
        self.btn_send = QPushButton("Send"); self.btn_send.clicked.connect(self.send_manual)
        l_cmd.addWidget(self.line_cmd); l_cmd.addWidget(self.btn_send); layout.addLayout(l_cmd)

        layout.addWidget(QLabel("Console Output:")); self.console = QTextEdit(); self.console.setReadOnly(True)
        layout.addWidget(self.console); self.ctl = PrinterController(self.console)
        self.timer = QTimer(); self.timer.timeout.connect(self.update_status)
        self.conn_timer = QTimer(); self.conn_timer.timeout.connect(self.check_bambu_connect)
        return tab

    # --- printer type / connection helpers ---
    def is_bambu(self):
        return self.params.get("printer_type", "usb") == "bambu"

    def printer_connected(self):
        return self.bambu.is_connected() if self.is_bambu() else self.ctl.is_connected

    def apply_printer_type(self):
        is_b = self.is_bambu()
        # never leave the other kind of connection open
        if is_b and self.ctl.is_connected:
            self.ctl.disconnect()
        if not is_b and self.bambu.is_active():
            self.bambu.disconnect()
            self.conn_timer.stop()
        self.timer.stop()
        self.grp_bstat.setVisible(is_b)
        self.grp_bctl.setVisible(is_b)
        self.grp_pos.setVisible(not is_b)
        self.btn_sd.setText("Printer Files" if is_b else "SD Card Manager")
        self.line_cmd.setPlaceholderText("Enter G-code (e.g., G28)")
        self.reset_labels()
        self.update_conn_ui()

    def update_conn_ui(self):
        connected = self.printer_connected()
        if self.is_bambu() and self.bambu.state == "connecting":
            self.btn_con.setText("Connecting..."); self.btn_con.setEnabled(False)
        else:
            self.btn_con.setText("Disconnect" if connected else "Connect"); self.btn_con.setEnabled(True)
        for w in (self.btn_bpause, self.btn_bresume, self.btn_bstop, self.btn_blight, self.combo_bspeed):
            w.setEnabled(connected and self.is_bambu())

    def flush_bambu_log(self):
        for line in self.bambu.drain_log():
            self.console.append(line)

    def check_setup(self):
        data = load_settings_file()
        if data is not None:
            self.slicer_exe = data.get("slicer", "")
            self.params.update(data.get("params", {}))
            self.apply_printer_type()
            self.ctl.set_firmware(self.params.get("gcode_flavor", "marlin"))
            if self.params.get("last_run_version", "") != APP_VERSION:
                ReleaseNotesDialog(self).exec()
                self.params["last_run_version"] = APP_VERSION; self.save_settings()
            if not self.slicer_exe: self.run_wizard()

            # Silent background check on startup
            if self.params.get("check_updates_on_startup", 1):
                self.perform_auto_check()
        else:
            self.run_wizard()

    def perform_auto_check(self):
        self.auto_up = UpdateChecker()
        self.auto_up.finished.connect(self.on_auto_up_finished)
        self.auto_up.start()

    def on_auto_up_finished(self, data):
        if "error" not in data and data.get("tag_name") != APP_VERSION:
            if QMessageBox.question(self, "Update", "New version available. Open Settings?") == QMessageBox.StandardButton.Yes:
                self.open_config()

    def run_wizard(self):
        wiz = SetupWizard(self.params, self)
        if wiz.exec():
            self.slicer_exe = wiz.paths["slicer"]
            self.params["last_run_version"] = APP_VERSION; self.save_settings()
            self.ctl.set_firmware(self.params.get("gcode_flavor", "marlin"))
            self.apply_printer_type()

    def open_config(self):
        if ParameterDialog(self.params, self).exec():
            self.save_settings()
            self.apply_printer_type()

    def save_settings(self):
        try:
            write_settings_file(self.slicer_exe, self.params)
        except Exception as e:
            QMessageBox.warning(self, "Settings", f"Your settings could not be saved:\n{e}")

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
        safe_x = float(p['bed_x']) * 0.05
        safe_y = float(p['bed_y']) * 0.05
        safe_z = 2.0
        present_y = float(p['bed_y']) * 0.95
        temp_n, temp_b = p['temp_nozzle'], p['temp_bed']
        fan = int(p.get('fan_speed', 100))

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
temperature = {temp_n}
first_layer_temperature = {temp_n}
bed_temperature = {temp_b}
first_layer_bed_temperature = {temp_b}
cooling = 1
min_fan_speed = {fan}
max_fan_speed = {fan}
bridge_fan_speed = {100 if fan > 0 else 0}
disable_fan_first_layers = 1
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
start_gcode = {build_start_gcode(p, safe_x, safe_y, safe_z)}
end_gcode = {build_end_gcode(p, present_y)}
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
        exe = resolve_slicer_executable(self.slicer_exe)
        cmd = [exe, "--load", cfg_path, "--scale", str(scale_factor), action_flag, self.model_path, "--output", out_f]

        self.temp_cfg = cfg_path
        self.pending_out = out_f
        self.btn_slice.setEnabled(False); self.btn_slice.setText("Working...")
        self.slicer_thread = SlicingThread(cmd)
        self.slicer_thread.finished_sig.connect(self.on_slice_done)
        self.slicer_thread.start()

    def on_slice_done(self, code, path, log):
        self.btn_slice.setEnabled(True); self.btn_slice.setText("Slice and Save G-code")
        self.slice_log = log
        if self.temp_cfg and os.path.exists(self.temp_cfg): os.remove(self.temp_cfg)
        if code == 0:
            self.last_gcode = self.pending_out
            QMessageBox.information(self, "Success", "Operation Complete!")
        else: QMessageBox.warning(self, "Failed", "Operation failed. Check debug logs.")

    def show_logs(self): LogWindow(self.slice_log, self).exec()

    def set_polling_mode(self, mode):
        self.timer.stop()
        self.poll_mode = mode
        interval = int(self.params.get("poll_interval_print" if mode == "print" else "poll_interval_idle", 2)) * 1000
        self.timer.start(interval)

    def toggle_connect(self):
        if self.is_bambu():
            self.toggle_connect_bambu()
            return
        if self.ctl.is_connected:
            self.ctl.disconnect(); self.btn_con.setText("Connect"); self.timer.stop(); self.reset_labels()
        else:
            port = self.params.get("serial_port", "")
            if not port or port in NO_PORT_MARKERS: QMessageBox.warning(self, "Error", "No port selected."); return
            if self.ctl.connect(port, self.params.get("baud_rate", "115200")):
                self.btn_con.setText("Disconnect"); self.set_polling_mode("idle")

    def toggle_connect_bambu(self):
        if self.bambu.is_active():
            self.bambu.disconnect()
            self.conn_timer.stop(); self.timer.stop()
            self.flush_bambu_log()
            self.reset_labels(); self.update_conn_ui()
            return
        if mqtt is None:
            QMessageBox.warning(self, "Bambu Lab",
                                "The paho-mqtt package is not installed, so network control is unavailable.\n"
                                "Install it with: pip install paho-mqtt")
            return
        try:
            self.bambu.connect_async(self.params.get("bambu_ip", ""), self.params.get("bambu_serial", ""),
                                     self.params.get("bambu_access_code", ""))
        except ValueError as e:
            QMessageBox.warning(self, "Bambu Lab", f"{e}\nOpen Settings, Bambu Lab tab, to fix it.")
            return
        self._last_bstate = None
        self._last_berror = 0
        self.update_conn_ui()
        self.conn_timer.start(250)

    def check_bambu_connect(self):
        state = self.bambu.poll_state()
        self.flush_bambu_log()
        if state == "connecting":
            return
        self.conn_timer.stop()
        if state == "connected":
            self.update_conn_ui()
            self.set_polling_mode("idle")
        else:
            err = self.bambu.error or "The connection failed."
            self.bambu.disconnect(quiet=True)
            self.update_conn_ui()
            QMessageBox.warning(self, "Bambu Lab Connection Failed", err)

    def reset_labels(self):
        self.lbl_noz.setText("Nozzle: -- / --"); self.lbl_bed.setText("Bed: -- / --"); self.lbl_pos.setText("X: --  Y: --  Z: --")
        self.lbl_bstate.setText("Status: --"); self.lbl_bfile.setText("File: --"); self.lbl_bprog.setText("Progress: --")
        self.lbl_blayer.setText("Layer: -- / --"); self.lbl_beta.setText("Time Remaining: --"); self.lbl_bchamber.setText("Chamber: --")

    def update_status(self):
        if self.is_bambu():
            self.update_status_bambu()
            return
        if not self.ctl.is_connected:
            # the connection dropped (cable pulled, port error)
            self.timer.stop(); self.reset_labels(); self.update_conn_ui()
            return
        s = self.ctl.get_status()
        self.lbl_noz.setText(f"Nozzle: {s['nozzle_temp']} / {s['nozzle_target']}")
        self.lbl_bed.setText(f"Bed: {s['bed_temp']} / {s['bed_target']}")
        self.lbl_pos.setText(f"{s['position']}")
        if not self.ctl.is_connected:
            self.timer.stop(); self.reset_labels(); self.update_conn_ui()

    def update_status_bambu(self):
        self.bambu.poll_state()
        self.flush_bambu_log()
        if not self.bambu.is_active():
            self.timer.stop(); self.reset_labels(); self.update_conn_ui()
            return
        if not self.bambu.is_connected():
            return      # reconnecting; the log already says so
        self.bambu.maybe_pushall()
        s = self.bambu.snapshot()
        self.lbl_noz.setText(f"Nozzle: {s['nozzle_temp']} / {s['nozzle_target']}")
        self.lbl_bed.setText(f"Bed: {s['bed_temp']} / {s['bed_target']}")
        self.lbl_bchamber.setText(f"Chamber: {s['chamber_temp']}")
        self.lbl_bstate.setText(f"Status: {s['state']}")
        self.lbl_bfile.setText(f"File: {s['file']}")
        pct = s['percent']
        self.lbl_bprog.setText(f"Progress: {pct}%" if pct is not None else "Progress: --")
        lay = s['layer'] if s['layer'] is not None else "--"
        tot = s['total_layers'] if s['total_layers'] is not None else "--"
        self.lbl_blayer.setText(f"Layer: {lay} / {tot}")
        self.lbl_beta.setText(f"Time Remaining: {s['remaining']}")

        if s['light'] is not None:
            self.bambu_light_on = s['light']
            self.btn_blight.setText("Turn Chamber Light Off" if s['light'] else "Turn Chamber Light On")
        if s['speed_level'] in (1, 2, 3, 4) and not self.combo_bspeed.view().isVisible():
            self.combo_bspeed.setCurrentIndex(s['speed_level'] - 1)

        # say it in the console when something important changes
        if s['raw_state'] and s['raw_state'] != self._last_bstate:
            if self._last_bstate is not None:
                self.console.append(f"Printer status: {s['state']}")
            self._last_bstate = s['raw_state']
            busy = s['raw_state'] in ("RUNNING", "PAUSE", "PREPARE", "SLICING")
            wanted = "print" if busy else "idle"
            if wanted != self.poll_mode:
                self.set_polling_mode(wanted)
        err = s['error']
        if err and err != self._last_berror:
            self.console.append(f"Printer reported error code 0x{int(err):08X}")
        self._last_berror = err

    def send_manual(self):
        text = self.line_cmd.text().strip()
        if not text:
            return
        if self.is_bambu():
            if not self.bambu.is_connected():
                self.console.append("Not connected."); return
            if not self.bambu.send_gcode(text):
                self.console.append("The command could not be sent.")
        else:
            if not self.ctl.is_connected:
                self.console.append("Not connected."); return
            self.ctl.send_command(text)
        self.line_cmd.clear()
        self.flush_bambu_log()

    def emergency_stop(self):
        if self.is_bambu():
            if self.bambu.is_connected():
                self.bambu.stop()
                self.flush_bambu_log()
            else:
                self.console.append("Not connected.")
        elif self.ctl.is_connected:
            self.ctl.send_command("M112")
        else:
            self.console.append("Not connected.")

    def bambu_pause(self):
        self.bambu.pause(); self.flush_bambu_log()

    def bambu_resume(self):
        self.bambu.resume(); self.flush_bambu_log()

    def bambu_stop(self):
        if QMessageBox.question(self, "Stop Print", "Stop the current print? This cannot be resumed.") == QMessageBox.StandardButton.Yes:
            self.bambu.stop(); self.flush_bambu_log()

    def bambu_toggle_light(self):
        want_on = not bool(self.bambu_light_on)
        if self.bambu.set_light(want_on):
            self.bambu_light_on = want_on
            self.btn_blight.setText("Turn Chamber Light Off" if want_on else "Turn Chamber Light On")
        self.flush_bambu_log()

    def bambu_set_speed(self, index):
        self.bambu.set_speed(index + 1); self.flush_bambu_log()

    def open_sd(self):
        if not self.printer_connected(): QMessageBox.warning(self, "Error", "Not connected."); return
        self.timer.stop()
        if self.is_bambu():
            BambuFilesDialog(self, self.bambu).exec()
        else:
            SDCardManagerDialog(self, self.ctl).exec()
        if self.printer_connected(): self.set_polling_mode(self.poll_mode)

    def closeEvent(self, event):
        try:
            self.timer.stop(); self.conn_timer.stop()
            if self.ctl is not None and self.ctl.is_connected: self.ctl.disconnect()
            self.bambu.disconnect(quiet=True)
        finally:
            super().closeEvent(event)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    w = CombinedWindow(); w.show()
    sys.exit(app.exec())
