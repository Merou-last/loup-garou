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
