"""منطق لعبة Loup-Garou (بدون أي اعتماد على discord) — قابل للاختبار."""
import random
from dataclasses import dataclass, field
from typing import Optional

WOLF_TEAM = frozenset({"werewolf", "white_wolf"})

# (الحد الأدنى لعدد اللاعبين, الدور)
SPECIALS = [
    (4, "seer"), (5, "doctor"), (7, "hunter"), (8, "witch"),
    (9, "guardian"), (10, "little_girl"), (11, "mayor"),
]
LITTLE_GIRL_CAUGHT_CHANCE = 0.20


def build_roles(n: int, rng=random) -> list:
    """قائمة أدوار مخلوطة لعدد n من اللاعبين."""
    if n < 4:
        raise ValueError("الحد الأدنى 4 لاعبين")
    wolves = max(1, n // 4)
    roles = []
    if n >= 12:
        roles.append("white_wolf")
        wolves -= 1
    roles += ["werewolf"] * wolves
    roles += [role for need, role in SPECIALS if n >= need]
    roles = roles[:n]
    roles += ["villager"] * (n - len(roles))
    rng.shuffle(roles)
    return roles


@dataclass
class NightActions:
    wolf_votes: dict = field(default_factory=dict)   # ذئب -> ضحية
    ww_target: Optional[int] = None                  # الذئب الأبيض (ليالي زوجية)
    doctor: Optional[int] = None
    guardian: Optional[int] = None
    seer_done: bool = False
    lg_done: bool = False
    lg_caught: bool = False
    witch_save: bool = False
    witch_poison: Optional[int] = None
    wolf_target: Optional[int] = None


@dataclass
class Game:
    roles: dict                                      # uid -> role key
    alive: set = field(default_factory=set)
    night: int = 0
    witch_heal: bool = True
    witch_poison: bool = True
    guardian_last: Optional[int] = None

    def __post_init__(self):
        if not self.alive:
            self.alive = set(self.roles)

    def is_wolf(self, uid) -> bool:
        return self.roles.get(uid) in WOLF_TEAM

    def uids_with(self, role) -> list:
        return [u for u, r in self.roles.items() if r == role]

    def alive_wolves(self) -> set:
        return {u for u in self.alive if self.is_wolf(u)}

    def check_win(self):
        """None | 'villagers' | 'wolves' | 'white_wolf'"""
        wolves = self.alive_wolves()
        others = self.alive - wolves
        if not wolves:
            return "villagers"
        if not others:
            if len(wolves) == 1 and self.roles[next(iter(wolves))] == "white_wolf":
                return "white_wolf"
            return "wolves"
        if len(wolves) >= len(others):
            return "wolves"
        return None

    def winners(self, winner) -> set:
        if winner == "villagers":
            return {u for u, r in self.roles.items() if r not in WOLF_TEAM}
        if winner == "wolves":
            return {u for u, r in self.roles.items() if r in WOLF_TEAM}
        if winner == "white_wolf":
            return set(self.uids_with("white_wolf"))
        return set()


def pick_wolf_target(g: Game, a: NightActions, rng=random):
    """أغلبية أصوات الذئاب الأحياء؛ التعادل عشوائي؛ بلا أصوات = لا ضحية."""
    counts = {}
    for wolf, target in a.wolf_votes.items():
        if wolf in g.alive and g.is_wolf(wolf) and target in g.alive and not g.is_wolf(target):
            counts[target] = counts.get(target, 0) + 1
    if not counts:
        return None
    best = max(counts.values())
    return rng.choice(sorted(t for t, c in counts.items() if c == best))


def resolve_night(g: Game, a: NightActions, rng=random) -> list:
    """يعيد [(uid, cause)] ويحدّث حالة الجرعات والحارس."""
    deaths = []
    target = a.wolf_target
    if target is not None and target in g.alive:
        saved = target in (a.doctor, a.guardian)
        if a.witch_save and g.witch_heal:
            g.witch_heal = False
            saved = True
        if not saved:
            deaths.append((target, "wolves"))
    if a.witch_poison is not None and g.witch_poison and a.witch_poison in g.alive:
        g.witch_poison = False
        deaths.append((a.witch_poison, "poison"))
    if a.ww_target is not None and a.ww_target in g.alive and g.is_wolf(a.ww_target):
        deaths.append((a.ww_target, "white_wolf"))
    if a.lg_caught:
        for lg in g.uids_with("little_girl"):
            if lg in g.alive:
                deaths.append((lg, "caught"))
    g.guardian_last = a.guardian
    seen, out = set(), []
    for uid, cause in deaths:
        if uid not in seen:
            seen.add(uid)
            out.append((uid, cause))
    return out


def tally_votes(g: Game, votes: dict):
    """votes: voter -> target|None. يعيد (counts, eliminated|None, tied)."""
    counts = {}
    for voter, target in votes.items():
        if voter not in g.alive or target not in g.alive:
            continue
        counts[target] = counts.get(target, 0) + (2 if g.roles[voter] == "mayor" else 1)
    if not counts:
        return counts, None, False
    best = max(counts.values())
    top = [t for t, c in counts.items() if c == best]
    if len(top) > 1:
        return counts, None, True
    return counts, top[0], False


def little_girl_hint(g: Game, lg_uid, rng=random) -> list:
    """3 أسماء بينها ذئب واحد (أو أقل إذا لم يتوفر عدد كافٍ)."""
    wolves = [u for u in g.alive_wolves() if u != lg_uid]
    others = [u for u in g.alive if not g.is_wolf(u) and u != lg_uid]
    if not wolves:
        return []
    hint = [rng.choice(sorted(wolves))]
    rng.shuffle(others)
    hint += others[:2]
    rng.shuffle(hint)
    return hint


def roll_caught(rng=random) -> bool:
    return rng.random() < LITTLE_GIRL_CAUGHT_CHANCE
