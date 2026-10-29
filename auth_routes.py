"""مسارات aiohttp لتسجيل الدخول بديسكورد — طبقة رقيقة فوق auth.py (كل المنطق والأمان هناك)."""
import time

import aiohttp
from aiohttp import web

import auth

DISCORD_API = "https://discord.com/api/v10"
USER_AGENT = "DiscordBot (youcef-alpacino-site, 1.0)"
PAGE_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                               "base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
}


class DiscordHTTP:
    """عميل Discord الحقيقي (تبديل الرمز + قراءة الحساب). api_base قابل للتغيير للاختبار بخادم وهمي."""

    def __init__(self, client_id, client_secret, api_base=DISCORD_API, timeout=10):
        self.client_id, self.client_secret = client_id, client_secret
        self.api_base = api_base.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout)

    async def exchange_code(self, code, redirect_uri):
        form = {"client_id": self.client_id, "client_secret": self.client_secret, "grant_type": "authorization_code",
                "code": code, "redirect_uri": redirect_uri}
        async with aiohttp.ClientSession(timeout=self.timeout, headers={"User-Agent": USER_AGENT}) as session:
            async with session.post(f"{self.api_base}/oauth2/token", data=form) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"token exchange failed ({resp.status})")
                data = await resp.json(content_type=None)
        token = data.get("access_token") if isinstance(data, dict) else None
        if not token:
            raise RuntimeError("token exchange returned no access_token")
        return token

    async def fetch_user(self, access_token):
        headers = {"User-Agent": USER_AGENT, "Authorization": f"Bearer {access_token}"}
        async with aiohttp.ClientSession(timeout=self.timeout, headers=headers) as session:
            async with session.get(f"{self.api_base}/users/@me") as resp:
                if resp.status != 200:
                    raise RuntimeError(f"user lookup failed ({resp.status})")
                return await resp.json(content_type=None)


def _forwarded(request, header, fallback):
    return (request.headers.get(header) or fallback).split(",")[0].strip()


def _is_https(request):
    return _forwarded(request, "X-Forwarded-Proto", request.scheme) == "https"


def _respond(spec):
    headers = dict(PAGE_HEADERS)
    if spec.get("location"):
        headers["Location"] = spec["location"]
        return web.Response(status=spec["status"], headers=headers)
    return web.Response(status=spec["status"], text=spec["html"], content_type="text/html", headers=headers)


def register(app, cfg, *, member_check, discord_api=None, clock=time.time):
    """يضيف مسارات الدخول إلى تطبيق aiohttp. member_check(user_id) ← True/False/None (None = تعذّر التحقق)."""
    api = discord_api or DiscordHTTP(cfg.client_id, cfg.client_secret)
    check = auth.MemberCache(member_check)

    def redirect_uri(request):
        return auth.resolve_redirect_uri(cfg, _forwarded(request, "X-Forwarded-Proto", request.scheme),
                                         _forwarded(request, "X-Forwarded-Host", request.host))

    async def status(request):
        return web.json_response({"ok": True, "enabled": cfg.enabled})

    async def start(request):
        q = request.query
        try:
            url, nonce = auth.begin_login(cfg, origin=q.get("origin", ""), return_url=q.get("return", ""),
                                          mode=q.get("mode", "popup"), redirect_uri=redirect_uri(request), now=clock())
        except auth.AuthError as exc:
            return _respond(auth.error_response(exc.code))
        resp = web.Response(status=302, headers={**PAGE_HEADERS, "Location": url})
        resp.set_cookie(auth.COOKIE_NAME, nonce, max_age=auth.STATE_TTL, path=auth.COOKIE_PATH,
                        secure=_is_https(request), httponly=True, samesite="Lax")
        return resp

    async def callback(request):
        outcome = await auth.complete_login(cfg, dict(request.query), request.cookies.get(auth.COOKIE_NAME, ""),
                                            redirect_uri(request), api, check, now=clock())
        resp = _respond(auth.outcome_to_response(outcome))
        resp.del_cookie(auth.COOKIE_NAME, path=auth.COOKIE_PATH)
        return resp

    async def me(request):
        code, body = await auth.whoami(cfg, request.headers.get("Authorization", ""), check, now=clock())
        return web.json_response(body, status=code)

    app.router.add_get("/auth/discord/status", status)
    app.router.add_get(auth.START_PATH, start)
    app.router.add_get(auth.CALLBACK_PATH, callback)
    app.router.add_get("/api/me", me)
