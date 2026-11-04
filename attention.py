"""Claude Code hook: tell the monitor a session is waiting for the user (`on`) or not (`off`).

Usage: python attention.py on|off [--account NAME] [--host HOST]
  --account  the monitor's account (config.json `name`) whose letter gets the yellow line;
             default: the monitor's `attention_account`.
  --host     the PC the monitor runs on; default 127.0.0.1. A session on another machine (a laptop
             driven over Remote Control) points this at that PC's LAN address.

Sends one UDP datagram, `{"action", "account", "session"}`, to HOST:47821; the monitor keeps the
state per account and per session, so one session answering never clears another's question.
A marker file per session in ~/.ditoo/attention/ lets the hooks skip starting Python for `off`
when this machine has nothing waiting. Reads the hook's JSON from stdin for session_id.
"""
import argparse
import json
import os
import socket
import sys

DIR = os.path.join(os.path.expanduser("~"), ".ditoo", "attention")
PORT = 47821


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["on", "off"])
    parser.add_argument("--account", default="")
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    try:
        session = json.load(sys.stdin).get("session_id") or "unknown"
    except ValueError:
        session = "unknown"
    session = os.path.basename(session)
    path = os.path.join(DIR, session)
    if args.action == "on":
        os.makedirs(DIR, exist_ok=True)
        open(path, "w").close()
    elif os.path.exists(path):
        os.remove(path)
    else:
        return
    message = {"action": args.action, "account": args.account, "session": session}
    try:
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(
            json.dumps(message).encode(), (args.host, PORT)
        )
    except OSError:
        pass  # the monitor is not reachable; nothing to wait on


if __name__ == "__main__":
    main()
