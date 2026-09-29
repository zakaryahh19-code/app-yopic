"""
LocalShare - Local file & message transfer app (phone <-> PC) over same network (hotspot)
Runs on Kivy for desktop and Android with the same code.
"""

import socket
import threading
import time
import os
import uuid
import tempfile
import textwrap
import traceback

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp, sp
from kivy.graphics import Color, RoundedRectangle
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.button import Button
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.progressbar import ProgressBar
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.filechooser import FileChooserIconView
from kivy.uix.textinput import TextInput

# ==================================================
#              DESIGN SYSTEM
# ==================================================
SPACE_XS = dp(6)
SPACE_SM = dp(8)
SPACE_MD = dp(14)
SPACE_LG = dp(20)

RADIUS_SM = dp(10)
RADIUS_MD = dp(12)

FONT_XS = sp(11)
FONT_SM = sp(12)
FONT_MD = sp(14)
FONT_LG = sp(17)

ICON_SM = dp(22)
ICON_LG = dp(52)

ROW_H = dp(60)
BTN_H = dp(44)
HEADER_H = dp(44)

# ---------- General settings ----------
UDP_PORT = 50000
TCP_PORT = 50001
BROADCAST_INTERVAL = 2
PEER_TIMEOUT = 6
CHUNK_SIZE = 65536

ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

def asset(name):
    return os.path.join(ASSETS_DIR, name)

def log(msg):
    print(f"[LocalShare] {msg}")


# ==================================================
#        Android helpers (permissions / network)
# ==================================================
def is_android():
    try:
        from kivy.utils import platform
        return platform == "android"
    except Exception:
        return False

_multicast_lock = None

def request_android_permissions():
    """Ask for runtime permissions (storage etc.). INTERNET is granted automatically
    but MUST be declared in buildozer.spec."""
    if not is_android():
        return
    try:
        from android.permissions import request_permissions, Permission
        perms = [Permission.READ_EXTERNAL_STORAGE, Permission.WRITE_EXTERNAL_STORAGE]
        for extra in ("READ_MEDIA_IMAGES", "READ_MEDIA_VIDEO", "READ_MEDIA_AUDIO"):
            if hasattr(Permission, extra):
                perms.append(getattr(Permission, extra))
        request_permissions(perms)
    except Exception as e:
        log(f"permission request error: {e}")

def acquire_multicast_lock():
    """Without this lock many Android phones silently drop incoming UDP broadcasts."""
    global _multicast_lock
    if not is_android():
        return
    try:
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Context = autoclass("android.content.Context")
        wifi = PythonActivity.mActivity.getSystemService(Context.WIFI_SERVICE)
        _multicast_lock = wifi.createMulticastLock("localshare_lock")
        _multicast_lock.setReferenceCounted(True)
        _multicast_lock.acquire()
        log("Multicast lock acquired")
    except Exception as e:
        log(f"multicast lock error: {e}")

def get_broadcast_targets():
    """Return every broadcast address worth trying (Android often blocks 255.255.255.255)."""
    targets = {"255.255.255.255"}
    ips = set()
    # 1) trick: which local IP would be used to reach some address (no packet is sent)
    for probe in ("8.8.8.8", "192.168.43.1", "192.168.1.1", "10.0.0.1"):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((probe, 9))
            ips.add(s.getsockname()[0])
            s.close()
        except Exception:
            pass
    # 2) Android: ask WifiManager directly
    if is_android():
        try:
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            Context = autoclass("android.content.Context")
            wifi = PythonActivity.mActivity.getSystemService(Context.WIFI_SERVICE)
            ip_int = wifi.getConnectionInfo().getIpAddress()
            if ip_int:
                ips.add(socket.inet_ntoa(ip_int.to_bytes(4, "little")))
        except Exception as e:
            log(f"wifi ip error: {e}")
    for ip in ips:
        if ip and not ip.startswith("127.") and ip != "0.0.0.0":
            parts = ip.split(".")
            targets.add(".".join(parts[:3] + ["255"]))
    # 3) typical hotspot subnets (own phone hotspot / Windows hotspot / Wi-Fi Direct)
    targets.update({"192.168.43.255", "192.168.137.255", "192.168.49.255", "172.20.10.255"})
    return sorted(targets)

def get_downloads_dir():
    candidates = [
        "/storage/emulated/0/Download",
        os.path.join(os.path.expanduser("~"), "Downloads"),
    ]
    for p in candidates:
        if os.path.isdir(p):
            return p
    p = os.path.join(os.path.expanduser("~"), "Downloads")
    os.makedirs(p, exist_ok=True)
    return p

DOWNLOAD_DIR = get_downloads_dir()
log(f"Received files will be saved to: {DOWNLOAD_DIR}")

class State:
    device_name = socket.gethostname() + "-" + str(uuid.uuid4())[:8]
    theme = "light"

log(f"Starting as: {State.device_name}")

GREEN = (35 / 255, 197 / 255, 94 / 255, 1)
GREEN_DARK = (22 / 255, 163 / 255, 74 / 255, 1)
RED = (0.9, 0.3, 0.3, 1)

LIGHT_THEME = {"BG": (0.99, 0.99, 0.99, 1), "CARD": (1, 1, 1, 1),
               "CARD_ALT": (0.95, 0.96, 0.95, 1),
               "TEXT": (0.10, 0.10, 0.10, 1), "SUBTEXT": (0.48, 0.48, 0.48, 1)}
DARK_THEME = {"BG": (0.06, 0.06, 0.06, 1), "CARD": (0.13, 0.13, 0.13, 1),
              "CARD_ALT": (0.17, 0.17, 0.17, 1),
              "TEXT": (0.95, 0.95, 0.95, 1), "SUBTEXT": (0.62, 0.62, 0.62, 1)}

def theme():
    return DARK_THEME if State.theme == "dark" else LIGHT_THEME

Window.clearcolor = theme()["BG"]
Window.minimum_width = dp(300)
Window.minimum_height = dp(500)

FILE_ICONS = {
    ".pdf": "file_pdf.png",
    ".doc": "file_doc.png", ".docx": "file_doc.png",
    ".mp3": "file_audio.png", ".wav": "file_audio.png", ".m4a": "file_audio.png",
    ".jpg": "file_image.png", ".jpeg": "file_image.png", ".png": "file_image.png",
    ".mp4": "file_video.png", ".mkv": "file_video.png", ".avi": "file_video.png",
    ".txt": "file_text.png",
    ".zip": "file_zip.png", ".rar": "file_zip.png",
    ".apk": "file_generic.png",
}

def get_file_icon(filename):
    ext = os.path.splitext(filename)[1].lower()
    return asset(FILE_ICONS.get(ext, "file_generic.png"))

def guess_dir(*names):
    home = os.path.expanduser("~")
    candidates = []
    for n in names:
        candidates.append(os.path.join(home, n))
        candidates.append(os.path.join("/storage/emulated/0", n))
    for p in candidates:
        if os.path.isdir(p):
            return p
    return home

def files_root_dir():
    """Real, visible storage root (like a computer's file explorer), not the sandboxed home."""
    if os.path.isdir("/storage/emulated/0"):
        return "/storage/emulated/0"
    return os.path.expanduser("~")

HIDDEN_SKIP = {".thumbnails", ".trashed", "$recycle.bin"}

def scan_files(root_dir, extensions, max_files=60):
    """Background-safe scan; skips hidden/cache folders that hold broken thumbnails."""
    found = []
    try:
        for dirpath, dirnames, filenames in os.walk(root_dir):
            dirnames[:] = [d for d in dirnames
                           if not d.startswith(".") and d.lower() not in HIDDEN_SKIP]
            for fn in filenames:
                if os.path.splitext(fn)[1].lower() in extensions:
                    found.append(os.path.join(dirpath, fn))
                    if len(found) >= max_files:
                        return found
    except Exception as e:
        log(f"scan_files error: {e}")
    return found


def wrapped_label(text, chars_per_line=30, font_size=FONT_MD, color=(0, 0, 0, 1),
                   bold=False, halign="left"):
    lines = textwrap.wrap(text, chars_per_line) or [text]
    wrapped_text = "\n".join(lines)
    height = dp(20) * len(lines) + dp(14)
    return Label(text=wrapped_text, font_size=font_size, color=color, bold=bold,
                 halign=halign, valign="middle", size_hint_y=None, height=height)


# ==================================================
#              Reusable styled widgets
# ==================================================
class RoundedBG(BoxLayout):
    def __init__(self, bg_color=(1, 1, 1, 1), radius=None, **kwargs):
        super().__init__(**kwargs)
        radius = radius if radius is not None else RADIUS_MD
        with self.canvas.before:
            self._color_instr = Color(*bg_color)
            self.rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[radius])
        self.bind(pos=self._update, size=self._update)

    def _update(self, *args):
        self.rect.pos = self.pos
        self.rect.size = self.size

    def set_bg(self, color):
        self._color_instr.rgba = color


class TruncateLabel(Label):
    def __init__(self, **kwargs):
        kwargs.setdefault("shorten", True)
        kwargs.setdefault("shorten_from", "right")
        super().__init__(**kwargs)
        self.bind(size=self._sync)

    def _sync(self, *args):
        self.text_size = (self.width, self.height)


class IconButton(ButtonBehavior, Image):
    """Plain icon button, no background circle/box."""
    def __init__(self, icon, size_dp=32, **kwargs):
        super().__init__(source=icon, size_hint=(None, None),
                          size=(dp(size_dp), dp(size_dp)), allow_stretch=True,
                          keep_ratio=True, **kwargs)

    def on_press(self):
        self.opacity = 0.5

    def on_release(self):
        self.opacity = 1


class GreenButton(ButtonBehavior, RoundedBG):
    def __init__(self, text="", icon=None, **kwargs):
        kwargs.setdefault("height", BTN_H)
        kwargs.setdefault("size_hint_y", None)
        super().__init__(bg_color=GREEN, radius=RADIUS_MD,
                          orientation="horizontal", padding=SPACE_SM, spacing=SPACE_XS, **kwargs)
        if icon:
            self.add_widget(Image(source=icon, size_hint=(None, None), size=(ICON_SM, ICON_SM)))
        if text:
            self.label = TruncateLabel(text=text, color=(1, 1, 1, 1), bold=True, font_size=FONT_MD)
            self.add_widget(self.label)

    def on_press(self):
        self.set_bg(GREEN_DARK)

    def on_release(self):
        self.set_bg(GREEN)


class DangerButton(ButtonBehavior, RoundedBG):
    def __init__(self, text="", icon=None, **kwargs):
        kwargs.setdefault("height", BTN_H)
        kwargs.setdefault("size_hint_y", None)
        super().__init__(bg_color=RED, radius=RADIUS_MD,
                          orientation="horizontal", padding=SPACE_SM, spacing=SPACE_XS, **kwargs)
        if icon:
            self.add_widget(Image(source=icon, size_hint=(None, None), size=(ICON_SM, ICON_SM)))
        if text:
            self.label = TruncateLabel(text=text, color=(1, 1, 1, 1), bold=True, font_size=FONT_MD)
            self.add_widget(self.label)


class TabButton(ButtonBehavior, RoundedBG):
    def __init__(self, text, icon, active=False, **kwargs):
        t = theme()
        super().__init__(bg_color=GREEN if active else t["CARD_ALT"], radius=RADIUS_SM,
                          orientation="vertical", size_hint=(None, None), size=(dp(78), dp(64)),
                          padding=dp(6), spacing=dp(2), **kwargs)
        self.icon_img = Image(source=icon, size_hint=(None, None), size=(ICON_SM, ICON_SM),
                               pos_hint={"center_x": 0.5}, allow_stretch=True, keep_ratio=True)
        self.add_widget(self.icon_img)
        self.label = TruncateLabel(text=text, font_size=FONT_XS, bold=active,
                                    color=(1, 1, 1, 1) if active else t["TEXT"],
                                    size_hint_y=None, height=dp(16))
        self.add_widget(self.label)

    def set_active(self, active):
        t = theme()
        self.set_bg(GREEN if active else t["CARD_ALT"])
        self.label.color = (1, 1, 1, 1) if active else t["TEXT"]
        self.label.bold = active


class SectionLabel(TruncateLabel):
    def __init__(self, text, **kwargs):
        t = theme()
        super().__init__(text=text, color=t["TEXT"], bold=True, font_size=FONT_MD,
                          size_hint_y=None, height=dp(24), halign="left", valign="middle", **kwargs)


class MessageRow(BoxLayout):
    def __init__(self, text, outgoing, **kwargs):
        t = theme()
        label = wrapped_label(text, chars_per_line=26,
                               color=(1, 1, 1, 1) if outgoing else t["TEXT"],
                               font_size=FONT_MD, halign="left")
        bubble = RoundedBG(bg_color=GREEN if outgoing else t["CARD_ALT"], radius=RADIUS_MD,
                            padding=SPACE_SM, size_hint=(0.78, None))
        bubble.add_widget(label)
        bubble.height = label.height + dp(20)

        super().__init__(size_hint_y=None, height=bubble.height, **kwargs)
        spacer = BoxLayout(size_hint_x=0.22)
        if outgoing:
            self.add_widget(spacer)
            self.add_widget(bubble)
        else:
            self.add_widget(bubble)
            self.add_widget(spacer)


class StyledPopup(Popup):
    def __init__(self, title_text, message_text, chars_per_line=30, **kwargs):
        t = theme()
        content = BoxLayout(orientation="vertical", padding=SPACE_MD)
        label = wrapped_label(message_text, chars_per_line=chars_per_line,
                               color=t["TEXT"], font_size=FONT_MD, halign="center")
        content.add_widget(label)
        super().__init__(title=title_text, content=content,
                          size_hint=(0.85, None), height=label.height + dp(120),
                          background_color=t["BG"], title_color=t["TEXT"],
                          title_size=FONT_MD, **kwargs)


# ==================================================
#                  Network layer
# ==================================================
class NetworkManager:
    def __init__(self, app):
        self.app = app
        self.peers = {}
        self.lock = threading.Lock()
        self.send_lock = threading.Lock()
        self.active_conn = None
        self.running = True
        self.send_cancel_event = threading.Event()
        self.recv_cancel_event = threading.Event()

    def start(self):
        threading.Thread(target=self.broadcast_loop, daemon=True).start()
        threading.Thread(target=self.listen_udp_loop, daemon=True).start()
        threading.Thread(target=self.tcp_server_loop, daemon=True).start()
        threading.Thread(target=self.cleanup_peers_loop, daemon=True).start()

    def broadcast_loop(self):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except Exception as e:
            log(f"FATAL: could not create broadcast socket: {e}")
            return
        targets = get_broadcast_targets()
        last_refresh = time.time()
        log(f"Broadcast targets: {targets}")
        while self.running:
            if time.time() - last_refresh > 20:  # network may have changed (hotspot toggled)
                targets = get_broadcast_targets()
                last_refresh = time.time()
            msg = f"LOCALSHARE|{State.device_name}|{TCP_PORT}".encode()
            for target in targets:
                try:
                    sock.sendto(msg, (target, UDP_PORT))
                except Exception:
                    pass  # unreachable subnets are normal, ignore
            time.sleep(BROADCAST_INTERVAL)

    def listen_udp_loop(self):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", UDP_PORT))
        except Exception as e:
            log(f"FATAL: could not bind UDP listener: {e}")
            return
        while self.running:
            try:
                data, addr = sock.recvfrom(1024)
                text = data.decode(errors="ignore")
                if text.startswith("LOCALSHARE|"):
                    _, name, _port = text.split("|")
                    ip = addr[0]
                    if name == State.device_name:
                        continue
                    is_new = ip not in self.peers
                    with self.lock:
                        self.peers[ip] = {"name": name, "last_seen": time.time()}
                    if is_new:
                        log(f"Discovered new peer: {name} at {ip}")
                    Clock.schedule_once(lambda dt: self.app.refresh_peers())
            except Exception as e:
                log(f"UDP receive error: {e}")

    def cleanup_peers_loop(self):
        while self.running:
            time.sleep(2)
            now = time.time()
            with self.lock:
                dead = [ip for ip, p in self.peers.items()
                        if now - p["last_seen"] > PEER_TIMEOUT]
                for ip in dead:
                    del self.peers[ip]
            if dead:
                Clock.schedule_once(lambda dt: self.app.refresh_peers())

    def tcp_server_loop(self):
        try:
            server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_sock.bind(("", TCP_PORT))
            server_sock.listen(5)
            log(f"TCP server listening on port {TCP_PORT}")
        except Exception as e:
            log(f"FATAL: could not start TCP server: {e}")
            return
        while self.running:
            try:
                conn, addr = server_sock.accept()
                log(f"Incoming TCP connection from {addr}")
                threading.Thread(target=self.handle_incoming,
                                  args=(conn, addr), daemon=True).start()
            except Exception as e:
                log(f"TCP accept error: {e}")

    def handle_incoming(self, conn, addr):
        try:
            header = self.recv_line(conn)
            if header.startswith("CONNECT_REQUEST:"):
                sender_name = header.split(":", 1)[1]
                accepted = self.app.ask_accept_connection(sender_name, addr[0])
                if accepted:
                    conn.sendall(b"ACCEPT\n")
                    conn.settimeout(None)
                    self.active_conn = conn
                    Clock.schedule_once(lambda dt: self.app.open_chat_screen(sender_name))
                    self.file_receive_loop(conn)
                else:
                    conn.sendall(b"REJECT\n")
                    conn.close()
        except Exception as e:
            log(f"handle_incoming ERROR: {e}")
            traceback.print_exc()

    def request_connect(self, ip, my_name, on_result):
        def worker():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(10)
                sock.connect((ip, TCP_PORT))
                sock.sendall(f"CONNECT_REQUEST:{my_name}\n".encode())
                sock.settimeout(35)
                resp = self.recv_line(sock)
                if resp == "ACCEPT":
                    sock.settimeout(None)
                    self.active_conn = sock
                    threading.Thread(target=self.file_receive_loop, args=(sock,), daemon=True).start()
                    Clock.schedule_once(lambda dt: on_result(True, sock))
                else:
                    sock.close()
                    Clock.schedule_once(lambda dt: on_result(False, None))
            except Exception as e:
                log(f"Connect error to {ip}: {e}")
                Clock.schedule_once(lambda dt: on_result(False, None))
        threading.Thread(target=worker, daemon=True).start()

    def recv_line(self, sock):
        data = b""
        while not data.endswith(b"\n"):
            chunk = sock.recv(1)
            if not chunk:
                break
            data += chunk
        return data.decode(errors="ignore").strip()

    def send_file(self, filepath, on_progress, on_finish):
        def worker():
            self.send_cancel_event.clear()
            try:
                sock = self.active_conn
                filesize = os.path.getsize(filepath)
                filename = os.path.basename(filepath)
                with self.send_lock:
                    sock.sendall(f"FILE:{filename}:{filesize}\n".encode())
                    sent = 0
                    with open(filepath, "rb") as f:
                        while sent < filesize:
                            if self.send_cancel_event.is_set():
                                log(f"Send cancelled by user: {filename}")
                                sock.close()
                                self.active_conn = None
                                Clock.schedule_once(lambda dt: on_finish("cancelled"))
                                return
                            chunk = f.read(CHUNK_SIZE)
                            if not chunk:
                                break
                            sock.sendall(chunk)
                            sent += len(chunk)
                            pct = sent / filesize * 100
                            Clock.schedule_once(lambda dt, p=pct: on_progress(p))
                Clock.schedule_once(lambda dt: on_finish("done"))
            except Exception as e:
                log(f"send_file ERROR (peer likely cancelled/disconnected): {e}")
                Clock.schedule_once(lambda dt: on_finish("cancelled"))
        threading.Thread(target=worker, daemon=True).start()

    def cancel_send(self):
        self.send_cancel_event.set()

    def send_message(self, text):
        def worker():
            try:
                with self.send_lock:
                    self.active_conn.sendall(f"MSG:{text}\n".encode())
            except Exception as e:
                log(f"send_message ERROR: {e}")
        threading.Thread(target=worker, daemon=True).start()

    def file_receive_loop(self, conn):
        while self.running:
            try:
                header = self.recv_line(conn)
                if not header:
                    log("Connection closed by peer")
                    break
                if header.startswith("FILE:"):
                    self.receive_one_file(conn, header)
                elif header.startswith("MSG:"):
                    text = header.split(":", 1)[1]
                    Clock.schedule_once(lambda dt: self.app.on_incoming_message(text))
            except Exception as e:
                log(f"file_receive_loop ERROR: {e}")
                break

    def cancel_recv(self):
        self.recv_cancel_event.set()
        try:
            if self.active_conn:
                self.active_conn.close()
        except Exception:
            pass

    def receive_one_file(self, conn, header):
        self.recv_cancel_event.clear()
        _, filename, filesize = header.split(":")
        filesize = int(filesize)
        save_path = os.path.join(DOWNLOAD_DIR, filename)
        received = 0
        Clock.schedule_once(lambda dt: self.app.on_incoming_file_start(filename, filesize))
        try:
            with open(save_path, "wb") as f:
                while received < filesize:
                    if self.recv_cancel_event.is_set():
                        raise ConnectionAbortedError("cancelled by user")
                    chunk = conn.recv(min(CHUNK_SIZE, filesize - received))
                    if not chunk:
                        break
                    f.write(chunk)
                    received += len(chunk)
                    pct = received / filesize * 100
                    Clock.schedule_once(lambda dt, p=pct: self.app.on_incoming_file_progress(filename, p))
            if received >= filesize:
                Clock.schedule_once(lambda dt: self.app.on_incoming_file_finish(filename, "done"))
            else:
                if os.path.exists(save_path):
                    os.remove(save_path)
                Clock.schedule_once(lambda dt: self.app.on_incoming_file_finish(filename, "cancelled"))
        except Exception as e:
            log(f"receive_one_file ERROR/cancelled: {e}")
            if os.path.exists(save_path):
                os.remove(save_path)
            Clock.schedule_once(lambda dt: self.app.on_incoming_file_finish(filename, "cancelled"))


# ==================================================
#                  UI Screens
# ==================================================
class PeerRow(RoundedBG):
    def __init__(self, ip, name, on_connect, **kwargs):
        t = theme()
        super().__init__(bg_color=t["CARD"], radius=RADIUS_MD, orientation="horizontal",
                          size_hint_y=None, height=ROW_H, padding=SPACE_SM, spacing=SPACE_SM, **kwargs)
        text_box = BoxLayout(orientation="vertical")
        text_box.add_widget(TruncateLabel(text=name, color=t["TEXT"], bold=True,
                                           font_size=FONT_MD, halign="left", valign="middle"))
        text_box.add_widget(TruncateLabel(text=ip, color=t["SUBTEXT"], font_size=FONT_XS,
                                           halign="left", valign="middle"))
        self.add_widget(text_box)
        connect_btn = GreenButton(text="Connect", icon=asset("icon_connect.png"),
                                   size_hint=(None, None), size=(dp(120), dp(44)))
        connect_btn.bind(on_release=lambda inst: on_connect(ip, name))
        self.add_widget(connect_btn)


class HomeScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        t = theme()
        root = BoxLayout(orientation="vertical", padding=SPACE_MD, spacing=SPACE_MD)

        header = BoxLayout(size_hint_y=None, height=HEADER_H, spacing=SPACE_SM)
        header.add_widget(TruncateLabel(text=f"My device: {State.device_name}", color=t["TEXT"],
                                         bold=True, font_size=FONT_MD, halign="left", valign="middle"))
        refresh_btn = IconButton(asset("icon_refresh.png"), size_dp=28)
        refresh_btn.bind(on_release=lambda inst: App.get_running_app().refresh_peers())
        header.add_widget(refresh_btn)
        settings_btn = IconButton(asset("icon_settings.png"), size_dp=28)
        settings_btn.bind(on_release=lambda inst: setattr(App.get_running_app().sm, "current", "settings"))
        header.add_widget(settings_btn)
        root.add_widget(header)

        manual_card = RoundedBG(bg_color=t["CARD_ALT"], radius=RADIUS_MD, orientation="horizontal",
                                 size_hint_y=None, height=dp(56), padding=SPACE_SM, spacing=SPACE_SM)
        self.ip_input = TextInput(hint_text="Type the other device's IP here",
                                   multiline=False, background_color=t["CARD"],
                                   foreground_color=t["TEXT"], font_size=FONT_MD,
                                   padding=[SPACE_SM, dp(10), SPACE_SM, dp(10)])
        manual_btn = GreenButton(text="Connect", icon=asset("icon_connect.png"),
                                  size_hint=(None, None), size=(dp(110), dp(40)))
        manual_btn.bind(on_release=self.manual_connect)
        manual_card.add_widget(self.ip_input)
        manual_card.add_widget(manual_btn)
        root.add_widget(manual_card)

        root.add_widget(SectionLabel("Nearby devices"))

        self.empty_label = Label(text="Searching for nearby devices...",
                                  color=t["SUBTEXT"], font_size=FONT_MD,
                                  size_hint_y=None, height=dp(40))

        self.scroll = ScrollView(bar_width=dp(4))
        self.peer_list = BoxLayout(orientation="vertical", size_hint_y=None, spacing=SPACE_SM)
        self.peer_list.bind(minimum_height=self.peer_list.setter("height"))
        self.peer_list.add_widget(self.empty_label)
        self.scroll.add_widget(self.peer_list)
        root.add_widget(self.scroll)

        self.add_widget(root)

    def update_peers(self, peers):
        self.peer_list.clear_widgets()
        if not peers:
            self.peer_list.add_widget(self.empty_label)
            return
        app = App.get_running_app()
        for ip, info in peers.items():
            row = PeerRow(ip, info["name"], app.connect_to_peer)
            self.peer_list.add_widget(row)

    def manual_connect(self, instance):
        ip = self.ip_input.text.strip()
        if ip:
            App.get_running_app().connect_to_peer(ip, "manual")


class SettingsScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        t = theme()
        root = BoxLayout(orientation="vertical", padding=SPACE_MD, spacing=SPACE_LG)

        header = BoxLayout(size_hint_y=None, height=HEADER_H, spacing=SPACE_SM)
        back_btn = IconButton(asset("icon_back.png"), size_dp=26)
        back_btn.bind(on_release=lambda inst: setattr(App.get_running_app().sm, "current", "home"))
        header.add_widget(back_btn)
        header.add_widget(TruncateLabel(text="Settings", color=t["TEXT"], bold=True, font_size=FONT_LG))
        root.add_widget(header)

        card1 = RoundedBG(bg_color=t["CARD_ALT"], radius=RADIUS_MD, orientation="vertical",
                           size_hint_y=None, height=dp(90), padding=SPACE_SM, spacing=SPACE_XS)
        card1.add_widget(TruncateLabel(text="Device name", color=t["SUBTEXT"], font_size=FONT_SM,
                                        size_hint_y=None, height=dp(18), halign="left"))
        name_row = BoxLayout(size_hint_y=None, height=dp(46), spacing=SPACE_SM)
        self.name_input = TextInput(text=State.device_name, multiline=False, font_size=FONT_MD)
        save_btn = GreenButton(text="Save", size_hint=(None, None), size=(dp(90), dp(42)))
        save_btn.bind(on_release=self.save_name)
        name_row.add_widget(self.name_input)
        name_row.add_widget(save_btn)
        card1.add_widget(name_row)
        root.add_widget(card1)

        theme_card = RoundedBG(bg_color=t["CARD_ALT"], radius=RADIUS_MD, orientation="horizontal",
                                size_hint_y=None, height=dp(58), padding=SPACE_SM, spacing=SPACE_SM)
        theme_card.add_widget(TruncateLabel(text="Dark mode", color=t["TEXT"], font_size=FONT_MD))
        self.theme_btn = GreenButton(text=("On" if State.theme == "dark" else "Off"),
                                      size_hint=(None, None), size=(dp(80), dp(38)))
        self.theme_btn.bind(on_release=self.toggle_theme)
        theme_card.add_widget(self.theme_btn)
        root.add_widget(theme_card)

        root.add_widget(BoxLayout())
        self.add_widget(root)

    def save_name(self, instance):
        new_name = self.name_input.text.strip()
        if new_name:
            State.device_name = new_name
            App.get_running_app().rebuild_ui("settings")

    def toggle_theme(self, instance):
        State.theme = "dark" if State.theme == "light" else "light"
        App.get_running_app().rebuild_ui("settings")


class FileRow(RoundedBG):
    def __init__(self, filename, direction, on_cancel=None, **kwargs):
        t = theme()
        super().__init__(bg_color=t["CARD"], radius=RADIUS_MD, orientation="horizontal",
                          size_hint_y=None, height=dp(58), padding=SPACE_SM, spacing=SPACE_SM, **kwargs)
        self.done = False
        self.cancelled = False

        self.add_widget(Image(source=get_file_icon(filename),
                               size_hint=(None, None), size=(dp(26), dp(26))))
        dir_icon = "icon_send.png" if direction == "up" else "icon_download.png"
        self.add_widget(Image(source=asset(dir_icon), size_hint=(None, None), size=(dp(16), dp(16))))

        mid = BoxLayout(orientation="vertical", spacing=dp(4))
        mid.add_widget(TruncateLabel(text=filename, color=t["TEXT"], font_size=FONT_SM,
                                      halign="left", valign="bottom", size_hint_y=0.6))
        self.progress = ProgressBar(max=100, value=0, size_hint_y=None, height=dp(6))
        mid.add_widget(self.progress)
        self.add_widget(mid)

        self.status_icon = Image(source=asset("time.png"), size_hint=(None, None), size=(dp(20), dp(20)))
        self.add_widget(self.status_icon)

        self.cancel_btn = None
        if on_cancel:
            self.cancel_btn = IconButton(asset("icon_reject.png"), size_dp=20)
            self.cancel_btn.bind(on_release=lambda inst: on_cancel())
            self.add_widget(self.cancel_btn)

    def set_progress(self, pct):
        if self.cancelled:
            return
        self.progress.value = pct
        if pct >= 100:
            self.done = True
            self.status_icon.source = asset("icon_accept.png")
            self._hide_cancel()

    def mark_cancelled(self):
        self.cancelled = True
        self.status_icon.source = asset("icon_reject.png")
        self._hide_cancel()

    def _hide_cancel(self):
        if self.cancel_btn:
            self.cancel_btn.opacity = 0
            self.cancel_btn.disabled = True


# ---------- Android apps (real icons, background-loaded) ----------
def fetch_android_apps():
    """Runs in a background thread. Returns list of {name, icon (path or None), apk_path}."""
    apps = []
    try:
        from jnius import autoclass
        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        Bitmap = autoclass('android.graphics.Bitmap')
        BitmapConfig = autoclass('android.graphics.Bitmap$Config')
        BitmapDrawable = autoclass('android.graphics.drawable.BitmapDrawable')
        Canvas = autoclass('android.graphics.Canvas')
        FileOutputStream = autoclass('java.io.FileOutputStream')
        CompressFormat = autoclass('android.graphics.Bitmap$CompressFormat')

        context = PythonActivity.mActivity
        pm = context.getPackageManager()
        installed = pm.getInstalledApplications(0)

        cache_dir = os.path.join(tempfile.gettempdir(), "localshare_app_icons")
        os.makedirs(cache_dir, exist_ok=True)

        for i in range(installed.size()):
            info = installed.get(i)
            try:
                label = str(pm.getApplicationLabel(info))
                pkg = str(info.packageName)
                apk_path = str(info.publicSourceDir)
                icon_path = os.path.join(cache_dir, pkg + ".png")
                if not os.path.exists(icon_path):
                    drawable = pm.getApplicationIcon(info)
                    if isinstance(drawable, BitmapDrawable):
                        bmp = drawable.getBitmap()
                    else:
                        w = drawable.getIntrinsicWidth() or 128
                        h = drawable.getIntrinsicHeight() or 128
                        bmp = Bitmap.createBitmap(w, h, BitmapConfig.ARGB_8888)
                        canvas = Canvas(bmp)
                        drawable.setBounds(0, 0, w, h)
                        drawable.draw(canvas)
                    fos = FileOutputStream(icon_path)
                    bmp.compress(CompressFormat.PNG, 100, fos)
                    fos.close()
                apps.append({"name": label, "icon": icon_path, "apk_path": apk_path})
            except Exception as e:
                continue
    except Exception as e:
        log(f"App list unavailable here: {e}")
    return apps


class GalleryItem(ButtonBehavior, RoundedBG):
    def __init__(self, path, thumb_source, on_select, **kwargs):
        t = theme()
        super().__init__(bg_color=t["CARD_ALT"], radius=RADIUS_SM, orientation="vertical",
                          size_hint=(None, None), size=(dp(100), dp(118)),
                          padding=dp(4), spacing=dp(4), **kwargs)
        self.path = path
        self.on_select = on_select
        self.thumb = Image(source=thumb_source, size_hint=(1, None), height=dp(80),
                            allow_stretch=True, keep_ratio=True)
        self.add_widget(self.thumb)
        self.add_widget(TruncateLabel(text=os.path.basename(path), font_size=FONT_XS,
                                       color=t["TEXT"], size_hint_y=None, height=dp(20)))

    def on_release(self):
        self.on_select(self)

    def set_selected(self, sel):
        self.set_bg(GREEN if sel else theme()["CARD_ALT"])


class CategorizedFilePicker(Popup):
    CATEGORIES = {
        "Photos": {"exts": [".jpg", ".jpeg", ".png", ".gif", ".bmp"],
                   "path": lambda: guess_dir("Pictures", "DCIM"),
                   "icon": "tab_photos.png"},
        "Videos": {"exts": [".mp4", ".mkv", ".avi", ".mov"],
                   "path": lambda: guess_dir("Movies", "DCIM/Camera"),
                   "icon": "tab_videos.png", "thumb": "file_video.png"},
        "Music":  {"exts": [".mp3", ".wav", ".m4a", ".ogg"],
                   "path": lambda: guess_dir("Music"),
                   "icon": "tab_music.png", "thumb": "file_audio.png"},
        "Files":  {"exts": [], "path": files_root_dir,
                   "icon": "tab_files.png"},
    }

    def __init__(self, on_pick, **kwargs):
        self.on_pick = on_pick
        self.selected_path = None
        t = theme()

        root = BoxLayout(orientation="vertical", spacing=SPACE_SM, padding=SPACE_SM)

        self.tab_bar = BoxLayout(size_hint_y=None, height=dp(72), spacing=SPACE_XS)
        self.tabs = {}
        tab_defs = [(name, cat["icon"]) for name, cat in self.CATEGORIES.items()]
        tab_defs.append(("Apps", "file_generic.png"))
        for name, icon in tab_defs:
            tab = TabButton(name, asset(icon), active=(name == "Files"))
            tab.bind(on_release=lambda inst, n=name: self.switch_tab(n))
            self.tab_bar.add_widget(tab)
            self.tabs[name] = tab
        root.add_widget(self.tab_bar)

        self.content_area = BoxLayout(orientation="vertical")
        root.add_widget(self.content_area)

        btn_row = BoxLayout(size_hint_y=None, height=BTN_H, spacing=SPACE_SM)
        self.select_btn = GreenButton(text="Send")
        self.select_btn.bind(on_release=self._confirm)
        cancel_btn = DangerButton(text="Cancel")
        btn_row.add_widget(self.select_btn)
        btn_row.add_widget(cancel_btn)
        root.add_widget(btn_row)

        super().__init__(title="Choose a file to send", content=root,
                          size_hint=(0.95, 0.92), background_color=t["BG"],
                          title_color=t["TEXT"], **kwargs)
        cancel_btn.bind(on_release=lambda inst: self.dismiss())
        self.switch_tab("Files")

    def _loading_view(self, text="Loading..."):
        t = theme()
        box = BoxLayout(orientation="vertical", padding=SPACE_LG)
        box.add_widget(Label(text=text, color=t["SUBTEXT"], halign="center", valign="middle"))
        return box

    def switch_tab(self, name):
        for n, tab in self.tabs.items():
            tab.set_active(n == name)
        self.content_area.clear_widgets()
        self.selected_path = None
        self._request_id = getattr(self, "_request_id", 0) + 1
        my_request = self._request_id

        if name == "Files":
            chooser = FileChooserIconView(path=self.CATEGORIES["Files"]["path"]())
            chooser.bind(selection=self._on_chooser_select)
            self.content_area.add_widget(chooser)
            return

        self.content_area.add_widget(self._loading_view())

        if name == "Apps":
            def worker():
                apps = fetch_android_apps()
                Clock.schedule_once(lambda dt: self._show_apps(apps, my_request))
            threading.Thread(target=worker, daemon=True).start()
            return

        cat = self.CATEGORIES[name]

        def worker():
            paths = scan_files(cat["path"](), cat["exts"])
            Clock.schedule_once(lambda dt: self._show_gallery(name, cat, paths, my_request))
        threading.Thread(target=worker, daemon=True).start()

    def _show_gallery(self, name, cat, paths, request_id):
        if request_id != self._request_id:
            return  # user switched tabs before this finished
        self.content_area.clear_widgets()
        t = theme()
        if not paths:
            box = BoxLayout(orientation="vertical", padding=SPACE_LG)
            box.add_widget(Label(text=f"No {name.lower()} found on this device.",
                                  color=t["TEXT"], halign="center", valign="middle"))
            self.content_area.add_widget(box)
            return

        outer = BoxLayout(orientation="vertical", padding=[0, SPACE_SM, 0, 0])
        grid = GridLayout(cols=3, size_hint_y=None, spacing=SPACE_XS, padding=SPACE_XS)
        grid.bind(minimum_height=grid.setter("height"))
        items = []

        def select(item):
            for it in items:
                it.set_selected(it is item)
            self.selected_path = item.path

        for p in paths:
            thumb_source = p if name == "Photos" else asset(cat["thumb"])
            item = GalleryItem(p, thumb_source, select)
            items.append(item)
            grid.add_widget(item)

        scroll = ScrollView()
        scroll.add_widget(grid)
        outer.add_widget(scroll)
        self.content_area.add_widget(outer)

    def _show_apps(self, apps, request_id):
        if request_id != self._request_id:
            return
        self.content_area.clear_widgets()
        t = theme()
        if not apps:
            box = BoxLayout(orientation="vertical", padding=SPACE_LG)
            box.add_widget(Label(
                text="Apps list is only available when this app is installed "
                     "as a real Android APK (not inside Pydroid).",
                color=t["TEXT"], halign="center", valign="middle"))
            self.content_area.add_widget(box)
            return

        outer = BoxLayout(orientation="vertical", padding=[0, SPACE_MD, 0, 0])
        grid = GridLayout(cols=3, size_hint_y=None, spacing=SPACE_SM, padding=SPACE_SM)
        grid.bind(minimum_height=grid.setter("height"))
        items_data = []

        def select(cell, apk_path):
            for c, _ in items_data:
                c.set_bg(theme()["CARD_ALT"])
            cell.set_bg(GREEN)
            self.selected_path = apk_path

        for a in apps:
            icon_src = a["icon"] if a["icon"] else asset("file_generic.png")
            cell = RoundedBG(bg_color=t["CARD_ALT"], radius=RADIUS_SM, orientation="vertical",
                              size_hint_y=None, height=dp(96), padding=dp(6))
            cell.add_widget(Image(source=icon_src, size_hint_y=None, height=dp(48),
                                   allow_stretch=True, keep_ratio=True))
            cell.add_widget(TruncateLabel(text=a["name"], font_size=FONT_XS,
                                           color=t["TEXT"], halign="center"))
            cell_btn = ButtonBehavior()
            items_data.append((cell, a["apk_path"]))
            cell.bind(on_touch_down=lambda inst, touch, c=cell, p=a["apk_path"]:
                      select(c, p) if inst.collide_point(*touch.pos) else False)
            grid.add_widget(cell)

        scroll = ScrollView()
        scroll.add_widget(grid)
        outer.add_widget(scroll)
        self.content_area.add_widget(outer)

    def _on_chooser_select(self, instance, selection):
        if selection:
            self.selected_path = selection[0]

    def _confirm(self, instance):
        if self.selected_path:
            path = self.selected_path
            self.dismiss()
            self.on_pick(path)


class ChatScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.file_rows = {}
        root = BoxLayout(orientation="vertical", padding=SPACE_MD, spacing=SPACE_SM)

        header = BoxLayout(size_hint_y=None, height=HEADER_H, spacing=SPACE_SM)
        back_btn = IconButton(asset("icon_back.png"), size_dp=26)
        back_btn.bind(on_release=lambda inst: setattr(App.get_running_app().sm, "current", "home"))
        header.add_widget(back_btn)
        t = theme()
        self.status_label = TruncateLabel(text="Connected", color=t["TEXT"], bold=True,
                                           font_size=FONT_MD, halign="left", valign="middle")
        header.add_widget(self.status_label)
        root.add_widget(header)

        self.scroll = ScrollView(bar_width=dp(4))
        self.files_box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=SPACE_SM)
        self.files_box.bind(minimum_height=self.files_box.setter("height"))
        self.scroll.add_widget(self.files_box)
        root.add_widget(self.scroll)

        # Composer: text field + two plain (non-boxed) icon buttons, same big size
        compose_row = BoxLayout(size_hint_y=None, height=ICON_LG, spacing=SPACE_SM)
        self.msg_input = TextInput(hint_text="Type a message...", multiline=False, font_size=FONT_MD)
        self.msg_input.bind(on_text_validate=self.send_message)
        msg_send_btn = IconButton(asset("icon_send.png"), size_dp=52)
        msg_send_btn.bind(on_release=self.send_message)
        file_pick_btn = IconButton(asset("tab_apps.png"), size_dp=52)
        file_pick_btn.bind(on_release=self.open_file_picker)
        compose_row.add_widget(self.msg_input)
        compose_row.add_widget(msg_send_btn)
        compose_row.add_widget(file_pick_btn)
        root.add_widget(compose_row)

        self.add_widget(root)

    def open_file_picker(self, instance):
        popup = CategorizedFilePicker(on_pick=self.send_file)
        popup.open()

    def send_file(self, filepath):
        filename = os.path.basename(filepath)
        row = FileRow(filename, "up", on_cancel=lambda: self.cancel_outgoing(row))
        self.files_box.add_widget(row)
        app = App.get_running_app()

        def on_finish(status):
            if status == "done":
                row.set_progress(100)
            else:
                row.mark_cancelled()

        app.net.send_file(filepath, on_progress=lambda pct: row.set_progress(pct), on_finish=on_finish)

    def cancel_outgoing(self, row):
        App.get_running_app().net.cancel_send()
        row.mark_cancelled()

    def send_message(self, instance):
        text = self.msg_input.text.strip()
        if not text:
            return
        text_safe = text.replace("\n", " ").replace("\r", " ")
        row = MessageRow(text_safe, outgoing=True)
        self.files_box.add_widget(row)
        self.msg_input.text = ""
        App.get_running_app().net.send_message(text_safe)

    def add_incoming_message(self, text):
        row = MessageRow(text, outgoing=False)
        self.files_box.add_widget(row)

    def add_incoming_row(self, filename):
        row = FileRow(filename, "down", on_cancel=lambda: self.cancel_incoming(filename))
        self.file_rows[filename] = row
        self.files_box.add_widget(row)

    def cancel_incoming(self, filename):
        App.get_running_app().net.cancel_recv()
        if filename in self.file_rows:
            self.file_rows[filename].mark_cancelled()

    def update_incoming_progress(self, filename, pct):
        if filename in self.file_rows:
            self.file_rows[filename].set_progress(pct)

    def finish_incoming(self, filename, status):
        if filename in self.file_rows:
            if status == "done":
                self.file_rows[filename].set_progress(100)
            else:
                self.file_rows[filename].mark_cancelled()


# ==================================================
#                  Main App
# ==================================================
class LocalShareApp(App):
    def build(self):
        self.icon = asset("app_icon.png")
        self.net = NetworkManager(self)
        self.sm = ScreenManager()
        self.rebuild_ui("home")
        request_android_permissions()
        acquire_multicast_lock()
        self.net.start()
        return self.sm

    def rebuild_ui(self, keep_screen):
        Window.clearcolor = theme()["BG"]
        self.sm.clear_widgets()
        self.home = HomeScreen(name="home")
        self.chat = ChatScreen(name="chat")
        self.settings = SettingsScreen(name="settings")
        self.sm.add_widget(self.home)
        self.sm.add_widget(self.chat)
        self.sm.add_widget(self.settings)
        self.sm.current = keep_screen

    def refresh_peers(self):
        with self.net.lock:
            peers_copy = dict(self.net.peers)
        self.home.update_peers(peers_copy)

    def connect_to_peer(self, ip, name):
        def on_result(accepted, sock):
            if accepted:
                self.sm.current = "chat"
            else:
                self.show_popup("Rejected", f"{name} rejected the connection or did not respond")
        self.net.request_connect(ip, State.device_name, on_result)

    def ask_accept_connection(self, sender_name, ip):
        result = {"accepted": None}
        event = threading.Event()

        def build_and_show(dt):
            t = theme()
            content = BoxLayout(orientation="vertical", padding=SPACE_MD, spacing=SPACE_MD)
            msg_label = wrapped_label(f"{sender_name} ({ip}) wants to connect",
                                       chars_per_line=28, color=t["TEXT"],
                                       font_size=FONT_MD, halign="center")
            content.add_widget(msg_label)
            btns = BoxLayout(size_hint_y=None, height=BTN_H, spacing=SPACE_SM)

            def on_yes(instance):
                result["accepted"] = True
                popup.dismiss()
                event.set()

            def on_no(instance):
                result["accepted"] = False
                popup.dismiss()
                event.set()

            yes_btn = GreenButton(text="Accept", icon=asset("icon_accept.png"))
            yes_btn.bind(on_release=on_yes)
            no_btn = DangerButton(text="Reject", icon=asset("icon_reject.png"))
            no_btn.bind(on_release=on_no)
            btns.add_widget(yes_btn)
            btns.add_widget(no_btn)
            content.add_widget(btns)

            popup = Popup(title="Connection Request", content=content,
                          size_hint=(0.85, None), height=msg_label.height + dp(160),
                          auto_dismiss=False, background_color=t["BG"], title_color=t["TEXT"])
            popup.open()

        Clock.schedule_once(build_and_show)
        event.wait(timeout=30)
        return bool(result["accepted"])

    def open_chat_screen(self, peer_name):
        self.chat.status_label.text = f"Connected with {peer_name}"
        self.sm.current = "chat"

    def on_incoming_file_start(self, filename, filesize):
        self.chat.add_incoming_row(filename)

    def on_incoming_file_progress(self, filename, pct):
        self.chat.update_incoming_progress(filename, pct)

    def on_incoming_file_finish(self, filename, status):
        self.chat.finish_incoming(filename, status)

    def on_incoming_message(self, text):
        self.chat.add_incoming_message(text)

    def show_popup(self, title, msg):
        popup = StyledPopup(title, msg, chars_per_line=32)
        popup.open()


if __name__ == "__main__":
    LocalShareApp().run()