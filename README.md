# Ten x You Marketplace Sales (Vercel)

Static dashboard (`index.html`, `login.html`) plus three Python functions:

| Path | What it does |
|---|---|
| `api/data.py` | Pulls dropship Sales Orders and B2B Sales Invoices from the ERP, 4 queries in parallel (~2 s). CDN-cached 5 min. |
| `api/login.py` | Checks the password and sets a 30-day sign-in cookie. `?logout=1` signs out. |
| `api/customers.py` | The shared customer list for each POs tab, stored in Postgres (Neon). |
| `middleware.js` | Locks every page and API behind the sign-in. |

## Environment variables (Vercel → Project → Settings → Environment Variables)

| Name | Value |
|---|---|
| `SITE_PASSWORD` | The team password. Change it any time and redeploy: everyone gets signed out. |
| `ERP_API_KEY` | ERP API key (same one the ERP connector uses) |
| `ERP_API_SECRET` | ERP API secret |
| `DATABASE_URL` | Added automatically when you connect a Neon database (Storage tab) |

Without `SITE_PASSWORD` the site stays locked and says so. Without a database the customer lists show the defaults and can't be changed.

## Deploy

1. Create an empty private GitHub repo and push this folder to it.
2. Vercel → Add New → Project → import the repo. Framework preset: **Other**. No build command. Deploy.
3. Add `SITE_PASSWORD`, `ERP_API_KEY`, `ERP_API_SECRET` under Settings → Environment Variables (Production, Preview).
4. Storage → Create Database → **Neon** (Postgres) → connect to this project.
5. Deployments → ⋯ on the latest → **Redeploy** so the new variables take effect.

## Local

```
python -I dev_server.py        # http://localhost:8791, password "localtest"
python -I make_app.py          # rebuild index.html after editing src/head.part or src/script.part
```
