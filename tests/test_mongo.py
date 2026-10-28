"""اختبار MongoDatabase بمكتبة pymongo وهمية (بدون شبكة)."""
import os, sys, types, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

store = {"stats": {}, "settings": {}}
class Coll:
    def __init__(s, n): s.n = n
    def find(s, q): return [dict(v, _id=k) for k, v in store[s.n].items()]
    def update_one(s, flt, upd, upsert=False):
        d = store[s.n].setdefault(flt["_id"], {}) if upsert else store[s.n][flt["_id"]]
        for k, v in upd.get("$setOnInsert", {}).items(): d.setdefault(k, v)
        for k, v in upd.get("$inc", {}).items(): d[k] = d.get(k, 0) + v
        for k, v in upd.get("$set", {}).items(): d[k] = v
class DB_:
    stats = Coll("stats"); settings = Coll("settings")
class Client:
    def __init__(s, uri, **kw): s.admin = types.SimpleNamespace(command=lambda c: None)
    def __getitem__(s, n): return DB_()
pm = types.ModuleType("pymongo"); pm.MongoClient = Client; sys.modules["pymongo"] = pm
import db

class T(unittest.TestCase):
    def test_flow(self):
        m = db.MongoDatabase("mongodb://x")
        self.assertEqual(m.add(1, 5, xp=2, games=1), 2)
        self.assertEqual(m.add(1, 5, xp=3, games=1, wins=1), 5)
        m.add(1, 6, xp=9); m.set_manager_role(1, 77)
        m.pool.shutdown(wait=True)
        self.assertEqual(m.stats(1, 5), (5, 2, 1))
        self.assertEqual(m.top(1)[0][:2], (6, 9))
        self.assertEqual(m.manager_role(1), 77)
        self.assertEqual(store["stats"]["1:5"]["xp"], 5)       # كُتب في «القاعدة»
        m2 = db.MongoDatabase("mongodb://x")                   # إعادة تشغيل: تُحمَّل من القاعدة
        self.assertEqual(m2.stats(1, 5), (5, 2, 1)); self.assertEqual(m2.manager_role(1), 77)

    def test_fallback_to_sqlite(self):
        os.environ["MONGODB_URI"] = "mongodb://bad"
        good = pm.MongoClient
        pm.MongoClient = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no net"))
        import tempfile
        try:
            d = db.make_database(tempfile.mktemp(suffix=".db"))
            self.assertIsInstance(d, db.Database)
        finally:
            pm.MongoClient = good
            os.environ.pop("MONGODB_URI")

if __name__ == "__main__":
    unittest.main()
