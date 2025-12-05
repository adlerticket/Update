#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
DeinAdlerTicket - Stehblöcke-Only (Kalibrierung + API-Sniffer + Auto-Klick)
Version: v1.1_DDDDOCR_ONLY (Queue-it Solver ohne Tesseract/OpenCV)

Änderungen in dieser Version:
- DDDD-OCR Only: mehrere Bildvarianten mit Pillow (optional) zur robusteren Captcha-Erkennung.
- Automatische Eingabe des Codes und Klick auf Bestätigung.
"""

import sys, os, json as pyjson, re, time, hashlib, urllib.request
import json
import subprocess
import socket
from urllib.parse import urlparse
from datetime import datetime
from threading import Thread, Lock
from collections import deque
import base64

# --- ddddocr (optional, für robustere Captcha-OCR) ---
try:
    import ddddocr
    DDDDOCR_DEPRECATED = True
    try:
        DDD_OCR = ddddocr.DdddOcr(show_ad=False)
    except TypeError:
        # Fallback für ältere ddddocr-Versionen ohne show_ad-Parameter
        DDD_OCR = ddddocr.DdddOcr()
except ImportError:
    DDDDOCR_DEPRECATED = False
    DDD_OCR = None
    print("Hinweis: ddddocr nicht installiert – erweitertes Captcha-OCR nicht aktiv.")
# --------------------------------------------------------


from PyQt6.QtCore import QUrl, QTimer, pyqtSignal, QObject, Qt
from PyQt6.QtGui import QPixmap, QIcon, QDesktopServices, QGuiApplication
from PyQt6.QtWidgets import (
QSizePolicy,
QLabel,
QApplication, QWidget, QCheckBox, QPushButton,
QTextEdit, QVBoxLayout, QGridLayout, QMainWindow, QHBoxLayout, QLineEdit,
QMessageBox
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEngineSettings, QWebEnginePage
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

# --- Helper: Pfad zu Ressourcen (PyInstaller-kompatibel) ---
def app_path(rel_path: str) -> str:
    try:
        base = getattr(sys, "_MEIPASS", None)
        if base:
            return os.path.join(base, rel_path)
    except Exception:
        pass
    try:
        base = os.path.dirname(os.path.abspath(__file__))
    except Exception:
        base = os.getcwd()
    return os.path.join(base, rel_path)

APP_NAME = "Dein Adler Ticket - v1.1 OCR"
APP_VERSION = "1.1.0"

# URL zu einer JSON-Datei auf GitHub, die die neueste Version beschreibt.
# Beispiel-Inhalt der JSON-Datei:
# {
#   "version": "1.2.0",
#   "url": "https://github.com/DEINUSER/DEINREPO/releases/latest",
#   "changelog": "Kurzbeschreibung der wichtigsten Änderungen"
# }
UPDATE_INFO_URL = "https://raw.githubusercontent.com/DEINUSER/DEINREPO/main/update.json"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(os.getenv("LOCALAPPDATA") or os.path.join(SCRIPT_DIR, "config"), "DeinAdlerTicket")
SETTINGS_PATH = os.path.join(CONFIG_DIR, 'settings.json')

# --- Persistentes Web-Profil ---
def create_persistent_web_profile(parent=None) -> QWebEngineProfile:
    profile = QWebEngineProfile("dat_profile", parent)
    try:
        profile.setPersistentStoragePath(os.path.join(CONFIG_DIR, "web_profile"))
    except Exception:
        pass
    try:
        profile.setCachePath(os.path.join(CONFIG_DIR, "web_cache"))
    except Exception:
        pass
    try:
        profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
        )
    except Exception:
        pass
    try:
        profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)
    except Exception:
        pass
    return profile

# --- App Icon helper ---
def _load_app_icon() -> 'QIcon':
    try:
        cand = [
            app_path("eintracht_logo.ico"),
            os.path.join(SCRIPT_DIR, "eintracht_logo.ico"),
            os.path.join(CONFIG_DIR, "eintracht_logo.ico")
        ]
        for p in cand:
            if os.path.exists(p):
                return QIcon(p)
        if os.path.exists("eintracht_logo.ico"):
            return QIcon("eintracht_logo.ico")
    except Exception:
        pass
    return QIcon()

THEME_CSS = """
* { font-family: 'Segoe UI', system-ui, -apple-system, Roboto, Arial; }
QWidget { background: #0f1115; color: #e6e6e6; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 18px; height: 18px; }
QLineEdit {
  background: #171a21; border: 1px solid #2c3340; border-radius: 10px;
  padding: 8px 10px; selection-background-color: #2b5cff;
}
QPushButton {
  background: #1b64ff; color: white; border: none; border-radius: 12px;
  padding: 10px 16px; font-weight: 600;
}
QPushButton:hover { background: #2a73ff; }
QPushButton:pressed { background: #1551cc; }
QPushButton:disabled { background: #2a2f3a; color: #9aa3af; }
QTextEdit {
  background: #0b0d10; border: 1px solid #252a33; border-radius: 12px; padding: 10px;
}
"""

# --- E-Mail Versand ---
def sende_email(empfaenger: str, betreff: str, inhalt: str) -> bool:
    try:
        import smtplib
        from email.mime.text import MIMEText
        absender = "deinadlerticket@gmail.com"
        app_passwort = "rjatzcjymbrynktg"
        msg = MIMEText(inhalt)
        msg["Subject"] = betreff
        msg["From"] = absender
        msg["To"] = empfaenger
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(absender, app_passwort)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print("Fehler beim E-Mail-Versand:", e)
        return False

START_URL = "https://stores.eintracht.de/tickets/profis/bundesliga/"
DEBUG_PORT = int(os.environ.get("DAT_CDP_PORT", 9229))

API_HOST = "ticketing-api.eintrachttech.de"
API_PATH_REGEX = re.compile(
    r"(?:^/index\.php)?/api/v1/frontend/purchasing/event/[^/]+/availablePlaces/?(?:$|[?#])",
    re.IGNORECASE
)
VENUEPLAN_PATH_REGEX = re.compile(
    r"(?:^/index\.php)?/api/v1/frontend/purchasing/venuePlan/[^/]+",
    re.IGNORECASE
)
PLACE_SELECTION_MATCH = ("ticketing.eintrachttech.de", "/placeSelection/")

STEHBLOECKE = [str(b) for b in [35,36,37,38,39,40,41,42,43,45,47,49,51]]
COORDS_FILE = os.path.join(CONFIG_DIR, "stehblock_coords.json")
MAX_CHILD_BROWSERS = 3

# --- Update-Checker (GitHub) -------------------------------------------------
def _parse_version_tuple(v: str):
    """Wandelt eine Versions-String wie '1.2.3' in ein Tupel (1,2,3) um."""
    try:
        parts = [int(p) for p in re.findall(r"\d+", str(v))]
        return tuple(parts) if parts else (0,)
    except Exception:
        return (0,)

def is_remote_newer(remote: str, local: str) -> bool:
    """Vergleicht zwei Versions-Strings und gibt True zurück, wenn remote > local ist."""
    return _parse_version_tuple(remote) > _parse_version_tuple(local)

def check_for_updates(logger, parent_window=None):
    """
    Prüft optional auf GitHub, ob eine neuere Version verfügbar ist.
    Logger: Funktion, die einen Log-String entgegennimmt (z.B. self.log).
    parent_window: Optionales QWidget für MessageBox.
    """
    if not UPDATE_INFO_URL:
        # Kein Update-Endpoint konfiguriert – stillschweigend abbrechen
        return
    try:
        with urllib.request.urlopen(UPDATE_INFO_URL, timeout=4) as resp:
            raw = resp.read().decode("utf-8", "replace")
        info = json.loads(raw)
    except Exception:
        # Keine Internetverbindung oder URL nicht erreichbar – leise ignorieren
        logger("ℹ️ Konnte nicht nach Updates suchen (vermutlich offline oder GitHub nicht erreichbar).")
        return

    try:
        remote_ver = str(info.get("version", "")).strip()
    except Exception:
        remote_ver = ""

    if not remote_ver:
        return

    if not is_remote_newer(remote_ver, APP_VERSION):
        logger(f"ℹ️ Du verwendest die aktuelle Version ({APP_VERSION}).")
        return

    download_url = info.get("url") or info.get("download") or ""
    changelog = info.get("changelog") or info.get("message") or ""

    logger(f"🔔 Neue Version verfügbar: {remote_ver} (aktuell: {APP_VERSION}).")

    if parent_window is not None:
        try:
            msg = QMessageBox(parent_window)
            msg.setWindowTitle("Dein Adler Ticket – Update verfügbar")
            text = f"Es ist eine neue Version verfügbar: {remote_ver}\nDeine Version: {APP_VERSION}"
            if changelog:
                text += f"\n\nÄnderungen:\n{changelog}"
            msg.setText(text)
            if download_url:
                msg.setInformativeText("Möchtest du die Download-Seite im Browser öffnen?")
                msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                msg.setDefaultButton(QMessageBox.StandardButton.Yes)
            else:
                msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            res = msg.exec()
            if download_url:
                yes = getattr(QMessageBox.StandardButton, "Yes", None)
                if res == yes:
                    try:
                        QDesktopServices.openUrl(QUrl(download_url))
                    except Exception:
                        pass
        except Exception:
            # Falls Qt-Dialog scheitert, bleibt zumindest der Logeintrag
            pass


def find_free_debug_port(start: int = 9229, end: int = 9500) -> int:
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            try:
                s.connect(("127.0.0.1", port))
            except (ConnectionRefusedError, OSError):
                return port
    return start

LOG_MAX_LEN = 50000
CAPTCHA_SCAN_INTERVAL_MS = 1000
CLICK_INTERVAL_MS = 1000
AVAIL_TTL_SEC = 2.0
WATCHDOG_INTERVAL_MS = 15000
WATCHDOG_MAX_FAILS = 8
FLOOD_WINDOW_SEC = 5
FLOOD_THRESHOLD = 80
AUTO_PAUSE_DURATION_SEC = 10

CAPTCHA_URL_HINTS = (
    "friendlycaptcha","frcapi","eu.frcapi",
    "recaptcha","hcaptcha","turnstile",
    "cf-challenge","cdn-cgi/challenge","cdn-cgi/challenge-platform",
    "__cf_chl_tk","__cf_chl_rt","captcha="
)

def ensure_dirs():
    os.makedirs(CONFIG_DIR, exist_ok=True)

def load_block_coords() -> dict:
    ensure_dirs()
    if os.path.exists(COORDS_FILE):
        try:
            with open(COORDS_FILE, "r", encoding="utf-8") as f:
                data = pyjson.load(f)
            if isinstance(data, dict):
                return {str(k): (float(v[0]), float(v[1])) for k, v in data.items()
                        if isinstance(v, (list, tuple)) and len(v) == 2}
        except Exception:
            pass
    return {}

def save_block_coords(mapping: dict):
    ensure_dirs()
    try:
        serial = {str(k): [float(v[0]), float(v[1])] for k, v in mapping.items()}
        with open(COORDS_FILE, "w", encoding="utf-8") as f:
            pyjson.dump(serial, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

# --- CAPTCHA SOLVER LOGIC (OPTIMIERT FÜR HOHLE SCHRIFT & NOISE) ---
class CaptchaSolver:
    """ddddocr-Multi-Pipeline Captcha-Solver (Variante B, DDDD-OCR ONLY).

    Diese Version nutzt ausschließlich ddddocr zur Erkennung der Captcha-Codes
    und versucht mehrere Bildvarianten (ohne OpenCV), um schwierige Captchas
    robuster zu erkennen.
    """

    @staticmethod
    def _decode_base64_bytes(base64_img: str):
        """Dekodiert ein Base64-/Data-URL-Image in rohe Byte-Daten (PNG/JPEG usw.)."""
        try:
            if not base64_img:
                return None
            if "," in base64_img:
                base64_img = base64_img.split(",", 1)[1]
            import base64 as _b64
            return _b64.b64decode(base64_img)
        except Exception:
            return None

    @staticmethod
    def _score_candidate(text: str) -> int:
        """Scoring für Plausibilität (Länge 4–8, optimal 6–7)."""
        if not text:
            return -1
        length = len(text)
        if 6 <= length <= 7:
            # starker Bonus für typische Captcha-Längen
            return 100 + length
        if 4 <= length <= 8:
            return length
        return 0

    @staticmethod
    def _make_variants(img_bytes: bytes):
        """Erzeugt mehrere Bildvarianten nur mit Pillow (falls vorhanden),
        damit ddddocr bei schwierigen Captchas bessere Chancen hat.

        Varianten:
        - raw: Originalbytes
        - zoom2x: 2x vergrößert, Graustufen
        - contrast: hoher Kontrast
        - invert: invertierte Version
        - binary: harte Schwarz/Weiß-Schwelle

        Wenn Pillow nicht installiert ist, wird lediglich ('raw', img_bytes) zurückgegeben.
        """
        variants = [("raw", img_bytes)]

        try:
            from io import BytesIO
            from PIL import Image, ImageOps, ImageEnhance  # type: ignore
        except Exception:
            # Pillow nicht installiert -> nur raw
            return variants

        try:
            base_img = Image.open(BytesIO(img_bytes))
        except Exception:
            return variants

        try:
            gray = base_img.convert("L")
        except Exception:
            gray = base_img

        # 2x Zoom
        try:
            scale = 2
            if gray.width > 0 and gray.height > 0:
                big = gray.resize(
                    (gray.width * scale, gray.height * scale),
                    getattr(Image, "LANCZOS", Image.BICUBIC),
                )
            else:
                big = gray
        except Exception:
            big = gray

        def _add_variant(name: str, pil_img):
            try:
                buf = BytesIO()
                pil_img.save(buf, format="PNG")
                variants.append((name, buf.getvalue()))
            except Exception:
                pass

        _add_variant("zoom2x", big)

        # Kontrast erhöhen
        try:
            enh = ImageEnhance.Contrast(big)
            highc = enh.enhance(1.8)
            _add_variant("contrast", highc)
        except Exception:
            pass

        # Invertierte Version
        try:
            inv = ImageOps.invert(big)
            _add_variant("invert", inv)
        except Exception:
            pass

        # Harte Schwelle
        try:
            thr = big.point(lambda p: 255 if p > 180 else 0)
            _add_variant("binary", thr)
        except Exception:
            pass

        # Duplikate entfernen (z. B. identische Bytes)
        seen = set()
        unique = []
        for name, b in variants:
            try:
                h = hash(b)
            except Exception:
                h = None
            key = (name, h)
            if key in seen:
                continue
            seen.add(key)
            unique.append((name, b))
        return unique

    @staticmethod
    def _clean_text(raw_text: str) -> str:
        """Reinigt die von ddddocr gelesene Zeichenkette:
        - Großbuchstaben
        - nur A–Z und 0–9
        - Whitespace abschneiden
        """
        import re as _re
        return _re.sub(r"[^A-Z0-9]", "", str(raw_text).upper()).strip()

    @staticmethod
    def solve(base64_img: str) -> str:
        """Führt mehrere ddddocr-Läufe auf verschiedenen Bildvarianten aus
        und wählt per Voting + Scoring den wahrscheinlichsten Code."""

        # Ohne ddddocr kein OCR
        if not globals().get("DDDDOCR_DEPRECATED") or globals().get("DDD_OCR") is None:
            return ""

        img_bytes = CaptchaSolver._decode_base64_bytes(base64_img)
        if not img_bytes:
            return ""

        variants = CaptchaSolver._make_variants(img_bytes)
        results = []  # (variant_name, clean_text, score)

        for vname, vb in variants:
            try:
                raw = globals()["DDD_OCR"].classification(vb) or ""
            except Exception as e:
                print(f"ddddocr Error ({vname}): {e}")
                continue
            clean = CaptchaSolver._clean_text(raw)
            score = CaptchaSolver._score_candidate(clean)
            if score > 0 and clean:
                results.append((vname, clean, score))

        if not results:
            return ""

        # Voting: zähle gleiche Texte
        from collections import Counter
        texts = [r[1] for r in results]
        counts = Counter(texts)
        max_votes = max(counts.values())
        top_texts = [txt for txt, cnt in counts.items() if cnt == max_votes]

        if len(top_texts) == 1:
            winner = top_texts[0]
        else:
            # Bei Gleichstand: besten Score nehmen
            best_score = -1
            winner = ""
            for txt in top_texts:
                sc = max((r[2] for r in results if r[1] == txt), default=-1)
                if sc > best_score:
                    best_score = sc
                    winner = txt

        try:
            dbg = ", ".join([f"{v}:{t}({s})" for (v, t, s) in results])
            print(f"🧩 ddddocr variants -> {dbg} | winner={winner!r}, votes={max_votes}")
        except Exception:
            pass

        return winner or ""


# ------------------------- Signale


class SnifferSignals(QObject):
    log = pyqtSignal(str)
    standing_hits = pyqtSignal(list)
    autopause = pyqtSignal(bool)
    cdpResult = pyqtSignal(dict)
    captchaNet = pyqtSignal(bool)

# ------------------------- GUI -------------------------
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        import os
        try: SCRIPT_DIR
        except NameError: SCRIPT_DIR = os.path.dirname(__file__) if '__file__' in globals() else os.getcwd()
        self._alarm_path = app_path('Alarm.mp3')
        try:
            self._audio_out = QAudioOutput()
            try: self._audio_out.setVolume(1.0)
            except Exception: pass
            self._player = QMediaPlayer()
            self._player.setAudioOutput(self._audio_out)
        except Exception as _e:
            pass
        self.setWindowTitle(APP_NAME)
        try: self.setWindowIcon(_load_app_icon())
        except Exception: pass
        self._ui_scale = 1.0
        try:
            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                geo = screen.availableGeometry()
                base_w, base_h = 1100, 980
                scale_h = geo.height() / base_h if base_h > 0 else 1.0
                scale_w = geo.width() / base_w if base_w > 0 else 1.0
                self._ui_scale = min(1.0, scale_w, scale_h)
                w = min(int(base_w * self._ui_scale), int(geo.width() * 0.95))
                h = min(int(base_h * self._ui_scale), int(geo.height() * 0.95))
                if w < 800: w = 800
                if h < 600: h = 600
                self.resize(w, h)
                self.setMinimumSize(w, h)
            else:
                self.setMinimumSize(1100, 980)
        except Exception:
            self.setMinimumSize(1100, 980)

        self.setStyleSheet(THEME_CSS)

        self.chk_all = QCheckBox("Alle Stehblöcke durchsuchen")
        self.chk_email = QCheckBox("E-Mail-Benachrichtigung aktivieren")
        self.chk_sound = QCheckBox("Sound Alarm aktivieren")

        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("E-Mail-Adresse für Benachrichtigungen")
        self.email_input.setFixedWidth(360)
        self.email_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.email_input.setEnabled(False)

        def _toggle_email_ui(_state):
            self.email_input.setEnabled(self.chk_email.isChecked())
        self.chk_email.toggled.connect(_toggle_email_ui)

        self.chk_autoreload = QCheckBox("Automatischen Reload aktivieren")
        self.reload_input = QLineEdit()
        self.reload_input.setPlaceholderText("Reload alle X Sekunden (z.B. 125)")
        self.reload_input.setFixedWidth(220)
        self.reload_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.reload_input.setEnabled(False)

        def _toggle_reload_ui(_state):
            self.reload_input.setEnabled(self.chk_autoreload.isChecked())
        self.chk_autoreload.toggled.connect(_toggle_reload_ui)

        self.block_checkboxes = {}
        block_layout = QGridLayout()
        for i, block in enumerate(STEHBLOECKE):
            cb = QCheckBox(f"Block {block}")
            cb.setEnabled(True)
            self.block_checkboxes[block] = cb
            block_layout.addWidget(cb, i // 4, i % 4)

        def on_all_toggle(_state):
            checked = self.chk_all.isChecked()
            for cb in self.block_checkboxes.values():
                cb.setChecked(checked)
        self.chk_all.toggled.connect(on_all_toggle)

        self.start_button = QPushButton("Login und Suche starten")
        self.start_button.clicked.connect(self.start_browser)
        self.reset_button = QPushButton("🧰 Kalibrierung zurücksetzen (alle)")
        self.reset_button.clicked.connect(self.reset_calibration)

        self.lbl_sniffer = QLabel("Sniffer: 0 aktiv")
        self.lbl_captcha = QLabel("Captcha: -")
        self.lbl_autopause = QLabel("Auto-Pause: frei")

        self.log_output = QTextEdit()
        self.log_output.setStyleSheet('font-size: 13px;')
        self.log_output.setReadOnly(True)

        layout = QVBoxLayout()
        try: s = float(getattr(self, "_ui_scale", 1.0))
        except Exception: s = 1.0
        layout.setSpacing(int(10 * s))

        logo = QLabel()
        _logo_px = QPixmap(app_path("DeinAdlerTicketLogo.png"))
        if not _logo_px.isNull():
            size = int(320 * s)
            try:
                max_logo = int(self.height() * 0.22)
                if max_logo <= 0: max_logo = 140
            except Exception: max_logo = 220
            size = min(size, max_logo)
            if size < 140: size = 140
            _logo_px = _logo_px.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            logo.setPixmap(_logo_px)
        logo.setScaledContents(False)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top_pad = int(16 * s) if int(16*s) >=8 else 8
        layout.addSpacing(top_pad)
        layout.addWidget(logo, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(int(8 * s))

        layout.addWidget(self.email_input, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.chk_email, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.chk_sound, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.chk_autoreload, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.reload_input, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(8)
        layout.addWidget(self.chk_all, 0, Qt.AlignmentFlag.AlignHCenter)
        block_container = QWidget()
        block_container.setLayout(block_layout)
        layout.addWidget(block_container, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(8)
        layout.addWidget(self.start_button, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.reset_button, 0, Qt.AlignmentFlag.AlignHCenter)

        # Captcha-Statistik
        self._captcha_stats = {
            "seen": 0,
            "auto_attempts": 0,
            "auto_success": 0,
            "auto_captchas": 0,
            "attempts_sum": 0,
            "current_attempts": 0,
            "current_had_auto": False
        }
        self.lbl_captcha_stats = QLabel("Captcha-Stats: -")

        status_row = QHBoxLayout()
        status_row.addWidget(self.lbl_captcha_stats)
        status_row.addSpacing(20)
        status_row.addStretch(1)
        status_row.addWidget(self.lbl_sniffer)
        status_row.addSpacing(20)
        status_row.addWidget(self.lbl_captcha)
        status_row.addSpacing(20)
        status_row.addWidget(self.lbl_autopause)
        status_row.addStretch(1)
        layout.addLayout(status_row)

        min_log = int(240 * s)
        if min_log < 160: min_log = 160
        self.log_output.setMinimumHeight(min_log)
        layout.addWidget(self.log_output)
        self.setLayout(layout)

        QTimer.singleShot(0, self.load_settings)
        self.chk_email.toggled.connect(lambda _s: self.save_settings())
        self.chk_sound.toggled.connect(lambda _s: self.save_settings())
        self.chk_all.toggled.connect(lambda _s: self.save_settings())
        self.email_input.textChanged.connect(lambda _t: self.save_settings())
        self.chk_autoreload.toggled.connect(lambda _s: self.save_settings())
        self.reload_input.textChanged.connect(lambda _t: self.save_settings())
        for _b, _cb in self.block_checkboxes.items():
            _cb.toggled.connect(lambda _s, __b=_b: self.save_settings())

        ensure_dirs()
        self._log_trim = QTimer(self); self._log_trim.setInterval(5000)
        self._log_trim.timeout.connect(self._trim_log); self._log_trim.start()
        self._reload_timer = QTimer(self); self._reload_timer.setInterval(1000)
        self._reload_timer.timeout.connect(self._check_reload_timer); self._reload_timer.start()
        self._last_reload = time.time()
        self._btn_block = {"reset": False}
        self.child_procs = []
        self.sessions_label = QLabel(f"Aktive Spiele: 0 / {MAX_CHILD_BROWSERS}")
        self.sessions_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.sessions_label, 0, Qt.AlignmentFlag.AlignHCenter)
        self._proc_timer = QTimer(self); self._proc_timer.setInterval(3000)
        self._proc_timer.timeout.connect(self._cleanup_child_procs); self._proc_timer.start()

        if "--child" not in sys.argv[1:]:
            try:
                self._log_relay = LogRelay()
                self._log_relay.log_received.connect(self.log)
                self.log_server_port = find_free_debug_port(50050, 50100)
                self._log_server = LogServer(self._log_relay, self.log_server_port)
                self._log_server.start()
                self.log("🦅 Guuude! Willkommen zu Dein Adler Ticket! | Wähle deine Stehblöcke, (optional) E-Mail eintragen, klicke dann auf 'Login & Suche starten'.")
                if not DDDDOCR_DEPRECATED:
                    self.log("⚠️ Hinweis: ddddocr nicht installiert – Auto-Captcha nicht verfügbar.")

                # Kleiner verzögerter Update-Check (GitHub), damit die GUI zuerst erscheint
                QTimer.singleShot(2000, self._check_updates)
            except Exception as e:
                self.log(f"⚠️ Log-Server Fehler: {e}")
                self.log_server_port = None
        else:
            self.log_server_port = None

    def _trim_log(self):
        txt = self.log_output.toPlainText()
        if len(txt) > LOG_MAX_LEN:
            self.log_output.clear(); self.log_output.append(txt[-LOG_MAX_LEN:])

    def _check_reload_timer(self):
        if not hasattr(self, "chk_autoreload") or not self.chk_autoreload.isChecked(): return
        try: txt = (self.reload_input.text() if hasattr(self, "reload_input") else "").strip()
        except Exception: txt = ""
        if not txt: return
        try: sec = int(txt)
        except Exception: return
        if sec < 10: sec = 10
        now = time.time()
        if now - getattr(self, "_last_reload", 0.0) < sec: return
        self._last_reload = now
        any_reloaded = False
        for w in QApplication.topLevelWidgets():
            try:
                if hasattr(w, "browser") and getattr(w, "browser") is not None:
                    w.browser.reload(); any_reloaded = True
            except Exception: continue
        if any_reloaded: self.log("🔁 Automatischer Reload.")

    def log(self, msg: str):
        """Schreibt Log-Ausgabe und aktualisiert Captcha-Statistik (falls möglich)."""
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        try:
            self.log_output.append(line)
        except Exception:
            try:
                print(line)
            except Exception:
                pass

        # Captcha-Statistik aus Log ableiten (nur im Haupt-GUI sinnvoll)
        try:
            if hasattr(self, "_captcha_stats"):
                self._update_captcha_stats_from_log(msg)
        except Exception:
            pass


    def _check_updates(self):
        """Startet einen kleinen Update-Check (GitHub), ohne die GUI zu blockieren."""
        try:
            check_for_updates(self.log, self)
        except Exception as e:
            # Nur als Info ins Log, Programm soll weiterlaufen
            self.log(f"ℹ️ Update-Check nicht möglich: {e}")
    def _refresh_captcha_stats_label(self):
        """Aktualisiert die Anzeige der Captcha-Statistik unten links."""
        if not hasattr(self, "lbl_captcha_stats") or not hasattr(self, "_captcha_stats"):
            return
        s = self._captcha_stats
        if s["auto_captchas"] <= 0:
            text = "Captcha-Stats: -"
        else:
            avg_attempts = s["attempts_sum"] / max(1, s["auto_captchas"])
            success_rate = (s["auto_success"] / max(1, s["auto_captchas"])) * 100.0
            text = (
                f"Captcha-Stats: {s['auto_success']}/{s['auto_captchas']} auto gelöst | "
                f"⌀ Versuche: {avg_attempts:.1f} | Erfolgsrate: {success_rate:.0f}%"
            )
        self.lbl_captcha_stats.setText(text)

    def _update_captcha_stats_from_log(self, msg: str):
        """Wertet bestimmte Logzeilen aus, um Captcha-Versuche zu zählen."""
        s = self._captcha_stats

        # Neues Captcha erkannt
        if "Captcha erkannt - Suche pausiert" in msg:
            s["seen"] += 1
            s["current_attempts"] = 0
            s["current_had_auto"] = False
            self._refresh_captcha_stats_label()
            return

        # Auto-Captcha-Versuch
        if "Versuche Captcha automatisch zu lösen" in msg:
            s["current_attempts"] += 1
            s["auto_attempts"] += 1
            s["current_had_auto"] = True
            self._refresh_captcha_stats_label()
            return

        # Maximale Auto-Versuche erreicht -> als gescheitertes Auto-Captcha zählen
        if "Maximale Auto-Captcha-Versuche erreicht" in msg:
            if s["current_had_auto"] and s["current_attempts"] > 0:
                s["auto_captchas"] += 1
                s["attempts_sum"] += s["current_attempts"]
            s["current_attempts"] = 0
            s["current_had_auto"] = False
            self._refresh_captcha_stats_label()
            return

        # Captcha gelöst – Suche läuft weiter
        if "Captcha gelöst" in msg and "Suche läuft weiter" in msg:
            if s["current_had_auto"] and s["current_attempts"] > 0:
                s["auto_captchas"] += 1
                s["attempts_sum"] += s["current_attempts"]
                s["auto_success"] += 1
            s["current_attempts"] = 0
            s["current_had_auto"] = False
            self._refresh_captcha_stats_label()
            return

    def notify_email(self, subject: str, body: str):
        try:
            if not self.chk_email.isChecked(): return
            addr = (self.email_input.text() or "").strip()
            if not addr: return
            if not sende_email(addr, subject, body): self.log("⚠️ E-Mail-Versand fehlgeschlagen.")
        except Exception as e:
            self.log(f"⚠️ E-Mail-Fehler: {e}")

    def play_alarm(self):
        try:
            if hasattr(self, 'chk_sound') and not self.chk_sound.isChecked(): return
            path = app_path('Alarm.mp3')
            if not os.path.exists(path): return
            try: self._player.stop()
            except Exception: pass
            self._player.setSource(QUrl.fromLocalFile(path))
            try: self._player.setPosition(0)
            except Exception: pass
            self._player.play()
        except Exception as e: pass

    def load_settings(self):
        try:
            if os.path.exists(SETTINGS_PATH):
                with open(SETTINGS_PATH, "r", encoding="utf-8") as f: data = json.load(f)
                self.chk_email.setChecked(bool(data.get("chk_email", False)))
                self.chk_sound.setChecked(bool(data.get("chk_sound", True)))
                self.chk_all.setChecked(bool(data.get("chk_all", True)))
                self.chk_autoreload.setChecked(bool(data.get("chk_autoreload", False)))
                if hasattr(self, "reload_input"): self.reload_input.setText(str(data.get("reload_seconds", "")))
                if hasattr(self, "email_input"): self.email_input.setText(data.get("email_address", ""))
                selected = set(data.get("selected_blocks", []))
                for b, cb in self.block_checkboxes.items(): cb.setChecked(b in selected)
        except Exception as e: self.log(f"⚠️ Settings load error: {e}")

    def save_settings(self):
        try:
            data = {
                "chk_email": self.chk_email.isChecked(),
                "chk_sound": self.chk_sound.isChecked(),
                "chk_all": self.chk_all.isChecked(),
                "email_address": (self.email_input.text() if hasattr(self, "email_input") else ""),
                "selected_blocks": [b for b, cb in self.block_checkboxes.items() if cb.isChecked()],
                "chk_autoreload": self.chk_autoreload.isChecked(),
                "reload_seconds": (self.reload_input.text() if hasattr(self, "reload_input") else ""),
            }
            os.makedirs(CONFIG_DIR, exist_ok=True)
            with open(SETTINGS_PATH, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception: pass

    def closeEvent(self, event):
        try: self.save_settings()
        except Exception: pass
        super().closeEvent(event)

    def reset_calibration(self):
        if self._btn_block["reset"]: return
        self._btn_block["reset"] = True
        self.reset_button.setDisabled(True)
        try:
            if os.path.exists(COORDS_FILE): os.remove(COORDS_FILE); self.log("✅ Kalibrierung gelöscht.")
            else: self.log("ℹ️ Keine Kalibrierung gefunden.")
        except Exception as e: self.log(f"⚠️ Reset error: {e}")
        finally: QTimer.singleShot(400, lambda: (self._btn_release("reset"), self.reset_button.setDisabled(False)))

    def _btn_release(self, which): self._btn_block[which] = False

    def start_browser(self):
        self._cleanup_child_procs()
        if len(self.child_procs) >= MAX_CHILD_BROWSERS:
            self.log(f"⚠️ Max. Spiele ({MAX_CHILD_BROWSERS}) erreicht.")
            return
        try: self.save_settings()
        except Exception: pass
        script_path = os.path.abspath(sys.argv[0])
        env = os.environ.copy()
        port = str(find_free_debug_port(9229, 9500))
        env["DAT_CDP_PORT"] = port
        env["QTWEBENGINE_REMOTE_DEBUGGING"] = port
        if getattr(self, "log_server_port", None):
            env["DAT_LOG_PORT"] = str(self.log_server_port)
        try:
            proc = subprocess.Popen([sys.executable, script_path, "--child"], env=env)
        except Exception as e:
            self.log(f"⚠️ Start error: {e}"); return
        self.child_procs.append(proc)
        self._update_sessions_label()
        self.log("✅ Browserfenster gestartet.")

    def _cleanup_child_procs(self):
        alive = []
        for proc in self.child_procs:
            try:
                if proc.poll() is None: alive.append(proc)
                else: self.log(f"ℹ️ Browser beendet (PID {proc.pid}).")
            except Exception: continue
        self.child_procs = alive
        self._update_sessions_label()

    def _update_sessions_label(self):
        try:
            active = len(self.child_procs)
            self.sessions_label.setText(f"Aktive Spiele: {active} / {MAX_CHILD_BROWSERS}")
            self.lbl_sniffer.setText(f"Sniffer: {active} aktiv" if active > 0 else "Sniffer: 0 aktiv")
        except Exception: pass

class LogRelay(QObject):
    log_received = pyqtSignal(str)

class LogServer(Thread):
    def __init__(self, relay: LogRelay, port: int):
        super().__init__(daemon=True)
        self.relay = relay
        self.port = int(port)
        self._sock = None; self._stop = False
    def run(self):
        try:
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("127.0.0.1", self.port)); srv.listen(5); self._sock = srv
        except Exception: return
        while not self._stop:
            try: conn, _ = srv.accept()
            except OSError: break
            Thread(target=self._handle_client, args=(conn,), daemon=True).start()
    def _handle_client(self, conn):
        with conn:
            buf = b""
            while not self._stop:
                try: data = conn.recv(4096)
                except Exception: break
                if not data: break
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    try: msg = line.decode("utf-8", "ignore").rstrip("\r")
                    except Exception: continue
                    if msg: 
                        try: self.relay.log_received.emit(msg)
                        except Exception: pass
    def stop(self):
        self._stop = True
        try:
            if self._sock: self._sock.close()
        except Exception: pass

class RemoteLogger:
    def __init__(self, host: str, port: int):
        self.host = host; self.port = int(port); self._sock = None; self._lock = Lock()
    def _ensure_conn(self):
        if self._sock is not None: return
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2.0); s.connect((self.host, self.port)); s.settimeout(None); self._sock = s
        except Exception: self._sock = None
    def __call__(self, msg: str):
        data = (str(msg).replace("\r", "") + "\n").encode("utf-8", "ignore")
        with self._lock:
            if self._sock is None: self._ensure_conn()
            if self._sock is None: return
            try: self._sock.sendall(data)
            except Exception:
                try: self._sock.close()
                except Exception: pass
                self._sock = None

class DevToolsSniffer(Thread):
    def __init__(self, port: int, signals: SnifferSignals):
        super().__init__(daemon=True)
        self.port = port
        self.signals = signals
        self._lock = Lock()
        self._msg_id = 0
        self._ws = None
        self._should_run = True
        self._pending = {}
        self._body_msg_for_req = {}
        self._last_activity = time.time()
        self._captcha_active = False
        self._auto_pause_until = 0.0
        self._rate_events = deque(maxlen=5000)
        self._attached_sessions = {}
        self._click_queue = deque()
        self._click_active = None
        self._id_map = {}
        self._id_log_shown = False

    def update_id_map(self, mapping: dict):
        with self._lock: self._id_map = dict(mapping or {})

    def _next_id(self):
        with self._lock: self._msg_id += 1; return self._msg_id

    def _send(self, method, params=None, sessionId=None):
        try:
            msg = {"id": self._next_id(), "method": method}
            if params: msg["params"] = params
            if sessionId: msg["sessionId"] = sessionId
            self._ws.send(pyjson.dumps(msg))
            return msg["id"]
        except Exception: return None

    def set_captcha_active(self, active: bool):
        with self._lock: self._captcha_active = bool(active)
        try: self.signals.captchaNet.emit(self._captcha_active)
        except Exception: pass
    def is_captcha_active(self) -> bool:
        with self._lock: return self._captcha_active
    def is_auto_paused(self) -> bool: return time.time() < self._auto_pause_until

    def _enable_autopause(self, seconds: float):
        now = time.time()
        if now < self._auto_pause_until: return
        self._auto_pause_until = now + float(seconds)
        self.signals.autopause.emit(True)

    def _maybe_disable_autopause(self):
        if self._auto_pause_until and time.time() >= self._auto_pause_until:
            self._auto_pause_until = 0.0
            if not self.is_captcha_active(): self.signals.autopause.emit(False)

    def _target_url_allowed(self, ttype: str, url: str) -> bool:
        if not url: return False
        u = url.lower()
        if u.startswith("https://ticketing.eintrachttech.de/"): return True
        if u.startswith("blob:https://ticketing.eintrachttech.de/"): return True
        return False

    def _select_ticket_session(self):
        for sid, info in list(self._attached_sessions.items()):
            url = info.get("url","") or ""
            if "ticketing.eintrachttech.de" in url and "/placeSelection/" in url: return sid, url
        for sid, info in list(self._attached_sessions.items()):
            url = info.get("url","") or ""
            if "ticketing.eintrachttech.de" in url: return sid, url
        return None, None

    def request_cdp_click(self, wx: float, wy: float) -> str:
        token = f"cdp_{int(time.time()*1000)}_{int(wx)}_{int(wy)}"
        req = {"token": token, "x": float(wx), "y": float(wy), "stage": "init"}
        self._click_queue.append(req)
        return token

    def _cdp_world_to_dom(self, sid: str, wx: float, wy: float) -> dict:
        js = r"""
        (function(){
          function vis(el){
            try{
              const r = el.getClientRects(); const st = getComputedStyle(el);
              if (st.display === "none" || st.visibility === "hidden" || parseFloat(st.opacity||"1") === 0) return false;
              return (el.offsetWidth>0 || el.offsetHeight>0 || (r && r.length>0));
            }catch(e){ return false; }
          }
          const list = Array.from(document.querySelectorAll('canvas')).filter(vis).map(c => (
            {w:c.width,h:c.height,cw:c.clientWidth,ch:c.clientHeight,rect:c.getBoundingClientRect(),el:c}
          ));
          if(!list.length) return {ok:false, reason:"NO_CANVAS"};
          list.sort((a,b)=>(b.rect.width*b.rect.height)-(a.rect.width*a.rect.height));
          const c = list[0];
          function findViewport(){
            const cand = [];
            try{ for(const k in window){
              const v = window[k]; if (v && typeof v.toScreen==="function" && typeof v.toWorld==="function") cand.push(v);
            }}catch(e){}
            try{
              const v = c.el && (c.el.__viewport || c.el.viewport || c.el.__pixiViewport);
              if (v && typeof v.toScreen==="function") cand.unshift(v);
            }catch(e){}
            return cand[0]||null;
          }
          let sx = __WX__, sy = __WY__;
          const vp = findViewport();
          if (vp){ try { const scr = vp.toScreen({x:__WX__, y:__WY__}); sx = scr.x; sy = scr.y; } catch(e){} }
          const scaleX = (c.cw>0 && c.w>0) ? (c.cw/c.w) : 1;
          const scaleY = (c.ch>0 && c.h>0) ? (c.ch/c.h) : 1;
          const domX = c.rect.left + sx * scaleX;
          const domY = c.rect.top  + sy * scaleY;
          return {ok:true, x:domX, y:domY};
        })();
        """.replace("__WX__", str(float(wx))).replace("__WY__", str(float(wy)))
        mid = self._send("Runtime.evaluate", {"expression": js, "returnByValue": True, "awaitPromise": True}, sessionId=sid)
        if not mid: return {}
        deadline = time.time() + 2.0
        while time.time() < deadline:
            try: raw = self._ws.recv()
            except Exception: break
            if not raw: break
            try: evt = pyjson.loads(raw)
            except Exception: continue
            if evt.get("id") == mid and "result" in evt:
                val = (evt["result"].get("result") or {}).get("value") or {}
                return val if isinstance(val, dict) else {}
        return {}

    def _cdp_mouse(self, sid, mtype, x, y, button="left", clickCount=1):
        params = {"type": mtype, "x": float(x), "y": float(y)}
        if mtype in ("mousePressed","mouseReleased"):
            params.update({"button": button, "clickCount": int(clickCount)})
        self._send("Input.dispatchMouseEvent", params, sessionId=sid)

    def _drive_click_state(self):
        if self._click_active is None and self._click_queue:
            req = self._click_queue.popleft()
            sid, _url = self._select_ticket_session()
            if not sid:
                try: self.signals.cdpResult.emit({"token": req["token"], "ok": False, "error": "NO_SESSION"})
                except Exception: pass
                return
            val = self._cdp_world_to_dom(sid, req["x"], req["y"])
            if not (val and val.get("ok")):
                try: self.signals.cdpResult.emit({"token": req["token"], "ok": False, "error": "COORDS"})
                except Exception: pass
                return
            req["sid"] = sid; req["px"] = float(val.get("x", 0.0)); req["py"] = float(val.get("y", 0.0))
            self._click_active = req
            self._cdp_mouse(sid, "mouseMoved", req["px"], req["py"])
            self._cdp_mouse(sid, "mousePressed", req["px"], req["py"], button="left", clickCount=1)
            self._cdp_mouse(sid, "mouseReleased", req["px"], req["py"], button="left", clickCount=1)
            try: self.signals.cdpResult.emit({"token": req["token"], "ok": True, "pageX": req["px"], "pageY": req["py"]})
            except Exception: pass
            self._click_active = None

    def _choose_ws_url(self, wait_seconds=20):
        deadline = time.time() + wait_seconds
        chosen = None
        while time.time() < deadline and self._should_run:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/list", timeout=3) as resp:
                    data = pyjson.loads(resp.read().decode("utf-8", "replace"))
                for entry in data:
                    if entry.get("type") == "page":
                        url = entry.get("url", "")
                        if PLACE_SELECTION_MATCH[0] in url and PLACE_SELECTION_MATCH[1] in url:
                            chosen = (entry.get("webSocketDebuggerUrl"), url); break
                if chosen: break
                for entry in data:
                    if entry.get("type") == "page":
                        url = entry.get("url", "")
                        if "stores.eintracht.de" in url:
                            chosen = (entry.get("webSocketDebuggerUrl"), url); break
                if chosen: break
            except Exception: pass
            time.sleep(1.0)
        return chosen

    def stop(self):
        self._should_run = False
        try:
            if self._ws: self._ws.close()
        except Exception: pass

    def _domain(self, url: str) -> str:
        try: return urlparse(url).netloc.lower()
        except Exception: return ""

    def _api_whitelisted(self, url: str) -> bool:
        try:
            parsed = urlparse(url)
            if parsed.netloc.lower() != API_HOST: return False
            path = (parsed.path or "")
            return bool(API_PATH_REGEX.search(path) or VENUEPLAN_PATH_REGEX.search(path))
        except Exception: return False

    def run(self):
        try:
            import websocket
            from websocket import WebSocketTimeoutException
        except Exception:
            self.signals.log.emit("[FEHLT] Bitte 'pip install websocket-client' ausführen.")
            return

        while self._should_run:
            try:
                chosen = self._choose_ws_url(wait_seconds=20)
                if not chosen: time.sleep(1.0); continue
                ws_url, _page_url = chosen
                if not ws_url: time.sleep(1.0); continue

                self._ws = websocket.create_connection(ws_url, timeout=30)
                self._ws.settimeout(0.05)
                self._send("Target.setAutoAttach", {"autoAttach": True, "waitForDebuggerOnStart": False, "flatten": True})
                self._send("Target.setDiscoverTargets", {"discover": True})
                self._send("Network.enable")
                self._send("Network.setCacheDisabled", {"cacheDisabled": False})
                self._last_activity = time.time()
                self._send("Target.getTargets")

                while self._should_run:
                    self._maybe_disable_autopause()
                    if time.time() - self._last_activity > 45: raise ConnectionError("DevTools idle timeout")
                    try: raw = self._ws.recv()
                    except WebSocketTimeoutException:
                        self._send("Runtime.getIsolateId")
                        try: self._drive_click_state()
                        except Exception: pass
                        continue
                    if not raw: break
                    evt = pyjson.loads(raw)
                    self._last_activity = time.time()
                    try: self._drive_click_state()
                    except Exception: pass
                    method = evt.get("method")
                    params = evt.get("params", {}) or {}
                    sid = evt.get("sessionId")

                    if method is None and "id" in evt and "result" in evt:
                        res = evt["result"]
                        if isinstance(res, dict) and "targetInfos" in res:
                            for ti in res.get("targetInfos", []):
                                ttype = ti.get("type","")
                                tid = ti.get("targetId")
                                turl = ti.get("url","")
                                if ttype in ("page","iframe","worker","service_worker","shared_worker") and self._target_url_allowed(ttype, turl) and not self.is_captcha_active():
                                    self._send("Target.attachToTarget", {"targetId": tid, "flatten": True})

                    if method == "Target.targetCreated":
                        tinfo = params.get("targetInfo", {}) or {}
                        ttype = tinfo.get("type","")
                        tid = tinfo.get("targetId")
                        turl = tinfo.get("url","")
                        if ttype in ("page","iframe","worker","service_worker","shared_worker"):
                            if self._target_url_allowed(ttype, turl):
                                self._send("Target.attachToTarget", {"targetId": tid, "flatten": True})
                            else:
                                if "sessionId" in params:
                                    self._send("Target.detachFromTarget", {"sessionId": params["sessionId"]})
                        continue

                    if method == "Target.attachedToTarget":
                        sid2 = params.get("sessionId")
                        tinfo = params.get("targetInfo", {}) or {}
                        ttype = tinfo.get("type","")
                        turl = tinfo.get("url","")
                        if not self._target_url_allowed(ttype, turl):
                            self._send("Target.detachFromTarget", {"sessionId": sid2}); continue
                        self._attached_sessions[sid2] = {"type": ttype, "url": turl, "ts": time.time()}
                        self._send("Network.enable", sessionId=sid2)
                        self._send("Network.setCacheDisabled", {"cacheDisabled": False}, sessionId=sid2)
                        continue

                    if method == "Target.detachedFromTarget":
                        sid2 = params.get("sessionId")
                        self._attached_sessions.pop(sid2, None); continue

                    if self.is_captcha_active() or self.is_auto_paused(): continue

                    if method == "Network.requestWillBeSent":
                        req = params.get("request", {}) or {}
                        url = (req.get("url") or "")
                        req_id = params.get("requestId")
                        method_http = req.get("method", "")
                        low = url.lower()
                        if any(h in low for h in CAPTCHA_URL_HINTS): self.set_captcha_active(True)
                        if not self._api_whitelisted(url): continue
                        if req_id and method_http in ("GET", "POST"):
                            self._pending[(sid, req_id)] = {"url": url, "status": None, "ts": time.time()}
                        now = time.time()
                        self._rate_events.append(now)
                        while self._rate_events and (now - self._rate_events[0]) > FLOOD_WINDOW_SEC:
                            self._rate_events.popleft()
                        if len(self._rate_events) > FLOOD_THRESHOLD and not self.is_auto_paused():
                            self._enable_autopause(AUTO_PAUSE_DURATION_SEC)

                    if method == "Network.responseReceived":
                        req_id = params.get("requestId")
                        resp = params.get("response", {}) or {}
                        url = (resp.get("url") or "")
                        if not self._api_whitelisted(url): continue
                        status = resp.get("status")
                        key = (sid, req_id)
                        if key in self._pending: self._pending[key]["status"] = status

                    if method == "Network.loadingFinished":
                        req_id = params.get("requestId")
                        key = (sid, req_id)
                        info = self._pending.get(key)
                        if info:
                            url = info.get("url","")
                            if not self._api_whitelisted(url): self._pending.pop(key, None)
                            else:
                                mid = self._send("Network.getResponseBody", {"requestId": req_id}, sessionId=sid)
                                if mid is not None: self._body_msg_for_req[mid] = key

                    if method == "Network.loadingFailed":
                        req_id = params.get("requestId")
                        key = (sid, req_id)
                        if key in self._pending: self._pending.pop(key, None)

                    if method is None and "id" in evt and "result" in evt:
                        mid = evt["id"]
                        key = self._body_msg_for_req.pop(mid, None)
                        if not key: continue
                        info = self._pending.pop(key, {"url": "?", "status": None})
                        url = info.get("url","")
                        if not self._api_whitelisted(url): continue
                        result = evt["result"]
                        body = result.get("body", "")
                        if result.get("base64Encoded"):
                            import base64
                            try: body = base64.b64decode(body).decode("utf-8", "replace")
                            except Exception: body = ""
                        if not body: continue
                        try: data = pyjson.loads(body)
                        except Exception: continue
                        try:
                            parsed_url = urlparse(url)
                            path = parsed_url.path or ""
                        except Exception: parsed_url = None; path = ""

                        if VENUEPLAN_PATH_REGEX.search(path):
                            try:
                                new_map = {}
                                items = None
                                if isinstance(data, dict):
                                    items = data.get("standingBlocks") or data.get("blocks") or data.get("seats")
                                elif isinstance(data, list): items = data
                                if isinstance(items, list):
                                    for item in items:
                                        if not isinstance(item, dict): continue
                                        if item.get("selectable") is False: continue
                                        label = (item.get("blockLabel") or "").strip()
                                        m = re.match(r"^(\d+)$", label)
                                        if not m: continue
                                        blk = m.group(1)
                                        if blk not in STEHBLOECKE: continue
                                        tid = item.get("id")
                                        if not tid: continue
                                        new_map[str(tid).strip()] = blk
                                if new_map:
                                    with self._lock: self._id_map = new_map
                                    if not self._id_log_shown:
                                        self._id_log_shown = True
                                        try: self.signals.log.emit("Stehblock-IDs wurden geladen.")
                                        except Exception: pass
                                else:
                                    if not self._id_log_shown:
                                        self._id_log_shown = True
                                        try: self.signals.log.emit("Keine passenden Stehblock-IDs im venuePlan.")
                                        except Exception: pass
                            except Exception: pass
                            continue

                        hits = []
                        try:
                            ids = set()
                            has_avail_flag = False
                            def collect_with_availability(obj):
                                nonlocal has_avail_flag
                                if isinstance(obj, dict):
                                    if "id" in obj and "availableCapacity" in obj:
                                        has_avail_flag = True
                                        tid = obj.get("id")
                                        avail = obj.get("availableCapacity")
                                        try: avail_val = int(avail) if avail is not None else 0
                                        except Exception: avail_val = 0
                                        if isinstance(tid, (str, int)) and avail_val > 0:
                                            ids.add(str(tid))
                                        return
                                    for v in obj.values(): collect_with_availability(v)
                                elif isinstance(obj, list):
                                    for it in obj: collect_with_availability(it)
                            collect_with_availability(data)

                            if not has_avail_flag and not ids:
                                def collect_legacy(obj):
                                    if isinstance(obj, dict):
                                        for k, v in obj.items():
                                            lk = str(k).lower()
                                            if lk in ("id", "ticketid", "ticket_id"):
                                                if isinstance(v, (str, int)): ids.add(str(v))
                                            else: collect_legacy(v)
                                    elif isinstance(obj, list):
                                        for it in obj: collect_legacy(it)
                                collect_legacy(data)

                            with self._lock: id_map = dict(self._id_map)
                            for tid in ids:
                                blk = id_map.get(tid)
                                if blk: hits.append({"id": tid, "block": str(blk)})
                        except Exception: hits = []
                        if hits:
                            seen = set(); compact = []
                            for h in hits:
                                b = h["block"]
                                if b not in seen: compact.append(h); seen.add(b)
                            self.signals.standing_hits.emit(compact)
            except Exception:
                try:
                    if self._ws: self._ws.close()
                except Exception: pass
                time.sleep(1.0)

class BrowserWindow(QMainWindow):
    def reset_calibration(self):
        try:
            js_cancel = "(function(){try{window.__datCalibArmed=false; window.__datCalibResult=null; window.__datCalibToken=null; window.__datCalibProceed=false;}catch(e){}})();"
            self.browser.page().runJavaScript(js_cancel)
            self.calib_state = {"active": False, "block": None, "token": None}
            self.block_coords.clear()
            save_block_coords(self.block_coords)
            js = "(function(){try{var d=document.getElementById('dat-marker-layer'); if(d) d.innerHTML='';}catch(e){}})();"
            self.browser.page().runJavaScript(js)
            QTimer.singleShot(200, self._maybe_start_calibration)
        except Exception as e: self.ui("warn", f"Zurücksetzen fehlgeschlagen: {e}")

    def __init__(self, gui_ref: MainWindow, debug_port: int = DEBUG_PORT):
        super().__init__()
        self.setWindowTitle("AdlerBrowser")
        try: self.setWindowIcon(_load_app_icon())
        except Exception: pass
        self._debug_port = int(debug_port)
        try:
            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                geo = screen.availableGeometry()
                base_w, base_h = 1600, 1000
                w = min(base_w, int(geo.width()*0.95))
                h = min(base_h, int(geo.height()*0.95))
                if w < 1024: w = 1024
                if h < 700: h = 700
                self.setFixedSize(w, h)
            else: self.setFixedSize(1600, 1000)
        except Exception: self.setFixedSize(1600, 1000)
        try: self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, False)
        except Exception:
            try: self.setWindowFlag(Qt.WindowMaximizeButtonHint, False)
            except Exception: pass

        self.gui_ref = gui_ref
        self.game_title = None
        self._game_title_failed = False
        self._calibration_entry_started = False
        self._game_title_requested = False
        self._icons = {"map":"🗺️","start":"🚀","standing":"👣","queue":"📥","click":"🖱️","ok":"✅","warn":"⚠️","captcha":"🧩","reload":"🔁","info":"ℹ️"}
        def _format_prefix():
            title = getattr(self, "game_title", None)
            return f"[{title}] " if title else ""
        self.ui = lambda key, text: self.gui_ref.log(f"{self._icons.get(key,'•')} {_format_prefix()}{text}")

        profile = create_persistent_web_profile(self)
        page = QWebEnginePage(profile, self)
        try: page.renderProcessTerminated.connect(self._on_render_crash)
        except Exception: pass
        page.createWindow = lambda _type: self.browser.page()

        self.browser = QWebEngineView()
        self.browser.setPage(page)
        self.browser.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        self.browser.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
        self.setCentralWidget(self.browser)
        self.browser.setUrl(QUrl(START_URL))

        self.browser.page().loadFinished.connect(self._on_load_finished)
        self.browser.urlChanged.connect(lambda _u: QTimer.singleShot(300, self._wait_for_canvas_then_start))

        self.signals = SnifferSignals()
        self.signals.log.connect(self._sniffer_log)
        self.signals.autopause.connect(self._on_autopause_change)
        self.signals.standing_hits.connect(self._handle_standing_hits)
        self.signals.cdpResult.connect(self._on_cdp_result)
        self.signals.captchaNet.connect(self._on_captcha_net)

        self._captcha_net_active = False
        self._captcha_net_since = 0.0
        self._silent_captcha_timer = QTimer(self)
        self._silent_captcha_timer.setInterval(1000)
        self._silent_captcha_timer.timeout.connect(self._check_silent_captcha)
        self._silent_captcha_timer.start()

        self.block_coords = load_block_coords()
        self._id_to_block = {}
        self._search_active = False
        self._sniffer_started = False
        try:
            if not self._sniffer_started: self._start_sniffer()
        except Exception: pass
        self._captcha_active = False
        self._captcha_first_seen = 0.0
        self._captcha_email_sent = False
        self._available_blocks = {}
        self._click_cooldown = {}
        self._map_seen = False
        self._last_cart_counts = {}
        self._purchase_hint_shown = False
        self._free_log_until = {}
        self._last_clicked_block = None

        self._captcha_timer = QTimer(self); self._captcha_timer.setInterval(CAPTCHA_SCAN_INTERVAL_MS)
        self._captcha_timer.timeout.connect(self._scan_captcha); self._captcha_timer.start()
        QTimer.singleShot(200, self._scan_captcha)

        self._click_timer = QTimer(self); self._click_timer.setInterval(CLICK_INTERVAL_MS)
        self._click_timer.timeout.connect(self._click_loop); self._click_timer.start()

        self._watchdog_fail = 0
        self._watchdog = QTimer(self); self._watchdog.setInterval(WATCHDOG_INTERVAL_MS)
        self._watchdog.timeout.connect(self._watchdog_check); self._watchdog.start()

        self._queue_timer = QTimer(self); self._queue_timer.setInterval(2000)
        self._queue_timer.timeout.connect(self._check_waitingroom_button); self._queue_timer.start()

        QTimer.singleShot(500, self._wait_for_canvas_then_start)
        QTimer.singleShot(600, self._render_markers_js)

        self.calib_state = {"active": False, "block": None, "token": None}
        self._cdp_callbacks = {}
        # Sperre für OCR (nur alle X Sekunden versuchen)
        self._last_captcha_solve_attempt = 0

    def closeEvent(self, event):
        try: save_block_coords(self.block_coords)
        except Exception: pass
        try:
            if hasattr(self, "sniffer"): self.sniffer.stop()
        except Exception: pass
        try: super().closeEvent(event)
        except Exception: pass

    def _sniffer_log(self, msg: str):
        try: self.ui("info", msg)
        except Exception:
            try: self.gui_ref.log(msg)
            except Exception: pass

    def _update_game_title(self):
        js = r"""(function(){
            try {
                var el = document.querySelector("._teamName_xl1ij_81");
                if (el && el.innerText) return el.innerText.trim();
                if (document.title) return document.title.trim();
                return "";
            } catch(e) { return ""; }
        })();"""
        self.browser.page().runJavaScript(js, self._on_game_title_js)

    def _ensure_game_title(self):
        """
        Versucht den Spieltitel aus dem DOM zu lesen, falls noch keiner gesetzt ist.
        Bei leeren Ergebnissen wird nicht sofort aufgegeben, damit spätere Versuche noch möglich sind.
        """
        if self.game_title or self._game_title_failed:
            return
        try:
            self._update_game_title()
        except Exception:
            # Bei harten Fehlern nicht endlos weiterprobieren
            self._game_title_failed = True

    def _on_game_title_js(self, title):
        """Callback für den JavaScript-Aufruf zum Lesen des Spieltitels.

        Wichtig: Der JS-Aufruf kann mehrfach ausgelöst werden (z.B. beim ersten
        Erkennen der Map und später erneut vor der Kalibrierung). Damit der Log
        nur einmal erscheint, loggen wir nur dann, wenn vorher noch kein
        `game_title` gesetzt war.
        """
        if isinstance(title, str):
            t = title.strip()
            if t:
                already_had_title = bool(self.game_title)
                self.game_title = t
                self._game_title_failed = False
                # Nur beim ersten erfolgreichen Setzen loggen
                if not already_had_title:
                    self.ui("ok", f"Spiel erkannt: {self.game_title}")
            else:
                # Leerer Titel – wir werten das als "failed",
                # damit die Suche trotzdem starten kann, auch ohne Spieltitel.
                self._game_title_failed = True
                return
        else:
            # Nur bei echten Fehlern das Flag setzen
            self._game_title_failed = True

    def _on_autopause_change(self, active: bool):
        self.gui_ref.lbl_autopause.setText(f"Auto-Pause: {'aktiv' if active else 'frei'}")
        if active:
            self._autopause_since = time.time()
            QTimer.singleShot(20000, self._maybe_reload_after_long_autopause)

    def _maybe_reload_after_long_autopause(self):
        try:
            sniffer = getattr(self, "sniffer", None)
            if not sniffer: return
            try: auto_paused = sniffer.is_auto_paused()
            except Exception: auto_paused = False
            captcha_active = bool(getattr(self, "_captcha_active", False))
            if auto_paused and not captcha_active:
                self.ui("reload", "Autopause >20s – Seite wird neu geladen …")
                self.browser.reload()
        except Exception: pass
        else: self._autopause_since = 0.0

    def _on_load_finished(self, ok: bool):
        QTimer.singleShot(300, self._render_markers_js)
        QTimer.singleShot(500, self._wait_for_canvas_then_start)

    def _on_captcha_net(self, active: bool):
        self._captcha_net_active = bool(active)
        if active and not getattr(self, "_captcha_net_since", 0.0):
            self._captcha_net_since = time.time()
        if not active: self._captcha_net_since = 0.0

    def _check_silent_captcha(self):
        if getattr(self, "_captcha_active", False): return
        if getattr(self, "_captcha_net_active", False) and getattr(self, "_captcha_net_since", 0.0):
            try: since = float(self._captcha_net_since)
            except Exception: since = 0.0
            if since and (time.time() - since >= 25.0):
                self._captcha_net_since = 0.0
                try: self.ui("reload", "Stumme Captcha-Phase >25s - Seite wird neu geladen ...")
                except Exception: pass
                try: self.browser.reload()
                except Exception: pass

    # --- UPDATED CAPTCHA SCAN & SOLVE ---
    def _scan_captcha(self):
        js = r"""
        (function(){
          try{
            function isVisible(el){
              try{
                const r = el.getClientRects(); const st = getComputedStyle(el);
                if (st.display === "none" || st.visibility === "hidden" || parseFloat(st.opacity||"1") === 0) return false;
                return (el.offsetWidth>0 || el.offsetHeight>0 || (r && r.length>0));
              }catch(e){ return false; }
            }
            const HINTS = ["friendlycaptcha","frcapi","eu.frcapi","recaptcha","hcaptcha","turnstile","cf-challenge","cdn-cgi/challenge","cdn-cgi/challenge-platform","__cf_chl_tk","__cf_chl_rt","captcha="];
            const ifr = Array.from(document.querySelectorAll('iframe')).some(f => {
              try{
                const s=((f.src||"")+" "+(f.title||"")).toLowerCase();
                return isVisible(f) && HINTS.some(h=>s.indexOf(h)!==-1);
              }catch(e){ return false; }
            });
            const body = (document.body? (document.body.innerText||""):"").toLowerCase();
            const bodyHit = ["captcha","kein roboter","not a robot"].some(k=> body.indexOf(k)!==-1);
            return {active: !!(ifr||bodyHit)};
          }catch(e){ return {active:false}; }
        })();
        """
        def _after(res):
            active = bool((res or {}).get("active", False)) if isinstance(res, dict) else False
            if active:
                if not self._captcha_active:
                    self._captcha_active = True
                    self._captcha_first_seen = time.time()
                    self._captcha_email_sent = False
                    if hasattr(self, "sniffer"): self.sniffer.set_captcha_active(True)
                    self.ui("captcha", "Captcha erkannt - Suche pausiert.")
                    self.gui_ref.lbl_captcha.setText("Captcha: aktiv")
                    QTimer.singleShot(10000, self._maybe_send_captcha_email)
                
                # --- AUTO SOLVER HOOK ---
                if DDDDOCR_DEPRECATED and (time.time() - self._last_captcha_solve_attempt > 6.0):
                    self._last_captcha_solve_attempt = time.time()
                    self._attempt_solve_queue_it_captcha()
                # ------------------------

            elif (not active) and self._captcha_active:
                self._captcha_active = False
                self._captcha_first_seen = 0.0
                self._captcha_email_sent = False
                if hasattr(self, "sniffer"): self.sniffer.set_captcha_active(False)
                self.ui("ok", "Captcha gelöst – Suche läuft weiter.")
                self.gui_ref.lbl_captcha.setText("Captcha: frei")
                QTimer.singleShot(2000, lambda: self.browser.reload())

        self.browser.page().runJavaScript(js, _after)

    def _attempt_solve_queue_it_captcha(self):
        """Extrahiert das Bild, löst es und klickt den Button."""
        js_extract = r"""
        (function() {
            try {
                // Selektoren für Queue-it Captcha
                const img = document.querySelector('.captcha-code, #img-captcha, [alt="captcha image"], img[src^="data:image"]');
                const inp = document.querySelector('input[type="text"], .captcha-input, #captcha-input');
                const btn = document.querySelector('.botdetect-button, button[type="submit"]');
                
                if (!img || !inp || !btn) return {found: false};
                
                // Bildquelle holen (oft data URI)
                let src = img.src;
                if (!src.startsWith('data:image')) {
                    // Falls kein Data-URI, versuche auf Canvas zu zeichnen (CORS Risiko)
                    var c = document.createElement('canvas');
                    c.width = img.naturalWidth; c.height = img.naturalHeight;
                    var ctx = c.getContext('2d');
                    ctx.drawImage(img, 0, 0);
                    src = c.toDataURL('image/jpeg');
                }
                return {found: true, src: src};
            } catch(e) { return {found: false, err: String(e)}; }
        })();
        """
        def _on_image_extracted(res):
            if not isinstance(res, dict) or not res.get("found"):
                return
            
            base64_src = res.get("src", "")
            if not base64_src: return

            self.ui("info", "Versuche Captcha automatisch zu lösen...")
            
            # Helper Thread/Process logic um GUI nicht zu blockieren, 
            # hier vereinfacht synchron da OpenCV schnell ist
            code = CaptchaSolver.solve(base64_src)
            
            if code and len(code) >= 4:
                self.ui("ok", f"Captcha Code ermittelt: {code}")
                # Code eintragen und klicken
                js_fill = r"""
                (function(c) {
                    try {
                        const inp = document.querySelector('input[type="text"], .captcha-input');
                        const btn = document.querySelector('.botdetect-button, button[type="submit"]');
                        if (inp && btn) {
                            inp.value = c;
                            inp.dispatchEvent(new Event('input', { bubbles: true }));
                            setTimeout(() => btn.click(), 200);
                            return true;
                        }
                    } catch(e) {}
                    return false;
                })('%s');
                """ % code
                self.browser.page().runJavaScript(js_fill)
            else:
                self.ui("warn", "Konnte Captcha nicht sicher lesen (OCR unsicher).")

        self.browser.page().runJavaScript(js_extract, _on_image_extracted)

    def _maybe_send_captcha_email(self):
        try:
            if not getattr(self, "_captcha_active", False): return
            if not getattr(self, "_search_active", False): return
            if getattr(self, "_captcha_email_sent", False): return
            game = self.game_title or "Unbekanntes Spiel"
            subject = f"🧩 Captcha entdeckt – {game}"
            body = "Captcha entdeckt - bitte manuell lösen.\nSpiel: " + game
            self.gui_ref.notify_email(subject, body)
            self._captcha_email_sent = True
        except Exception: pass

    def _check_canvas_and_url(self, cb):
        js = r"""
        (function(){
            try {
                const href = location.href || "";
                function vis(el){
                    try{
                        const r = el.getClientRects(); const st = getComputedStyle(el);
                        if (st.display==="none"||st.visibility==="hidden"||parseFloat(st.opacity||"1")===0) return false;
                        return (el.offsetWidth>0||el.offsetHeight>0||(r&&r.length>0));
                    }catch(e){ return false; }
                }
                const canvases = Array.from(document.querySelectorAll('canvas')).filter(vis);
                return { href, hasCanvas: canvases.length>0 };
            } catch(e) { return { href:"", hasCanvas:false }; }
        })();
        """
        def _after(res):
            if isinstance(res, dict): cb(res.get("href",""), bool(res.get("hasCanvas")))
            else: cb("", False)
        self.browser.page().runJavaScript(js, _after)

    def _wait_for_canvas_then_start(self):
        if self._captcha_active:
            QTimer.singleShot(1000, self._wait_for_canvas_then_start); return
        def _after_check(href, has_canvas):
            on_place_selection = (PLACE_SELECTION_MATCH[0] in href and PLACE_SELECTION_MATCH[1] in href)
            if on_place_selection and has_canvas and not self._captcha_active:
                if not self._map_seen:
                    self.ui("map", "Stadion-Map erkannt.")
                    self._map_seen = True
                    # Beim ersten Erkennen der Stadion-Map versuchen wir, den Spieltitel zu lesen
                    self._ensure_game_title()
                self._render_markers_js()
                if not self._sniffer_started: self._start_sniffer()
                if not self._search_active: self._maybe_start_calibration()
            else: QTimer.singleShot(1000, self._wait_for_canvas_then_start)
        self._check_canvas_and_url(_after_check)

    def _start_sniffer(self):
        self.sniffer = DevToolsSniffer(self._debug_port, self.signals)
        self.sniffer.start()
        try: self.sniffer.update_id_map(getattr(self, "_id_to_block", {}))
        except Exception: pass
        self._sniffer_started = True

    def _block_order(self): return [b for b in STEHBLOECKE]

    def _next_uncalibrated_block(self):
        for b in self._block_order():
            if b not in self.block_coords:
                if self.gui_ref.block_checkboxes[b].isChecked() or self.gui_ref.chk_all.isChecked(): return b
        return None

    def _inject_modal_js(self, text, step, total):
        js = """
        (function(){
          try{
            var txt = %s, stepTxt = %s, totalTxt = %s;
            function ensure(){
              var wrap=document.getElementById('dat-calib-modal');
              if(!wrap){
                wrap=document.createElement('div'); wrap.id='dat-calib-modal';
                wrap.style.position='fixed'; wrap.style.left=0; wrap.style.top=0; wrap.style.right=0; wrap.style.bottom=0;
                wrap.style.background='rgba(0,0,0,0.45)'; wrap.style.zIndex=2147483647; wrap.style.display='flex';
                wrap.style.alignItems='center'; wrap.style.justifyContent='center'; wrap.style.pointerEvents='auto';
                var box=document.createElement('div'); box.id='dat-calib-box';
                box.style.background='#fff'; box.style.padding='18px 22px'; box.style.borderRadius='14px';
                box.style.boxShadow='0 10px 40px rgba(0,0,0,0.25)'; box.style.maxWidth='520px'; box.style.width='92%%';
                box.style.font='14px system-ui, Arial';
                var h=document.createElement('div'); h.id='dat-calib-head'; h.style.fontWeight='700'; h.style.fontSize='16px'; h.style.marginBottom='8px';
                var p=document.createElement('div'); p.id='dat-calib-text'; p.style.marginBottom='14px';
                var s=document.createElement('div'); s.id='dat-calib-step'; s.style.color='#666'; s.style.marginBottom='12px';
                var btn=document.createElement('button'); btn.id='dat-calib-ok'; btn.textContent='OK';
                btn.style.border='none'; btn.style.padding='10px 16px'; btn.style.borderRadius='10px'; btn.style.cursor='pointer';
                btn.style.fontWeight='600'; btn.style.boxShadow='0 2px 10px rgba(0,0,0,0.15)';
                btn.addEventListener('click',function(){ wrap.style.display='none'; window.__datCalibProceed = true; });
                box.appendChild(h); box.appendChild(p); box.appendChild(s); box.appendChild(btn); wrap.appendChild(box); document.body.appendChild(wrap);
              }
              return wrap;
            }
            var w=ensure();
            document.getElementById('dat-calib-head').textContent='Kalibrierung';
            document.getElementById('dat-calib-text').textContent=txt;
            document.getElementById('dat-calib-step').textContent='Schritt '+stepTxt+' von '+totalTxt;
            w.style.display='flex'; window.__datCalibProceed = false;
            return true;
          }catch(e){ return false; }
        })();
        """ % (pyjson.dumps(text), int(step), int(total))
        self.browser.page().runJavaScript(js, lambda _: None)

    def _show_calib_intro_modal(self):
        total = len([b for b in self._block_order() if (self.gui_ref.chk_all.isChecked() or self.gui_ref.block_checkboxes[b].isChecked()) and b not in self.block_coords]) or 1
        self._inject_modal_js("Bitte die Kalibrierung durchführen. Klicke auf OK und danach genau EINMAL in den gefragten Block im Stadion-Canvas.", 1, total)

    def _show_step_modal(self, block_label: str, step_idx: int, total: int):
        self._inject_modal_js(f"Bitte jetzt genau EINMAL in der Stadion-Map auf Block {block_label} klicken.", step_idx, total)

    def _maybe_start_calibration(self):
        if not self._calibration_entry_started:
            if not (self.game_title or self._game_title_failed):
                if not self._game_title_requested:
                    try: self._update_game_title()
                    except Exception: self._game_title_failed = True
                    self._game_title_requested = True
                QTimer.singleShot(300, self._maybe_start_calibration); return
            self._calibration_entry_started = True

        if getattr(self, "_search_active", False): return
        if self.calib_state.get("active"): return
        nxt = self._next_uncalibrated_block()
        if not nxt:
            self.ui("ok", "Kalibrierung abgeschlossen.")
            self._render_markers_js()
            self._search_active = True
            try:
                if self.gui_ref.chk_all.isChecked():
                    scope = "alle Stehblöcke"
                else:
                    sel = [b for b, cb in self.gui_ref.block_checkboxes.items() if cb.isChecked()]
                    scope = "Blöcke " + ", ".join(sel) if sel else "keine Blöcke ausgewählt"

                # Neuer Log-Eintrag wie in der alten Version:
                self.ui("start", f"Suche gestartet für {scope}.")

                game = self.game_title or "Unbekanntes Spiel"
                subject = f"🔎 Suche gestartet – {game}"
                body = f"Suche wurde gestartet für {scope}.\nSpiel: {game}"
                self.gui_ref.notify_email(subject, body)
            except Exception:
                pass
            return
        step_idx = sum(1 for b in STEHBLOECKE if b in self.block_coords) + 1
        total = len(STEHBLOECKE)
        self._show_step_modal(nxt, step_idx, total)
        self._wait_for_user_ok_then_arm(nxt)

    def _wait_for_user_ok_then_arm(self, block_label: str):
        js = "(()=>{ try{return !!window.__datCalibProceed;}catch(e){return false;} })();"
        def _after(flag):
            if bool(flag): self._arm_calibration_click(block_label)
            else: QTimer.singleShot(120, lambda: self.browser.page().runJavaScript(js, _after))
        self.browser.page().runJavaScript(js, _after)

    def _arm_calibration_click(self, block_label: str):
        if getattr(self, "_search_active", False): return
        if self.calib_state.get("active"): return
        token = f"calib_{int(time.time()*1000)}_{block_label}"
        self.calib_state = {"active": True, "block": str(block_label), "token": token}
        js = """
        (function(){
          try{
            var BLK=%s, TOK=%s;
            window.__datCalibResult = null; window.__datCalibToken = TOK; window.__datCalibArmed = true;
            function vis(el){
              try{
                var r = el.getClientRects(); var st = getComputedStyle(el);
                if (st.display==='none'||st.visibility==='hidden'||parseFloat(st.opacity||'1')===0) return false;
                return (el.offsetWidth>0||el.offsetHeight>0||(r&&r.length>0));
              }catch(e){ return false; }
            }
            function chooseCanvas(){
              var arr = Array.from(document.querySelectorAll('canvas')).filter(vis).map(function(c){return {el:c,rect:c.getBoundingClientRect()};});
              if(!arr.length) return null;
              arr.sort(function(a,b){ return (b.rect.width*b.rect.height)-(a.rect.width*a.rect.height); });
              return arr[0].el;
            }
            function findViewport(c){
              var cand=[];
              try{ for(var k in window){ var v=window[k]; if(v&&typeof v.toScreen==='function'&&typeof v.toWorld==='function') cand.push(v);} }catch(e){}
              try{ var v=c&&(c.__viewport||c.viewport||c.__pixiViewport); if(v&&typeof v.toWorld==='function') cand.unshift(v);}catch(e){}
              return cand[0]||null;
            }
            var c = chooseCanvas(); if(!c){ window.__datCalibArmed=false; return "NO_CANVAS"; }
            var rect = c.getBoundingClientRect();
            var scaleX = (c.clientWidth>0&&c.width>0)? (c.width/c.clientWidth) : 1;
            var scaleY = (c.clientHeight>0&&c.height>0)? (c.height/c.clientHeight) : 1;
            var vp = findViewport(c);
            function onClick(ev){
              try{
                if(!window.__datCalibArmed) return;
                window.__datCalibArmed=false;
                var cx = ev.clientX - rect.left; var cy = ev.clientY - rect.top;
                var px = cx * scaleX; var py = cy * scaleY;
                var wx = px, wy = py;
                if (vp){ try{ var world = vp.toWorld({x: px, y: py}); wx = world.x; wy = world.y; }catch(e){} }
                window.__datCalibResult = {block: BLK, token:TOK, worldX: wx, worldY: wy, px: px, py: py};
              }catch(e){ window.__datCalibResult = {block: BLK, token:TOK, err: String(e)}; }
              setTimeout(function(){ try{ c.removeEventListener('click', onClick, true); }catch(e){} }, 0);
            }
            c.addEventListener('click', onClick, true);
            return "OK";
          }catch(e){ window.__datCalibArmed=false; return "ERR"; }
        })();
        """ % (pyjson.dumps(str(block_label)), pyjson.dumps(token))
        self.browser.page().runJavaScript(js, lambda res: None)
        def poll():
            jsr = "(()=>{ try{return window.__datCalibResult||null;}catch(e){return null;} })();"
            def _after(r):
                if not self.calib_state.get("active") or self.calib_state.get("token") != token: return
                if isinstance(r, dict) and r.get("token")==token and ("worldX" in r) and ("worldY" in r):
                    x = float(r["worldX"]); y = float(r["worldY"])
                    blk = str(r.get("block") or block_label)
                    self.block_coords[blk] = (x, y)
                    save_block_coords(self.block_coords)
                    self.ui("ok", f"Block {blk} gespeichert: ({x:.1f},{y:.1f}).")
                    self._render_markers_js()
                    self.browser.page().runJavaScript("try{window.__datCalibProceed=false;}catch(e){}", lambda _: None)
                    self.calib_state = {"active": False, "block": None, "token": None}
                    QTimer.singleShot(250, self._maybe_start_calibration)
                else: QTimer.singleShot(120, lambda: self.browser.page().runJavaScript(jsr, _after))
            self.browser.page().runJavaScript(jsr, _after)
        QTimer.singleShot(120, poll)

    def _render_markers_js(self):
        markers = [{"block": b, "x": xy[0], "y": xy[1]} for b, xy in self.block_coords.items()]
        payload = pyjson.dumps(markers)
        js = """
        (function(){
          try{
            var markers = %s;
            function ensureLayer(){
              var d=document.getElementById('dat-marker-layer');
              if(!d){
                d=document.createElement('div'); d.id='dat-marker-layer';
                d.style.position='fixed'; d.style.left='0'; d.style.top='0'; d.style.width='100%%'; d.style.height='100%%';
                d.style.pointerEvents='none'; d.style.zIndex='2147483646';
                document.body.appendChild(d);
              }
              return d;
            }
            function vis(el){
              try{
                var r=el.getClientRects(); var st=getComputedStyle(el);
                if(st.display==='none'||st.visibility==='hidden'||parseFloat(st.opacity||'1')===0) return false;
                return (el.offsetWidth>0||el.offsetHeight>0||(r&&r.length>0));
              }catch(e){return false;}
            }
            function chooseCanvas(){
              var arr=Array.from(document.querySelectorAll('canvas')).filter(vis).map(function(c){return {el:c,rect:c.getBoundingClientRect()};});
              if(!arr.length) return null;
              arr.sort(function(a,b){return (b.rect.width*b.rect.height)-(a.rect.width*a.rect.height);});
              return arr[0].el;
            }
            function findViewport(c){
              var cand=[];
              try{ for(var k in window){ var v=window[k]; if(v&&typeof v.toScreen==='function'&&typeof v.toWorld==='function') cand.push(v);} }catch(e){}
              try{ var v=c&&(c.__viewport||c.viewport||c.__pixiViewport); if(v&&typeof v.toScreen==='function') cand.unshift(v);}catch(e){}
              return cand[0]||null;
            }
            var layer = ensureLayer();
            function ensureBlockEl(block){
              var ring=document.getElementById('dat-marker-ring-'+block);
              var label=document.getElementById('dat-marker-label-'+block);
              if(!ring){
                ring=document.createElement('div'); ring.id='dat-marker-ring-'+block;
                ring.style.position='fixed'; ring.style.width='20px'; ring.style.height='20px';
                ring.style.border='3px solid red'; ring.style.borderRadius='50%%'; ring.style.boxSizing='border-box';
                ring.style.pointerEvents='none'; layer.appendChild(ring);
              }
              if(!label){
                label=document.createElement('div'); label.id='dat-marker-label-'+block;
                label.style.position='fixed'; label.style.font='600 12px system-ui, Arial'; label.style.color='red';
                label.style.textShadow='0 0 2px #fff'; label.style.pointerEvents='none'; layer.appendChild(label);
              }
              return {ring:ring, label:label};
            }
            function rerender(){
              var c=chooseCanvas(); if(!c){ return; }
              var rect=c.getBoundingClientRect(); var vp=findViewport(c);
              var scaleX=(c.clientWidth>0&&c.width>0)?(c.clientWidth/c.width):1;
              var scaleY=(c.clientHeight>0&&c.height>0)?(c.clientHeight/c.height):1;
              for(var i=0;i<markers.length;i++){
                var m=markers[i];
                var block=String(m.block||''); if(!block) continue;
                var sx=m.x, sy=m.y;
                if(vp){ try{ var scr=vp.toScreen({x:m.x,y:m.y}); sx=scr.x; sy=scr.y; }catch(e){} }
                var domX=rect.left + sx*scaleX; var domY=rect.top + sy*scaleY;
                var objs=ensureBlockEl(block);
                objs.ring.style.left=(domX-10)+'px'; objs.ring.style.top=(domY-10)+'px';
                objs.label.textContent='Block '+block; objs.label.style.left=(domX+14)+'px'; objs.label.style.top=(domY-8)+'px';
              }
            }
            rerender();
            if(!window.__datMarkerBound){
              window.__datMarkerBound=true;
              window.addEventListener('scroll', rerender, true);
              window.addEventListener('resize', rerender);
            }
          }catch(e){} 
        })();
        """ % payload
        self.browser.page().runJavaScript(js)

    def _handle_standing_hits(self, hits: list):
        if not hits or self._captcha_active or not getattr(self, "_search_active", False): return
        erlaubte = set(STEHBLOECKE) if self.gui_ref.chk_all.isChecked() else {b for b, cb in self.gui_ref.block_checkboxes.items() if cb.isChecked()}
        now = time.time()
        new_blocks = []
        for h in hits:
            blk = str(h.get("block") or "").strip()
            if not blk or blk not in erlaubte: continue
            if blk not in self.block_coords:
                self.ui("warn", f"Block {blk} gefunden, aber nicht kalibriert.")
                continue
            self._available_blocks[blk] = now
            if now >= float(self._free_log_until.get(blk, 0.0)):
                new_blocks.append(blk)
                self._free_log_until[blk] = now + AVAIL_TTL_SEC
        if new_blocks:
            blks = sorted(set(new_blocks))
            if len(blks) == 1: self.ui("standing", f"Ticket in Block {blks[0]} gefunden.")
            else: self.ui("standing", "Freie Stehplätze erkannt in: " + ", ".join(blks))

    def _on_cdp_result(self, payload: dict):
        try:
            ok = bool((payload or {}).get("ok"))
            if ok:
                self.ui("click", f"Klick auf Block {getattr(self, '_last_clicked_block', '-')} ausgeführt.")
                QTimer.singleShot(3000, self._check_cart_detailed)
            else: self.ui("warn", f"Klick auf Block {getattr(self, '_last_clicked_block', '-')} fehlgeschlagen.")
        except Exception: pass

    def _show_purchase_hint_and_open(self):
        try:
            current_url = ""
            try: current_url = self.browser.url().toString()
            except Exception: current_url = ""
            msg = QMessageBox(self)
            try: msg.setIcon(QMessageBox.Icon.Information)
            except Exception: pass
            msg.setWindowTitle("Kauf im Standardbrowser")
            msg.setText("""Ticket im Warenkorb! Bitte schließe den Kauf im Standardbrowser ab.
Klicke auf OK - ich öffne den Standardbrowser mit der aktuellen Stadion-Map.
Hinweis: Stelle sicher, dass Du im Browser eingeloggt bist; der Warenkorb ist ggf. an die Sitzung gebunden.""" )
            try: msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            except Exception: msg.setStandardButtons(QMessageBox.Ok)
            res = msg.exec()
            try: ok_btn = QMessageBox.StandardButton.Ok
            except Exception: ok_btn = getattr(QMessageBox, "Ok", 0)
            if res == ok_btn:
                if current_url:
                    try: QDesktopServices.openUrl(QUrl(current_url))
                    except Exception: pass
                try: self._last_cart_counts = {}
                except Exception: pass
                try: self._purchase_hint_shown = False
                except Exception: pass
                try: QTimer.singleShot(45000, lambda: (self.ui("reload", "45s nach Ticket-Kauf – Seite wird neu geladen …"), self.browser.reload()))
                except Exception: pass
        except Exception as e:
            try: self.ui("warn", f"Hinweis-Fenster fehlgeschlagen: {e}")
            except Exception: pass

    def _click_loop(self):
        if not self._sniffer_started or not self._search_active or self._captcha_active: return
        now = time.time()
        stale = [b for b, ts in self._available_blocks.items() if (now - ts) > AVAIL_TTL_SEC]
        for b in stale: self._available_blocks.pop(b, None)
        for blk, last_seen in list(self._available_blocks.items()):
            if (now - last_seen) > AVAIL_TTL_SEC: continue
            last_click = self._click_cooldown.get(blk, 0.0)
            if (now - last_click) < (CLICK_INTERVAL_MS/1000.0 - 0.05): continue
            xy = self.block_coords.get(blk)
            if not xy: continue
            wx, wy = xy
            try:
                if hasattr(self, "sniffer") and getattr(self, "sniffer", None):
                    self._last_clicked_block = blk
                    tok = self.sniffer.request_cdp_click(wx, wy)
                    if tok: self._click_cooldown[blk] = now
                else: self.ui("warn", "Sniffer nicht aktiv.")
            except Exception as e: self.ui("warn", f"CDP-Klick Fehler: {e}")

    def _check_cart_detailed(self):
        js = r"""
        (function(){
          try {
            const cart = document.querySelector('[class^="_TicketBasketContainer_"]');
            if (!cart) return {ok:false, counts:[]};
            const txt = cart.innerText || "";
            const lines = txt.split(/\n+/).map(s=>s.trim()).filter(s=>s.length>0);
            const cnt = {};
            for (const line of lines){
              const m = line.match(/block\s*(\d{1,2})/i);
              if (m){ const b = m[1]; cnt[b] = (cnt[b]||0)+1; }
            }
            const m2 = txt.match(/anzahl\s*(\d+)[^\d]+block\s*(\d{1,2})/i);
            if (m2){
              const n = parseInt(m2[1],10), b = m2[2];
              if (!isNaN(n)) cnt[b] = Math.max(cnt[b]||0, n);
            }
            const out = Object.keys(cnt).map(b => [b, cnt[b]]);
            return {ok:true, counts: out};
          } catch(e) { return {ok:false, err:String(e), counts:[]}; }
        })();
        """
        def _after(res):
            try:
                if not (isinstance(res, dict) and res.get("ok")): return
                pairs = res.get("counts") or []
                current = {}
                for b, n in pairs:
                    sb = str(b).strip()
                    try: iv = int(n)
                    except Exception: iv = 0
                    if sb and iv >= 0: current[sb] = iv
                for b in sorted(current.keys(), key=lambda x: int(x) if x.isdigit() else x):
                    prev = int(self._last_cart_counts.get(b, 0)) if hasattr(self, "_last_cart_counts") else 0
                    n = current[b]
                    if n > prev:
                        if n == 1: self.ui("ok", f"Warenkorb: 1 Ticket für Block {b} erkannt.")
                        else: self.ui("ok", f"Warenkorb: {n} Tickets für Block {b} im Warenkorb.")
                        try:
                            game = self.game_title or "Unbekanntes Spiel"
                            subj = f"🛒 Ticket im Warenkorb – {game}"
                            body = (f"Ein Ticket für Block {b} wurde in deinen Warenkorb gelegt." if n == 1 else f"{n} Tickets für Block {b} sind in deinem Warenkorb.")
                            body += f"\nSpiel: {game}"
                            self.gui_ref.notify_email(subj, body)
                        except Exception: pass
                        try: self.gui_ref.play_alarm()
                        except Exception: pass
                was_nonempty = any(v>0 for v in getattr(self, "_last_cart_counts", {}).values()) if hasattr(self, "_last_cart_counts") else False
                try:
                    any_added = False
                    prev = dict(getattr(self, "_last_cart_counts", {}))
                    for _b, _n in current.items():
                        if int(_n) > int(prev.get(_b, 0)): any_added = True; break
                    if any_added and not getattr(self, "_purchase_hint_shown", False):
                        self._purchase_hint_shown = True
                        QTimer.singleShot(0, self._show_purchase_hint_and_open)
                except Exception: pass
                self._last_cart_counts = current
                if (not current) and was_nonempty:
                    self.ui("warn", "Warenkorb nun leer.")
                    try: self._purchase_hint_shown = False
                    except Exception: pass
            except Exception: pass
        self.browser.page().runJavaScript(js, _after)

    def _on_render_crash(self, terminationStatus, statusCode):
        try: last_url = self.browser.url().toString()
        except Exception: last_url = START_URL
        try: self.ui("warn", f"Browser abgestürzt ({terminationStatus}) – Reload...")
        except Exception: pass
        try:
            old_view = getattr(self, "browser", None)
            self.browser = None
            if old_view is not None: old_view.deleteLater()
        except Exception: pass
        profile = create_persistent_web_profile(self)
        page = QWebEnginePage(profile, self)
        try: page.renderProcessTerminated.connect(self._on_render_crash)
        except Exception: pass
        page.createWindow = lambda _type: self.browser.page()
        new_view = QWebEngineView()
        new_view.setPage(page)
        try:
            s = new_view.settings()
            s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
            s.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
        except Exception: pass
        self.browser = new_view
        self.setCentralWidget(self.browser)
        try: self.browser.page().loadFinished.connect(self._on_load_finished)
        except Exception: pass
        try: self.browser.urlChanged.connect(lambda _u: QTimer.singleShot(300, self._wait_for_canvas_then_start))
        except Exception: pass
        try: self.browser.setUrl(QUrl(last_url))
        except Exception: pass

    def _check_waitingroom_button(self):
        try: current_url = self.browser.url().toString().lower()
        except Exception: current_url = ""
        if "ticketing.eintrachttech.de" in current_url and "/placeselection/" in current_url: return
        if getattr(self, "_captcha_active", False): return

        js = r"""(function(){
          try {
            const candidates = Array.from(document.querySelectorAll(
              'button, a, [role="button"], input[type="button"], input[type="submit"]'
            ));
            function textOf(el){ return ((el.innerText || el.value || "") + "").toLowerCase().trim(); }
            for (const el of candidates) {
              const t = textOf(el);
              if (!t) continue;
              if (t.indexOf("neue wartenummer") !== -1 || t.indexOf("neue warte") !== -1 || t.indexOf("neue nummer") !== -1) {
                el.click(); return {clicked:true, label:t};
              }
            }
            return {clicked:false};
          } catch(e) { return {clicked:false, err:String(e)}; }
        })();"""
        def _after(res):
            try:
                from collections.abc import Mapping
                is_mapping = isinstance(res, Mapping)
            except Exception: is_mapping = isinstance(res, dict)
            if not is_mapping: return
            if res.get("clicked"):
                label = res.get("label", "")
                try: self.ui("queue", f'Warteseite – Button „{label}“ gedrückt.')
                except Exception: pass
        try: self.browser.page().runJavaScript(js, _after)
        except Exception: pass

    def _watchdog_check(self):
        js = r"""
        (function(){
            try {
                function vis(el){
                    try{
                      const r = el.getClientRects(); const st = getComputedStyle(el);
                      if (st.display === "none" || st.visibility === "hidden" || parseFloat(st.opacity||"1") === 0) return false;
                      return (el.offsetWidth>0 || el.offsetHeight>0 || (r && r.length>0));
                    }catch(e){ return false; }
                }
                const canvases = Array.from(document.querySelectorAll('canvas')).filter(vis);
                const href = (location && location.href) ? location.href : "";
                return { visCount: canvases.length, href };
            } catch(e) { return { visCount:0, href:"" }; }
        })();
        """
        def _after(res):
            visCount = int((res or {}).get("visCount", 0) or 0) if isinstance(res, dict) else 0
            ok = (visCount > 0)
            if ok: self._watchdog_fail = 0
            else:
                self._watchdog_fail += 1
                if self._watchdog_fail >= WATCHDOG_MAX_FAILS:
                    self._watchdog_fail = 0
                    self.ui("reload", "Seite reagiert nicht – Map wird neu geladen …")
                    try: self.browser.reload()
                    except Exception: pass
        self.browser.page().runJavaScript(js, _after)

def main():
    ensure_dirs()
    args = sys.argv[1:]
    if "--child" in args:
        port = os.environ.get("DAT_CDP_PORT") or str(DEBUG_PORT)
        os.environ.setdefault("QTWEBENGINE_REMOTE_DEBUGGING", port)
        app = QApplication(sys.argv)
        try: app.setWindowIcon(_load_app_icon())
        except Exception: pass
        gui = MainWindow()
        log_port = os.environ.get("DAT_LOG_PORT")
        if log_port:
            try: gui.log = RemoteLogger("127.0.0.1", int(log_port))
            except Exception: pass
        gui.hide()
        win = BrowserWindow(gui, debug_port=int(port))
        win.show()
        sys.exit(app.exec())
    else:
        os.environ.setdefault("QTWEBENGINE_REMOTE_DEBUGGING", str(DEBUG_PORT))
        app = QApplication(sys.argv)
        try: app.setWindowIcon(_load_app_icon())
        except Exception: pass
        win = MainWindow()
        win.show()
        sys.exit(app.exec())

if __name__ == "__main__":
    main()