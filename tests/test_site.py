"""اختبارات واجهة الموقع: قاعدة SQLite + منطق site_api (بدون discord/aiohttp)."""
import sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import db, site_api


class SqliteSite(unittest.TestCase):
    def setUp(self):
        self.d = db.Database(str(Path(tempfile.mkdtemp()) / "t.db"))

    def test_news_order_and_delete(self):
        a = self.d.add_news(1, "عادي", "نص", "م")
        b = self.d.add_news(1, "مثبت", "نص", "م", pinned=True)
        self.d.add_news(2, "آخر", "x")
        self.assertEqual([n["title"] for n in self.d.list_news(1)], ["مثبت", "عادي"])
        self.assertTrue(self.d.delete_news(1, a)); self.assertFalse(self.d.delete_news(1, a))
        self.assertFalse(self.d.delete_news(2, b))              # لا يحذف من سيرفر آخر

    def test_games_totals_and_site(self):
        self.d.add(1, 10, xp=5, games=1); self.d.add(1, 11, xp=1, games=1)
        self.d.add_game(1, "wolves", 6, 3, ["أحمد", "سارة"])
        g = self.d.list_games(1)[0]
        self.assertEqual((g["winner"], g["players"], g["winners"]), ("wolves", 6, ["أحمد", "سارة"]))
        self.assertEqual(self.d.totals(1), (2, 1))
        self.d.site_set(1, "banner", "x"); self.assertEqual(self.d.site_get(1, "banner"), "x")
        self.d.site_set(1, "banner", ""); self.assertEqual(self.d.site_get(1, "banner", "-"), "-")


class SiteApi(unittest.TestCase):
    def test_invite_validation(self):
        ok = ["https://discord.gg/abc123", "https://discord.com/invite/Ab-1/"]
        bad = ["http://discord.gg/abc", "https://evil.com/discord.gg/abc", "https://discord.gg/", "javascript:alert(1)",
               "https://discord.gg/abc?x=<script>"]
        self.assertTrue(all(site_api.valid_invite(u) for u in ok))
        self.assertFalse(any(site_api.valid_invite(u) for u in bad))

    def test_clean(self):
        self.assertEqual(site_api.clean("  a\x00b\x07c ", 10), "abc")
        self.assertEqual(len(site_api.clean("x" * 500, 200)), 200)

    def test_cors(self):
        self.assertEqual(site_api.cors_headers("https://a.com", ["*"])["Access-Control-Allow-Origin"], "*")
        allowed = site_api.allowed_origins("https://a.com/, https://b.com")
        self.assertEqual(site_api.cors_headers("https://a.com", allowed)["Access-Control-Allow-Origin"], "https://a.com")
        self.assertNotIn("Access-Control-Allow-Origin", site_api.cors_headers("https://evil.com", allowed))
        self.assertNotIn("Access-Control-Allow-Origin", site_api.cors_headers(None, allowed))

    def test_status_payload(self):
        idle = site_api.status_payload(bot_online=True, guild_name="س", guild_found=True, phase="idle", game=None,
                                       waiting=3, min_players=5, max_players=25, member_count=40)
        self.assertEqual((idle["waiting_players"], idle["alive_players"], idle["phase_label"]), (3, 0, "التسجيل مفتوح"))
        game = SimpleNamespace(alive=[1, 2, 3], roles={i: "x" for i in range(6)}, night=2)
        live = site_api.status_payload(bot_online=True, guild_name="س", guild_found=True, phase="vote", game=game,
                                       waiting=0, min_players=5, max_players=25)
        self.assertEqual((live["alive_players"], live["dead_players"], live["total_players"], live["night"]), (3, 3, 6, 2))
        self.assertNotIn("roles", live)                           # لا تسريب للأدوار

    def test_payload_shapes(self):
        n = site_api.news_payload([{"id": 1, "title": "t", "body": "b", "author": None, "pinned": 1, "created": 1_700_000_000}])
        self.assertTrue(n[0]["pinned"] and n[0]["created_at"].startswith("2023"))
        g = site_api.games_payload([{"winner": "wolves", "players": 7, "nights": 3, "winners": [], "created": 1_700_000_000}])
        self.assertEqual(g[0]["winner_label"], "الذئاب")


if __name__ == "__main__":
    unittest.main()
