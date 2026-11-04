import argparse
import html
import http.client
import json
import os
import re
import secrets
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.cookies import SimpleCookie

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from minihttp import HTTPServer, html_response, json_response

APP = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(APP)
WEB = os.path.join(APP, "web")
PORTAL_PORT = 8000


class Seat:
    def __init__(self, name, host, port, student=None, ip=None, public=None, label=None):
        self.name = name
        self.host = host
        self.port = port
        self.student = student
        self.ip = ip or host
        self.public = public or name
        self.label = label or name


class DeviceGuard:
    """Blocks a browser (device) after repeated failed logins, whichever seat it moves to."""

    def __init__(self, max_failures=3, controller="http://127.0.0.1:8080", log=print):
        self.max_failures = max_failures
        self.controller = controller.rstrip("/") if controller else None
        self.log = log
        self.lock = threading.Lock()
        self.failures = {}
        self.bans = {}
        self._cache = (0.0, None)

    def _controller_blocked(self):
        if not self.controller:
            return None
        now = time.time()
        if now - self._cache[0] < 2:
            return self._cache[1]
        try:
            with urllib.request.urlopen(self.controller + "/exam/status", timeout=1.5) as r:
                blocked = set(json.loads(r.read().decode()).get("blocked", {}))
        except (OSError, ValueError):
            blocked = None
        self._cache = (now, blocked)
        return blocked

    def _block_seat(self, ip):
        if not self.controller:
            return
        try:
            req = urllib.request.Request(self.controller + "/exam/block/" + ip, method="POST", data=b"")
            urllib.request.urlopen(req, timeout=1.5).read()
        except OSError:
            pass

    def is_blocked(self, dev):
        with self.lock:
            ban = self.bans.get(dev)
        if not ban:
            return False
        blocked = self._controller_blocked()
        if blocked is None:
            return True
        if ban["ip"] in blocked:
            ban["seen"] = True
            return True
        if ban["seen"]:
            with self.lock:
                self.bans.pop(dev, None)
                self.failures.pop(dev, None)
            self.log("[GATEWAY] device unblocked after the examiner unblocked %s" % ban["ip"])
            return False
        self._block_seat(ban["ip"])
        return True

    def record(self, dev, seat, ok):
        with self.lock:
            if ok:
                self.failures.pop(dev, None)
                return
            count = self.failures.get(dev, 0) + 1
            self.failures[dev] = count
            if count < self.max_failures:
                return
            self.bans[dev] = {"ip": seat.ip, "since": time.time(), "seen": False}
        self.log("[GATEWAY] device blocked after %d failed logins (last seat %s)" % (count, seat.label))
        self._block_seat(seat.ip)


DEV_RE = re.compile(r"^[0-9a-f]{24}$")
BLOCKED_MSG = "This device is blocked after 3 failed logins. Ask the examiner to unblock it."


def build_seats(args):
    with open(args.students, encoding="utf-8") as f:
        roster = json.load(f)
    seats = []
    overrides = {}
    if args.seat_map:
        for item in args.seat_map.split(","):
            name, target = item.split("=")
            host, port = target.rsplit(":", 1)
            overrides[name.strip()] = (host.strip(), int(port))
    for i, s in enumerate(roster, 1):
        name = "st%d" % i
        host, port = overrides.get(name, (s["ip"], PORTAL_PORT))
        seats.append(Seat(name, host, port, s, s["ip"], str(i), "Seat %d" % i))
    host, port = overrides.get("intr", ("10.0.0.66", PORTAL_PORT))
    seats.append(Seat("intr", host, port, None, "10.0.0.66", "guest", "Guest seat"))
    return seats


def redirect(location, **extra):
    headers = {"Location": location}
    headers.update({k.replace("_", "-"): v for k, v in extra.items()})
    return 302, "text/plain; charset=utf-8", b"", headers


def forward(seat, method, path, body=b"", timeout=20):
    conn = http.client.HTTPConnection(seat.host, seat.port, timeout=timeout)
    try:
        headers = {"Content-Type": "application/json"} if body else {}
        conn.request(method, path, body=body or None, headers=headers)
        r = conn.getresponse()
        return r.status, r.getheader("Content-Type", "text/plain"), r.read()
    finally:
        conn.close()


def seat_status(seat):
    try:
        status, _, body = forward(seat, "GET", "/api/state", timeout=1.5)
        state = json.loads(body.decode())
        if state.get("stage") == "login":
            return "free"
        return "busy"
    except (OSError, ValueError, http.client.HTTPException):
        return "offline"


def all_status(seats):
    result = {}

    def check(seat):
        result[seat.name] = seat_status(seat)
    threads = [threading.Thread(target=check, args=(s,)) for s in seats]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return result


def make_handler(seats, title, guard=None):
    guard = guard or DeviceGuard(controller=None)
    by_name = {s.public: s for s in seats}
    with open(os.path.join(WEB, "seats.html"), encoding="utf-8") as f:
        picker = f.read()

    def cookies(req):
        cookie = SimpleCookie()
        try:
            cookie.load(req.headers.get("cookie", ""))
        except Exception:
            return {}
        return {k: m.value for k, m in cookie.items()}

    def chosen(req):
        return by_name.get(cookies(req).get("seat", ""))

    def device(req):
        dev = cookies(req).get("dev", "")
        return dev if DEV_RE.match(dev) else None

    def dev_cookie(dev):
        return {"Set-Cookie": "dev=%s; Path=/; Max-Age=86400; SameSite=Lax; HttpOnly" % dev}

    def blocked_page():
        return html_response("<div style='font-family:system-ui,sans-serif;max-width:520px;margin:60px auto;padding:24px;"
                             "border:1px solid #f1c4c0;background:#fde8e7;color:#b42318;border-radius:14px'>"
                             "<h2 style='margin-top:0'>Device blocked</h2><p>%s</p></div>" % BLOCKED_MSG)

    def handler(req):
        dev = device(req)
        new_dev = None
        if not dev and req.path in ("/seats", "/seats/api", "/seats/pick"):
            dev = new_dev = secrets.token_hex(12)
        if req.path == "/seats/api":
            states = all_status(seats)
            resp = json_response({"title": title, "device_blocked": bool(dev and guard.is_blocked(dev)), "seats": [
                {"id": s.public, "label": s.label, "state": states[s.name], "registered": bool(s.student)}
                for s in seats]})
            return resp + (dev_cookie(new_dev),) if new_dev else resp
        if req.path == "/seats":
            resp = html_response(picker)
            return resp + (dev_cookie(new_dev),) if new_dev else resp
        if req.path == "/seats/pick" and new_dev:
            return redirect("/seats/pick?seat=" + urllib.parse.quote(req.query.get("seat", "")),
                            Set_Cookie=dev_cookie(new_dev)["Set-Cookie"])
        if dev and guard.is_blocked(dev):
            if req.path.startswith("/api/"):
                return json_response({"stage": "login", "error": BLOCKED_MSG, "student": None, "question": None,
                                      "result": None}, 403)
            return blocked_page()
        if req.path == "/seats/pick":
            name = req.query.get("seat", "")
            if name == "auto":
                states = all_status(seats)
                free = [s.public for s in seats if s.student and states[s.name] == "free"]
                if not free:
                    return redirect("/seats?full=1")
                name = free[0]
            if name not in by_name:
                return redirect("/seats")
            return redirect("/", Set_Cookie="seat=%s; Path=/; Max-Age=7200; SameSite=Lax" % name)
        if req.path == "/seats/leave":
            return redirect("/seats", Set_Cookie="seat=; Path=/; Max-Age=0; SameSite=Lax")
        seat = chosen(req)
        if not seat:
            if req.path.startswith("/api/"):
                return json_response({"stage": "login", "error": "Pick a seat first.",
                                      "student": None, "question": None, "result": None}, 409)
            return redirect("/seats")
        try:
            status, ctype, body = forward(seat, req.method, req.path, req.body)
        except (OSError, http.client.HTTPException) as exc:
            if req.path.startswith("/api/"):
                return json_response({"stage": "login",
                                      "error": "%s is offline. Ask the examiner or pick another seat." % seat.label,
                                      "student": None, "question": None, "result": None}, 502)
            return html_response("<p style='font-family:sans-serif;padding:24px'>Seat %s is offline. "
                                 "<a href='/seats/leave'>Pick another seat</a></p>" % html.escape(seat.label))
        if req.path == "/api/login" and req.method == "POST":
            if not dev:
                return redirect("/seats")
            try:
                state = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                state = {}
            if state.get("error") == "invalid credentials":
                guard.record(dev, seat, ok=False)
                if guard.is_blocked(dev):
                    state["error"] = BLOCKED_MSG
                    return json_response(state, 403)
            elif state.get("stage") in ("exam", "result"):
                guard.record(dev, seat, ok=True)
        if ctype.startswith("text/html"):
            bar = ("<div style=\"background:#1f5fae;color:#fff;font:13px system-ui,sans-serif;padding:8px 16px;"
                   "display:flex;gap:12px;justify-content:center;flex-wrap:wrap\"><span>Exam gateway · <b>%s</b>"
                   "</span><a href=\"/seats/leave\" style=\"color:#fff\">Change seat</a></div>" % html.escape(seat.label))
            body = body.decode("utf-8").replace("<body>", "<body>" + bar, 1).encode("utf-8")
        return status, ctype, body
    return handler


def main():
    ap = argparse.ArgumentParser(description="Public gateway: one URL for every seat portal")
    ap.add_argument("--listen", default="0.0.0.0")
    ap.add_argument("--http-port", type=int, default=7000)
    ap.add_argument("--students", default=os.path.join(BASE, "data", "students.json"))
    ap.add_argument("--seat-map", default=None)
    ap.add_argument("--controller", default="http://127.0.0.1:8080")
    ap.add_argument("--max-login-failures", type=int, default=3)
    args = ap.parse_args()
    seats = build_seats(args)
    with open(os.path.join(BASE, "data", "questions.json"), encoding="utf-8") as f:
        title = json.load(f).get("title", "Online Examination")
    httpd = HTTPServer(args.listen, args.http_port, make_handler(seats, title, DeviceGuard(args.max_login_failures, args.controller)))
    print("[GATEWAY] http://localhost:%d -> %s" % (args.http_port, ", ".join(
        "%s=%s:%d" % (s.name, s.host, s.port) for s in seats)), flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.stop()


if __name__ == "__main__":
    main()
