import random, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine
from engine import Game, NightActions


def mk(roles):
    return Game(roles={i + 1: r for i, r in enumerate(roles)})


class RolesTest(unittest.TestCase):
    def test_counts_for_all_sizes(self):
        for n in range(4, 26):
            r = engine.build_roles(n, random.Random(n))
            self.assertEqual(len(r), n)
            wolves = sum(x in engine.WOLF_TEAM for x in r)
            self.assertEqual(wolves, max(1, n // 4), n)
            self.assertLess(wolves, n - wolves)
            self.assertLessEqual(r.count("white_wolf"), 1)
            for unique in ("seer", "doctor", "hunter", "witch", "guardian", "little_girl", "mayor"):
                self.assertLessEqual(r.count(unique), 1)

    def test_too_few(self):
        with self.assertRaises(ValueError):
            engine.build_roles(3)


class WinTest(unittest.TestCase):
    def test_villagers(self):
        g = mk(["werewolf", "villager", "seer"]); g.alive.discard(1)
        self.assertEqual(g.check_win(), "villagers")

    def test_wolves_parity(self):
        g = mk(["werewolf", "villager", "seer"]); g.alive.discard(3)
        self.assertEqual(g.check_win(), "wolves")

    def test_ongoing(self):
        g = mk(["werewolf", "villager", "seer", "doctor", "villager"])
        self.assertIsNone(g.check_win())

    def test_white_wolf_solo(self):
        g = mk(["white_wolf", "villager"]); g.alive.discard(2)
        self.assertEqual(g.check_win(), "white_wolf")
        self.assertEqual(g.winners("white_wolf"), {1})

    def test_winners_sets(self):
        g = mk(["werewolf", "villager", "seer"])
        self.assertEqual(g.winners("villagers"), {2, 3})
        self.assertEqual(g.winners("wolves"), {1})


class NightTest(unittest.TestCase):
    def setUp(self):
        self.g = mk(["werewolf", "werewolf", "seer", "doctor", "witch", "guardian", "villager", "villager"])
        self.rng = random.Random(1)

    def test_wolf_majority_and_tie(self):
        a = NightActions(wolf_votes={1: 7, 2: 7})
        self.assertEqual(engine.pick_wolf_target(self.g, a, self.rng), 7)
        a = NightActions(wolf_votes={1: 7, 2: 8})
        self.assertIn(engine.pick_wolf_target(self.g, a, self.rng), (7, 8))
        self.assertIsNone(engine.pick_wolf_target(self.g, NightActions(), self.rng))

    def test_wolf_cannot_target_wolf(self):
        a = NightActions(wolf_votes={1: 2})
        self.assertIsNone(engine.pick_wolf_target(self.g, a))

    def test_kill(self):
        a = NightActions(wolf_target=7)
        self.assertEqual(engine.resolve_night(self.g, a), [(7, "wolves")])

    def test_doctor_and_guardian_save(self):
        for kw in ({"doctor": 7}, {"guardian": 7}):
            g = mk(["werewolf", "villager", "doctor", "guardian", "villager"])
            a = NightActions(wolf_target=2, **{k: 2 for k in kw})
            self.assertEqual(engine.resolve_night(g, a), [])

    def test_witch_save_consumed_once(self):
        a = NightActions(wolf_target=7, witch_save=True)
        self.assertEqual(engine.resolve_night(self.g, a), [])
        self.assertFalse(self.g.witch_heal)
        a2 = NightActions(wolf_target=7, witch_save=True)
        self.assertEqual(engine.resolve_night(self.g, a2), [(7, "wolves")])

    def test_poison_ignores_protection_and_dedupes(self):
        a = NightActions(wolf_target=7, doctor=8, witch_poison=8)
        self.assertEqual(engine.resolve_night(self.g, a), [(7, "wolves"), (8, "poison")])
        self.assertFalse(self.g.witch_poison)
        g = mk(["werewolf", "villager", "witch", "villager"])
        a = NightActions(wolf_target=2, witch_poison=2)
        self.assertEqual(engine.resolve_night(g, a), [(2, "wolves")])

    def test_guardian_memory(self):
        engine.resolve_night(self.g, NightActions(guardian=3))
        self.assertEqual(self.g.guardian_last, 3)
        engine.resolve_night(self.g, NightActions())
        self.assertIsNone(self.g.guardian_last)

    def test_little_girl_caught(self):
        g = mk(["werewolf", "little_girl", "seer", "villager", "villager"])
        a = NightActions(lg_caught=True)
        self.assertEqual(engine.resolve_night(g, a), [(2, "caught")])

    def test_white_wolf_kills_wolf_only(self):
        g = mk(["white_wolf", "werewolf", "villager", "villager", "seer"])
        self.assertEqual(engine.resolve_night(g, NightActions(ww_target=2)), [(2, "white_wolf")])
        self.assertEqual(engine.resolve_night(g, NightActions(ww_target=3)), [])


class VoteTest(unittest.TestCase):
    def test_majority(self):
        g = mk(["werewolf", "villager", "seer", "doctor", "villager"])
        c, t, tie = engine.tally_votes(g, {2: 1, 3: 1, 4: 5, 5: 1, 1: 2})
        self.assertEqual(t, 1); self.assertFalse(tie)

    def test_tie_no_elimination(self):
        g = mk(["werewolf", "villager", "seer", "doctor"])
        c, t, tie = engine.tally_votes(g, {1: 2, 2: 1})
        self.assertIsNone(t); self.assertTrue(tie)

    def test_mayor_double(self):
        g = mk(["mayor", "villager", "werewolf", "villager", "seer"])
        c, t, tie = engine.tally_votes(g, {1: 3, 2: 4})
        self.assertEqual(c[3], 2); self.assertEqual(t, 3)

    def test_skips_and_dead_ignored(self):
        g = mk(["werewolf", "villager", "seer", "doctor", "villager"]); g.alive.discard(5)
        c, t, tie = engine.tally_votes(g, {1: None, 2: None, 5: 1, 3: 5})
        self.assertEqual(c, {}); self.assertIsNone(t); self.assertFalse(tie)


class HintTest(unittest.TestCase):
    def test_hint_has_exactly_one_wolf(self):
        g = mk(["werewolf", "werewolf", "little_girl"] + ["villager"] * 6)
        for s in range(30):
            h = engine.little_girl_hint(g, 3, random.Random(s))
            self.assertEqual(len(h), 3)
            self.assertEqual(sum(g.is_wolf(u) for u in h), 1)
            self.assertNotIn(3, h)


if __name__ == "__main__":
    unittest.main()
