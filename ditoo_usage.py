"""Show Claude subscription usage (5h session + weekly) for up to three accounts on a Divoom Ditoo Pro.

Settings come from config.json next to this file (see config.example.json).
Tokens live in ~/.ditoo/<name>.json (created by auth.py) and are refreshed here.
Usage: pythonw ditoo_usage.py
"""
import ipaddress
import json
import math
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

import serial

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import auth  # noqa: E402
from font import LABEL_WIDTH, glyph_pixels  # noqa: E402

CONFIG_PATH = os.path.join(HERE, "config.json")
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
REFRESH_MARGIN_MS = 5 * 60 * 1000
STALE_AFTER_S = 30 * 60
LAST_USAGE = os.path.join(auth.DIR, "last_usage.json")
DARK_FLAG = os.path.join(auth.DIR, "dark")
MAX_ACCOUNTS = 3
# Claude Code sessions waiting for an answer (attention.py, run by hooks, sends a datagram); a mark
# older than this is a session that died without saying so.
ATTENTION_PORT = 47821
ATTENTION_MAX_AGE_S = 12 * 3600

BLACK = (0, 0, 0)
TRACK = (22, 22, 22)
ERROR = (255, 0, 0)
ATTENTION = (255, 220, 0)
GREEN, AMBER, RED = (0, 200, 60), (255, 180, 0), (255, 30, 0)
WARN_AT, CRITICAL_AT = 60, 85
BAR_X0 = LABEL_WIDTH + 1
BAR_LEN = 16 - BAR_X0


def hex_color(s):
    s = s.lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    accounts = [(a["name"], a["letter"].upper(), hex_color(a["color"])) for a in cfg["accounts"]]
    if not 1 <= len(accounts) <= MAX_ACCOUNTS:
        sys.exit(f"config.json: 1..{MAX_ACCOUNTS} accounts supported")
    return {
        "port": cfg.get("port", "COM3"),
        "interval": cfg.get("interval_seconds", 120),
        "brightness": cfg.get("brightness", 100),
        "accounts": accounts,
        "attention_account": cfg.get("attention_account", cfg["accounts"][0]["name"]),
        # Who may send attention.py's datagrams besides this PC: addresses or networks
        # ("192.168.0.0/24"). Empty: the monitor listens on loopback only.
        "attention_allow": [ipaddress.ip_network(a, strict=False) for a in cfg.get("attention_allow", [])],
    }


# --- Divoom protocol ---------------------------------------------------------------------------

def packet(cmd, args=b""):
    """01 | len(LE) | cmd | args | checksum(LE) | 02, where len counts cmd + args + checksum."""
    body = bytes([cmd]) + bytes(args)
    data = (len(body) + 2).to_bytes(2, "little") + body
    return b"\x01" + data + (sum(data) & 0xFFFF).to_bytes(2, "little") + b"\x02"


def image_packet(pixels):
    """Static 16x16 frame: palette + pixel indices bit-packed LSB-first."""
    palette, idx = [], []
    for p in pixels:
        if p not in palette:
            palette.append(p)
        idx.append(palette.index(p))
    n = len(palette)
    bits = max(1, math.ceil(math.log2(n)))
    acc = nbits = 0
    out = bytearray()
    for i in idx:
        acc |= i << nbits
        nbits += bits
        while nbits >= 8:
            out.append(acc & 0xFF)
            acc >>= 8
            nbits -= 8
    if nbits:
        out.append(acc & 0xFF)
    inner = b"\x00\x00\x00" + bytes([n % 256]) + b"".join(bytes(c) for c in palette) + bytes(out)
    frame = b"\xAA" + (len(inner) + 3).to_bytes(2, "little") + inner
    return packet(0x44, b"\x00\x0A\x0A\x04" + frame)


# --- Rendering ---------------------------------------------------------------------------------

def severity_color(pct):
    if pct < WARN_AT:
        return GREEN
    if pct < CRITICAL_AT:
        return AMBER
    return RED


def draw_bar(px, rows, pct):
    """rows: bar rows bottom-first; fills column by column, bottom pixel before top within a column."""
    cells = BAR_LEN * len(rows)
    filled = round(cells * min(max(pct, 0), 100) / 100)
    if pct > 0:
        filled = max(filled, 1)
    color = severity_color(pct)
    for ri, row in enumerate(rows):
        for x in range(BAR_LEN):
            px[row * 16 + BAR_X0 + x] = color if x * len(rows) + ri < filled else TRACK


def render(results, waiting_at=()):
    """results: list of (letter, label_color, (five_h, week) | None), one per account.
    waiting_at: indexes of the accounts to underline in yellow - a Claude Code session waits for an answer."""
    px = [BLACK] * 256
    for i, (letter, label, usage) in enumerate(results):
        top = i * 6
        for x, y in glyph_pixels(letter):
            px[(top + y) * 16 + x] = label if usage else ERROR
        if i in waiting_at and top + 4 < 16:
            for x in range(LABEL_WIDTH):
                px[(top + 4) * 16 + x] = ATTENTION
        if usage:
            five, week = usage
            draw_bar(px, [top + 1, top], five)
            draw_bar(px, [top + 3], week)
    return px


# --- Usage API ---------------------------------------------------------------------------------

def load_creds(name):
    with open(os.path.join(auth.DIR, f"{name}.json"), encoding="utf-8") as f:
        return json.load(f)


def get_usage(token):
    req = urllib.request.Request(
        USAGE_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": "oauth-2025-04-20",
            "User-Agent": auth.USER_AGENT,
        },
    )
    data = json.load(urllib.request.urlopen(req, timeout=30))
    return (
        (data.get("five_hour") or {}).get("utilization") or 0,
        (data.get("seven_day") or {}).get("utilization") or 0,
    )


def account_usage(name):
    try:
        creds = load_creds(name)
        if creds["expiresAt"] - REFRESH_MARGIN_MS < time.time() * 1000:
            creds = auth.refresh(name)
        try:
            return get_usage(creds["accessToken"])
        except urllib.error.HTTPError as e:
            if e.code != 401:
                raise
            return get_usage(auth.refresh(name)["accessToken"])
    except Exception as e:  # one broken account must not take down the others
        print(f"{name}: {e}", flush=True)
        return None


def load_last():
    try:
        with open(LAST_USAGE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_last(last):
    with open(LAST_USAGE + ".tmp", "w", encoding="utf-8") as f:
        json.dump(last, f)
    os.replace(LAST_USAGE + ".tmp", LAST_USAGE)


def usage_or_last(name, last):
    """Transient failures (e.g. 429) keep showing the last good value until it is STALE_AFTER_S old."""
    usage = account_usage(name)
    if usage is not None:
        last[name] = {"usage": list(usage), "at": time.time()}
        return usage
    cached = last.get(name)
    if cached and time.time() - cached["at"] < STALE_AFTER_S:
        return tuple(cached["usage"])
    return None


# --- Waiting for an answer ---------------------------------------------------------------------

class Attention:
    """Which accounts have a Claude Code session waiting for an answer: {account: {session: since}}."""

    def __init__(self, names, default):
        self.names = names
        self.default = default
        self.sessions = {}
        self.lock = threading.Lock()

    def apply(self, message):
        """One datagram from attention.py; True when it changed anything."""
        account = message.get("account") or self.default
        session = str(message.get("session", ""))[:100]
        if account not in self.names or not session:
            return False
        with self.lock:
            marks = self.sessions.setdefault(account, {})
            if message.get("action") == "on":
                marks[session] = time.time()
                return True
            return marks.pop(session, None) is not None

    def waiting_at(self):
        """Indexes (in account order) of the accounts with a live session waiting."""
        now = time.time()
        with self.lock:
            return {
                self.names.index(account)
                for account, marks in self.sessions.items()
                if any(now - since < ATTENTION_MAX_AGE_S for since in marks.values())
            }


def listen_for_attention(attention, allow, tick):
    """attention.py sends a UDP datagram on every change; apply it and redraw at once.
    Datagrams from anywhere but this PC and the `attention_allow` networks are dropped."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0" if allow else "127.0.0.1", ATTENTION_PORT))
    while True:
        data, (host, _) = sock.recvfrom(512)
        address = ipaddress.ip_address(host)
        if not address.is_loopback and not any(address in net for net in allow):
            continue
        try:
            message = json.loads(data)
        except ValueError:
            continue
        if isinstance(message, dict) and attention.apply(message):
            tick.set()


# --- Sleep / wake ------------------------------------------------------------------------------

def is_dark():
    return os.path.exists(DARK_FLAG)


def go_dark(ser):
    """Screen brightness 0 + keyboard backlight off. The flag makes it idempotent, since 0x23 0x02 is a toggle."""
    if is_dark():
        return
    ser.write(packet(0x74, b"\x00"))
    time.sleep(0.3)
    ser.write(packet(0x23, b"\x02"))
    ser.flush()
    open(DARK_FLAG, "w").close()


def wake_up(ser, brightness=100):
    ser.write(packet(0x74, bytes([brightness])))
    if is_dark():
        time.sleep(0.3)
        ser.write(packet(0x23, b"\x02"))
        os.remove(DARK_FLAG)


class Device:
    """Serial link shared between the refresh loop and the power-notification thread."""

    def __init__(self, port):
        self.port = port
        self.ser = None
        self.lock = threading.Lock()
        self.suspended = False

    def run(self, fn):
        with self.lock:
            try:
                if self.ser is None:
                    self.ser = serial.Serial(self.port, 115200, timeout=1, write_timeout=5)
                fn(self.ser)
                return True
            except serial.SerialException as e:
                print("serial error:", e, flush=True)
                if self.ser is not None:
                    self.ser.close()
                self.ser = None
                return False


def main():
    import power

    cfg = load_config()
    accounts = cfg["accounts"]
    dev = Device(cfg["port"])
    tick = threading.Event()

    def on_sleep(reason):
        dev.suspended = True
        ok = dev.run(go_dark)
        print(time.strftime("%H:%M:%S"), f"{reason}: dark={ok}", flush=True)

    def on_wake(reason):
        nonlocal next_fetch
        next_fetch = 0.0  # fresh usage after sleep, not the cached frame
        dev.suspended = False
        print(time.strftime("%H:%M:%S"), reason, flush=True)
        tick.set()  # the loop restores brightness once the Bluetooth link is back

    power.watch(on_sleep, on_wake)
    names = [a[0] for a in accounts]
    default = cfg["attention_account"] if cfg["attention_account"] in names else names[0]
    attention = Attention(names, default)
    threading.Thread(
        target=listen_for_attention, args=(attention, cfg["attention_allow"], tick), daemon=True
    ).start()
    last = load_last()
    results = None
    next_fetch = 0.0
    while True:
        if not dev.suspended:
            fetched = results is None or time.time() >= next_fetch
            if fetched:
                results = [(letter, color, usage_or_last(name, last)) for name, letter, color in accounts]
                save_last(last)
                next_fetch = time.time() + cfg["interval"]
            wait = attention.waiting_at()
            frame = image_packet(render(results, wait))

            def push(ser):
                wake_up(ser, cfg["brightness"])
                ser.write(frame)
                ser.reset_input_buffer()

            if not dev.suspended and dev.run(push):
                summary = " ".join(f"{a[1]}={r[2]}" for a, r in zip(accounts, results))
                waiting = "".join(accounts[i][1] for i in sorted(wait))
                print(time.strftime("%H:%M:%S"), summary + (f" waiting={waiting}" if wait else ""), flush=True)
        # A datagram (attention.py) or a wake redraws at once; usage is fetched again only when due.
        tick.wait(max(1.0, next_fetch - time.time()))
        tick.clear()

if __name__ == "__main__":
    os.makedirs(auth.DIR, exist_ok=True)
    if sys.stdout is None:  # pythonw: no console
        sys.stdout = sys.stderr = open(os.path.join(auth.DIR, "monitor.log"), "a", encoding="utf-8", buffering=1)
    main()
