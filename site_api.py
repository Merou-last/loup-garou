"""منطق صرف (بدون discord أو aiohttp) لواجهة الموقع العامة — قابل للاختبار بسهولة."""
import re
import time
from datetime import datetime, timezone

INVITE_RE = re.compile(r"^https://(discord\.gg|discord\.com/invite|www\.discord\.com/invite)/[A-Za-z0-9-]{2,64}/?$")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

PHASE_LABELS = {"idle": "التسجيل مفتوح", "starting": "توزيع الأدوار", "night": "الليل", "witch": "دور الساحرة",
                "dawn": "الفجر", "day": "النقاش", "vote": "التصويت", "dusk": "إعلان النتيجة"}
WINNER_LABELS = {"villagers": "القرويون", "wolves": "الذئاب", "white_wolf": "الذئب الأبيض"}


def clean(text, limit):
    """تنظيف نص قادم من مستخدم: إزالة رموز التحكم، قص الفراغات، تحديد الطول."""
    text = _CTRL.sub("", str(text or "")).strip()
    return text[:limit]


def valid_invite(url: str) -> bool:
    return bool(INVITE_RE.match((url or "").strip()))


def iso(ts):
    try:
        return datetime.fromtimestamp(float(ts), timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def allowed_origins(raw: str):
    items = [o.strip().rstrip("/") for o in (raw or "*").split(",") if o.strip()]
    return items or ["*"]


def cors_headers(origin, allowed):
    """Headers للقراءة فقط. مع SITE_ORIGINS محددة يُسمح فقط لأصول موقعك."""
    base = {"Access-Control-Allow-Methods": "GET, OPTIONS", "Access-Control-Allow-Headers": "Content-Type, Authorization",
            "Access-Control-Max-Age": "600"}
    if "*" in allowed:
        base["Access-Control-Allow-Origin"] = "*"
    elif origin and origin.rstrip("/") in allowed:
        base["Access-Control-Allow-Origin"] = origin.rstrip("/")
        base["Vary"] = "Origin"
    return base


def news_payload(rows):
    return [{"id": r["id"], "title": r["title"], "body": r["body"], "author": r.get("author") or "",
             "pinned": bool(r.get("pinned")), "created_at": iso(r.get("created"))} for r in rows]


def games_payload(rows):
    return [{"winner": r["winner"], "winner_label": WINNER_LABELS.get(r["winner"], r["winner"]),
             "players": r["players"], "nights": r["nights"], "winners": r.get("winners", []),
             "ended_at": iso(r.get("created"))} for r in rows]


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def status_payload(*, bot_online, guild_name, guild_found, phase, game, waiting, min_players, max_players,
                   member_count=0):
    alive = len(game.alive) if game else 0
    total = len(game.roles) if game else 0
    return {
        "ok": True, "product": "Merou Last", "game": "Loup-Garou Ultimate",
        "bot_online": bool(bot_online), "guild_found": bool(guild_found), "guild_name": guild_name,
        "phase": phase, "phase_label": PHASE_LABELS.get(phase, "غير معروف"),
        "night": game.night if game else 0, "active": bool(game),
        "waiting_players": waiting if not game else 0,
        "alive_players": alive, "dead_players": total - alive if game else 0,
        "total_players": total if game else waiting,
        "min_players": min_players, "max_players": max_players,
        "member_count": int(member_count or 0), "updated_at": utc_now_iso(),
    }
