"""اختبار طبقة aiohttp الحقيقية (auth_routes.py) أمام خادم Discord وهمي محلي.
يُتخطّى تلقائيًا إن لم يكن aiohttp مثبتًا:  pip install -r requirements.txt
"""
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import aiohttp
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
    import auth_routes
except ImportError:                      # pragma: no cover
    aiohttp = None

from test_auth import SITE, make_cfg

USER = {"id": "4242424242", "username": "yousef", "global_name": "Yousef", "avatar": "abc123", "discriminator": "0"}


@unittest.skipIf(aiohttp is None, "aiohttp غير مثبت")
class RoutesWithFakeDiscord(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.token_requests = []
        self.members = {4242424242: True}

        async def token(request):
            form = dict(await request.post())
            self.token_requests.append(form)
            if form.get("client_secret") != "shh" or form.get("code") != "good-code":
                return web.json_response({"error": "invalid_grant"}, status=400)
            return web.json_response({"access_token": "tok", "token_type": "Bearer"})

        async def me(request):
            if request.headers.get("Authorization") != "Bearer tok":
                return web.Response(status=401)
            return web.json_response(USER)

        fake = web.Application()
        fake.router.add_post("/oauth2/token", token)
        fake.router.add_get("/users/@me", me)
        self.fake = TestServer(fake)
        await self.fake.start_server()
        self.api = auth_routes.DiscordHTTP("123", "shh", api_base=str(self.fake.make_url("/")).rstrip("/"))

        async def is_member(user_id):
            return self.members.get(user_id, False)

        app = web.Application()
        auth_routes.register(app, make_cfg(), member_check=is_member, discord_api=self.api)
        self.client = TestClient(TestServer(app), cookie_jar=aiohttp.DummyCookieJar())
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        await self.fake.close()

    async def begin(self, **params):
        resp = await self.client.get("/auth/discord/start", params=params, allow_redirects=False)
        return resp

    async def finish(self, start_resp, code="good-code"):
        state = parse_qs(urlsplit(start_resp.headers["Location"]).query)["state"][0]
        nonce = start_resp.cookies["ya_oauth"].value
        return await self.client.get("/auth/discord/callback", params={"code": code, "state": state},
                                     headers={"Cookie": f"ya_oauth={nonce}"}, allow_redirects=False)

    async def test_discord_http_client(self):
        self.assertEqual(await self.api.exchange_code("good-code", "https://x/cb"), "tok")
        form = self.token_requests[0]
        self.assertEqual((form["grant_type"], form["client_id"], form["redirect_uri"]), ("authorization_code", "123", "https://x/cb"))
        with self.assertRaises(RuntimeError):
            await self.api.exchange_code("bad-code", "https://x/cb")
        self.assertEqual((await self.api.fetch_user("tok"))["id"], "4242424242")
        with self.assertRaises(RuntimeError):
            await self.api.fetch_user("bad-token")

    async def test_status(self):
        resp = await self.client.get("/auth/discord/status")
        self.assertEqual(await resp.json(), {"ok": True, "enabled": True})

    async def test_start_sets_cookie_and_redirects_to_discord(self):
        resp = await self.begin(origin=SITE, mode="redirect")
        self.assertEqual(resp.status, 302)
        location = urlsplit(resp.headers["Location"])
        self.assertEqual((location.netloc, location.path), ("discord.com", "/oauth2/authorize"))
        cookie = resp.cookies["ya_oauth"]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")
        redirect_uri = parse_qs(location.query)["redirect_uri"][0]
        self.assertEqual(redirect_uri, str(self.client.make_url("/auth/discord/callback")))

    async def test_start_rejects_unknown_site(self):
        for params in ({"origin": "https://evil.com"}, {}, {"origin": SITE, "mode": "bogus"}):
            resp = await self.begin(**params)
            self.assertEqual(resp.status, 400, params)
            self.assertNotIn("ya_oauth", resp.cookies)

    async def test_full_flow_redirect_mode_then_api_me(self):
        start = await self.begin(origin=SITE, mode="redirect", **{"return": SITE + "/p/games.html"})
        done = await self.finish(start)
        self.assertEqual(done.status, 302)
        location = done.headers["Location"]
        self.assertTrue(location.startswith(SITE + "/p/games.html#ya_auth="))
        self.assertEqual(self.token_requests[0]["redirect_uri"], str(self.client.make_url("/auth/discord/callback")))
        token = location.split("#ya_auth=", 1)[1]

        me = await self.client.get("/api/me", headers={"Authorization": "Bearer " + token})
        body = await me.json()
        self.assertEqual((me.status, body["ok"], body["user"]["name"]), (200, True, "Yousef"))

        self.members[4242424242] = False                      # غادر السيرفر
        gone = await self.client.get("/api/me", headers={"Authorization": "Bearer " + token})
        self.assertIn(gone.status, (200, 403))                # قد تبقى النتيجة الإيجابية في الذاكرة حتى 60 ثانية

        self.assertEqual((await self.client.get("/api/me")).status, 401)

    async def test_popup_mode_returns_page_that_posts_to_site_only(self):
        done = await self.finish(await self.begin(origin=SITE))
        page = await done.text()
        self.assertEqual(done.status, 200)
        self.assertIn("window.opener.postMessage", page)
        self.assertIn('"' + SITE + '"', page)
        self.assertIn("default-src 'none'", done.headers["Content-Security-Policy"])
        self.assertEqual(done.headers["Referrer-Policy"], "no-referrer")

    async def test_failures_come_back_as_error_codes(self):
        bad_code = await self.finish(await self.begin(origin=SITE, mode="redirect"), code="wrong")
        self.assertTrue(bad_code.headers["Location"].endswith("#ya_auth_error=failed"))
        self.members[4242424242] = False
        outsider = await self.finish(await self.begin(origin=SITE, mode="redirect"))
        self.assertTrue(outsider.headers["Location"].endswith("#ya_auth_error=not_member"))

    async def test_callback_without_cookie_is_rejected(self):
        start = await self.begin(origin=SITE, mode="redirect")
        state = parse_qs(urlsplit(start.headers["Location"]).query)["state"][0]
        resp = await self.client.get("/auth/discord/callback", params={"code": "good-code", "state": state},
                                     allow_redirects=False)
        self.assertEqual(resp.status, 400)
        self.assertEqual(self.token_requests, [])             # لم يُرسَل أي شيء إلى Discord


if __name__ == "__main__":
    unittest.main()
