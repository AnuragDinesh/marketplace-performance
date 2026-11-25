"""Build index.html for Vercel from src/head.part + src/script.part (the same source as the Claude preview).

Changes for the live site: real HTML skeleton, data from /api/data (CDN-cached, auto-refresh),
shared customer lists via /api/customers, sign-out button. Run:  python -I make_app.py
"""
import os
here = os.path.dirname(os.path.abspath(__file__))
h = open(os.path.join(here, "src", "head.part"), encoding="utf-8").read()
s = open(os.path.join(here, "src", "script.part"), encoding="utf-8").read()


def rep(src, o, n):
    assert src.count(o) == 1, (src.count(o), o[:90])
    return src.replace(o, n)


# ---- head: proper document + sign out
h = h.replace('<meta name="claude:viewport-fit-sides" content="cover">\n', "")
h = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
     '<meta name="viewport" content="width=device-width, initial-scale=1">\n<meta name="robots" content="noindex">\n'
     '<link rel="icon" href="/favicon.svg" type="image/svg+xml">\n' + h)
h = rep(h, "</style>\n", "</style>\n</head>\n<body>\n")
h = rep(h, '<button class="btn" id="theme" type="button">☾ Dark</button>',
        '<button class="btn" id="theme" type="button">☾ Dark</button><a class="btn" href="/api/login?logout=1" style="text-decoration:none">Sign out</a>')

# ---- data from the API; prefs restored once; CDN copy refreshed when it is stale
s = rep(s, 'async function load(force){\n  $("#asof").textContent="Refreshing…";\n  try{const r=await fetch("data.json"+(force?"?t="+Date.now():""));if(!r.ok)throw 0;D=await r.json()}catch(e){',
        'let BOOTED=false,LOADING=false;\nasync function load(force,quiet){if(LOADING)return;LOADING=true;\n  if(!quiet||!D)$("#asof").textContent="Refreshing…";\n  try{const r=await fetch("/api/data"+(force?"?fresh="+Date.now():""));if(r.status===401){location.replace("/login.html");return}if(!r.ok)throw 0;D=await r.json();await loadCust()}catch(e){LOADING=false;if(D&&quiet){$("#asof").textContent="ERP data as of "+fmtD(ASOF_D)+", "+ASOF.slice(11)+" · update failed";return}')
s = rep(s, '  if(!force){try{const s=JSON.parse(localStorage.getItem("mpsales2")',
        '  LOADING=false;\n  if(!BOOTED){BOOTED=true;try{const s=JSON.parse(localStorage.getItem("mpsales2")')
s = rep(s, '$("#dFrom").min=$("#dTo").min="2026-04-01";', '$("#dFrom").min=$("#dTo").min=D.since||"2026-04-01";')
s = rep(s, "  render();\n}\nload();\n</script>",
        '''  render();
  // The CDN may hand back a copy up to a day old (instant), so if it is more than 10 minutes old pull a fresh one now.
  const age=(Date.now()-new Date(ASOF.replace(" ","T")+":00+05:30"))/6e4;if(age>10&&!force)load(true,true);
}
load();
setInterval(()=>{if(!document.hidden)load(false,true)},5*60*1000);
document.addEventListener("visibilitychange",()=>{if(!document.hidden&&D&&(Date.now()-new Date(ASOF.replace(" ","T")+":00+05:30"))/6e4>10)load(true,true)});
</script>
</body>
</html>''')

# ---- shared customer lists (Postgres via /api/customers), never browser storage
s = rep(s, 'collapsed:S.collapsed,cust:S.cust,hm:S.hm}', 'collapsed:S.collapsed,hm:S.hm}')
s = rep(s, 'if(s.cust&&typeof s.cust==="object")S.cust=Object.assign(S.cust,s.cust);else if(Array.isArray(s.others))S.cust[4]=s.others;', '')
s = rep(s, 'function addCustomer(){',
        '''let CUST_SHARED=true;
async function loadCust(){try{const r=await fetch("/api/customers");if(r.ok){const j=await r.json();S.cust={};for(const k in j.cust)S.cust[+k]=j.cust[k];CUST_SHARED=j.shared!==false}}catch(e){}}
async function saveCust(ch,name,action){const r=await fetch("/api/customers",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({ch,name,action})});const j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(j.error||"Couldn't save");S.cust={};for(const k in j.cust)S.cust[+k]=j.cust[k]}
async function addCustomer(){''')
s = rep(s, '  const ch=curCh();const list=S.cust[ch]||(S.cust[ch]=[]);if(list.some(n=>norm(n)===norm(v)))return fail(`${v} is already in this list.`);\n  const k=poCount(v);\n  list.push(v);render();',
        '  const ch=curCh();const list=S.cust[ch]||[];if(list.some(n=>norm(n)===norm(v)))return fail(`${v} is already in this list.`);\n  const k=poCount(v);\n  try{await saveCust(ch,v,"add")}catch(e){return fail(e.message)}render();')
s = rep(s, 'if(d.rmc){const ch=curCh();S.cust[ch]=(S.cust[ch]||[]).filter(n=>n!==d.rmc);render();toast(`Removed ${d.rmc}`);return}',
        'if(d.rmc){const ch=curCh(),n=d.rmc;saveCust(ch,n,"remove").then(()=>{render();toast(`Removed ${n}`)}).catch(e=>toast(e.message));return}')
i = s.index("On the live site this list is shared")
j = s.index("</p>", i)
s = s[:i] + '${CUST_SHARED?"Everyone using the dashboard sees and edits the same list.":"Shared storage isn\'t connected yet, so this list can\'t be changed."}' + s[j:]

open(os.path.join(here, "index.html"), "w", encoding="utf-8").write(h + s)
print("index.html", len(h + s) // 1024, "KB")
