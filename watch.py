"""Is the site answering? One Telegram line when it stops, one when it is back.

Runs in GitHub Actions every 5 minutes, so it keeps watching when the office PC is off.
Every DNS address is probed: one Vercel address can hang from a given network while the
site is serving everyone else. Up = at least one address answers below HTTP 500 (Vercel's
bot checkpoint answers 429 to scripts, which still proves the edge is serving).
Down = every address fails twice, 60 seconds apart. State (up/down) is carried between
runs in state/status.txt through the Actions cache.
"""
import json, os, socket, ssl, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone

HOST = os.environ.get("SITE_HOST", "book.pure-arabia.online")
STATE = "state/status.txt"


def addresses():
    try:
        return sorted({a[4][0] for a in socket.getaddrinfo(HOST, 443, socket.AF_INET, socket.SOCK_STREAM)})
    except OSError:
        return []


def probe(ip):
    try:
        with socket.create_connection((ip, 443), timeout=20) as raw:
            with ssl.create_default_context().wrap_socket(raw, server_hostname=HOST) as s:
                s.settimeout(20)
                s.sendall(f"GET / HTTP/1.1\r\nHost: {HOST}\r\nUser-Agent: pa-site-watch\r\nConnection: close\r\n\r\n".encode())
                line = s.recv(256).split(b"\r\n", 1)[0].decode("latin-1", "replace")
    except Exception as e:
        return False, f"{ip} {type(e).__name__}"
    parts = line.split()
    code = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    return 0 < code < 500, f"{ip} {line[:40]}"


def check():
    ips = addresses()
    if not ips:
        return False, ["DNS: no address"]
    res = [probe(ip) for ip in ips]
    return any(ok for ok, _ in res), [n for _, n in res]


def telegram(text):
    token, chat = os.environ.get("TG_TOKEN"), os.environ.get("TG_CHAT")
    if not token or not chat:
        print("no Telegram secrets; would send:", text)
        return
    data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=20).read()


def main():
    prev = open(STATE).read().strip() if os.path.exists(STATE) else "up"
    up, notes = check()
    if not up:
        time.sleep(60)
        up, notes = check()
    now = datetime.now(timezone.utc).strftime("%d %b %H:%M UTC")
    print(now, "UP" if up else "DOWN", notes, "previous:", prev)
    if not up and prev == "up":
        telegram(f"WEBSITE DOWN (cloud check): {HOST} is not answering, {now}.\n" + "\n".join(notes[:3])
                 + "\nIf it is down after a release, roll back to the previous deploy in Vercel "
                   "(egypt-dmc-web -> Deployments -> Instant Rollback) or ask Claude to do it.")
    elif up and prev.startswith("down"):
        telegram(f"Website BACK UP (cloud check): {HOST} is answering again, {now}.")
    os.makedirs("state", exist_ok=True)
    open(STATE, "w").write("up" if up else "down")


if __name__ == "__main__":
    main()
