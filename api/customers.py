"""
Shared customer lists for the POs tabs (which ERP customer names count as each marketplace's POs).

GET  /api/customers                          -> {"cust": {"0": [...], "1": [...], "2": [...], "4": [...]}, "shared": true}
POST /api/customers {"ch": 2, "name": "Cocoblu", "action": "add" | "remove"}

Stored in Postgres (Vercel Storage -> Neon: DATABASE_URL or POSTGRES_URL), so everyone sees
the same list. Locally (no database URL) it uses a SQLite file. On Vercel without a database
the defaults are shown and changes are refused, rather than kept in one browser.
"""
import hashlib, hmac, json, os, re, ssl, urllib.parse
from http.server import BaseHTTPRequestHandler

DB_URL = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or ""
ON_VERCEL = bool(os.environ.get("VERCEL"))
DEFAULTS = {0: ["Myntra Jabong"], 1: ["Flipkart India"], 2: ["Cocoblu"], 4: ["Reliance Retail", "Block Pool"]}
VALID_CH = {0, 1, 2, 4}


def authed(headers):
    pw = os.environ.get("SITE_PASSWORD", "")
    m = re.search(r"(?:^|;\s*)mps_auth=([a-f0-9]{64})", headers.get("Cookie") or "")
    return bool(pw and m and hmac.compare_digest(m.group(1), hmac.new(pw.encode(), b"mpsales-v1", hashlib.sha256).hexdigest()))


def connect():
    if DB_URL:
        import pg8000.dbapi
        u = urllib.parse.urlparse(DB_URL)
        c = pg8000.dbapi.connect(
            user=urllib.parse.unquote(u.username or ""), password=urllib.parse.unquote(u.password or ""),
            host=u.hostname, port=u.port or 5432, database=(u.path or "/postgres").lstrip("/") or "postgres",
            ssl_context=ssl.create_default_context(), timeout=15)
        return c, "%s"
    import sqlite3
    return sqlite3.connect(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "local-customers.db")), "?"


def with_db(fn):
    c, ph = connect()
    try:
        cur = c.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS mps_customers (ch INTEGER NOT NULL, name TEXT NOT NULL, added_at TEXT, PRIMARY KEY (ch, name))")
        cur.execute("CREATE TABLE IF NOT EXISTS mps_meta (k TEXT PRIMARY KEY, v TEXT)")
        cur.execute("SELECT v FROM mps_meta WHERE k='seeded'")
        if not cur.fetchall():
            for ch, names in DEFAULTS.items():
                for n in names:
                    cur.execute(f"INSERT INTO mps_customers (ch, name, added_at) VALUES ({ph},{ph},'default')", (ch, n))
            cur.execute("INSERT INTO mps_meta (k, v) VALUES ('seeded','1')")
        out = fn(cur, ph)
        c.commit()
        return out
    finally:
        c.close()


def read_all(cur, ph):
    cur.execute("SELECT ch, name FROM mps_customers ORDER BY name")
    d = {str(k): [] for k in VALID_CH}
    for ch, name in cur.fetchall():
        d.setdefault(str(ch), []).append(name)
    return d


class handler(BaseHTTPRequestHandler):
    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not authed(self.headers):
            return self._json(401, {"error": "login"})
        if ON_VERCEL and not DB_URL:
            return self._json(200, {"cust": {str(k): v for k, v in DEFAULTS.items()}, "shared": False})
        try:
            self._json(200, {"cust": with_db(read_all), "shared": True})
        except Exception as e:
            self._json(500, {"error": f"Couldn't read the customer list ({type(e).__name__})"})

    def do_POST(self):
        if not authed(self.headers):
            return self._json(401, {"error": "login"})
        if ON_VERCEL and not DB_URL:
            return self._json(503, {"error": "Shared storage isn't connected yet. Connect a Neon database in Vercel → Storage, then redeploy."})
        try:
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            ch, name, action = int(data.get("ch")), re.sub(r"\s+", " ", str(data.get("name", ""))).strip(), data.get("action")
        except (ValueError, TypeError):
            return self._json(400, {"error": "Bad request"})
        if ch not in VALID_CH or not name or len(name) > 120 or action not in ("add", "remove"):
            return self._json(400, {"error": "Bad request"})

        def op(cur, ph):
            if action == "add":
                cur.execute(f"SELECT 1 FROM mps_customers WHERE ch={ph} AND lower(name)=lower({ph})", (ch, name))
                if not cur.fetchall():
                    cur.execute(f"INSERT INTO mps_customers (ch, name, added_at) VALUES ({ph},{ph},CURRENT_TIMESTAMP)", (ch, name))
            else:
                cur.execute(f"DELETE FROM mps_customers WHERE ch={ph} AND name={ph}", (ch, name))
            return read_all(cur, ph)
        try:
            self._json(200, {"cust": with_db(op), "shared": True})
        except Exception as e:
            self._json(500, {"error": f"Couldn't save ({type(e).__name__})"})
