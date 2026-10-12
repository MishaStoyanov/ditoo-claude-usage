"""Ditoo control.

  python kb.py next [count]   keyboard backlight: next preset (position is tracked)
  python kb.py prev [count]   keyboard backlight: previous preset
  python kb.py toggle         keyboard backlight on/off
  python kb.py note <text>    remember what the current preset looks like
  python kb.py list           remembered presets, current one marked
  python kb.py goto <pos|text>  step forward to a remembered preset
  python kb.py cycle <N>      set how many presets there are (enables wrap-around in goto)
  python kb.py here <pos>     re-sync position after switching presets with the device buttons
  python kb.py off | on       screen + keyboard dark / back (same as on shutdown / startup)

The device doesn't report its current preset, so the position is counted locally in
~/.ditoo/kb_state.json. Keyboard args (0x23): 0x00 prev, 0x01 next, 0x02 on/off toggle.
Commands that talk to the device pause the usage monitor (it holds the COM port) and restart it,
except "off", which is meant for logoff/shutdown.
"""
import json
import os
import subprocess
import sys
import time

import serial

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import auth  # noqa: E402
from ditoo_usage import go_dark, load_config, packet, wake_up  # noqa: E402

TASK = "Ditoo Claude Usage"
STATE = os.path.join(auth.DIR, "kb_state.json")


def load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"pos": 0, "cycle": None, "effects": {}}


def save_state(state):
    with open(STATE + ".tmp", "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(STATE + ".tmp", STATE)


def ps(cmd):
    subprocess.run(["powershell", "-NoProfile", "-Command", cmd], check=False)


def send(packets, restart_monitor=True, fn=None):
    ps(
        f"Stop-ScheduledTask -TaskName '{TASK}'; "
        "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | "
        "Where-Object { $_.CommandLine -match 'ditoo_usage' } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
    )
    time.sleep(1)
    try:
        with serial.Serial(load_config()["port"], 115200, timeout=1, write_timeout=5) as ser:
            for p in packets:
                ser.write(p)
                time.sleep(0.5)
            if fn:
                fn(ser)
    finally:
        if restart_monitor:
            ps(f"Start-ScheduledTask -TaskName '{TASK}'")


def advance(state, count):
    send([packet(0x23, b"\x01" if count > 0 else b"\x00")] * abs(count))
    state["pos"] += count
    if state["cycle"]:
        state["pos"] %= state["cycle"]
    save_state(state)
    print_current(state)


def print_current(state):
    pos = state["pos"]
    print(f"pos {pos}: {state['effects'].get(str(pos), '?')}")


def resolve_target(state, arg):
    if arg.isdigit():
        return int(arg)
    matches = [int(p) for p, text in state["effects"].items() if arg.lower() in text.lower()]
    if len(matches) != 1:
        sys.exit(f"'{arg}' matches {len(matches)} presets; use a position number")
    return matches[0]


def main():
    args = sys.argv[1:] or ["list"]
    action, rest = args[0], args[1:]
    state = load_state()
    if action == "next":
        advance(state, int(rest[0]) if rest else 1)
    elif action == "prev":
        advance(state, -(int(rest[0]) if rest else 1))
    elif action == "toggle":
        send([packet(0x23, b"\x02")])
    elif action == "note":
        state["effects"][str(state["pos"])] = " ".join(rest)
        save_state(state)
        print_current(state)
    elif action == "list":
        for p in sorted(state["effects"], key=int):
            mark = "->" if int(p) == state["pos"] else "  "
            print(f"{mark} {p}: {state['effects'][p]}")
        print(f"pos={state['pos']} cycle={state['cycle']}")
    elif action == "goto":
        target = resolve_target(state, rest[0])
        steps = target - state["pos"]
        if steps < 0:
            if not state["cycle"]:
                sys.exit("target is behind the current position and the cycle length is unknown")
            steps += state["cycle"]
        if steps:
            advance(state, steps)
        else:
            print_current(state)
    elif action == "cycle":
        state["cycle"] = int(rest[0])
        state["pos"] %= state["cycle"]
        save_state(state)
    elif action == "here":
        state["pos"] = int(rest[0])
        save_state(state)
        print_current(state)
    elif action == "off":
        send([], restart_monitor=False, fn=go_dark)
    elif action == "on":
        send([], fn=lambda ser: wake_up(ser, load_config()["brightness"]))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
