"""Claude Code hook: tell the monitor a session is waiting for the user (`on`) or not (`off`).

Usage: python attention.py on|off [--account NAME] [--entrypoint ENTRYPOINT=NAME ...] [--host HOST]
  --account     the monitor's account (config.json `name`) whose letter gets the yellow line;
                default: the monitor's `attention_account`.
  --entrypoint  the account for sessions started from one Claude app, by the session's
                CLAUDE_CODE_ENTRYPOINT (`cli`, `claude-desktop`): two accounts on one PC, one in the
                console and one in the desktop app, share one settings.json.
  --host        the PC the monitor runs on; default 127.0.0.1. A session on another machine (a laptop
                driven over Remote Control) points this at that PC's LAN address.

Sends one UDP datagram, `{"action", "account", "session"}`, to HOST:47821; the monitor keeps the
state per account and per session, so one session answering never clears another's question.
The desktop app asks through its own `mcp__ccd_turn__wrap_up` tool: only a call with an `ask`
waits for an answer (one without is the end of every turn), and its own PostToolUse is not an
answer. A marker file per session in ~/.ditoo/attention/ lets the hooks skip starting Python for `off`
when this machine has nothing waiting. Reads the hook's JSON from stdin for session_id.
"""
import argparse
import json
import os
import socket
import sys

DIR = os.path.join(os.path.expanduser("~"), ".ditoo", "attention")
PORT = 47821
WRAP_UP = "mcp__ccd_turn__wrap_up"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["on", "off"])
    parser.add_argument("--account", default="")
    parser.add_argument("--entrypoint", action="append", default=[])
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    try:
        hook = json.load(sys.stdin)
    except ValueError:
        hook = {}
    if hook.get("tool_name") == WRAP_UP:
        if args.action == "off" or not (hook.get("tool_input") or {}).get("ask"):
            return
    by_entrypoint = dict(item.split("=", 1) for item in args.entrypoint if "=" in item)
    account = by_entrypoint.get(os.environ.get("CLAUDE_CODE_ENTRYPOINT", ""), args.account)
    session = os.path.basename(hook.get("session_id") or "unknown")
    path = os.path.join(DIR, session)
    if args.action == "on":
        os.makedirs(DIR, exist_ok=True)
        open(path, "w").close()
    elif os.path.exists(path):
        os.remove(path)
    else:
        return
    message = {"action": args.action, "account": account, "session": session}
    try:
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(
            json.dumps(message).encode(), (args.host, PORT)
        )
    except OSError:
        pass  # the monitor is not reachable; nothing to wait on


if __name__ == "__main__":
    main()
