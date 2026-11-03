"""Claude Code hook: mark a session as waiting for the user (`on`) or not (`off`), then poke the monitor.

One empty file per session in ~/.ditoo/attention/, so one session answering never clears another's
question. The monitor underlines the account letter while any file is there (see ditoo_usage.py).
Reads the hook's JSON from stdin for session_id. Usage: python attention.py on|off
"""
import json
import os
import socket
import sys

DIR = os.path.join(os.path.expanduser("~"), ".ditoo", "attention")
PORT = 47821


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        session = json.load(sys.stdin).get("session_id") or "unknown"
    except ValueError:
        session = "unknown"
    path = os.path.join(DIR, os.path.basename(session))
    if action == "on":
        os.makedirs(DIR, exist_ok=True)
        open(path, "w").close()
    elif action == "off" and os.path.exists(path):
        os.remove(path)
    else:
        return
    try:
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b"poke", ("127.0.0.1", PORT))
    except OSError:
        pass  # the monitor is not running; it reads the files when it starts


if __name__ == "__main__":
    main()
