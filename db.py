"""تخزين دائم بسيط (SQLite) للخبرة والإعدادات."""
import os
import sqlite3
import threading


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
