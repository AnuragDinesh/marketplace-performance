"""Local stand-in for Vercel: static files + the password gate + /api/* functions.

    set SITE_PASSWORD=anything      (optional, defaults to "localtest")
    python -I dev_server.py          ->  http://localhost:8791

ERP keys come from ERP_API_KEY / ERP_API_SECRET, or locally from Documents\\tenxyou_erp_mcp.py.
Customer lists go to local-customers.db (SQLite) unless DATABASE_URL is set.
"""
import hashlib, hmac, importlib.util, mimetypes, os, re, sys
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("SITE_PASSWORD", "localtest")
if not os.environ.get("ERP_API_KEY"):
    sys.path.insert(0, os.path.join(os.path.expanduser("~"), "Documents"))
    import tenxyou_erp_mcp as erp  # local only; never deployed
    os.environ["ERP_API_KEY"], os.environ["ERP_API_SECRET"] = erp.API_KEY, erp.API_SECRET
OPEN = re.compile(r"^/(login\.html|api/login|favicon\.svg|robots\.txt)")
MODS = {}


def api(name):
    if name not in MODS:
        spec = importlib.util.spec_from_file_location("api_" + name, os.path.join(HERE, "api", name + ".py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        MODS[name] = m
    return MODS[name]


class Dev(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=HERE, **k)

    def gate(self):
        path = self.path.split("?")[0]
        if OPEN.match(path):
            return True
        pw = os.environ["SITE_PASSWORD"]
        m = re.search(r"(?:^|;\s*)mps_auth=([a-f0-9]{64})", self.headers.get("Cookie") or "")
        if m and m.group(1) == hmac.new(pw.encode(), b"mpsales-v1", hashlib.sha256).hexdigest():
            return True
        if path.startswith("/api/"):
            self.send_response(401); self.send_header("Content-Type", "application/json"); self.end_headers()
            self.wfile.write(b'{"error":"login"}')
        else:
            self.send_response(302); self.send_header("Location", "/login.html"); self.end_headers()
        return False

    def route(self, verb):
        if not self.gate():
            return
        path = self.path.split("?")[0]
        if path.startswith("/api/"):
            name = path[5:].strip("/")
            if not os.path.exists(os.path.join(HERE, "api", name + ".py")):
                self.send_error(404); return
            self.headers["x-local-dev"] = "1"
            self.__class__ = type("H", (api(name).handler,), {})
            return getattr(self, "do_" + verb)()
        if verb == "GET":
            if path.endswith((".py", ".db", ".part")) or "/src/" in path:
                self.send_error(404); return
            return super().do_GET()
        self.send_error(405)

    def do_GET(self): self.route("GET")
    def do_POST(self): self.route("POST")

    def end_headers(self):
        if self.path.endswith(".html") or self.path in ("/", ""):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8791"))
    print(f"http://localhost:{port}  (password: SITE_PASSWORD, default 'localtest')")
    ThreadingHTTPServer(("127.0.0.1", port), Dev).serve_forever()
