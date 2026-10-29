"""منطق تسجيل الدخول بحساب Discord — صرف (بدون discord أو aiohttp) وقابل للاختبار بسهولة.

التدفق: الموقع يفتح /auth/discord/start ← Discord ← /auth/discord/callback ← يتحقق البوت من العضوية
← جلسة موقّعة بـ HMAC تعود للموقع (postMessage في النافذة المنبثقة، أو #ya_auth في الرابط عند التحويل).
لا يُخزَّن أي شيء على الخادم: الجلسة والـ state رموز موقّعة ولها مدة انتهاء.
"""
import base64
import hashlib
import hmac
import html
import json
import logging
import re
import secrets
import time
from dataclasses import dataclass, field
from urllib.parse import urlencode, urlsplit, urlunsplit

import site_api

log = logging.getLogger("loup-garou.auth")

START_PATH = "/auth/discord/start"
CALLBACK_PATH = "/auth/discord/callback"
AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
COOKIE_NAME = "ya_oauth"
COOKIE_PATH = "/auth/discord"
STATE_TTL = 600                      # 10 دقائق لإتمام الدخول
MODES = ("popup", "redirect")
MESSAGE_TYPE = "youcef-discord-auth"  # نوع الرسالة التي يستقبلها الموقع
MIN_SECRET_LEN = 32
_ID_RE = re.compile(r"^\d{5,25}$")
_BAD_CHARS = re.compile(r"[\s\x00-\x1f\x7f\\]")

# رمز الخطأ ← (حالة HTTP، رسالة للمستخدم)
ERRORS = {
    "disabled": (503, "تسجيل الدخول بديسكورد غير مفعّل على هذا الخادم بعد."),
    "bad_origin": (400, "هذا الموقع غير مسموح له باستخدام تسجيل الدخول."),
    "bad_request": (400, "طلب غير صالح."),
    "bad_state": (400, "محاولة الدخول غير صالحة أو انتهت صلاحيتها. أغلق النافذة وجرّب مرة أخرى."),
    "denied": (403, "تم إلغاء تسجيل الدخول أو رفضه في ديسكورد."),
    "not_member": (403, "يجب أن تكون عضوًا في سيرفر المجتمع على ديسكورد قبل تسجيل الدخول."),
    "unavailable": (503, "تعذّر التحقق من عضويتك الآن (البوت غير جاهز). جرّب بعد دقيقة."),
    "failed": (502, "تعذّر إكمال تسجيل الدخول مع ديسكورد. جرّب مرة أخرى."),
}


class AuthError(Exception):
    def __init__(self, code, message=""):
        super().__init__(message or code)
        self.code = code


# ───────────────────────── رموز موقّعة (HMAC-SHA256) ─────────────────────────
def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode((text + "=" * (-len(text) % 4)).encode("ascii"))


def _mac(purpose: str, body: str, secret: str) -> bytes:
    return hmac.new(secret.encode("utf-8"), f"{purpose}.{body}".encode("ascii"), hashlib.sha256).digest()


def sign(purpose: str, payload: dict, secret: str) -> str:
    """purpose يفصل بين أنواع الرموز: رمز state لا يصلح كجلسة والعكس."""
    body = _b64e(json.dumps(payload, separators=(",", ":"), ensure_ascii=False, sort_keys=True).encode("utf-8"))
    return f"v1.{body}.{_b64e(_mac(purpose, body, secret))}"


def verify(purpose: str, token, secret: str, now=None):
    """يعيد الحمولة إن كان التوقيع سليمًا ولم تنتهِ مدته، وإلا None."""
    now = time.time() if now is None else now
    try:
        version, body, mac = str(token or "").split(".")
        if version != "v1":
            return None
        if not hmac.compare_digest(_b64e(_mac(purpose, body, secret)).encode("ascii"), mac.encode("utf-8")):
            return None
        payload = json.loads(_b64d(body))
        exp = payload.get("exp") if isinstance(payload, dict) else None
        if isinstance(exp, bool) or not isinstance(exp, (int, float)) or exp <= now:
            return None
        return payload
    except (ValueError, TypeError, UnicodeError, AttributeError):
        return None


# ───────────────────────── الأصول والروابط ─────────────────────────
def normalize_origin(value):
    """'https://Site.blogspot.com/' ← 'https://site.blogspot.com' ، أو None إن لم يكن أصلًا صالحًا."""
    text = str(value or "").strip()
    if not text or _BAD_CHARS.search(text):
        return None
    try:
        parts = urlsplit(text)
        host, port = parts.hostname, parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https") or not host or ":" in host:
        return None
    if parts.username or parts.password or parts.query or parts.fragment or parts.path not in ("", "/"):
        return None
    default = (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
    return f"{scheme}://{host.lower()}" + (f":{port}" if port and not default else "")


def safe_return_url(url, origin):
    """رابط العودة يجب أن يكون من نفس أصل الموقع تمامًا (يمنع التحويل إلى مواقع أخرى)."""
    text = str(url or "").strip()
    if not text or len(text) > 300 or _BAD_CHARS.search(text):
        return None
    try:
        parts = urlsplit(text)
        if parts.username or parts.password:
            return None
        if normalize_origin(f"{parts.scheme}://{parts.netloc}") != origin:
            return None
    except ValueError:
        return None
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", parts.query, ""))


def resolve_redirect_uri(cfg, scheme: str, host: str) -> str:
    if cfg.redirect_uri:
        return cfg.redirect_uri
    if cfg.public_base_url:
        return cfg.public_base_url.rstrip("/") + CALLBACK_PATH
    return f"{scheme}://{host}{CALLBACK_PATH}"


# ───────────────────────── الإعدادات ─────────────────────────
@dataclass(frozen=True)
class AuthConfig:
    client_id: str = ""
    client_secret: str = ""
    session_secret: str = ""
    guild_id: int = 0
    origins: tuple = ()          # أصول الموقع المسموحة (بعد التطبيع)
    wildcard: bool = False       # SITE_ORIGINS=* ← يُعطَّل الدخول (أمان)
    redirect_uri: str = ""
    public_base_url: str = ""
    session_days: int = 7

    @classmethod
    def from_env(cls, env, *, guild_id=0, origins=()):
        def get(key):
            return str(env.get(key, "") or "").strip()
        try:
            days = int(get("SESSION_DAYS") or 7)
        except ValueError:
            days = 7
        normalized, wildcard = [], False
        for item in origins or ():
            if item == "*":
                wildcard = True
            elif normalize_origin(item):
                normalized.append(normalize_origin(item))
        return cls(client_id=get("DISCORD_CLIENT_ID"), client_secret=get("DISCORD_CLIENT_SECRET"),
                   session_secret=get("SESSION_SECRET"), guild_id=int(guild_id or 0),
                   origins=tuple(dict.fromkeys(normalized)), wildcard=wildcard,
                   redirect_uri=get("OAUTH_REDIRECT_URI"), public_base_url=get("RENDER_EXTERNAL_URL"),
                   session_days=max(1, min(days, 30)))

    def problems(self):
        """أسباب تعطّل الدخول (نصوص آمنة للسجل، لا تحتوي أي قيمة سرية)."""
        out = []
        if not self.client_id:
            out.append("DISCORD_CLIENT_ID غير مضبوط")
        if not self.client_secret:
            out.append("DISCORD_CLIENT_SECRET غير مضبوط")
        if len(self.session_secret) < MIN_SECRET_LEN:
            out.append(f"SESSION_SECRET غير مضبوط أو أقصر من {MIN_SECRET_LEN} حرفًا")
        if not self.guild_id:
            out.append("GUILD_ID غير مضبوط")
        if self.wildcard:
            out.append("SITE_ORIGINS=* — حدّد رابط موقعك بدل * (وإلا يستطيع أي موقع استلام جلسات الدخول)")
        elif not self.origins:
            out.append("SITE_ORIGINS لا يحتوي أي رابط موقع صالح")
        if self.redirect_uri and not self.redirect_uri.startswith(("https://", "http://localhost", "http://127.0.0.1")):
            out.append("OAUTH_REDIRECT_URI يجب أن يبدأ بـ https://")
        return out

    @property
    def enabled(self) -> bool:
        return not self.problems()


# ───────────────────────── ملف المستخدم ─────────────────────────
def avatar_url(user: dict) -> str:
    uid, avatar = str(user.get("id", "")), str(user.get("avatar") or "")
    if uid and re.fullmatch(r"[A-Za-z0-9_]{1,64}", avatar):
        return f"https://cdn.discordapp.com/avatars/{uid}/{avatar}.{'gif' if avatar.startswith('a_') else 'png'}?size=128"
    disc = str(user.get("discriminator") or "0")
    try:
        index = (int(uid) >> 22) % 6 if disc == "0" else int(disc) % 5
    except ValueError:
        index = 0
    return f"https://cdn.discordapp.com/embed/avatars/{index}.png"


def display_name(user: dict) -> str:
    return site_api.clean(user.get("global_name") or user.get("username") or "", 40) or "لاعب"


# ───────────────────────── بدء الدخول ─────────────────────────
def begin_login(cfg, *, origin, redirect_uri, return_url="", mode="popup", now=None):
    """يعيد (رابط Discord، nonce للكوكي) أو يرفع AuthError."""
    now = time.time() if now is None else now
    if not cfg.enabled:
        raise AuthError("disabled")
    site = normalize_origin(origin)
    if not site or site not in cfg.origins:
        raise AuthError("bad_origin")
    if mode not in MODES:
        raise AuthError("bad_request")
    nonce = secrets.token_urlsafe(24)
    state = sign("state", {"n": nonce, "o": site, "m": mode, "r": safe_return_url(return_url, site) or site + "/",
                           "exp": int(now) + STATE_TTL}, cfg.session_secret)
    query = urlencode({"client_id": cfg.client_id, "response_type": "code", "redirect_uri": redirect_uri,
                       "scope": "identify", "state": state, "prompt": "none"})
    return f"{AUTHORIZE_URL}?{query}", nonce


# ───────────────────────── إنهاء الدخول ─────────────────────────
@dataclass
class LoginOutcome:
    ok: bool
    error: str = ""
    origin: str = ""        # لا يُملأ إلا من state صالح وموقّع (أي موثوق)
    return_url: str = ""
    mode: str = "popup"
    token: str = ""
    user: dict = field(default_factory=dict)
    expires_at: int = 0


async def complete_login(cfg, query, cookie_nonce, redirect_uri, discord_api, member_check, now=None):
    now = time.time() if now is None else now
    if not cfg.enabled:
        return LoginOutcome(False, "disabled")
    state = verify("state", query.get("state", ""), cfg.session_secret, now)
    nonce = str(cookie_nonce or "")
    if not state or not nonce or not hmac.compare_digest(nonce.encode("utf-8"), str(state.get("n", "")).encode("utf-8")):
        return LoginOutcome(False, "bad_state")
    origin = str(state.get("o", ""))
    if origin not in cfg.origins:          # أُزيل الموقع من SITE_ORIGINS بعد بدء المحاولة
        return LoginOutcome(False, "bad_state")
    mode = state.get("m") if state.get("m") in MODES else "popup"
    return_url = safe_return_url(state.get("r", ""), origin) or origin + "/"

    def fail(code):
        return LoginOutcome(False, code, origin=origin, return_url=return_url, mode=mode)

    if query.get("error"):
        return fail("denied")
    code = str(query.get("code", ""))
    if not code or len(code) > 512:
        return fail("failed")
    try:
        access_token = await discord_api.exchange_code(code, redirect_uri)
        user = await discord_api.fetch_user(access_token)
    except Exception as exc:                # noqa: BLE001 — أي فشل شبكة/Discord يعني فشل الدخول
        log.warning("Discord OAuth failed: %s: %s", type(exc).__name__, str(exc)[:200])
        return fail("failed")
    user = user if isinstance(user, dict) else {}
    uid = str(user.get("id", ""))
    if not _ID_RE.match(uid):
        return fail("failed")
    try:
        member = await member_check(int(uid))
    except Exception:                       # noqa: BLE001
        log.exception("membership check crashed")
        member = None
    if member is False:
        return fail("not_member")
    if member is not True:
        return fail("unavailable")

    profile = {"id": uid, "name": display_name(user), "avatar_url": avatar_url(user)}
    expires = int(now) + cfg.session_days * 86400
    token = sign("session", {"sub": uid, "name": profile["name"], "av": profile["avatar_url"],
                             "iat": int(now), "exp": expires}, cfg.session_secret)
    return LoginOutcome(True, origin=origin, return_url=return_url, mode=mode, token=token, user=profile,
                        expires_at=expires)


# ───────────────────────── صفحات الرد ─────────────────────────
def _js(value) -> str:
    """JSON آمن للتضمين داخل <script> (يمنع إغلاق الوسم أو حقن HTML)."""
    return json.dumps(value).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


_CSS = ("body{margin:0;min-height:100vh;display:grid;place-items:center;background:#080b14;color:#f1f5f9;"
        "font:16px/1.8 system-ui,sans-serif;text-align:center;padding:24px}.box{max-width:420px}")


def _page(title, message, script=""):
    return ('<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="referrer" content="no-referrer">'
            f"<title>{html.escape(title)}</title><style>{_CSS}</style></head><body>"
            f'<div class="box"><h2>{html.escape(title)}</h2><p>{html.escape(message)}</p></div>{script}</body></html>')


def _post_script(origin, message, fallback_url):
    # النافذة المنبثقة ترسل النتيجة للموقع الذي فتحها فقط (targetOrigin). إن فُقدت window.opener
    # (بعض المتصفحات تقطعها أثناء المرور بـ Discord) نحوّل النافذة نفسها إلى الموقع برمز في #.
    return ("<script>(function(){var t=%s,m=%s,f=%s;try{if(window.opener&&!window.opener.closed){"
            "window.opener.postMessage(m,t);setTimeout(function(){window.close()},200);return}}catch(e){}"
            "location.replace(f)})();</script>" % (_js(origin), _js(message), _js(fallback_url)))


def error_response(code):
    status, message = ERRORS.get(code, ERRORS["failed"])
    return {"status": status, "html": _page("تعذّر تسجيل الدخول", message)}


def outcome_to_response(outcome: LoginOutcome) -> dict:
    """يحوّل النتيجة إلى وصف محايد: {status, html} أو {status, location}."""
    if not outcome.origin:                          # state غير موثوق: صفحة عادية بلا أي سكربت
        return error_response(outcome.error)
    if outcome.ok:
        fragment = "ya_auth=" + outcome.token
        message = {"type": MESSAGE_TYPE, "ok": True, "token": outcome.token, "expires_at": outcome.expires_at,
                   "user": outcome.user}
        page = _page("تم تسجيل الدخول", "تم تسجيل الدخول بنجاح. يمكنك إغلاق هذه النافذة.")
        status = 200
    else:
        fragment = "ya_auth_error=" + outcome.error
        message = {"type": MESSAGE_TYPE, "ok": False, "error": outcome.error}
        status, text = ERRORS.get(outcome.error, ERRORS["failed"])
        page = _page("تعذّر تسجيل الدخول", text)
    location = outcome.return_url + "#" + fragment
    if outcome.mode == "redirect":
        return {"status": 302, "location": location}
    script = _post_script(outcome.origin, message, location)
    return {"status": status, "html": page.replace("</body>", script + "</body>")}


# ───────────────────────── /api/me ─────────────────────────
def bearer_token(header) -> str:
    parts = str(header or "").strip().split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer" and 0 < len(parts[1]) <= 2048:
        return parts[1].strip()
    return ""


async def whoami(cfg, authorization, member_check, now=None):
    """(status, body). يعيد فحص العضوية في كل مرة، فمن غادر السيرفر تنتهي جلسته."""
    if not cfg.enabled:
        return 503, {"ok": False, "error": "disabled"}
    payload = verify("session", bearer_token(authorization), cfg.session_secret, now)
    if not payload or not _ID_RE.match(str(payload.get("sub", ""))):
        return 401, {"ok": False, "error": "unauthorized"}
    try:
        member = await member_check(int(payload["sub"]))
    except Exception:                       # noqa: BLE001
        log.exception("membership check crashed")
        member = None
    if member is False:
        return 403, {"ok": False, "error": "not_member"}
    if member is not True:
        return 503, {"ok": False, "error": "unavailable"}
    return 200, {"ok": True, "expires_at": site_api.iso(payload["exp"]),
                 "user": {"id": str(payload["sub"]), "name": str(payload.get("name") or "لاعب"),
                          "avatar_url": str(payload.get("av") or "")}}


class MemberCache:
    """يغلّف فحص العضوية: يحفظ النتيجة الإيجابية دقيقة واحدة فقط لتخفيف الطلبات إلى Discord."""

    def __init__(self, check, ttl=60, max_items=2000, clock=time.monotonic):
        self._check, self._ttl, self._max, self._clock = check, ttl, max_items, clock
        self._ok = {}

    async def __call__(self, user_id: int):
        now = self._clock()
        if self._ok.get(user_id, 0) > now:
            return True
        result = await self._check(user_id)
        if result is True:
            if len(self._ok) >= self._max:
                self._ok = {k: v for k, v in self._ok.items() if v > now}
                if len(self._ok) >= self._max:
                    self._ok.clear()
            self._ok[user_id] = now + self._ttl
        else:
            self._ok.pop(user_id, None)
        return result
