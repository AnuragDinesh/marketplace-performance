// Password gate for the whole site (Vercel Routing Middleware, runs before every request).
// The password is the SITE_PASSWORD environment variable set in Vercel; nothing is hard-coded.
// Signed-in browsers carry a cookie holding an HMAC of the password, so changing the
// password in Vercel signs everyone out.

export const config = {
  matcher: ['/((?!login\\.html|api/login|favicon\\.svg|robots\\.txt).*)'],
};

async function token(pw) {
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey('raw', enc.encode(pw), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const sig = await crypto.subtle.sign('HMAC', key, enc.encode('mpsales-v1'));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

export default async function middleware(request) {
  const url = new URL(request.url);
  const pw = (typeof process !== 'undefined' && process.env && process.env.SITE_PASSWORD) || '';
  if (!pw) {
    return new Response('This dashboard has no password yet. Add SITE_PASSWORD in Vercel (Settings > Environment Variables) and redeploy.', {
      status: 503, headers: { 'content-type': 'text/plain; charset=utf-8' },
    });
  }
  const m = (request.headers.get('cookie') || '').match(/(?:^|;\s*)mps_auth=([a-f0-9]{64})/);
  if (m && m[1] === (await token(pw))) return; // signed in: carry on to the page or API
  if (url.pathname.startsWith('/api/')) {
    return new Response(JSON.stringify({ error: 'login' }), { status: 401, headers: { 'content-type': 'application/json' } });
  }
  const next = url.pathname === '/' ? '' : '?next=' + encodeURIComponent(url.pathname + url.search);
  return Response.redirect(new URL('/login.html' + next, url), 302);
}
