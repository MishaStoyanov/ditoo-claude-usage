"""OAuth (PKCE) login for the Ditoo monitor, separate from Claude Code's own session.

  python auth.py start <name>          -> prints authorize URL
  python auth.py finish <name> <code>  -> exchanges code, saves ~/.ditoo/<name>.json
"""
import base64
import hashlib
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
AUTHORIZE_URL = "https://claude.ai/oauth/authorize"
REDIRECT_URI = "https://platform.claude.com/oauth/code/callback"
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
SCOPES = "user:profile user:inference"
DIR = os.path.expanduser("~/.ditoo")
USER_AGENT = "ditoo-claude-usage/1.0"  # the default Python-urllib UA is blocked by Cloudflare


def b64url(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def post_json(url, payload):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    try:
        return json.load(urllib.request.urlopen(req, timeout=60))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{e.code}: {e.read()[:500].decode(errors='replace')}") from None


def save_tokens(name, tok):
    os.makedirs(DIR, exist_ok=True)
    data = {
        "accessToken": tok["access_token"],
        "refreshToken": tok["refresh_token"],
        "expiresAt": int((time.time() + tok.get("expires_in", 3600)) * 1000),
        "account": (tok.get("account") or {}).get("email_address"),
    }
    path = os.path.join(DIR, f"{name}.json")
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(path + ".tmp", path)
    return data


def start(name):
    verifier = b64url(secrets.token_bytes(32))
    state = b64url(secrets.token_bytes(32))
    os.makedirs(DIR, exist_ok=True)
    with open(os.path.join(DIR, f"{name}.pending.json"), "w", encoding="utf-8") as f:
        json.dump({"verifier": verifier, "state": state}, f)
    params = {
        "code": "true",
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "code_challenge": b64url(hashlib.sha256(verifier.encode()).digest()),
        "code_challenge_method": "S256",
        "state": state,
    }
    print(AUTHORIZE_URL + "?" + urllib.parse.urlencode(params))


def finish(name, raw_code):
    pending_path = os.path.join(DIR, f"{name}.pending.json")
    with open(pending_path, encoding="utf-8") as f:
        pending = json.load(f)
    code, _, state = raw_code.strip().partition("#")
    tok = post_json(TOKEN_URL, {
        "grant_type": "authorization_code",
        "code": code,
        "state": state or pending["state"],
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": pending["verifier"],
    })
    data = save_tokens(name, tok)
    os.remove(pending_path)
    print(f"saved {name}: {data['account']}")


def refresh(name):
    path = os.path.join(DIR, f"{name}.json")
    with open(path, encoding="utf-8") as f:
        cur = json.load(f)
    tok = post_json(TOKEN_URL, {
        "grant_type": "refresh_token",
        "refresh_token": cur["refreshToken"],
        "client_id": CLIENT_ID,
    })
    tok.setdefault("account", {"email_address": cur.get("account")})
    return save_tokens(name, tok)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "start":
        start(sys.argv[2])
    elif len(sys.argv) == 4 and sys.argv[1] == "finish":
        finish(sys.argv[2], sys.argv[3])
    else:
        sys.exit(__doc__)
