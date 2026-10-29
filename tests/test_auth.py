"""اختبارات تسجيل الدخول بديسكورد: منطق auth.py كاملًا بخادم Discord وهمي (بدون discord/aiohttp)."""
import json
import re
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import auth, site_api

SECRET = "s" * 48
SITE = "https://youcef.blogspot.com"
NOW = 1_800_000_000
REDIRECT = "https://bot.onrender.com/auth/discord/callback"


def make_cfg(**kw):
    base = dict(client_id="123", client_secret="shh", session_secret=SECRET, guild_id=999,
                origins=(SITE, "https://custom.example.com"))
    base.update(kw)
    return auth.AuthConfig(**base)


class FakeDiscord:
    """يحاكي تبديل الرمز وقراءة الحساب."""

    def __init__(self, user=None, fail_exchange=False, fail_user=False):
        self.user = user if user is not None else {"id": "4242424242", "username": "yousef", "global_name": "Yousef",
                                                   "avatar": "abc123", "discriminator": "0"}
        self.fail_exchange, self.fail_user, self.calls = fail_exchange, fail_user, []

    async def exchange_code(self, code, redirect_uri):
        self.calls.append(("exchange", code, redirect_uri))
        if self.fail_exchange:
            raise RuntimeError("token exchange failed (400)")
        return "access-token-1"

    async def fetch_user(self, access_token):
        self.calls.append(("user", access_token))
        if self.fail_user:
            raise RuntimeError("user lookup failed (401)")
        return self.user


def member(result):
    async def check(user_id):
        if isinstance(result, Exception):
            raise result
        return result
    return check


def start(cfg=None, **kw):
    cfg = cfg or make_cfg()
    args = dict(origin=SITE, redirect_uri=REDIRECT, now=NOW)
    args.update(kw)
    url, nonce = auth.begin_login(cfg, **args)
    state = parse_qs(urlsplit(url).query)["state"][0]
    return url, nonce, state


class Tokens(unittest.TestCase):
    def test_roundtrip_and_expiry(self):
        t = auth.sign("session", {"sub": "1", "exp": NOW + 10}, SECRET)
        self.assertEqual(auth.verify("session", t, SECRET, NOW)["sub"], "1")
        self.assertIsNone(auth.verify("session", t, SECRET, NOW + 10))      # انتهت بالضبط
        self.assertIsNone(auth.verify("session", t, SECRET, NOW + 999))

    def test_wrong_secret_and_purpose(self):
        t = auth.sign("session", {"sub": "1", "exp": NOW + 10}, SECRET)
        self.assertIsNone(auth.verify("session", t, "x" * 48, NOW))
        self.assertIsNone(auth.verify("state", t, SECRET, NOW))              # رمز جلسة لا يصلح كـ state

    def test_tampering_and_garbage(self):
        t = auth.sign("session", {"sub": "1", "exp": NOW + 10}, SECRET)
        v, body, mac = t.split(".")
        forged = auth.sign("session", {"sub": "2", "exp": NOW + 10}, "other" * 10).split(".")[1]
        for bad in (f"{v}.{forged}.{mac}", f"{v}.{body}.{mac[:-2]}AA", f"v2.{body}.{mac}", "", None, "a.b", "a.b.c.d",
                    "v1.é.é", 123, f"{v}.{body}"):
            self.assertIsNone(auth.verify("session", bad, SECRET, NOW), bad)

    def test_exp_must_be_a_number(self):
        for exp in ("9999999999", None, True, [1]):
            t = auth.sign("session", {"sub": "1", "exp": exp}, SECRET)
            self.assertIsNone(auth.verify("session", t, SECRET, NOW), exp)


class Origins(unittest.TestCase):
    def test_normalize(self):
        n = auth.normalize_origin
        self.assertEqual(n("https://Site.Blogspot.com/"), "https://site.blogspot.com")
        self.assertEqual(n("https://a.com:443"), "https://a.com")
        self.assertEqual(n("http://localhost:8080"), "http://localhost:8080")
        for bad in ("", None, "*", "javascript:alert(1)", "ftp://a.com", "https://a.com/path", "https://a.com?x=1",
                    "https://u:p@a.com", "https://a.com#x", "https://a .com", "//a.com", "https://[::1]"):
            self.assertIsNone(n(bad), bad)

    def test_return_url_same_origin_only(self):
        r = auth.safe_return_url
        self.assertEqual(r(SITE + "/p/games.html?m=1#x", SITE), SITE + "/p/games.html?m=1")   # يحذف الـ fragment
        self.assertEqual(r(SITE, SITE), SITE + "/")
        for bad in ("https://evil.com/", "https://youcef.blogspot.com.evil.com/", "https://youcef.blogspot.com@evil.com/",
                    "//evil.com", "javascript:alert(1)", "", None, SITE + "/a b", SITE + "/" + "a" * 400,
                    "http://youcef.blogspot.com/"):
            self.assertIsNone(r(bad, SITE), bad)


class Profile(unittest.TestCase):
    def test_avatar(self):
        self.assertEqual(auth.avatar_url({"id": "5", "avatar": "abc"}), "https://cdn.discordapp.com/avatars/5/abc.png?size=128")
        self.assertIn(".gif", auth.avatar_url({"id": "5", "avatar": "a_abc"}))
        self.assertTrue(auth.avatar_url({"id": str(7 << 22), "avatar": None, "discriminator": "0"}).endswith("/1.png"))
        self.assertTrue(auth.avatar_url({"id": "5", "avatar": None, "discriminator": "1234"}).endswith("/4.png"))
        self.assertTrue(auth.avatar_url({"id": "5", "avatar": "../../x"}).startswith("https://cdn.discordapp.com/embed/"))

    def test_display_name(self):
        self.assertEqual(auth.display_name({"global_name": " Yousef\x00 ", "username": "u"}), "Yousef")
        self.assertEqual(auth.display_name({"username": "u"}), "u")
        self.assertEqual(auth.display_name({}), "لاعب")
        self.assertEqual(len(auth.display_name({"username": "x" * 100})), 40)


class Config(unittest.TestCase):
    def test_problems(self):
        self.assertEqual(make_cfg().problems(), [])
        self.assertTrue(make_cfg().enabled)
        empty = auth.AuthConfig().problems()
        self.assertGreaterEqual(len(empty), 5)
        self.assertTrue(any("SESSION_SECRET" in p for p in auth.AuthConfig(session_secret="short").problems()))
        wild = make_cfg(wildcard=True)
        self.assertFalse(wild.enabled)
        self.assertTrue(any("SITE_ORIGINS" in p for p in wild.problems()))
        self.assertFalse(make_cfg(origins=()).enabled)
        self.assertFalse(make_cfg(redirect_uri="http://evil.example/cb").enabled)

    def test_problems_never_leak_secrets(self):
        text = " ".join(make_cfg(client_secret="TOPSECRET", session_secret="TOPSECRET2", guild_id=0).problems())
        self.assertNotIn("TOPSECRET", text)

    def test_from_env(self):
        env = {"DISCORD_CLIENT_ID": " 1 ", "DISCORD_CLIENT_SECRET": "s", "SESSION_SECRET": SECRET, "SESSION_DAYS": "99",
               "RENDER_EXTERNAL_URL": "https://bot.onrender.com"}
        cfg = auth.AuthConfig.from_env(env, guild_id=5, origins=[SITE + "/", "junk", SITE])
        self.assertEqual((cfg.client_id, cfg.guild_id, cfg.origins, cfg.session_days), ("1", 5, (SITE,), 30))
        self.assertTrue(cfg.enabled)
        self.assertTrue(auth.AuthConfig.from_env(env, guild_id=5, origins=["*"]).wildcard)
        self.assertEqual(auth.AuthConfig.from_env({"SESSION_DAYS": "abc"}).session_days, 7)

    def test_redirect_uri_resolution(self):
        self.assertEqual(auth.resolve_redirect_uri(make_cfg(redirect_uri="https://x.com/cb"), "http", "h"), "https://x.com/cb")
        self.assertEqual(auth.resolve_redirect_uri(make_cfg(public_base_url="https://b.onrender.com/"), "http", "h"),
                         "https://b.onrender.com" + auth.CALLBACK_PATH)
        self.assertEqual(auth.resolve_redirect_uri(make_cfg(), "https", "h.com"), "https://h.com" + auth.CALLBACK_PATH)


class BeginLogin(unittest.TestCase):
    def test_builds_discord_url(self):
        url, nonce, state = start(return_url=SITE + "/p/x.html", mode="redirect")
        parts = urlsplit(url)
        q = {k: v[0] for k, v in parse_qs(parts.query).items()}
        self.assertEqual(f"{parts.scheme}://{parts.netloc}{parts.path}", "https://discord.com/oauth2/authorize")
        self.assertEqual((q["client_id"], q["response_type"], q["scope"], q["redirect_uri"]), ("123", "code", "identify", REDIRECT))
        payload = auth.verify("state", state, SECRET, NOW)
        self.assertEqual((payload["n"], payload["o"], payload["m"], payload["r"]), (nonce, SITE, "redirect", SITE + "/p/x.html"))
        self.assertEqual(payload["exp"], NOW + auth.STATE_TTL)
        self.assertNotEqual(nonce, start()[1])

    def test_rejections(self):
        def code(**kw):
            with self.assertRaises(auth.AuthError) as cm:
                start(**kw)
            return cm.exception.code
        self.assertEqual(code(origin="https://evil.com"), "bad_origin")
        self.assertEqual(code(origin=""), "bad_origin")
        self.assertEqual(code(origin="*"), "bad_origin")
        self.assertEqual(code(mode="weird"), "bad_request")
        self.assertEqual(code(cfg=make_cfg(wildcard=True)), "disabled")
        self.assertEqual(code(cfg=make_cfg(session_secret="")), "disabled")

    def test_bad_return_url_falls_back_to_origin(self):
        self.assertEqual(auth.verify("state", start(return_url="https://evil.com/")[2], SECRET, NOW)["r"], SITE + "/")


class Complete(unittest.IsolatedAsyncioTestCase):
    async def run_flow(self, *, mode="popup", member_result=True, discord=None, cookie="nonce", query_extra=None,
                       now=NOW + 5, cfg=None, return_url=""):
        cfg = cfg or make_cfg()
        _, nonce, state = start(cfg, mode=mode, return_url=return_url)
        query = {"code": "the-code", "state": state}
        query.update(query_extra or {})
        discord = discord or FakeDiscord()
        outcome = await auth.complete_login(cfg, query, nonce if cookie == "nonce" else cookie, REDIRECT, discord,
                                            member(member_result), now=now)
        return outcome, discord

    async def test_success_popup(self):
        out, discord = await self.run_flow()
        self.assertTrue(out.ok)
        self.assertEqual((out.origin, out.mode, out.user["id"], out.user["name"]), (SITE, "popup", "4242424242", "Yousef"))
        self.assertEqual(discord.calls[0], ("exchange", "the-code", REDIRECT))
        session = auth.verify("session", out.token, SECRET, NOW + 6)
        self.assertEqual((session["sub"], session["exp"]), ("4242424242", NOW + 5 + 7 * 86400))
        self.assertIsNone(auth.verify("session", out.token, SECRET, NOW + 5 + 7 * 86400))     # تنتهي بعد 7 أيام
        self.assertIsNone(auth.verify("state", out.token, SECRET, NOW + 6))

    async def test_state_problems(self):
        _, _, state = start()
        for kwargs in (dict(cookie=""), dict(cookie="other-nonce"), dict(now=NOW + auth.STATE_TTL + 1)):
            out, discord = await self.run_flow(**kwargs)
            self.assertEqual((out.ok, out.error, out.origin), (False, "bad_state", ""), kwargs)
            self.assertEqual(discord.calls, [])                  # لا طلبات إلى Discord قبل التحقق
        cfg = make_cfg()
        for query in ({"code": "c"}, {"code": "c", "state": state[:-3] + "AAA"}, {"code": "c", "state": "junk"}):
            out = await auth.complete_login(cfg, query, "x", REDIRECT, FakeDiscord(), member(True), now=NOW)
            self.assertEqual(out.error, "bad_state", query)

    async def test_origin_removed_after_start(self):
        out, _ = await self.run_flow(cookie="nonce")
        self.assertTrue(out.ok)
        _, nonce, state = start()
        out = await auth.complete_login(make_cfg(origins=("https://other.com",)), {"code": "c", "state": state}, nonce,
                                        REDIRECT, FakeDiscord(), member(True), now=NOW)
        self.assertEqual((out.error, out.origin), ("bad_state", ""))

    async def test_denied_not_member_unavailable(self):
        out, _ = await self.run_flow(query_extra={"error": "access_denied"})
        self.assertEqual((out.error, out.origin), ("denied", SITE))
        out, _ = await self.run_flow(member_result=False)
        self.assertEqual((out.ok, out.error, out.token), (False, "not_member", ""))
        out, _ = await self.run_flow(member_result=None)
        self.assertEqual(out.error, "unavailable")
        out, _ = await self.run_flow(member_result=RuntimeError("boom"))
        self.assertEqual(out.error, "unavailable")
        out, _ = await self.run_flow(member_result="yes")      # قيمة غير منطقية لا تُعدّ عضوية
        self.assertEqual(out.error, "unavailable")

    async def test_discord_failures(self):
        for discord in (FakeDiscord(fail_exchange=True), FakeDiscord(fail_user=True), FakeDiscord(user={"username": "no-id"}),
                        FakeDiscord(user={"id": "abc"}), FakeDiscord(user="not-a-dict")):
            out, _ = await self.run_flow(discord=discord)
            self.assertEqual((out.ok, out.error, out.origin), (False, "failed", SITE))
        out, _ = await self.run_flow(query_extra={"code": ""})
        self.assertEqual(out.error, "failed")
        out, _ = await self.run_flow(query_extra={"code": "x" * 600})
        self.assertEqual(out.error, "failed")

    async def test_disabled(self):
        out = await auth.complete_login(make_cfg(wildcard=True), {}, "", REDIRECT, FakeDiscord(), member(True), now=NOW)
        self.assertEqual(out.error, "disabled")

    async def test_response_popup_success_targets_only_site_origin(self):
        out, _ = await self.run_flow()
        spec = auth.outcome_to_response(out)
        self.assertEqual(spec["status"], 200)
        page = spec["html"]
        self.assertIn("window.opener.postMessage(m,t)", page)
        self.assertIn(json.dumps(SITE), page)                    # targetOrigin = موقعك لا "*"
        self.assertNotIn('postMessage(m,"*")', page)
        self.assertIn(out.token, page)
        self.assertIn("#ya_auth=" + out.token, page)             # مسار احتياطي إن فُقدت window.opener
        self.assertIn(auth.MESSAGE_TYPE, page)

    async def test_response_redirect_mode(self):
        out, _ = await self.run_flow(mode="redirect", return_url=SITE + "/p/games.html")
        spec = auth.outcome_to_response(out)
        self.assertEqual(spec, {"status": 302, "location": SITE + "/p/games.html#ya_auth=" + out.token})
        out, _ = await self.run_flow(mode="redirect", member_result=False)
        self.assertEqual(auth.outcome_to_response(out), {"status": 302, "location": SITE + "/#ya_auth_error=not_member"})

    async def test_response_errors(self):
        out, _ = await self.run_flow(member_result=False)
        spec = auth.outcome_to_response(out)
        self.assertEqual(spec["status"], 403)
        self.assertIn('"ok": false', spec["html"])
        self.assertIn('"error": "not_member"', spec["html"])
        self.assertNotIn("token", spec["html"].replace("tokens", ""))
        bad, _ = await self.run_flow(cookie="")                  # state غير موثوق ← لا سكربت ولا postMessage
        spec = auth.outcome_to_response(bad)
        self.assertEqual(spec["status"], 400)
        self.assertNotIn("<script", spec["html"])
        self.assertEqual(auth.error_response("nope")["status"], 502)

    async def test_script_injection_is_escaped(self):
        evil = FakeDiscord(user={"id": "4242424242", "username": "x", "global_name": "</script><img src=x onerror=alert(1)>&"})
        out, _ = await self.run_flow(discord=evil)
        page = auth.outcome_to_response(out)["html"]
        self.assertEqual(page.count("</script>"), 1)             # وسم الإغلاق الوحيد هو وسم السكربت نفسه
        self.assertNotIn("<img", page)
        self.assertEqual(re.findall(r"<script", page), ["<script"])


class WhoAmI(unittest.IsolatedAsyncioTestCase):
    async def token(self, **extra):
        payload = {"sub": "4242424242", "name": "Yousef", "av": "https://cdn.discordapp.com/x.png", "exp": NOW + 100}
        payload.update(extra)
        return auth.sign("session", payload, SECRET)

    async def test_ok(self):
        code, body = await auth.whoami(make_cfg(), "Bearer " + await self.token(), member(True), now=NOW)
        self.assertEqual(code, 200)
        self.assertEqual(body["user"], {"id": "4242424242", "name": "Yousef", "avatar_url": "https://cdn.discordapp.com/x.png"})
        self.assertEqual(body["expires_at"], site_api.iso(NOW + 100))

    async def test_unauthorized_variants(self):
        good = await self.token()
        cases = [None, "", "Bearer", "Bearer ", "Basic " + good, good, "Bearer " + good[:-2] + "AA",
                 "Bearer " + await self.token(exp=NOW - 1), "Bearer " + await self.token(sub="abc"),
                 "Bearer " + auth.sign("state", {"sub": "4242424242", "exp": NOW + 100}, SECRET),
                 "Bearer " + "a" * 3000]
        for header in cases:
            code, body = await auth.whoami(make_cfg(), header, member(True), now=NOW)
            self.assertEqual((code, body["error"]), (401, "unauthorized"), header)

    async def test_left_server_and_unavailable(self):
        header = "bearer " + await self.token()                  # اسم المخطط غير حساس لحالة الأحرف
        self.assertEqual((await auth.whoami(make_cfg(), header, member(False), now=NOW))[0], 403)
        self.assertEqual((await auth.whoami(make_cfg(), header, member(None), now=NOW))[0], 503)
        self.assertEqual((await auth.whoami(make_cfg(), header, member(RuntimeError("x")), now=NOW))[0], 503)
        self.assertEqual((await auth.whoami(make_cfg(wildcard=True), header, member(True), now=NOW))[0], 503)


class MemberCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_caches_only_positive_results_for_ttl(self):
        clock, calls, answers = [0.0], [], [True, False, None, True]

        async def check(uid):
            calls.append(uid)
            return answers[len(calls) - 1]
        cache = auth.MemberCache(check, ttl=60, clock=lambda: clock[0])
        self.assertTrue(await cache(1)); self.assertTrue(await cache(1))
        self.assertEqual(len(calls), 1)                          # الثانية من الذاكرة
        clock[0] = 61
        self.assertIs(await cache(1), False)                     # انتهت المدة ← فحص جديد (غادر السيرفر)
        self.assertIsNone(await cache(1))                        # السلبي والمجهول لا يُحفظان
        self.assertTrue(await cache(1))
        self.assertEqual(len(calls), 4)

    async def test_bounded_size(self):
        async def check(uid):
            return True
        cache = auth.MemberCache(check, max_items=3, clock=lambda: 0.0)
        for uid in range(10):
            await cache(uid)
        self.assertLessEqual(len(cache._ok), 3)


class CorsAllowsAuthorization(unittest.TestCase):
    def test_header_listed(self):
        h = site_api.cors_headers("https://a.com", ["https://a.com"])
        self.assertIn("Authorization", h["Access-Control-Allow-Headers"])
        self.assertIn("Content-Type", h["Access-Control-Allow-Headers"])


if __name__ == "__main__":
    unittest.main()
