#======================= IMPORTS =================
import sys
import os
import csv
import serial
import serial.tools.list_ports
import traceback
import datetime
import subprocess

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel,
    QVBoxLayout, QHBoxLayout, QTabWidget,
    QGridLayout, QLineEdit, QSplashScreen,
    QStackedWidget, QTextEdit, QComboBox,
    QPushButton, QFileDialog
)
from PyQt6.QtGui import QColor, QPainter, QPixmap
from PyQt6.QtCore import ( 
    Qt, QRectF, QPropertyAnimation,
    pyqtProperty, pyqtSignal, QTimer, QThread
)

# ================= CRASH LOGGING =================

LOG_DIR = os.path.join(os.path.abspath("."), "logs")
LOG_FILE = os.path.join(LOG_DIR, "app.log")
os.makedirs(LOG_DIR, exist_ok=True)

def log_crash(exc_type, exc_value, exc_tb):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write("\n" + "=" * 60 + "\n")
        f.write(f"Crash Time: {datetime.datetime.now()}\n")
        traceback.print_exception(exc_type, exc_value, exc_tb, file=f)

sys.excepthook = log_crash

# ================= RESOURCE PATH =================

def resource_path(relative_path):
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

# ================= SERIAL UTILITIES =================

BAUD_RATES = [
    "300", "1200", "2400", "4800",
    "9600", "14400", "19200",
    "38400", "57600", "115200"
]

def list_com_ports():
    return [p.device for p in serial.tools.list_ports.comports()]

def get_default_com_port():
    ports = list_com_ports()
    return ports[0] if ports else None

class SerialThread(QThread):
    data_received = pyqtSignal(str)
    status_changed = pyqtSignal(bool, str)

    def __init__(self, port, baud=9600):
        super().__init__()
        self.port = port
        self.baud = baud
        self.running = True
        self.ser = None

    def run(self):
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=1)
            self.status_changed.emit(True, self.port)
        except Exception as e:
            self.status_changed.emit(False, str(e))
            raise

        while self.running:
            try:
                line = self.ser.readline().decode(errors="ignore").strip()
                if line:
                    self.data_received.emit(line)
            except Exception:
                raise

    def send(self, text):
        if self.ser and self.ser.is_open:
            self.ser.write((text + "\n").encode())

    def stop(self):
        self.running = False
        if self.ser and self.ser.is_open:
            self.ser.close()

# ================= THEMES =================

DARK_THEME = {
    "bg": "#121212", "text": "#FFFFFF", "panel": "#1E1E1E",
    "panel2": "#2A2A2A", "sidebar": "#2E2E2E", "sidebar_active": "#4A4A4A",
    "border": "#444444", "input_bg": "#FFFFFF", "switch_track": "#666666", "tab_text": "#FFFFFF"
}

LIGHT_THEME = {
    "bg": "#FFFFFF", "text": "#000000", "panel": "#EAEAEA",
    "panel2": "#F5F5F5", "sidebar": "#DDDDDD", "sidebar_active": "#C0C0C0",
    "border": "#AAAAAA", "input_bg": "#FFFFFF", "switch_track": "#BBBBBB", "tab_text": "#000000"
}

ERROR_BG = "#C62828"
ERROR_TEXT = "#FFFFFF"

# ================= TOGGLE SWITCH =================

class ToggleSwitch(QWidget):
    toggled = pyqtSignal(bool)
    def __init__(self, checked=True):
        super().__init__()
        self.setFixedSize(52,26)
        self._checked = checked
        self._offset = 26 if checked else 2
        self.track_color = QColor("#666666")
        self.anim = QPropertyAnimation(self, b"offset", self)
        self.anim.setDuration(180)

    def set_theme(self, theme):
        self.track_color = QColor(theme["switch_track"])
        self.update()

    def mousePressEvent(self, event):
        self._checked = not self._checked
        self.anim.stop()
        self.anim.setStartValue(self._offset)
        self.anim.setEndValue(26 if self._checked else 2)
        self.anim.start()
        self.toggled.emit(self._checked)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.track_color)
        p.drawRoundedRect(QRectF(0,0,52,26),13,13)
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QRectF(self._offset,2,22,22))

    def get_offset(self): return self._offset
    def set_offset(self, v): self._offset = v; self.update()
    offset = pyqtProperty(int, get_offset, set_offset)

# ================= SIDEBAR ITEM =================

class SidebarItem(QLabel):
    clicked = pyqtSignal()
    def mousePressEvent(self, event):
        self.clicked.emit()

# ================= DATA RECORDING =================

class DataRecorder:
    def __init__(self):
        self.data_history = []
        self.field_names = [
            "TIME", "Voltage", "Current", "Frequency-PWM", "POT Detection",
            "Watts", "POT Temperature", "Coil Temperature", "OUT8", 
            "Set value", "A", "E", "B", "F", "C", "G", "D"
        ]
        self.last_serial_data = ["0"] * 8  # For incoming serial data (first 8 fields)
        self.last_input_data = ["0"] * 8   # For user input data (last 8 fields)
        
    def record_data(self, serial_data, input_data):
        """Record a new data entry with timestamp"""
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        
        # Ensure we have exactly 8 values for each section
        serial_values = serial_data[:8] + ["0"] * (8 - len(serial_data))
        input_values = input_data[:8] + ["0"] * (8 - len(input_data))
        
        # Combine timestamp, serial data, and input data
        record = [timestamp] + serial_values + input_values
        self.data_history.append(record)
        
        # Store for CSV export
        self.last_serial_data = serial_values
        self.last_input_data = input_values
        
    def get_csv_data(self):
        """Return data in CSV format with headers"""
        return [self.field_names] + self.data_history

# ================= MAIN WINDOW =================

class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Flame Free")
        self.resize(1000,600)
        self.current_theme = DARK_THEME
        self.hw_params = []
        self.serial_history = {"input": [], "output": []}
        self.monitor_paused = False
        self.data_recorder = DataRecorder()
        self.record_timer = QTimer()
        self.record_timer.timeout.connect(self.record_current_data)
        self.record_timer.start(1000)  # Record every second

        central = QWidget()
        self.setCentralWidget(central)
        main = QVBoxLayout(central)
        self.tabs = QTabWidget()
        main.addWidget(self.tabs)

        self.build_monitor_tab()
        self.build_serial_log_tab()
        self.build_calibration_tab()
        self.build_settings_tab()

        self.apply_theme(self.current_theme)

        port = get_default_com_port()
        if port:
            self.serial = SerialThread(port,9600)
            self.serial.data_received.connect(self.on_serial_line)
            self.serial.status_changed.connect(self.on_serial_status)
            self.serial.start()
        else:
            self.setWindowTitle("Flame Free — No COM Ports Found")

    # ================= SERIAL HANDLERS =================
    def on_serial_line(self,line):
        ts = datetime.datetime.now().strftime("[%H:%M:%S.%f]")[:-3]
        self.serial_history["input"].append(f"{ts} {line}")
        if not self.monitor_paused:
            self.update_serial_monitor()
        parts = line.split(",")
        for i in range(min(len(parts),8)):
            self.update_hardware_param(i,parts[i])
        
        # Update last serial data for recording
        for i in range(min(len(parts), 8)):
            if i < len(parts):
                self.data_recorder.last_serial_data[i] = parts[i]

    def on_serial_status(self,connected,info):
        if connected:
            self.setWindowTitle(f"Flame Free — Connected ({info})")
        else:
            self.setWindowTitle("Flame Free — Serial Disconnected")

    # ================= DATA RECORDING =================
    def record_current_data(self):
        """Record current data values periodically"""
        # Get current input values
        input_values = [inp.text() for inp in self.bottom_inputs]
        
        # Record data
        self.data_recorder.record_data(
            self.data_recorder.last_serial_data,
            input_values
        )

    # ================= MONITOR TAB =================
    def build_monitor_tab(self):
        w = QWidget()
        l = QVBoxLayout(w)

        header = QHBoxLayout()
        title = QLabel("INDUCTION PARAMETERS")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-weight:bold;font-size:16px;")
        header.addStretch()
        header.addWidget(title)
        header.addStretch()

        logo = QLabel()
        pix = QPixmap(resource_path("assets/logo.png"))
        logo.setPixmap(pix.scaled(48,48,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
        logo.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        header.addWidget(logo)
        l.addLayout(header)

        self.top_panel = QWidget()
        top = QGridLayout(self.top_panel)
        names = [
            "Voltage","Current","Frequency - PWM","POT detection",
            "Watts","POT temperature","Coil temperature","OUT8"
        ]
        self.hw_params=[]
        for i,name in enumerate(names):
            r,c = divmod(i,4)
            top.addWidget(QLabel(name),r*2,c)
            e=QLineEdit("0")
            e.setReadOnly(True)
            self.hw_params.append(e)
            top.addWidget(e,r*2+1,c)
        l.addWidget(self.top_panel)

        self.bottom_panel = QWidget()
        bottom=QGridLayout(self.bottom_panel)
        input_names=["Set value","A","E","B","F","C","G","D"]
        self.bottom_inputs=[]
        for i,name in enumerate(input_names):
            r,c=divmod(i,4)
            bottom.addWidget(QLabel(name),r*2,c)
            inp=QLineEdit()
            bottom.addWidget(inp,r*2+1,c)
            self.bottom_inputs.append(inp)
            inp.textChanged.connect(lambda text, idx=i:self.send_input_to_serial(idx,text))
        l.addWidget(self.bottom_panel)

        l.addStretch()
        self.tabs.addTab(w,"MONITOR")

    # ================= SERIAL TAB =================
    def build_serial_log_tab(self):
        w = QWidget()
        l = QVBoxLayout(w)

        title = QLabel("SERIAL LOG")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-weight:bold;font-size:16px;")
        l.addWidget(title)

        row = QHBoxLayout()
        self.monitor_mode = QComboBox()
        self.monitor_mode.addItems(["Both", "Incoming", "Outgoing"])
        self.monitor_mode.currentIndexChanged.connect(self.update_serial_monitor)
        row.addWidget(self.monitor_mode)

        self.btn_pause = QPushButton("Pause")
        self.btn_pause.clicked.connect(self.toggle_pause)
        row.addWidget(self.btn_pause)

        self.btn_stop = QPushButton("Stop Serial")
        self.btn_stop.clicked.connect(self.stop_serial)
        row.addWidget(self.btn_stop)

        self.btn_export = QPushButton("Export CSV")
        self.btn_export.clicked.connect(self.export_csv)
        row.addWidget(self.btn_export)

        self.btn_logs = QPushButton("View Logs")
        self.btn_logs.clicked.connect(self.view_logs)
        row.addWidget(self.btn_logs)

        row.addStretch()
        l.addLayout(row)

        self.serial_monitor = QTextEdit()
        self.serial_monitor.setReadOnly(True)
        l.addWidget(self.serial_monitor)

        self.tabs.addTab(w, "SERIAL LOG")

    # ================= UPDATE SERIAL MONITOR =================
    def update_serial_monitor(self):
        mode=self.monitor_mode.currentText()
        self.serial_monitor.clear()
        if mode=="Both":
            for line in self.serial_history["input"]:
                self.serial_monitor.append(f"IN: {line}")
            for line in self.serial_history["output"]:
                self.serial_monitor.append(f"OUT: {line}")
        elif mode=="Incoming":
            for line in self.serial_history["input"]:
                self.serial_monitor.append(line)
        elif mode=="Outgoing":
            for line in self.serial_history["output"]:
                self.serial_monitor.append(line)

    def send_input_to_serial(self,index,value):
        if hasattr(self,'serial') and self.serial.ser and self.serial.ser.is_open:
            values=[inp.text() for inp in self.bottom_inputs]
            line=",".join(values)
            ts = datetime.datetime.now().strftime("[%H:%M:%S.%f]")[:-3]
            self.serial.send(line)
            self.serial_history["output"].append(f"{ts} {line}")
            if not self.monitor_paused:
                self.update_serial_monitor()
            
            # Update last input data for recording
            self.data_recorder.last_input_data[index] = value

    def toggle_pause(self):
        self.monitor_paused = not self.monitor_paused
        self.btn_pause.setText("Resume" if self.monitor_paused else "Pause")

    def stop_serial(self):
        if hasattr(self,'serial'):
            self.serial.stop()
            self.setWindowTitle("Flame Free — Serial Stopped")
            self.btn_pause.setEnabled(False)
            self.btn_stop.setEnabled(False)

    def export_csv(self):
        """Export data in the table format shown in the screenshot"""
        path, _ = QFileDialog.getSaveFileName(self, "Save CSV", "", "CSV Files (*.csv)")
        if path:
            try:
                with open(path, "w", newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    
                    # Write headers
                    writer.writerow(self.data_recorder.field_names)
                    
                    # Write all recorded data
                    writer.writerows(self.data_recorder.data_history)
                    
                self.serial_monitor.append(f"Data exported successfully to {path}")
                
                # Show a sample of the exported data
                sample_size = min(2, len(self.data_recorder.data_history))
                if sample_size > 0:
                    self.serial_monitor.append("\nSample of exported data:")
                    self.serial_monitor.append(", ".join(self.data_recorder.field_names))
                    for i in range(sample_size):
                        self.serial_monitor.append(", ".join(self.data_recorder.data_history[i]))
                    self.serial_monitor.append(f"\nTotal records exported: {len(self.data_recorder.data_history)}")
                    
            except Exception as e:
                self.serial_monitor.append(f"Error exporting CSV: {str(e)}")

    def view_logs(self):
        if os.path.exists(LOG_FILE):
            if sys.platform.startswith("win"):
                os.startfile(LOG_FILE)
            elif sys.platform.startswith("darwin"):
                subprocess.call(["open", LOG_FILE])
            else:
                subprocess.call(["xdg-open", LOG_FILE])
        else:
            self.serial_monitor.append("No logs found.")

    def build_calibration_tab(self):
        w=QWidget()
        QVBoxLayout(w)
        self.tabs.addTab(w,"CALIBRATION")

    # ================= SETTINGS TAB =================
    def build_settings_tab(self):
        w = QWidget()
        l = QHBoxLayout(w)
        self.sidebar = QWidget()
        self.sidebar.setFixedWidth(160)
        sl = QVBoxLayout(self.sidebar)
        self.stack = QStackedWidget()
        self.sidebar_items = []

        for i, name in enumerate(["Display", "Port", "2", "3", "Contact"]):
            item = SidebarItem(name)
            item.setAlignment(Qt.AlignmentFlag.AlignCenter)
            item.setFixedHeight(32)
            item.clicked.connect(lambda x=i: self.select_page(x))
            self.sidebar_items.append(item)
            sl.addWidget(item)
            self.stack.addWidget(QWidget())

        display_page = self.stack.widget(0)
        dl = QVBoxLayout(display_page)
        row = QHBoxLayout()
        lbl = QLabel("LIGHT / DARK MODE")
        lbl.setStyleSheet("font-weight:bold;")
        self.toggle = ToggleSwitch(True)
        self.toggle.toggled.connect(self.on_theme_toggle)
        row.addWidget(lbl)
        row.addSpacing(20)
        row.addWidget(self.toggle)
        row.addStretch()
        dl.addLayout(row)
        dl.addStretch()

        port_page = self.stack.widget(1)
        pl = QVBoxLayout(port_page)
        port_row = QHBoxLayout()
        port_label = QLabel("Port")
        port_label.setStyleSheet("font-weight:bold;")
        self.port_combo = QComboBox()
        self.refresh_ports()
        port_row.addWidget(port_label)
        port_row.addSpacing(20)
        port_row.addWidget(self.port_combo)
        port_row.addStretch()

        baud_row = QHBoxLayout()
        baud_label = QLabel("Baud Rate")
        baud_label.setStyleSheet("font-weight:bold;")
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(BAUD_RATES)
        self.baud_combo.setCurrentText("9600")
        baud_row.addWidget(baud_label)
        baud_row.addSpacing(20)
        baud_row.addWidget(self.baud_combo)
        baud_row.addStretch()

        self.btn_apply_serial = QPushButton("Apply")
        self.btn_apply_serial.clicked.connect(self.apply_serial_settings)

        pl.addLayout(port_row)
        pl.addLayout(baud_row)
        pl.addSpacing(10)
        pl.addWidget(self.btn_apply_serial)
        pl.addStretch()

        sl.addStretch()
        l.addWidget(self.sidebar)
        l.addWidget(self.stack)
        self.tabs.addTab(w, "SETTINGS")
        self.select_page(0)

    def select_page(self, index):
        self.stack.setCurrentIndex(index)
        if index == 1:
            self.refresh_ports()
        for i, item in enumerate(self.sidebar_items):
            item.setStyleSheet(
                f"background:{self.current_theme['sidebar_active']};font-weight:bold;"
                if i == index else ""
            )

    def on_theme_toggle(self,checked):
        self.apply_theme(DARK_THEME if checked else LIGHT_THEME)

    def apply_theme(self,theme):
        self.current_theme=theme
        self.toggle.set_theme(theme)
        self.setStyleSheet(f"""
            QWidget{{background:{theme['bg']};color:{theme['text']};}}
            QLineEdit{{background:{theme['input_bg']};border:1px solid {theme['border']};}}
            QTabBar::tab{{background:{theme['sidebar']};color:{theme['tab_text']};padding:8px 18px;}}
            QTabBar::tab:selected{{background:{theme['sidebar_active']};}}
        """)
        self.sidebar.setStyleSheet(f"background:{theme['sidebar']};")
        self.top_panel.setStyleSheet(f"background:{theme['panel']};")
        self.bottom_panel.setStyleSheet(f"background:{theme['panel2']};")
        self.select_page(self.stack.currentIndex())

    def update_hardware_param(self,index,value):
        if 0<=index<8:
            field=self.hw_params[index]
            field.setText(str(value))
            if str(value).lower()=="e":
                field.setStyleSheet(f"background:{ERROR_BG};color:{ERROR_TEXT};")
            else:
                field.setStyleSheet("")

    def refresh_ports(self):
        self.port_combo.clear()
        ports = list_com_ports()
        if ports:
            self.port_combo.addItems(ports)
        else:
            self.port_combo.addItem("No ports found")

    def apply_serial_settings(self):
        port = self.port_combo.currentText()
        baud = int(self.baud_combo.currentText())
        if "No ports" in port:
            return
        if hasattr(self, "serial"):
            self.serial.stop()
            self.serial.wait()
        self.serial = SerialThread(port, baud)
        self.serial.data_received.connect(self.on_serial_line)
        self.serial.status_changed.connect(self.on_serial_status)
        self.serial.start()

# ================= APP =================

app=QApplication(sys.argv)
pixmap = QPixmap(resource_path("assets/logo.png"))
splash=QSplashScreen(pixmap,Qt.WindowType.FramelessWindowHint)
splash.show()
app.processEvents()

window=Window()

def show_main():
    window.show()
    splash.finish(window)

QTimer.singleShot(3000,show_main)
sys.exit(app.exec())