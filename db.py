"""تخزين دائم بسيط (SQLite) للخبرة والإعدادات."""
import json
import os
import sqlite3
import threading
import time


class Database:
    def __init__(self, path: str):
        folder = os.path.dirname(os.path.abspath(path))
        os.makedirs(folder, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock, self.conn:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS stats(
                    guild_id INTEGER, user_id INTEGER,
                    xp INTEGER DEFAULT 0, games INTEGER DEFAULT 0, wins INTEGER DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id));
                CREATE TABLE IF NOT EXISTS settings(
                    guild_id INTEGER PRIMARY KEY, manager_role_id INTEGER);
                CREATE TABLE IF NOT EXISTS news(
                    id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, title TEXT, body TEXT,
                    author TEXT, pinned INTEGER DEFAULT 0, created REAL);
                CREATE TABLE IF NOT EXISTS games(
                    id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, winner TEXT,
                    players INTEGER, nights INTEGER, winners TEXT, created REAL);
                CREATE TABLE IF NOT EXISTS site(
                    guild_id INTEGER, key TEXT, value TEXT, PRIMARY KEY (guild_id, key));
                """
            )

    def add(self, guild_id, user_id, xp=0, games=0, wins=0) -> int:
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO stats(guild_id,user_id) VALUES(?,?)", (guild_id, user_id))
            self.conn.execute(
                "UPDATE stats SET xp=xp+?, games=games+?, wins=wins+? WHERE guild_id=? AND user_id=?",
                (xp, games, wins, guild_id, user_id))
            return self.conn.execute(
                "SELECT xp FROM stats WHERE guild_id=? AND user_id=?", (guild_id, user_id)).fetchone()[0]

    def stats(self, guild_id, user_id):
        with self.lock:
            row = self.conn.execute(
                "SELECT xp,games,wins FROM stats WHERE guild_id=? AND user_id=?",
                (guild_id, user_id)).fetchone()
        return row or (0, 0, 0)

    def top(self, guild_id, limit=10):
        with self.lock:
            return self.conn.execute(
                "SELECT user_id,xp,games,wins FROM stats WHERE guild_id=? ORDER BY xp DESC, wins DESC LIMIT ?",
                (guild_id, limit)).fetchall()

    def set_manager_role(self, guild_id, role_id):
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT INTO settings(guild_id,manager_role_id) VALUES(?,?) "
                "ON CONFLICT(guild_id) DO UPDATE SET manager_role_id=excluded.manager_role_id",
                (guild_id, role_id))

    def manager_role(self, guild_id):
        with self.lock:
            row = self.conn.execute(
                "SELECT manager_role_id FROM settings WHERE guild_id=?", (guild_id,)).fetchone()
        return row[0] if row else None

    # ── الموقع: الأخبار وسجل الجولات والإعدادات العامة ──
    def add_news(self, guild_id, title, body, author="", pinned=False) -> int:
        with self.lock, self.conn:
            cur = self.conn.execute(
                "INSERT INTO news(guild_id,title,body,author,pinned,created) VALUES(?,?,?,?,?,?)",
                (guild_id, title, body, author, 1 if pinned else 0, time.time()))
            return cur.lastrowid

    def list_news(self, guild_id, limit=10):
        with self.lock:
            rows = self.conn.execute(
                "SELECT id,title,body,author,pinned,created FROM news WHERE guild_id=? "
                "ORDER BY pinned DESC, created DESC, id DESC LIMIT ?", (guild_id, limit)).fetchall()
        return [{"id": r[0], "title": r[1], "body": r[2], "author": r[3], "pinned": bool(r[4]), "created": r[5]}
                for r in rows]

    def delete_news(self, guild_id, news_id) -> bool:
        with self.lock, self.conn:
            return self.conn.execute("DELETE FROM news WHERE guild_id=? AND id=?",
                                     (guild_id, news_id)).rowcount > 0

    def add_game(self, guild_id, winner, players, nights, winners=()):
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT INTO games(guild_id,winner,players,nights,winners,created) VALUES(?,?,?,?,?,?)",
                (guild_id, winner, int(players), int(nights), json.dumps(list(winners), ensure_ascii=False), time.time()))

    def list_games(self, guild_id, limit=10):
        with self.lock:
            rows = self.conn.execute(
                "SELECT winner,players,nights,winners,created FROM games WHERE guild_id=? "
                "ORDER BY created DESC, id DESC LIMIT ?", (guild_id, limit)).fetchall()
        return [{"winner": r[0], "players": r[1], "nights": r[2], "winners": json.loads(r[3] or "[]"), "created": r[4]}
                for r in rows]

    def totals(self, guild_id):
        """(عدد اللاعبين المسجلين، عدد الجولات المنتهية)"""
        with self.lock:
            players = self.conn.execute("SELECT COUNT(*) FROM stats WHERE guild_id=?", (guild_id,)).fetchone()[0]
            games = self.conn.execute("SELECT COUNT(*) FROM games WHERE guild_id=?", (guild_id,)).fetchone()[0]
        return players, games

    def site_get(self, guild_id, key, default=""):
        with self.lock:
            row = self.conn.execute("SELECT value FROM site WHERE guild_id=? AND key=?", (guild_id, key)).fetchone()
        return row[0] if row else default

    def site_set(self, guild_id, key, value):
        with self.lock, self.conn:
            if value:
                self.conn.execute(
                    "INSERT INTO site(guild_id,key,value) VALUES(?,?,?) "
                    "ON CONFLICT(guild_id,key) DO UPDATE SET value=excluded.value", (guild_id, key, value))
            else:
                self.conn.execute("DELETE FROM site WHERE guild_id=? AND key=?", (guild_id, key))


class MongoDatabase:
    """نفس واجهة Database لكن على MongoDB Atlas.
    القراءة من ذاكرة محمّلة عند الإقلاع، والكتابة تُرسل في خيط خلفي (لا تعطّل البوت)."""

    def __init__(self, uri: str, dbname: str = "loup_garou"):
        from concurrent.futures import ThreadPoolExecutor
        from pymongo import MongoClient
        self.client = MongoClient(uri, serverSelectionTimeoutMS=8000)
        self.client.admin.command("ping")                # فشل سريع إن كان الرابط/الشبكة خاطئة
        self.db = self.client[dbname]
        self.lock = threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=1)    # عامل واحد = ترتيب الكتابات محفوظ
        self.cache = {(d["guild_id"], d["user_id"]): [d.get("xp", 0), d.get("games", 0), d.get("wins", 0)]
                      for d in self.db.stats.find({})}
        self.managers = {d["_id"]: d.get("manager_role_id") for d in self.db.settings.find({})}
        self._news = {}      # (guild_id, id) -> dict
        for d in self.db.news.find({}):
            self._news[(d["guild_id"], d["id"])] = {k: d.get(k) for k in ("id", "guild_id", "title", "body", "author", "pinned", "created")}
        self._games = sorted((dict(d) for d in self.db.games.find({})), key=lambda d: d.get("created", 0))[-300:]
        self._site = {}      # (guild_id, key) -> value
        for d in self.db.site.find({}):
            self._site[(d["guild_id"], d["key"])] = d.get("value", "")

    def _bg(self, fn):
        def run():
            try:
                fn()
            except Exception:
                import logging
                logging.getLogger("loup-garou").exception("فشلت كتابة في MongoDB")
        self.pool.submit(run)

    def add(self, guild_id, user_id, xp=0, games=0, wins=0) -> int:
        with self.lock:
            row = self.cache.setdefault((guild_id, user_id), [0, 0, 0])
            row[0] += xp; row[1] += games; row[2] += wins
            total = row[0]
        self._bg(lambda: self.db.stats.update_one(
            {"_id": f"{guild_id}:{user_id}"},
            {"$inc": {"xp": xp, "games": games, "wins": wins},
             "$setOnInsert": {"guild_id": guild_id, "user_id": user_id}}, upsert=True))
        return total

    def stats(self, guild_id, user_id):
        with self.lock:
            return tuple(self.cache.get((guild_id, user_id), (0, 0, 0)))

    def top(self, guild_id, limit=10):
        with self.lock:
            rows = [(u, r[0], r[1], r[2]) for (g, u), r in self.cache.items() if g == guild_id]
        rows.sort(key=lambda x: (-x[1], -x[3]))
        return rows[:limit]

    def set_manager_role(self, guild_id, role_id):
        self.managers[guild_id] = role_id
        self._bg(lambda: self.db.settings.update_one(
            {"_id": guild_id}, {"$set": {"manager_role_id": role_id}}, upsert=True))

    def manager_role(self, guild_id):
        return self.managers.get(guild_id)

    # ── الموقع: الأخبار وسجل الجولات والإعدادات العامة ──
    def add_news(self, guild_id, title, body, author="", pinned=False) -> int:
        with self.lock:
            nid = max([i for (g, i) in self._news if g == guild_id] or [0]) + 1
            doc = {"id": nid, "guild_id": guild_id, "title": title, "body": body, "author": author,
                   "pinned": bool(pinned), "created": time.time()}
            self._news[(guild_id, nid)] = doc
        self._bg(lambda: self.db.news.update_one({"_id": f"{guild_id}:{nid}"}, {"$set": doc}, upsert=True))
        return nid

    def list_news(self, guild_id, limit=10):
        with self.lock:
            rows = [dict(d) for (g, _), d in self._news.items() if g == guild_id]
        rows.sort(key=lambda d: (not d["pinned"], -d["created"], -d["id"]))
        return [{k: d[k] for k in ("id", "title", "body", "author", "pinned", "created")} for d in rows[:limit]]

    def delete_news(self, guild_id, news_id) -> bool:
        with self.lock:
            existed = self._news.pop((guild_id, news_id), None) is not None
        if existed:
            self._bg(lambda: self.db.news.delete_one({"_id": f"{guild_id}:{news_id}"}))
        return existed

    def add_game(self, guild_id, winner, players, nights, winners=()):
        doc = {"guild_id": guild_id, "winner": winner, "players": int(players), "nights": int(nights),
               "winners": list(winners), "created": time.time()}
        with self.lock:
            self._games.append(doc)
            del self._games[:-300]
        self._bg(lambda: self.db.games.update_one({"_id": f"{guild_id}:{doc['created']}"}, {"$set": doc}, upsert=True))

    def list_games(self, guild_id, limit=10):
        with self.lock:
            rows = [d for d in self._games if d["guild_id"] == guild_id]
        rows.sort(key=lambda d: -d["created"])
        return [{k: d[k] for k in ("winner", "players", "nights", "winners", "created")} for d in rows[:limit]]

    def totals(self, guild_id):
        with self.lock:
            players = sum(1 for (g, _) in self.cache if g == guild_id)
            games = sum(1 for d in self._games if d["guild_id"] == guild_id)
        return players, games

    def site_get(self, guild_id, key, default=""):
        with self.lock:
            return self._site.get((guild_id, key), default)

    def site_set(self, guild_id, key, value):
        with self.lock:
            if value:
                self._site[(guild_id, key)] = value
            else:
                self._site.pop((guild_id, key), None)
        doc_id = f"{guild_id}:{key}"
        if value:
            self._bg(lambda: self.db.site.update_one(
                {"_id": doc_id}, {"$set": {"guild_id": guild_id, "key": key, "value": value}}, upsert=True))
        else:
            self._bg(lambda: self.db.site.delete_one({"_id": doc_id}))


def make_database(sqlite_path: str):
    """MongoDB إن وُجد MONGODB_URI، وإلا (أو عند فشل الاتصال) SQLite."""
    import logging
    uri = os.getenv("MONGODB_URI", "").strip()
    if uri:
        try:
            database = MongoDatabase(uri, os.getenv("MONGODB_DB", "loup_garou"))
            logging.getLogger("loup-garou").info("✅ متصل بـ MongoDB")
            return database
        except Exception as e:
            logging.getLogger("loup-garou").error(
                "❌ تعذّر الاتصال بـ MongoDB (%s). سيُستخدم SQLite مؤقتًا — راجع الرابط وإعدادات Network Access.", e)
    return Database(sqlite_path)
