"""
POST /api/login   body {"password": "..."}  -> sets the sign-in cookie
GET  /api/login?logout=1                       -> clears it and goes back to the login page

The password lives only in the Vercel env var SITE_PASSWORD. The cookie holds an
HMAC of that password, so changing SITE_PASSWORD signs everyone out.
"""
import hashlib, hmac, json, os, time, urllib.parse
from http.server import BaseHTTPRequestHandler

COOKIE = "mps_auth"
DAYS = 30
_tries = {}  # per-instance throttle: ip -> [count, first_ts]


def token(pw):
    return hmac.new(pw.encode(), b"mpsales-v1", hashlib.sha256).hexdigest()


class handler(BaseHTTPRequestHandler):
    def _json(self, code, obj, cookie=None):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
        if "logout" in q:
            self.send_response(302)
            self.send_header("Set-Cookie", f"{COOKIE}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax")
            self.send_header("Location", "/login.html")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        self._json(405, {"error": "POST your password"})

    def do_POST(self):
        pw = os.environ.get("SITE_PASSWORD", "")
        if not pw:
            return self._json(503, {"error": "No password set yet. Add SITE_PASSWORD in Vercel, then redeploy."})
        ip = (self.headers.get("x-forwarded-for") or "?").split(",")[0].strip()
        n, t0 = _tries.get(ip, [0, time.time()])
        if time.time() - t0 > 600:
            n, t0 = 0, time.time()
        if n >= 10:
            return self._json(429, {"error": "Too many tries. Wait 10 minutes and try again."})
        try:
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            data = {}
        if hmac.compare_digest(str(data.get("password", "")).encode(), pw.encode()):
            _tries.pop(ip, None)
            secure = "" if self.headers.get("x-local-dev") else " Secure;"
            return self._json(200, {"ok": True},
                              f"{COOKIE}={token(pw)}; Path=/; Max-Age={DAYS*86400}; HttpOnly;{secure} SameSite=Lax")
        _tries[ip] = [n + 1, t0]
        self._json(401, {"error": "That password isn't right."})
