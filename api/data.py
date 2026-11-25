"""
GET /api/data  ->  everything the dashboard needs, in one compact JSON.

Pulls straight from the ERP with child-table joins (one request per doctype, never
one request per order), runs the four pulls in parallel, and lets Vercel's CDN cache
the answer for 5 minutes (stale-while-revalidate keeps it instant after that).
?fresh=<anything> skips the CDN copy (the Refresh button).

Env: ERP_API_KEY, ERP_API_SECRET  (ERP_URL optional, defaults to https://erp.tenxyou.com)
"""
import datetime as dt, json, os, re, urllib.parse, urllib.request, gzip
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler

ERP = os.environ.get("ERP_URL", "https://erp.tenxyou.com").rstrip("/")
CH = ["Myntra", "Flipkart", "Amazon", "Scapia"]
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def frappe_list(doctype, filters, fields, limit=500000):
    q = {"limit_page_length": limit, "fields": json.dumps(fields)}
    if filters:
        q["filters"] = json.dumps(filters)
    url = f"{ERP}/api/resource/{urllib.parse.quote(doctype)}?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers={
        "Authorization": f"token {os.environ['ERP_API_KEY']}:{os.environ['ERP_API_SECRET']}",
        "Accept": "application/json", "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=50) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return json.loads(raw).get("data", [])


def start_date(now):
    """Start of the financial year (1 Apr), or the start of last month if that is earlier (MTD comparison)."""
    fy = dt.date(now.year if now.month >= 4 else now.year - 1, 4, 1)
    pm = dt.date(now.year - 1, 12, 1) if now.month == 1 else dt.date(now.year, now.month - 1, 1)
    return min(fy, pm).isoformat()


def clean_col(c):
    c = (c or "").strip().rstrip("_")
    c = re.sub(r"_NA$", "", c)
    return c.replace("_", " / ") or "—"


def cat(h):
    h = str(h or "")
    return "Footwear" if h.startswith("64") else "Apparel" if h[:2] in ("61", "62", "63") else "Accessories"


def alloc(rows):
    """Spread each order's grand total (incl. GST) over its lines in proportion to line amount."""
    s = defaultdict(float)
    for r in rows:
        s[r["name"]] += r["amount"] or 0
    for r in rows:
        tot = s[r["name"]]
        r["val"] = round((r["grand_total"] or 0) * ((r["amount"] or 0) / tot) if tot else 0, 2)


def build():
    now = dt.datetime.now(IST)
    since = start_date(now)
    F = ["name", "creation", "transaction_date", "status", "custom_channel", "grand_total",
         "`tabSales Order Item`.item_code as item_code", "`tabSales Order Item`.qty as qty",
         "`tabSales Order Item`.amount as amount"]
    FI = ["name", "posting_date", "customer", "grand_total", "po_no", "status",
          "`tabSales Invoice Item`.item_code as item_code", "`tabSales Invoice Item`.qty as qty",
          "`tabSales Invoice Item`.amount as amount", "`tabSales Invoice Item`.sales_order as so"]
    jobs = {
        "drop": ("Sales Order", [["transaction_date", ">=", since], ["custom_channel", "in", CH]], F),
        # POs = what we billed: every submitted Sales Invoice to a registered (B2B) customer, with or without a Sales Order
        "inv": ("Sales Invoice", [["posting_date", ">=", since], ["gst_category", "=", "Registered Regular"],
                                  ["docstatus", "=", 1], ["is_return", "=", 0], ["status", "!=", "Internal Transfer"]], FI),
        "items": ("Item", None, ["item_code", "item_name", "custom_color", "custom_size", "custom_website_item_name", "gst_hsn_code"]),
        "bars": ("Item", None, ["item_code", "`tabItem Barcode`.barcode as barcode"]),
    }
    with ThreadPoolExecutor(4) as ex:
        fut = {k: ex.submit(frappe_list, *v) for k, v in jobs.items()}
        res = {k: f.result() for k, f in fut.items()}
    drop, inv = res["drop"], [r for r in res["inv"] if "srt10" not in (r["customer"] or "").lower()]
    items = {i["item_code"]: i for i in res["items"]}
    gt = {}
    for b in res["bars"]:
        v = (b.get("barcode") or "").strip()
        if v.isdigit() and 12 <= len(v) <= 14 and b["item_code"] not in gt:
            gt[b["item_code"]] = v
    ilist, iidx = [], {}

    def item(code):
        if code in iidx:
            return iidx[code]
        it = items.get(code, {})
        w = it.get("custom_website_item_name")
        prod = ((w.split("/")[0] if w else it.get("item_name")) or code or "Unknown item").strip()
        iidx[code] = len(ilist)
        ilist.append([code, prod, clean_col(it.get("custom_color")), str(it.get("custom_size") or "—"),
                      cat(it.get("gst_hsn_code")), gt.get(code, "")])
        return iidx[code]

    alloc(drop)
    alloc(inv)
    oidx, D = {}, []
    for r in drop:
        o = oidx.setdefault(r["name"], len(oidx))
        D.append([r["transaction_date"], CH.index(r["custom_channel"]), int(r["creation"][11:13]),
                  item(r["item_code"] or "(no item code)"), r["qty"], r["val"], 1 if r["status"] == "Cancelled" else 0, o])
    pos, P, L = {}, [], []
    for r in inv:
        if r["name"] not in pos:
            pos[r["name"]] = len(P)
            P.append([r["posting_date"], 4, r["name"], (r["customer"] or "").split("\t")[0].strip(), r["status"],
                      (r["po_no"] or "").strip(), 0, 0, "", ""])
        p = pos[r["name"]]
        if r.get("so") and r["so"] not in P[p][8].split(","):
            P[p][8] = (P[p][8] + "," + r["so"]).strip(",")
        P[p][6] += r["qty"]
        P[p][7] += r["val"]
        L.append([p, item(r["item_code"] or "(no item code)"), r["qty"], r["val"]])
    for p in P:
        p[7] = round(p[7], 2)
    return {"asof": now.strftime("%Y-%m-%d %H:%M"), "since": since, "channels": CH,
            "items": ilist, "drop": D, "po": P, "poLines": L}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            body = json.dumps(build(), separators=(",", ":")).encode()
            code, cache = 200, "public, max-age=0, s-maxage=300, stale-while-revalidate=86400"
        except Exception as e:  # never cache a failure
            body = json.dumps({"error": f"ERP pull failed: {type(e).__name__}"}).encode()
            code, cache = 502, "no-store"
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", cache)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
