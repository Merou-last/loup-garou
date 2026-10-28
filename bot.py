"""🐺 Loup-Garou Discord Bot — نسخة كاملة تعمل تلقائيًا (ليل/نهار/تصويت/قدرات/فوز)."""
import asyncio
import logging
import os
import shutil
import sys
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Optional

import discord
from aiohttp import web
from discord import app_commands
from dotenv import load_dotenv

import engine
from db import Database
from engine import Game, NightActions, WOLF_TEAM

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("loup-garou")


def env_int(name, default):
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
GUILD_ID = env_int("GUILD_ID", 0)
MIN_PLAYERS = max(4, env_int("MIN_PLAYERS", 5))
MAX_PLAYERS = 25                       # حد قوائم الاختيار في Discord
NIGHT_SECONDS = env_int("NIGHT_SECONDS", 45)
WITCH_SECONDS = env_int("WITCH_SECONDS", 20)
DAY_SECONDS = env_int("DAY_SECONDS", 120)
VOTE_SECONDS = env_int("VOTE_SECONDS", 45)
HUNTER_SECONDS = env_int("HUNTER_SECONDS", 30)
START_DELAY = env_int("START_DELAY", 8)
DB_PATH = os.getenv("DB_PATH", "data/loup_garou.db")

BASE = Path(__file__).parent
ASSETS = BASE / "assets"
FFMPEG_OK = shutil.which("ffmpeg") is not None

CAT_NAME = "🐺・LOUP-GAROU"
CH_RULES, CH_ANN = "📜・القوانين", "📢・الإعلانات"
CH_GAME, CH_ROLES = "🎮・غرفة-اللعبة", "🎭・شرح-الأدوار"
CH_VOTE, CH_VOICE = "🗳️・التصويت", "🔊・قرية-الصوت"
CH_LAIR = "🐺・عرين-الذئاب"
ROLE_PLAYER = "🐺・لاعب Loup-Garou"
ROLE_MANAGER = "👑・إدارة Loup-Garou"

ROLE_INFO = {
    "werewolf": ("الذئب", "Werewolf", "🐺", "في الليل اتفق مع بقية الذئاب على ضحية. هدفك إقصاء القرويين دون كشف هويتك."),
    "villager": ("القروي", "Villager", "🧑‍🌾", "لا تملك قدرة ليلية. ناقش الأدلة وصوّت نهارًا لاكتشاف الذئاب."),
    "seer": ("العرافة", "Seer", "🔮", "كل ليلة افحص لاعبًا لتعرف هل هو ذئب أم لا (الذئب الأبيض يظهر ذئبًا)."),
    "doctor": ("الطبيب", "Doctor", "🩺", "كل ليلة اختر لاعبًا لحمايته من الذئاب. يجوز أن تحمي نفسك."),
    "hunter": ("الصياد", "Hunter", "🏹", "عند خروجك من اللعبة لأي سبب، تطلق سهمًا أخيرًا على لاعب حي."),
    "guardian": ("الحارس", "Guardian", "🛡️", "كل ليلة احمِ لاعبًا من الذئاب. لا تحمِ الشخص نفسه ليلتين متتاليتين."),
    "witch": ("الساحرة", "Witch", "🧙‍♀️", "جرعة إنقاذ وجرعة سم لكل لعبة (جرعة واحدة فقط في الليلة). ترين ضحية الذئاب كل ليلة."),
    "little_girl": ("الطفلة", "Little Girl", "👧", "كل ليلة يمكنك التجسس فتحصلين على 3 أسماء بينها ذئب واحد، لكن بنسبة 20% تُكشفين فتموتين."),
    "mayor": ("العمدة", "Mayor", "🎖️", "صوتك في التصويت النهاري يُحسب بصوتين."),
    "white_wolf": ("الذئب الأبيض", "White Wolf", "🤍", "ذئب يلعب مع الذئاب، وفي الليالي الزوجية يمكنه قتل ذئب من رفاقه. يفوز وحده إن بقي آخر لاعب حي."),
}
CAUSE = {
    "wolves": "افترسته الذئاب", "poison": "سمّته الساحرة", "vote": "أُقصي بتصويت القرية",
    "hunter": "أصابه سهم الصياد", "white_wolf": "قتله الذئب الأبيض",
    "caught": "كشفته الذئاب وهو يتجسس",
}
LEVELS = [(1, "🐺 مبتدئ"), (5, "🌙 لاعب متمرس"), (10, "🩸 صياد الليل"), (15, "👁️ عارف الأسرار"), (20, "👑 أسطورة القرية")]
XP_PLAY, XP_WIN = 2, 3

db = Database(DB_PATH)


def level_for(points: int) -> int:
    level = 1
    for threshold, _ in LEVELS:
        if points >= threshold:
            level = threshold
    return level


# ───────────────────────── الحالة ─────────────────────────
@dataclass
class Session:
    guild_id: int
    players: list = field(default_factory=list)
    game: Optional[Game] = None
    phase: str = "idle"          # idle|starting|night|witch|dawn|day|vote|dusk
    token: int = 0
    task: Optional[asyncio.Task] = None
    skip: asyncio.Event = field(default_factory=asyncio.Event)
    actions: Optional[NightActions] = None
    votes: dict = field(default_factory=dict)
    voice_id: int = 0
    channel_id: int = 0
    lair_id: int = 0
    ambience: bool = False
    warned_mute: bool = False
    hunter_future: Optional[asyncio.Future] = None
    hunter_uid: int = 0
    vote_msg: Optional[discord.Message] = None


sessions: dict = {}


def get_session(guild_id: int) -> Session:
    return sessions.setdefault(guild_id, Session(guild_id))


# ───────────────────────── أدوات مساعدة ─────────────────────────
async def get_member(guild, uid):
    m = guild.get_member(uid)
    if m is None:
        try:
            m = await guild.fetch_member(uid)
        except discord.HTTPException:
            m = None
    return m


def name_of(guild, uid) -> str:
    m = guild.get_member(uid)
    return m.display_name if m else f"لاعب {uid}"


async def safe_send(channel, *args, **kwargs):
    if channel is None:
        return None
    try:
        return await channel.send(*args, **kwargs)
    except discord.HTTPException:
        log.warning("فشل إرسال رسالة إلى %s", getattr(channel, "name", "?"), exc_info=True)
        return None


def find_text(guild, name):
    return discord.utils.get(guild.text_channels, name=name)


def game_ch(sess, guild):
    return find_text(guild, CH_GAME) or guild.get_channel(sess.channel_id)


def is_manager(interaction) -> bool:
    user = interaction.user
    if user.guild_permissions.administrator:
        return True
    role_id = db.manager_role(interaction.guild_id)
    for r in getattr(user, "roles", []):
        if (role_id and r.id == role_id) or r.name == ROLE_MANAGER:
            return True
    return False


async def ensure_role(guild, name, colour=discord.Colour.blurple()):
    role = discord.utils.get(guild.roles, name=name)
    if role is None:
        role = await guild.create_role(name=name, colour=colour, reason="Loup-Garou bot setup")
    return role


async def update_level_roles(member, points):
    current = level_for(points)
    add, remove = [], []
    for threshold, label in LEVELS:
        role = discord.utils.get(member.guild.roles, name=f"المستوى {threshold}・{label}")
        if not role:
            continue
        if threshold == current and role not in member.roles:
            add.append(role)
        elif threshold != current and role in member.roles:
            remove.append(role)
    try:
        if add:
            await member.add_roles(*add, reason="Loup-Garou progression")
        if remove:
            await member.remove_roles(*remove, reason="Loup-Garou progression")
    except discord.HTTPException:
        log.warning("تعذّر تحديث رولات المستوى (تحقق من ترتيب رول البوت)")


def role_embed(key, guild, game=None, uid=None):
    ar, en, emoji, desc = ROLE_INFO[key]
    embed = discord.Embed(title=f"{emoji} دورك في Loup-Garou: {ar} ({en})", description=desc,
                          colour=discord.Colour.dark_purple())
    if game and key in WOLF_TEAM:
        mates = [name_of(guild, u) for u, r in game.roles.items() if r in WOLF_TEAM and u != uid]
        embed.add_field(name="🐺 رفاقك في القطيع", value="، ".join(mates) or "أنت وحدك", inline=False)
    embed.add_field(name="🎯 هدفك", value="العب بذكاء، لا تكشف بطاقتك، والتزم بقواعد الجولة.", inline=False)
    embed.set_footer(text="هذه الرسالة سرية — لا تشاركها")
    kw = {"embed": embed}
    path = ASSETS / "cards" / f"{key}.png"
    if path.exists():
        embed.set_image(url="attachment://role.png")
        kw["file"] = discord.File(path, filename="role.png")
    return kw


# ───────────────────────── الصوت ─────────────────────────
def want_mute(sess, member_id) -> bool:
    g = sess.game
    if g is None:
        return False
    if member_id not in g.alive:
        return True                                  # الموتى والمتفرجون
    return sess.phase in ("night", "witch")


async def apply_mutes(sess, guild, only=None):
    vc = guild.get_channel(sess.voice_id)
    if not isinstance(vc, discord.VoiceChannel):
        return
    sem = asyncio.Semaphore(4)
    failed = 0

    async def one(m):
        nonlocal failed
        want = want_mute(sess, m.id)
        if m.voice and m.voice.mute == want:
            return
        async with sem:
            try:
                await m.edit(mute=want, reason="Loup-Garou")
            except discord.HTTPException:
                failed += 1

    await asyncio.gather(*(one(m) for m in vc.members if not m.bot and (only is None or m.id == only)))
    if failed and not sess.warned_mute:
        sess.warned_mute = True
        await safe_send(game_ch(sess, guild), f"⚠️ تعذّر كتم/فك كتم {failed} عضوًا. امنح البوت صلاحية **Mute Members** "
                                              "وارفع رتبته فوق رتب اللاعبين.")


async def release_mutes(guild, voice_id):
    vc = guild.get_channel(voice_id) if voice_id else None
    if not isinstance(vc, discord.VoiceChannel):
        return
    for m in vc.members:
        if not m.bot and m.voice and m.voice.mute:
            try:
                await m.edit(mute=False, reason="Loup-Garou: نهاية الجولة")
            except discord.HTTPException:
                pass


async def ensure_voice(guild, channel):
    try:
        vc = guild.voice_client
        if vc and vc.is_connected():
            if vc.channel.id != channel.id:
                await vc.move_to(channel)
            return vc
        return await channel.connect(timeout=20, reconnect=True)
    except Exception:
        log.warning("تعذّر دخول القناة الصوتية (PyNaCl/davey/FFmpeg/opus؟). اللعبة تعمل بدون صوت.", exc_info=True)
        return None


def _audio_ready(guild):
    vc = guild.voice_client
    return FFMPEG_OK and vc is not None and vc.is_connected()


async def start_ambience(sess, guild):
    path = ASSETS / "sounds" / "night_ambience.wav"
    if not _audio_ready(guild) or not path.exists():
        return
    sess.ambience = True
    loop = asyncio.get_running_loop()

    def play_loop():
        vc = guild.voice_client
        if not sess.ambience or vc is None or not vc.is_connected() or vc.is_playing():
            return
        try:
            src = discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(str(path)), volume=0.22)
            vc.play(src, after=lambda err: loop.call_soon_threadsafe(play_loop) if (sess.ambience and not err) else None)
        except Exception:
            log.warning("فشل تشغيل المؤثر الليلي", exc_info=True)

    play_loop()


async def stop_ambience(sess, guild):
    sess.ambience = False
    vc = guild.voice_client
    if vc and vc.is_playing():
        vc.stop()


async def play_cue(sess, guild):
    path = ASSETS / "sounds" / "phase_cue.wav"
    await stop_ambience(sess, guild)
    if not _audio_ready(guild) or not path.exists():
        return
    try:
        guild.voice_client.play(discord.PCMVolumeTransformer(discord.FFmpegPCMAudio(str(path)), volume=0.35))
    except Exception:
        log.warning("فشل تشغيل مؤثر الانتقال", exc_info=True)


# ───────────────────────── واجهات الأزرار والقوائم ─────────────────────────
class CallbackView(discord.ui.View):
    def add_button(self, label, callback, style=discord.ButtonStyle.primary):
        b = discord.ui.Button(label=label, style=style)
        b.callback = callback
        self.add_item(b)
        return b


class ChoiceSelect(discord.ui.Select):
    def __init__(self, sess, kind, tok, options, placeholder):
        super().__init__(placeholder=placeholder, min_values=1, max_values=1,
                         options=[discord.SelectOption(label=l[:100], value=v) for l, v in options[:25]])
        self.sess, self.kind, self.tok = sess, kind, tok

    async def callback(self, interaction):
        await handle_choice(self.sess, interaction, self.kind, self.tok, self.values[0])


class ChoiceView(discord.ui.View):
    def __init__(self, sess, tok, specs, timeout=180):
        super().__init__(timeout=timeout)
        for kind, placeholder, options in specs:
            self.add_item(ChoiceSelect(sess, kind, tok, options, placeholder))


def alive_options(sess, guild, exclude=(), only=None):
    g = sess.game
    uids = [u for u in g.alive if u not in exclude and (only is None or u in only)]
    return sorted(((name_of(guild, u), str(u)) for u in uids), key=lambda x: x[0])


async def reply(interaction, text, **kw):
    if interaction.response.is_done():
        await interaction.followup.send(text, ephemeral=True, **kw)
    else:
        await interaction.response.send_message(text, ephemeral=True, **kw)


async def show_my_role(sess, interaction):
    g = sess.game
    if not g or interaction.user.id not in g.roles:
        return await reply(interaction, "لست لاعبًا في هذه الجولة.")
    kw = role_embed(g.roles[interaction.user.id], interaction.guild, g, interaction.user.id)
    await interaction.response.send_message(ephemeral=True, **kw)


# ── القدرات الليلية ──
async def open_night(sess, tok, interaction):
    g, uid, guild = sess.game, interaction.user.id, interaction.guild
    if not g or sess.token != tok or sess.phase != "night":
        return await reply(interaction, "انتهى وقت هذه المرحلة.")
    if uid not in g.roles:
        return await reply(interaction, "لست لاعبًا في هذه الجولة.")
    if uid not in g.alive:
        return await reply(interaction, "💀 أنت خارج اللعبة.")
    role, a = g.roles[uid], sess.actions
    specs = []
    if role in WOLF_TEAM:
        specs.append(("wolf", "🐺 اختر ضحية القطيع", alive_options(sess, guild, only={u for u in g.alive if not g.is_wolf(u)})))
        if role == "white_wolf" and g.night % 2 == 0:
            others = {u for u in g.alive if g.is_wolf(u) and u != uid}
            if others:
                specs.append(("ww", "🤍 (اختياري) اقتل ذئبًا من رفاقك", alive_options(sess, guild, only=others)))
    elif role == "seer":
        if a.seer_done:
            return await reply(interaction, "🔮 استخدمتِ قدرتك هذه الليلة.")
        specs.append(("seer", "🔮 افحص لاعبًا", alive_options(sess, guild, exclude={uid})))
    elif role == "doctor":
        specs.append(("doctor", "🩺 احمِ لاعبًا", alive_options(sess, guild)))
    elif role == "guardian":
        specs.append(("guardian", "🛡️ احمِ لاعبًا (ليس نفس شخص الليلة الماضية)",
                      alive_options(sess, guild, exclude={g.guardian_last} if g.guardian_last else set())))
    elif role == "little_girl":
        if a.lg_done:
            return await reply(interaction, "👧 تجسّستِ بالفعل هذه الليلة.")
        view = CallbackView(timeout=120)
        view.add_button("👀 تجسّس (خطر 20%)", partial(little_girl_spy, sess, tok), discord.ButtonStyle.danger)
        return await interaction.response.send_message("هل تجرئين على التجسس؟", view=view, ephemeral=True)
    else:
        return await reply(interaction, "😴 لا قدرة لك هذه الليلة. أغمض عينيك وانتظر الفجر.")
    specs = [s for s in specs if s[2]]
    if not specs:
        return await reply(interaction, "لا توجد خيارات متاحة.")
    await interaction.response.send_message("اختر:", view=ChoiceView(sess, tok, specs), ephemeral=True)


async def little_girl_spy(sess, tok, interaction):
    g, a = sess.game, sess.actions
    if not g or sess.token != tok or sess.phase != "night" or g.roles.get(interaction.user.id) != "little_girl" \
            or interaction.user.id not in g.alive:
        return await reply(interaction, "انتهى وقت هذه المرحلة.")
    if a.lg_done:
        return await reply(interaction, "👧 تجسّستِ بالفعل هذه الليلة.")
    a.lg_done = True
    a.lg_caught = engine.roll_caught()
    hint = engine.little_girl_hint(g, interaction.user.id)
    names = "، ".join(name_of(interaction.guild, u) for u in hint) if hint else "لا ذئاب قريبة!"
    await interaction.response.edit_message(
        content=f"👀 رأيتِ ظلالًا بين: **{names}**\nواحد منهم ذئب.", view=None)


async def handle_choice(sess, interaction, kind, tok, value):
    g, uid, guild = sess.game, interaction.user.id, interaction.guild
    if not g:
        return await reply(interaction, "لا توجد جولة نشطة.")
    if uid not in g.alive and kind != "hunter":
        return await reply(interaction, "💀 أنت خارج اللعبة.")
    role = g.roles.get(uid)
    a = sess.actions

    # ----- ليلًا -----
    if kind in ("wolf", "ww", "seer", "doctor", "guardian"):
        if sess.token != tok or sess.phase != "night":
            return await interaction.response.edit_message(content="⏰ انتهى الوقت.", view=None)
        allowed = {"wolf": WOLF_TEAM, "ww": {"white_wolf"}, "seer": {"seer"},
                   "doctor": {"doctor"}, "guardian": {"guardian"}}[kind]
        if role not in allowed:
            return await reply(interaction, "غير مسموح.")
        target = int(value)
        if target not in g.alive:
            return await reply(interaction, "هذا اللاعب خارج اللعبة.")
        tname = name_of(guild, target)
        if kind == "wolf":
            if g.is_wolf(target):
                return await reply(interaction, "لا يمكنك اختيار ذئب.")
            a.wolf_votes[uid] = target
            await safe_send(guild.get_channel(sess.lair_id), f"🐺 **{name_of(guild, uid)}** اختار: **{tname}**")
            msg = f"🐺 سُجّل اختيارك: **{tname}** (يمكنك التغيير قبل انتهاء الوقت)"
        elif kind == "ww":
            if not g.is_wolf(target) or target == uid or g.night % 2 != 0:
                return await reply(interaction, "غير مسموح.")
            a.ww_target = target
            msg = f"🤍 سُجّل: ستقتل **{tname}**"
        elif kind == "seer":
            if a.seer_done:
                return await interaction.response.edit_message(content="استخدمتِ قدرتك بالفعل.", view=None)
            a.seer_done = True
            msg = f"🔮 **{tname}** " + ("**ذئب** 🐺" if g.is_wolf(target) else "**ليس ذئبًا** ✅")
        elif kind == "doctor":
            a.doctor = target
            msg = f"🩺 ستحمي **{tname}** هذه الليلة."
        else:
            if target == g.guardian_last:
                return await reply(interaction, "لا يجوز حماية نفس الشخص ليلتين متتاليتين.")
            a.guardian = target
            msg = f"🛡️ ستحمي **{tname}** هذه الليلة."
        return await interaction.response.edit_message(content=msg, view=None)

    # ----- الساحرة (سم) -----
    if kind == "witch_poison":
        if sess.token != tok or sess.phase != "witch" or role != "witch":
            return await interaction.response.edit_message(content="⏰ انتهى الوقت.", view=None)
        if a.witch_save or a.witch_poison is not None or not g.witch_poison:
            return await interaction.response.edit_message(content="لا يمكنك استخدام جرعة الآن.", view=None)
        a.witch_poison = int(value)
        return await interaction.response.edit_message(
            content=f"☠️ ستسممين **{name_of(guild, a.witch_poison)}** عند الفجر.", view=None)

    # ----- الصياد -----
    if kind == "hunter":
        fut = sess.hunter_future
        if not fut or fut.done() or uid != sess.hunter_uid:
            return await interaction.response.edit_message(content="⏰ انتهى الوقت.", view=None)
        fut.set_result(None if value == "none" else int(value))
        return await interaction.response.edit_message(content="🏹 تم إطلاق السهم.", view=None)

    # ----- التصويت -----
    if kind == "vote":
        if sess.token != tok or sess.phase != "vote":
            return await interaction.response.edit_message(content="⏰ انتهى التصويت.", view=None)
        sess.votes[uid] = None if value == "skip" else int(value)
        await interaction.response.edit_message(
            content="🗳️ سُجّل تصويتك: " + ("امتناع" if value == "skip" else f"**{name_of(guild, int(value))}**")
                    + " (يمكنك التغيير قبل انتهاء الوقت)", view=None)
        await refresh_vote_msg(sess, guild)
        if len(sess.votes) >= len(g.alive):
            sess.skip.set()


async def open_witch(sess, tok, interaction):
    g, uid, guild = sess.game, interaction.user.id, interaction.guild
    if not g or sess.token != tok or sess.phase != "witch":
        return await reply(interaction, "انتهى وقت هذه المرحلة.")
    if g.roles.get(uid) != "witch" or uid not in g.alive:
        return await reply(interaction, "😴 لا قدرة لك الآن.")
    a = sess.actions
    victim = a.wolf_target
    view = CallbackView(timeout=120)
    if g.witch_heal and victim is not None:
        view.add_button(f"💚 أنقذ {name_of(guild, victim)[:40]}", partial(witch_save, sess, tok), discord.ButtonStyle.success)
    if g.witch_poison:
        view.add_button("☠️ سمّم لاعبًا", partial(witch_poison_menu, sess, tok), discord.ButtonStyle.danger)
    view.add_button("⏭️ تمرير", partial(witch_pass, sess, tok), discord.ButtonStyle.secondary)
    txt = (f"ضحية الذئاب هذه الليلة: **{name_of(guild, victim)}**" if victim is not None
           else "الذئاب لم تختر ضحية هذه الليلة.")
    txt += f"\nجرعة الإنقاذ: {'✅' if g.witch_heal else '❌'} | جرعة السم: {'✅' if g.witch_poison else '❌'}"
    await interaction.response.send_message(txt, view=view, ephemeral=True)


def _witch_ok(sess, tok, interaction):
    g = sess.game
    return bool(g and sess.token == tok and sess.phase == "witch"
                and g.roles.get(interaction.user.id) == "witch" and interaction.user.id in g.alive)


async def witch_save(sess, tok, interaction):
    a = sess.actions
    if not _witch_ok(sess, tok, interaction) or not sess.game.witch_heal or a.wolf_target is None:
        return await interaction.response.edit_message(content="⏰ غير متاح.", view=None)
    if a.witch_save or a.witch_poison is not None:
        return await interaction.response.edit_message(content="استخدمتِ جرعة هذه الليلة.", view=None)
    a.witch_save = True
    await interaction.response.edit_message(content="💚 ستنقذين الضحية عند الفجر.", view=None)


async def witch_poison_menu(sess, tok, interaction):
    g, a = sess.game, sess.actions
    if not _witch_ok(sess, tok, interaction) or not g.witch_poison:
        return await interaction.response.edit_message(content="⏰ غير متاح.", view=None)
    if a.witch_save or a.witch_poison is not None:
        return await interaction.response.edit_message(content="استخدمتِ جرعة هذه الليلة.", view=None)
    opts = alive_options(sess, interaction.guild, exclude={interaction.user.id})
    if not opts:
        return await interaction.response.edit_message(content="لا أحد لتسميمه.", view=None)
    await interaction.response.edit_message(
        content="اختاري من تسممين:", view=ChoiceView(sess, tok, [("witch_poison", "☠️ اختاري الضحية", opts)]))


async def witch_pass(sess, tok, interaction):
    await interaction.response.edit_message(content="⏭️ مررتِ دورك.", view=None)


async def open_vote(sess, tok, interaction):
    g, uid = sess.game, interaction.user.id
    if not g or sess.token != tok or sess.phase != "vote":
        return await reply(interaction, "انتهى التصويت.")
    if uid not in g.alive:
        return await reply(interaction, "💀 الموتى لا يصوّتون.")
    opts = alive_options(sess, interaction.guild, exclude={uid}) + [("⏭️ امتناع", "skip")]
    await interaction.response.send_message(
        "اختر من تريد إقصاءه:", view=ChoiceView(sess, tok, [("vote", "🗳️ صوّتك سري", opts)]), ephemeral=True)


async def open_hunter(sess, interaction):
    g = sess.game
    if not g or not sess.hunter_future or sess.hunter_future.done() or interaction.user.id != sess.hunter_uid:
        return await reply(interaction, "هذا الزر للصياد فقط.")
    opts = alive_options(sess, interaction.guild) + [("🚫 لا أطلق", "none")]
    await interaction.response.send_message(
        "اختر هدفك الأخير:", view=ChoiceView(sess, 0, [("hunter", "🏹 هدفك", opts)]), ephemeral=True)


async def refresh_vote_msg(sess, guild):
    if sess.vote_msg and sess.game:
        try:
            await sess.vote_msg.edit(content=f"🗳️ **التصويت مفتوح** — صوّت {len(sess.votes)}/{len(sess.game.alive)}")
        except discord.HTTPException:
            pass


# ───────────────────────── محرك الجولة ─────────────────────────
async def wait_phase(sess, seconds):
    sess.skip.clear()
    try:
        await asyncio.wait_for(sess.skip.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass


async def night(sess, guild):
    g = sess.game
    ch = game_ch(sess, guild)
    g.night += 1
    sess.actions = NightActions()
    sess.phase, sess.token = "night", sess.token + 1
    tok = sess.token
    await apply_mutes(sess, guild)
    await start_ambience(sess, guild)
    view = CallbackView(timeout=None)
    view.add_button("🌙 افتح قدرتك الليلية", partial(open_night, sess, tok))
    extra = "\n🤍 *ليلة زوجية: للذئب الأبيض قدرة خاصة.*" if g.night % 2 == 0 and g.uids_with("white_wolf") else ""
    await safe_send(ch, f"🌑 **الليلة {g.night}** — حلّ الظلام، التزموا الصمت.\n"
                        f"اضغطوا الزر أدناه (الجميع، حتى من لا قدرة له، لإخفاء الأدوار). المدة: {NIGHT_SECONDS}ث{extra}", view=view)
    await wait_phase(sess, NIGHT_SECONDS)
    a = sess.actions
    a.wolf_target = engine.pick_wolf_target(g, a)

    if g.uids_with("witch"):                       # تُنفَّذ دائمًا لإخفاء حياة/وجود الساحرة
        sess.phase, sess.token = "witch", sess.token + 1
        wtok = sess.token
        wv = CallbackView(timeout=None)
        wv.add_button("🧙‍♀️ مرحلة الساحرة", partial(open_witch, sess, wtok), discord.ButtonStyle.secondary)
        await safe_send(ch, f"🧙‍♀️ **تستيقظ الساحرة...** ({WITCH_SECONDS}ث)", view=wv)
        await wait_phase(sess, WITCH_SECONDS)

    deaths = engine.resolve_night(g, a)
    sess.phase, sess.token = "dawn", sess.token + 1
    await stop_ambience(sess, guild)
    await apply_mutes(sess, guild)
    await play_cue(sess, guild)
    if deaths:
        await safe_send(ch, f"🌅 **طلع الفجر على الليلة {g.night}...**")
        await process_deaths(sess, guild, deaths)
    else:
        await safe_send(ch, f"🌅 **طلع الفجر.** مرّت الليلة {g.night} بسلام، لم يمت أحد! 🎉")
    return g.check_win()


async def day(sess, guild):
    g = sess.game
    ch = game_ch(sess, guild)
    sess.phase, sess.token = "day", sess.token + 1
    await apply_mutes(sess, guild)
    alive = "، ".join(name_of(guild, u) for u in sorted(g.alive))
    await safe_send(ch, f"☀️ **النهار** — ناقشوا واكشفوا الذئاب! ({DAY_SECONDS}ث)\n👥 الأحياء ({len(g.alive)}): {alive}")
    await wait_phase(sess, DAY_SECONDS)

    sess.phase, sess.token = "vote", sess.token + 1
    tok = sess.token
    sess.votes = {}
    vch = find_text(guild, CH_VOTE) or ch
    view = CallbackView(timeout=None)
    view.add_button("🗳️ صوّت", partial(open_vote, sess, tok))
    sess.vote_msg = await safe_send(vch, f"🗳️ **التصويت مفتوح** — صوّت 0/{len(g.alive)}", view=view)
    if vch != ch:
        await safe_send(ch, f"🗳️ حان وقت التصويت في {vch.mention} ({VOTE_SECONDS}ث)")
    await wait_phase(sess, VOTE_SECONDS)

    sess.phase, sess.token = "dusk", sess.token + 1
    if sess.vote_msg:
        try:
            await sess.vote_msg.edit(content="🗳️ **انتهى التصويت.**", view=None)
        except discord.HTTPException:
            pass
    counts, target, tied = engine.tally_votes(g, sess.votes)
    lines = [f"• {name_of(guild, t)}: **{c}**" for t, c in sorted(counts.items(), key=lambda x: -x[1])]
    result = "\n".join(lines) or "لم يصوّت أحد ضد أحد."
    await safe_send(ch, f"📊 **نتيجة التصويت**\n{result}")
    if target is None:
        await safe_send(ch, "⚖️ " + ("تعادلت الأصوات" if tied else "لا أغلبية") + " — لا إقصاء اليوم.")
    else:
        await process_deaths(sess, guild, [(target, "vote")])
    return g.check_win()


async def process_deaths(sess, guild, deaths):
    g = sess.game
    ch = game_ch(sess, guild)
    queue = list(deaths)
    while queue:
        uid, cause = queue.pop(0)
        if uid not in g.alive:
            continue
        g.alive.discard(uid)
        role = g.roles[uid]
        ar, _, emoji, _ = ROLE_INFO[role]
        await safe_send(ch, f"💀 **{name_of(guild, uid)}** — {CAUSE[cause]}.\nكان: {emoji} **{ar}**")
        await apply_mutes(sess, guild, only=uid)
        if role == "hunter":
            tgt = await hunter_shot(sess, guild, uid)
            if tgt:
                queue.append((tgt, "hunter"))


async def hunter_shot(sess, guild, uid):
    g, ch = sess.game, game_ch(sess, guild)
    if not g.alive:
        return None
    sess.hunter_future = asyncio.get_running_loop().create_future()
    sess.hunter_uid = uid
    view = CallbackView(timeout=None)
    view.add_button("🏹 اختر هدفك", partial(open_hunter, sess), discord.ButtonStyle.danger)
    msg = await safe_send(ch, f"🏹 <@{uid}> أنت **الصياد**! أمامك {HUNTER_SECONDS}ث لإطلاق سهمك الأخير.", view=view)
    try:
        tgt = await asyncio.wait_for(sess.hunter_future, HUNTER_SECONDS)
    except asyncio.TimeoutError:
        tgt = None
    finally:
        sess.hunter_future = None
    if msg:
        try:
            await msg.edit(view=None)
        except discord.HTTPException:
            pass
    if tgt is None:
        await safe_send(ch, "🏹 الصياد لم يطلق سهمه.")
    return tgt


async def finish_game(sess, guild, winner):
    g = sess.game
    ch = game_ch(sess, guild)
    title = {"villagers": "🏆 **فاز القرويون!** تخلّصوا من كل الذئاب.",
             "wolves": "🐺 **فازت الذئاب!** سيطرت على القرية.",
             "white_wolf": "🤍 **فاز الذئب الأبيض وحده!** خان الجميع."}[winner]
    winners = g.winners(winner)
    reveal = "\n".join(
        f"{'🏅' if u in winners else '▫️'} {name_of(guild, u)} — {ROLE_INFO[r][2]} {ROLE_INFO[r][0]}"
        f"{'' if u in g.alive else ' 💀'}" for u, r in g.roles.items())
    embed = discord.Embed(title="🌕 انتهت الجولة", description=f"{title}\n\n**كشف الأدوار:**\n{reveal}",
                          colour=discord.Colour.gold())
    for ch_ in {ch, find_text(guild, CH_ANN)}:
        await safe_send(ch_, embed=embed)
    for uid in g.roles:
        total = db.add(guild.id, uid, XP_PLAY + (XP_WIN if uid in winners else 0), 1, 1 if uid in winners else 0)
        m = guild.get_member(uid)
        if m:
            await update_level_roles(m, total)
    await cleanup(sess, guild)


async def cleanup(sess, guild):
    await stop_ambience(sess, guild)
    voice_id, lair_id = sess.voice_id, sess.lair_id
    if sess.hunter_future and not sess.hunter_future.done():
        sess.hunter_future.cancel()
    sess.hunter_future = None
    sess.game, sess.actions, sess.vote_msg = None, None, None
    sess.phase, sess.token, sess.players, sess.votes = "idle", sess.token + 1, [], {}
    sess.lair_id, sess.warned_mute = 0, False
    await release_mutes(guild, voice_id)
    lair = guild.get_channel(lair_id) if lair_id else None
    if lair:
        try:
            await lair.delete(reason="Loup-Garou: نهاية الجولة")
        except discord.HTTPException:
            pass


async def run_game(sess, guild):
    try:
        winner = None
        while winner is None:
            winner = await night(sess, guild) or await day(sess, guild)
        await finish_game(sess, guild, winner)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("انهارت الجولة")
        await safe_send(game_ch(sess, guild), "⚠️ حدث خطأ غير متوقع وتم إنهاء الجولة بدون احتساب نقاط.")
        await cleanup(sess, guild)


# ───────────────────────── العميل والأوامر ─────────────────────────
class LGTree(app_commands.CommandTree):
    async def interaction_check(self, interaction):
        if interaction.guild is None:
            await interaction.response.send_message("هذا الأمر يعمل داخل السيرفرات فقط.", ephemeral=True)
            return False
        return True

    async def on_error(self, interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            msg = "تحتاج صلاحية Administrator لاستخدام هذا الأمر."
        else:
            log.error("Command error", exc_info=error)
            msg = "حدث خطأ أثناء تنفيذ الأمر. تأكد من صلاحيات البوت وإعداداته."
        try:
            await reply(interaction, msg)
        except discord.HTTPException:
            pass


class LGClient(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True            # يتطلب تفعيل Server Members Intent في Developer Portal
        intents.voice_states = True
        super().__init__(intents=intents)
        self.tree = LGTree(self)
        self._ready_once = False

    async def setup_hook(self):
        if GUILD_ID:
            g = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=g)      # (النسخة القديمة كانت تزامن 0 أمر بدون هذا السطر)
            synced = await self.tree.sync(guild=g)
        else:
            synced = await self.tree.sync()
        log.info("تمت مزامنة %s أمرًا", len(synced))
        await start_health_server()

    async def on_ready(self):
        log.info("Logged in as %s | FFmpeg: %s", self.user, "✅" if FFMPEG_OK else "❌ (بدون مؤثرات صوتية)")
        if self._ready_once:
            return
        self._ready_once = True
        for guild in self.guilds:                  # استرجاع بعد انهيار/إعادة تشغيل: فك كتم قناة القرية
            vc = discord.utils.get(guild.voice_channels, name=CH_VOICE)
            if vc:
                await release_mutes(guild, vc.id)

    async def on_voice_state_update(self, member, before, after):
        sess = sessions.get(member.guild.id)
        if (sess and sess.game and not member.bot and after.channel
                and after.channel.id == sess.voice_id and (not before.channel or before.channel.id != after.channel.id)):
            await apply_mutes(sess, member.guild, only=member.id)


bot = LGClient()
tree = bot.tree


async def start_health_server():
    port = os.getenv("PORT")
    if not port:
        return
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Loup-Garou bot is running"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(port)).start()
    log.info("Health server on :%s", port)


@tree.command(name="setup", description="إنشاء قنوات ورولات Loup-Garou تلقائيًا")
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
async def setup_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    guild = interaction.guild
    try:
        category = discord.utils.get(guild.categories, name=CAT_NAME) or await guild.create_category(CAT_NAME)
        made = {}
        for name, voice in [(CH_RULES, 0), (CH_ANN, 0), (CH_GAME, 0), (CH_ROLES, 0), (CH_VOTE, 0), (CH_VOICE, 1)]:
            ch = discord.utils.get(category.channels, name=name)
            if ch is None:
                ch = (await guild.create_voice_channel(name, category=category) if voice
                      else await guild.create_text_channel(name, category=category))
            made[name] = ch
        await ensure_role(guild, ROLE_PLAYER, discord.Colour.blue())
        await ensure_role(guild, ROLE_MANAGER, discord.Colour.red())
        for threshold, label in LEVELS:
            await ensure_role(guild, f"المستوى {threshold}・{label}",
                              discord.Colour.gold() if threshold >= 15 else discord.Colour.blurple())
    except discord.Forbidden:
        return await interaction.followup.send("❌ ينقص البوت صلاحية **Manage Channels / Manage Roles**.", ephemeral=True)
    await safe_send(made[CH_RULES],
                    "## 🐺 قوانين Loup-Garou\n"
                    "1. ممنوع كشف الدور عبر لقطة شاشة أو مشاركة الرسائل السرية.\n"
                    "2. احترم اللاعبين ولا تستخدم الإهانة أو الإزعاج.\n"
                    "3. في الليل التزم الصمت؛ البوت يكتم الجميع تلقائيًا في قناة الصوت.\n"
                    "4. لا تستخدم معلومات خارج اللعبة للتأثير على التصويت.\n"
                    "5. الموتى يلتزمون الصمت حتى نهاية الجولة.\n"
                    "6. قرارات مدير الجولة تنظّم الجولة، وأي خلاف يُناقش بعد انتهائها.")
    await safe_send(made[CH_ROLES], "## 🎭 دليل الأدوار\n" + "\n".join(
        f"{v[2]} **{v[0]}** — {v[3]}" for v in ROLE_INFO.values()))
    await safe_send(made[CH_ANN], "🌕 مرحبًا بكم في قرية Loup-Garou! استخدموا `/join` للانضمام ثم `/start`.")
    await interaction.followup.send(
        "✅ تم تجهيز الفئة والقنوات والرولات.\n• عيّن المدير بـ `/setmanager`.\n"
        "• ارفع رول البوت فوق رولات اللاعبين، وتأكد من: Manage Channels, Manage Roles, Mute Members, Connect, Speak.",
        ephemeral=True)


@tree.command(name="setmanager", description="تعيين عضو كمدير للعبة")
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(member="العضو الذي سيبدأ ويوقف الجولات")
async def setmanager(interaction: discord.Interaction, member: discord.Member):
    role = await ensure_role(interaction.guild, ROLE_MANAGER, discord.Colour.red())
    await member.add_roles(role, reason="Loup-Garou manager")
    db.set_manager_role(interaction.guild_id, role.id)       # محفوظ في القاعدة (لا يضيع بالإعادة)
    await interaction.response.send_message(f"✅ {member.mention} أصبح مديرًا للعبة.", ephemeral=True)


@tree.command(name="join", description="الانضمام إلى الجولة القادمة")
async def join_cmd(interaction: discord.Interaction):
    sess = get_session(interaction.guild_id)
    if sess.phase != "idle":
        return await interaction.response.send_message("الجولة بدأت بالفعل؛ انتظر الجولة القادمة.", ephemeral=True)
    if interaction.user.id in sess.players:
        return await interaction.response.send_message("أنت في القائمة بالفعل.", ephemeral=True)
    if len(sess.players) >= MAX_PLAYERS:
        return await interaction.response.send_message(f"القائمة ممتلئة ({MAX_PLAYERS}).", ephemeral=True)
    sess.players.append(interaction.user.id)
    role = discord.utils.get(interaction.guild.roles, name=ROLE_PLAYER)
    if role and role not in interaction.user.roles:
        try:
            await interaction.user.add_roles(role)
        except discord.HTTPException:
            pass
    await interaction.response.send_message(
        f"🐺 {interaction.user.mention} انضم! العدد: **{len(sess.players)}** (الحد الأدنى {MIN_PLAYERS}).")


@tree.command(name="leave", description="مغادرة قائمة الجولة قبل بدايتها")
async def leave_cmd(interaction: discord.Interaction):
    sess = get_session(interaction.guild_id)
    if sess.phase != "idle":
        return await interaction.response.send_message("لا يمكن المغادرة بعد بدء الجولة.", ephemeral=True)
    if interaction.user.id in sess.players:
        sess.players.remove(interaction.user.id)
    await interaction.response.send_message("تمت إزالتك من القائمة.", ephemeral=True)


async def create_lair(guild, game):
    cat = discord.utils.get(guild.categories, name=CAT_NAME)
    ow = {guild.default_role: discord.PermissionOverwrite(view_channel=False),
          guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True)}
    for u, r in game.roles.items():
        if r in WOLF_TEAM:
            m = guild.get_member(u)
            if m:
                ow[m] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
    try:
        ch = await guild.create_text_channel(CH_LAIR, category=cat, overwrites=ow, reason="Loup-Garou wolves lair")
        await ch.send("🐺 **عرين الذئاب** — تشاوروا هنا سرًا، ثم اختاروا الضحية بزر الليل في غرفة اللعبة.")
        return ch.id
    except discord.HTTPException:
        log.warning("تعذّر إنشاء عرين الذئاب")
        return 0


@tree.command(name="start", description="بدء الجولة وتشغيلها تلقائيًا (ليل/نهار/تصويت)")
async def start_cmd(interaction: discord.Interaction):
    guild = interaction.guild
    sess = get_session(guild.id)
    xp = db.stats(guild.id, interaction.user.id)[0]
    if not (is_manager(interaction) or level_for(xp) >= 5):
        return await interaction.response.send_message(
            "تحتاج رتبة إدارة Loup-Garou أو المستوى 5 (5 نقاط خبرة) لبدء جولة.", ephemeral=True)
    if sess.phase != "idle":
        return await interaction.response.send_message("هناك جولة نشطة بالفعل.", ephemeral=True)
    await interaction.response.defer()
    sess.phase = "starting"
    members = []
    for uid in dict.fromkeys(sess.players):
        m = await get_member(guild, uid)
        if m and not m.bot:
            members.append(m)
    if len(members) < MIN_PLAYERS:
        sess.phase = "idle"
        return await interaction.followup.send(f"تحتاج الجولة إلى {MIN_PLAYERS} لاعبين على الأقل. استخدموا `/join` أولًا.")

    role_list = engine.build_roles(len(members))
    sess.game = Game(roles={m.id: r for m, r in zip(members, role_list)})
    sess.players = [m.id for m in members]
    sess.channel_id = interaction.channel_id
    sess.votes, sess.warned_mute = {}, False
    voice = discord.utils.get(guild.voice_channels, name=CH_VOICE)
    sess.voice_id = voice.id if voice else 0
    if voice:
        await ensure_voice(guild, voice)
    sess.lair_id = await create_lair(guild, sess.game)

    dm_failed = []
    for m in members:
        try:
            await m.send(**role_embed(sess.game.roles[m.id], guild, sess.game, m.id))
        except discord.HTTPException:
            dm_failed.append(m.mention)
        await asyncio.sleep(0.3)

    comp = {}
    for r in role_list:
        comp[r] = comp.get(r, 0) + 1
    comp_txt = "، ".join(f"{ROLE_INFO[r][2]} {ROLE_INFO[r][0]} ×{n}" for r, n in comp.items())
    view = CallbackView(timeout=None)
    view.add_button("🎭 اعرض دوري (سري)", partial(show_my_role, sess), discord.ButtonStyle.secondary)
    await interaction.followup.send(
        f"🌕 **بدأت الجولة!** اللاعبون: **{len(members)}**\n📋 التشكيلة: {comp_txt}\n"
        "وصلتكم بطاقة الدور في الخاص — أو اضغطوا الزر أدناه إن لم تصلكم.\n"
        f"ستبدأ الليلة الأولى بعد لحظات. ادخلوا قناة الصوت وسيتولى البوت الكتم تلقائيًا.", view=view)
    if dm_failed:
        await interaction.followup.send("⚠️ تعذّر إرسال البطاقة الخاصة إلى: " + "، ".join(dm_failed) +
                                        "\nيمكنهم استخدام زر «اعرض دوري».", ephemeral=True)
    await asyncio.sleep(START_DELAY)
    if sess.game is None:            # أُوقفت الجولة (/stop) أثناء الانتظار
        return
    sess.task = asyncio.create_task(run_game(sess, guild))


@tree.command(name="skip", description="(المدير) إنهاء المرحلة الحالية مبكرًا")
async def skip_cmd(interaction: discord.Interaction):
    if not is_manager(interaction):
        return await interaction.response.send_message("هذا الأمر خاص بمدير اللعبة.", ephemeral=True)
    sess = get_session(interaction.guild_id)
    if sess.phase not in ("night", "witch", "day", "vote"):
        return await interaction.response.send_message("لا توجد مرحلة قابلة للتخطي الآن.", ephemeral=True)
    sess.skip.set()
    await interaction.response.send_message("⏭️ تم تخطي المرحلة.", ephemeral=True)


@tree.command(name="stop", description="(المدير) إيقاف الجولة بدون احتساب نقاط")
async def stop_cmd(interaction: discord.Interaction):
    if not is_manager(interaction):
        return await interaction.response.send_message("هذا الأمر خاص بمدير اللعبة.", ephemeral=True)
    guild, sess = interaction.guild, get_session(interaction.guild_id)
    if sess.phase == "idle":
        sess.players.clear()
        return await interaction.response.send_message("لا توجد جولة نشطة. تم تفريغ قائمة الانتظار.", ephemeral=True)
    await interaction.response.defer()
    if sess.task and not sess.task.done():
        sess.task.cancel()
    await cleanup(sess, guild)
    await interaction.followup.send("🛑 تم إيقاف الجولة وإلغاء الكتم. (لا نقاط خبرة لجولة موقوفة)")


@tree.command(name="connect", description="جعل البوت يدخل قناة قرية الصوت")
@app_commands.describe(channel="قناة الصوت (اختياري)")
async def connect_cmd(interaction: discord.Interaction, channel: discord.VoiceChannel = None):
    if not is_manager(interaction):
        return await interaction.response.send_message("هذا الأمر خاص بمدير اللعبة.", ephemeral=True)
    target = channel or discord.utils.get(interaction.guild.voice_channels, name=CH_VOICE)
    if not target:
        return await interaction.response.send_message("لم أجد قناة الصوت. شغّل `/setup` أولًا.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    vc = await ensure_voice(interaction.guild, target)
    if vc:
        get_session(interaction.guild_id).voice_id = target.id
        await interaction.followup.send(f"🔊 دخلت {target.mention}." + ("" if FFMPEG_OK else "\n⚠️ FFmpeg غير مثبت: لا مؤثرات صوتية."),
                                        ephemeral=True)
    else:
        await interaction.followup.send("تعذّر دخول الصوت (PyNaCl / davey / opus / الصلاحيات). الكتم التلقائي يعمل بدون دخول البوت.",
                                        ephemeral=True)


@tree.command(name="vote", description="التصويت لإخراج لاعب نهارًا (بديل عن زر التصويت)")
@app_commands.describe(target="اللاعب الذي تصوّت ضده")
async def vote_cmd(interaction: discord.Interaction, target: discord.Member):
    sess = get_session(interaction.guild_id)
    g = sess.game
    if not g or sess.phase != "vote":
        return await interaction.response.send_message("التصويت غير مفتوح الآن.", ephemeral=True)
    if interaction.user.id not in g.alive or target.id not in g.alive or target.id == interaction.user.id:
        return await interaction.response.send_message("تصويت غير صالح (لاعبون أحياء فقط، وليس نفسك).", ephemeral=True)
    sess.votes[interaction.user.id] = target.id
    await interaction.response.send_message(f"🗳️ سُجّل تصويتك ضد {target.mention}.", ephemeral=True)
    await refresh_vote_msg(sess, interaction.guild)
    if len(sess.votes) >= len(g.alive):
        sess.skip.set()


@tree.command(name="roles", description="عرض بطاقات الأدوار وشروحاتها")
async def roles_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    for key in ROLE_INFO:
        kw = role_embed(key, interaction.guild)
        kw["embed"].title = f"{ROLE_INFO[key][2]} {ROLE_INFO[key][0]} / {ROLE_INFO[key][1]}"
        kw["embed"].clear_fields()
        await interaction.followup.send(ephemeral=True, **kw)


@tree.command(name="status", description="حالة الجولة والأحياء")
async def status_cmd(interaction: discord.Interaction):
    guild, sess = interaction.guild, get_session(interaction.guild_id)
    g = sess.game
    if not g:
        names = "، ".join(name_of(guild, u) for u in sess.players) or "—"
        return await interaction.response.send_message(
            f"⏳ لا جولة نشطة. قائمة الانتظار ({len(sess.players)}/{MIN_PLAYERS}+): {names}", ephemeral=True)
    alive = "، ".join(name_of(guild, u) for u in g.alive)
    dead = "، ".join(name_of(guild, u) for u in g.roles if u not in g.alive) or "—"
    await interaction.response.send_message(
        f"المرحلة: **{sess.phase}** | الليلة: **{g.night}**\n🟢 الأحياء ({len(g.alive)}): {alive}\n💀 الموتى: {dead}", ephemeral=True)


@tree.command(name="rank", description="مستواك ونقاطك")
@app_commands.describe(member="عضو آخر (اختياري)")
async def rank_cmd(interaction: discord.Interaction, member: discord.Member = None):
    m = member or interaction.user
    xp, games, wins = db.stats(interaction.guild_id, m.id)
    lvl = level_for(xp)
    label = dict(LEVELS)[lvl]
    nxt = next((t for t, _ in LEVELS if t > lvl), None)
    await interaction.response.send_message(
        f"**{m.display_name}** — {label}\n⭐ الخبرة: **{xp}** | 🎮 الجولات: **{games}** | 🏆 الفوز: **{wins}**"
        + (f"\nالمستوى التالي عند **{nxt}** نقطة." if nxt else "\n👑 وصلت إلى أعلى مستوى!"), ephemeral=True)


@tree.command(name="top", description="لوحة المتصدرين")
async def top_cmd(interaction: discord.Interaction):
    rows = db.top(interaction.guild_id, 10)
    if not rows:
        return await interaction.response.send_message("لا بيانات بعد. العبوا جولة أولًا!", ephemeral=True)
    medals = ["🥇", "🥈", "🥉"] + ["▫️"] * 7
    text = "\n".join(f"{medals[i]} {name_of(interaction.guild, u)} — ⭐ {xp} | 🏆 {w}" for i, (u, xp, _, w) in enumerate(rows))
    await interaction.response.send_message("**🏆 المتصدرون**\n" + text)


@tree.command(name="help_lg", description="دليل أوامر Loup-Garou")
async def help_cmd(interaction: discord.Interaction):
    await interaction.response.send_message(
        "**🐺 أوامر Loup-Garou**\n"
        "`/setup` تجهيز القنوات والرولات • `/setmanager` تعيين مدير\n"
        "`/join` `/leave` الانضمام/المغادرة • `/start` بدء الجولة (تلقائية بالكامل)\n"
        "`/skip` تخطي المرحلة • `/stop` إيقاف الجولة • `/connect` دخول قناة الصوت\n"
        "`/vote` تصويت (أو زر التصويت) • `/status` الحالة • `/roles` الأدوار\n"
        "`/rank` مستواك • `/top` المتصدرون\n\n"
        "الليل والنهار والتصويت وقدرات الأدوار والكتم والفوز تتم تلقائيًا. النقاط محفوظة في قاعدة بيانات SQLite.",
        ephemeral=True)


def main():
    if not TOKEN:
        print("❌ DISCORD_TOKEN غير موجود. انسخ .env.example إلى .env وضع التوكن، أو اضبطه كمتغير بيئة في الاستضافة.")
        sys.exit(1)
    try:
        bot.run(TOKEN, log_handler=None)
    except discord.PrivilegedIntentsRequired:
        print("❌ فعّل **Server Members Intent** من Developer Portal ← Bot ← Privileged Gateway Intents ثم أعد التشغيل.")
        sys.exit(1)
    except discord.LoginFailure:
        print("❌ توكن البوت غير صحيح. أعد توليده من Developer Portal.")
        sys.exit(1)


if __name__ == "__main__":
    main()
