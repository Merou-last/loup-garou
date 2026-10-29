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
import site_api
from db import make_database
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
SITE_URL = os.getenv("SITE_URL", "").strip()                 # رابط موقع Blogger (يظهر في /site)
SITE_ORIGINS = site_api.allowed_origins(os.getenv("SITE_ORIGINS", "*"))   # الأصول المسموح لها بقراءة الـ API
DEFAULT_INVITE = os.getenv("DISCORD_INVITE", "").strip()

BASE = Path(__file__).parent
ASSETS = BASE / "assets"
AUDIO = os.getenv("DISABLE_AUDIO", "") != "1"      # DISABLE_AUDIO=1 يعطّل الصوت (مفيد على استضافات ضعيفة)
FFMPEG_OK = AUDIO and shutil.which("ffmpeg") is not None

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
LEVELS = [(1, "🐺 مبتدئ"), (5, "🌙 لاعب متمرس"), (10, "🩸 صياد الليل"), (15, "👁️ عارف الأسرار"), (20, "👑 أسطورة القرية"), (30, "🌑 سيد الظلام"), (50, "🐺 ملك الذئاب")]
XP_PLAY, XP_WIN = 2, 3

db = make_database(DB_PATH)


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
    lobby_message_id: int = 0
    lobby_channel_id: int = 0
    speech_control: bool = False
    current_speaker: int = 0
    speaker_index: int = 0
    turn_requests: list = field(default_factory=list)
    extra_turns: list = field(default_factory=list)
    original_nicks: dict = field(default_factory=dict)  # uid -> nickname before this game
    death_causes: dict = field(default_factory=dict)    # uid -> public cause of death


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
    if sess.phase in ("night", "witch"):
        return True
    if sess.phase == "day" and sess.speech_control:
        return member_id != sess.current_speaker
    return False


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


async def lock_game_voice(guild, channel, members, locked=True):
    """أثناء الجولة يمنع دخول المتفرجين إلى قناة الصوت ويُبقي لاعبي الجولة مسموحًا لهم."""
    try:
        if locked:
            await channel.set_permissions(guild.default_role, connect=False, reason="Loup-Garou: lock voice lobby")
            for member in members:
                await channel.set_permissions(member, connect=True, reason="Loup-Garou: allow active player")
        else:
            await channel.set_permissions(guild.default_role, connect=None, reason="Loup-Garou: reopen voice lobby")
            # إزالة استثناءات الدخول التي أضافها البوت للاعبين الحاليين.
            for member in members:
                ow = channel.overwrites_for(member)
                if ow.connect is True:
                    await channel.set_permissions(member, overwrite=None, reason="Loup-Garou: cleanup player access")
    except discord.HTTPException:
        log.warning("تعذر تغيير صلاحيات دخول قناة الصوت", exc_info=True)


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



class ControlPanelView(discord.ui.View):
    """لوحة تحكم تفاعلية دائمة؛ صلاحيات الإدارة تُفحص عند كل ضغطة."""
    def __init__(self):
        super().__init__(timeout=None)

    async def _manager_only(self, interaction):
        if not is_manager(interaction):
            await reply(interaction, "🔒 هذا الزر مخصص لمدير اللعبة أو مسؤول السيرفر.")
            return False
        return True

    @discord.ui.button(label="بدء الجولة", emoji="▶️", style=discord.ButtonStyle.success, custom_id="lg:panel:start", row=0)
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._manager_only(interaction): return
        await start_cmd.callback(interaction)

    @discord.ui.button(label="حالة اللعبة", emoji="📊", style=discord.ButtonStyle.primary, custom_id="lg:panel:status", row=0)
    async def status_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        sess = get_session(interaction.guild_id)
        g = sess.game
        if not g:
            names = "، ".join(name_of(interaction.guild, u) for u in sess.players) or "لا يوجد لاعبون بعد"
            return await reply(interaction, f"⏳ لا توجد جولة نشطة. التسجيل: {len(sess.players)}/{MAX_PLAYERS}\n{names}")
        alive = "، ".join(name_of(interaction.guild, u) for u in g.alive) or "—"
        dead = "، ".join(name_of(interaction.guild, u) for u in g.roles if u not in g.alive) or "—"
        em = discord.Embed(title="📊 مركز حالة الجولة", colour=discord.Colour.from_rgb(30, 43, 75))
        em.add_field(name="المرحلة", value=f"`{sess.phase}` • الليلة {g.night}", inline=True)
        em.add_field(name="الأحياء", value=f"{len(g.alive)}\n{alive[:900]}", inline=True)
        em.add_field(name="المتوفون", value=dead[:1000], inline=False)
        await interaction.response.send_message(embed=em, ephemeral=True)

    @discord.ui.button(label="تخطي المرحلة", emoji="⏭️", style=discord.ButtonStyle.secondary, custom_id="lg:panel:skip", row=1)
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._manager_only(interaction): return
        await skip_cmd.callback(interaction)

    @discord.ui.button(label="إيقاف الجولة", emoji="🛑", style=discord.ButtonStyle.danger, custom_id="lg:panel:stop", row=1)
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._manager_only(interaction): return
        await stop_cmd.callback(interaction)

    @discord.ui.button(label="تعليمات اللعب", emoji="📜", style=discord.ButtonStyle.secondary, custom_id="lg:panel:help", row=1)
    async def help_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        em = discord.Embed(title="🐺 دليل القرية", description="1. اضغط الانضمام في لوحة التسجيل.\n2. استلم بطاقتك سرًا في الخاص.\n3. نفّذ قدرة دورك أثناء الليل.\n4. ناقش الأدلة نهارًا وصوّت سرًا.\n5. لا تكشف رسائلك الخاصة أو دورك.\n\n**أوامر الإدارة:** `/lobby` و`/start` و`/skip` و`/stop`.", colour=discord.Colour.from_rgb(38, 48, 82))
        await interaction.response.send_message(embed=em, ephemeral=True)


class LobbyView(discord.ui.View):
    """واجهة انضمام دائمة نسبيًا؛ يتم رفض التفاعل إذا بدأت الجولة."""
    def __init__(self, guild_id):
        super().__init__(timeout=None)
        self.guild_id = guild_id

    @discord.ui.button(label="انضم إلى القرية", emoji="🐺", style=discord.ButtonStyle.success, custom_id="lg:lobby:join")
    async def join_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        sess = get_session(interaction.guild_id)
        if sess.phase != "idle":
            return await reply(interaction, "🔒 بدأت الجولة وأُغلقت قائمة الانضمام.")
        if interaction.user.bot:
            return await reply(interaction, "البوتات لا تشارك في اللعبة.")
        if interaction.user.id in sess.players:
            return await reply(interaction, "أنت مسجل بالفعل في قائمة الجولة.")
        if len(sess.players) >= MAX_PLAYERS:
            return await reply(interaction, f"اكتمل الحد الأقصى ({MAX_PLAYERS} لاعبًا).")
        sess.players.append(interaction.user.id)
        role = discord.utils.get(interaction.guild.roles, name=ROLE_PLAYER)
        if role and role not in interaction.user.roles:
            try: await interaction.user.add_roles(role, reason="Loup-Garou lobby join")
            except discord.HTTPException: pass
        await update_lobby_panel(interaction.guild, sess)
        await reply(interaction, "✅ تم تسجيلك في الجولة القادمة.")

    @discord.ui.button(label="انسحب من القائمة", emoji="🚪", style=discord.ButtonStyle.secondary, custom_id="lg:lobby:leave")
    async def leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        sess = get_session(interaction.guild_id)
        if sess.phase != "idle":
            return await reply(interaction, "🔒 لا يمكن الانسحاب بعد بدء الجولة.")
        if interaction.user.id not in sess.players:
            return await reply(interaction, "أنت لست ضمن قائمة الانتظار.")
        sess.players.remove(interaction.user.id)
        await update_lobby_panel(interaction.guild, sess)
        await reply(interaction, "تم حذفك من قائمة الانتظار.")

    @discord.ui.button(label="تحديث القائمة", emoji="🔄", style=discord.ButtonStyle.primary, custom_id="lg:lobby:refresh")
    async def refresh_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        sess = get_session(interaction.guild_id)
        await update_lobby_panel(interaction.guild, sess)
        await reply(interaction, "تم تحديث قائمة اللاعبين.")


async def update_lobby_panel(guild, sess):
    if not sess.lobby_message_id or not sess.lobby_channel_id:
        return
    channel = guild.get_channel(sess.lobby_channel_id)
    if not isinstance(channel, discord.TextChannel):
        return
    try:
        msg = await channel.fetch_message(sess.lobby_message_id)
        names = []
        for uid in sess.players:
            member = guild.get_member(uid)
            names.append(f"• {member.display_name if member else f'لاعب {uid}'}")
        status = "🟢 التسجيل مفتوح" if sess.phase == "idle" else "🔒 التسجيل مغلق — الجولة بدأت"
        embed = discord.Embed(
            title="🐺 Loup-Garou Ultimate • بوابة القرية",
            description=f"{status}\n\n**اللاعبون المسجلون: {len(sess.players)}/{MAX_PLAYERS}**\n" +
                        ("\n".join(names) if names else "لا يوجد لاعبون بعد — كن أول من ينضم!") +
                        f"\n\nالحد الأدنى لبدء الجولة: **{MIN_PLAYERS}** لاعبًا.",
            colour=discord.Colour.from_rgb(28, 45, 85))
        embed.set_footer(text="اختر انضمام أو انسحاب من الأزرار • لا تكشف دورك أبدًا")
        banner = ASSETS / "loup_garou_promo.png"
        if banner.exists():
            embed.set_thumbnail(url="attachment://lobby.png")
            await msg.edit(embed=embed, view=LobbyView(guild.id), attachments=[discord.File(banner, filename="lobby.png")])
        else:
            await msg.edit(embed=embed, view=LobbyView(guild.id))
    except discord.HTTPException:
        log.debug("تعذر تحديث لوحة الانضمام", exc_info=True)


class TurnRequestView(discord.ui.View):
    def __init__(self, sess, token):
        super().__init__(timeout=None)
        self.sess, self.token = sess, token

    @discord.ui.button(label="طلب دور إضافي للكلام", emoji="🎙️", style=discord.ButtonStyle.primary, custom_id="lg:speech:request")
    async def request_turn(self, interaction: discord.Interaction, button: discord.ui.Button):
        s = self.sess
        if not s.game or s.phase != "day" or not s.speech_control:
            return await reply(interaction, "طلبات الكلام متاحة أثناء نقاش النهار فقط.")
        if interaction.user.id not in s.game.alive:
            return await reply(interaction, "المتفرجون والموتى لا يمكنهم طلب دور كلام.")
        if interaction.user.id == s.current_speaker:
            return await reply(interaction, "أنت تتكلم حاليًا بالفعل.")
        if interaction.user.id in s.turn_requests or interaction.user.id in s.extra_turns:
            return await reply(interaction, "طلبك مسجل بالفعل.")
        s.turn_requests.append(interaction.user.id)
        await reply(interaction, "📨 أُرسل طلبك إلى العمدة للموافقة عليه.")

    @discord.ui.button(label="لوحة العمدة: الموافقة على طلب", emoji="🎖️", style=discord.ButtonStyle.success, custom_id="lg:speech:mayor")
    async def mayor_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        s = self.sess
        if not s.game or interaction.user.id not in s.game.alive or s.game.roles.get(interaction.user.id) != "mayor":
            return await reply(interaction, "هذا الزر مخصص للعمدة الحي فقط.")
        if not s.turn_requests:
            return await reply(interaction, "لا توجد طلبات كلام تنتظر الموافقة.")
        uid = s.turn_requests.pop(0)
        s.extra_turns.append(uid)
        await reply(interaction, f"✅ وافقت على طلب <@{uid}>. سيأخذ دورًا إضافيًا بعد انتهاء الدور الحالي/التالي.")

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
    sess.speech_control = bool(sess.voice_id and guild.get_channel(sess.voice_id))
    sess.speaker_index = 0
    sess.turn_requests, sess.extra_turns = [], []
    living_order = [u for u in sess.players if u in g.alive]
    sess.current_speaker = living_order[0] if living_order else 0
    await apply_mutes(sess, guild)
    turn_view = TurnRequestView(sess, sess.token)
    await safe_send(ch, f"☀️ **النهار — نقاش بالدور** ({DAY_SECONDS}ث)\n👥 الأحياء ({len(g.alive)}): {alive}\n"
                        "🎙️ يمنح البوت الميكروفون للاعب واحد في كل مرة. استخدموا زر طلب دور إضافي، والعمدة يوافق عليه.",
                        view=turn_view)
    deadline = asyncio.get_running_loop().time() + DAY_SECONDS
    while asyncio.get_running_loop().time() < deadline:
        if sess.skip.is_set():
            sess.skip.clear()
            break
        # يبقى الميكروفون مع المتحدث الحالي مدة تصل إلى 20 ثانية قبل الانتقال.
        try:
            await asyncio.wait_for(sess.skip.wait(), timeout=min(20, max(0.1, deadline-asyncio.get_running_loop().time())))
            sess.skip.clear()
            break
        except asyncio.TimeoutError:
            pass
        if living_order:
            if sess.extra_turns:
                nxt = sess.extra_turns.pop(0)
                if nxt in g.alive:
                    sess.current_speaker = nxt
            else:
                sess.speaker_index = (sess.speaker_index + 1) % max(1, len(living_order))
                for _ in range(len(living_order)):
                    cand = living_order[sess.speaker_index]
                    if cand in g.alive:
                        sess.current_speaker = cand
                        break
            await apply_mutes(sess, guild)
    sess.speech_control = False
    sess.current_speaker = 0
    await apply_mutes(sess, guild)

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
        member = await get_member(guild, uid)
        # Save the original nickname once, then mark eliminated players as DEAD.
        if member:
            if uid not in sess.original_nicks:
                sess.original_nicks[uid] = member.nick
            sess.death_causes[uid] = CAUSE.get(cause, "سبب غير معروف")
            short_cause = {"wolves": "الذئاب", "poison": "السم", "vote": "التصويت",
                           "hunter": "الصياد", "white_wolf": "الذئب الأبيض", "caught": "كُشف ليلًا"}.get(cause, "مجهول")
            dead_nick = f"💀 DEAD | {short_cause}"[:32]
            try:
                await member.edit(nick=dead_nick, reason=f"Loup-Garou: dead by {cause}")
            except discord.Forbidden:
                await safe_send(ch, f"⚠️ لم أستطع تغيير اسم {member.mention} إلى DEAD. أحتاج Manage Nicknames وأن تكون رتبتي أعلى من رتبته.")
            except discord.HTTPException:
                pass
        await safe_send(ch, f"💀 **{name_of(guild, uid)}** — {CAUSE.get(cause, 'سبب غير معروف')}.\nكان: {emoji} **{ar}**\nتم تمييز اللاعب باسم **DEAD** حتى نهاية الجولة.")
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
    try:
        db.add_game(guild.id, winner, len(g.roles), g.night, [name_of(guild, u) for u in list(winners)[:12]])
    except Exception:
        log.exception("تعذّر تسجيل الجولة في السجل العام")
    for uid in g.roles:
        total = db.add(guild.id, uid, XP_PLAY + (XP_WIN if uid in winners else 0), 1, 1 if uid in winners else 0)
        m = guild.get_member(uid)
        if m:
            await update_level_roles(m, total)
    await cleanup(sess, guild)


async def cleanup(sess, guild):
    await stop_ambience(sess, guild)
    # Restore player nicknames after the round; keep the death cause in the game log.
    for uid, old_nick in list(sess.original_nicks.items()):
        member = await get_member(guild, uid)
        if member:
            try:
                await member.edit(nick=old_nick, reason="Loup-Garou: restore nickname after game")
            except (discord.Forbidden, discord.HTTPException):
                pass
    sess.original_nicks.clear()
    sess.death_causes.clear()
    voice_id, lair_id = sess.voice_id, sess.lair_id
    active_members = [guild.get_member(uid) for uid in (sess.game.roles.keys() if sess.game else [])]
    active_members = [m for m in active_members if m]
    if sess.hunter_future and not sess.hunter_future.done():
        sess.hunter_future.cancel()
    sess.hunter_future = None
    sess.game, sess.actions, sess.vote_msg = None, None, None
    sess.phase, sess.token, sess.players, sess.votes = "idle", sess.token + 1, [], {}
    sess.lair_id, sess.warned_mute = 0, False
    sess.speech_control, sess.current_speaker = False, 0
    sess.turn_requests, sess.extra_turns = [], []
    await release_mutes(guild, voice_id)
    voice_channel = guild.get_channel(voice_id) if voice_id else None
    if isinstance(voice_channel, discord.VoiceChannel):
        await lock_game_voice(guild, voice_channel, active_members, locked=False)
    locked_channel = find_text(guild, CH_GAME)
    if locked_channel:
        try:
            await locked_channel.set_permissions(guild.default_role, send_messages=None,
                                                 reason="Loup-Garou: reopen lobby after game")
        except discord.HTTPException:
            pass
    await update_lobby_panel(guild, sess)
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
        # تسجيل واجهة الانضمام الدائمة حتى تبقى أزرار اللوحة فعالة بعد إعادة التشغيل.
        self.add_view(LobbyView(GUILD_ID))
        self.add_view(ControlPanelView())
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


def _api_cors_headers(request=None):
    # واجهة قراءة فقط لموقع Blogger. لا توجد أي نقطة تتحكم في اللعبة.
    origin = request.headers.get("Origin") if request is not None else None
    headers = site_api.cors_headers(origin, SITE_ORIGINS)
    headers["Cache-Control"] = "no-store"
    return headers


@web.middleware
async def public_api_cors(request, handler):
    if request.method == "OPTIONS":
        return web.Response(status=204, headers=_api_cors_headers(request))
    try:
        response = await handler(request)
    except web.HTTPException as exc:
        response = exc
    for k, v in _api_cors_headers(request).items():
        response.headers.setdefault(k, v)
    return response


def _api_guild_id(request):
    # إن ضُبط GUILD_ID على الخادم فهو الوحيد المعروض (لا يمكن استعراض سيرفرات أخرى).
    if GUILD_ID:
        return GUILD_ID
    try:
        gid = int(request.query.get("guild_id", ""))
    except (TypeError, ValueError):
        return 0
    return gid if bot.get_guild(gid) else 0


def _missing_guild():
    return web.json_response({"ok": False, "error": "missing_guild_id",
                              "message": "أضف GUILD_ID إلى إعدادات الاستضافة."}, status=400)


def _status_data(gid):
    guild = bot.get_guild(gid)
    sess = sessions.get(gid)
    game = sess.game if sess else None
    return site_api.status_payload(
        bot_online=bot.is_ready(), guild_name=guild.name if guild else "سيرفر Loup-Garou", guild_found=guild is not None,
        phase=sess.phase if sess else "idle", game=game, waiting=len(sess.players) if sess else 0,
        min_players=MIN_PLAYERS, max_players=MAX_PLAYERS, member_count=guild.member_count if guild else 0)


def _leaderboard_data(gid, limit):
    guild = bot.get_guild(gid)
    players = []
    for rank, (uid, xp, games, wins) in enumerate(db.top(gid, limit), 1):
        member = guild.get_member(uid) if guild else None
        level = level_for(xp)
        players.append({"rank": rank, "user_id": str(uid),
                        "name": member.display_name if member else f"لاعب {str(uid)[-4:]}",
                        "avatar_url": str(member.display_avatar.url) if member else "", "xp": int(xp),
                        "games": int(games), "wins": int(wins), "level": int(level),
                        "level_name": dict(LEVELS).get(level, "🐺 مبتدئ")})
    return players


def _limit(request, default, cap):
    try:
        return max(1, min(cap, int(request.query.get("limit", default))))
    except ValueError:
        return default


async def api_public_status(request):
    gid = _api_guild_id(request)
    if not gid:
        return _missing_guild()
    return web.json_response(_status_data(gid))


async def api_public_leaderboard(request):
    gid = _api_guild_id(request)
    if not gid:
        return _missing_guild()
    guild = bot.get_guild(gid)
    players = _leaderboard_data(gid, _limit(request, 10, 50))
    return web.json_response({"ok": True, "product": "Merou Last", "guild_name": guild.name if guild else "Loup-Garou",
                              "count": len(players), "players": players})


async def api_public_news(request):
    gid = _api_guild_id(request)
    if not gid:
        return _missing_guild()
    return web.json_response({"ok": True, "news": site_api.news_payload(db.list_news(gid, _limit(request, 6, 30)))})


async def api_public_history(request):
    gid = _api_guild_id(request)
    if not gid:
        return _missing_guild()
    return web.json_response({"ok": True, "games": site_api.games_payload(db.list_games(gid, _limit(request, 8, 30)))})


async def api_public_summary(request):
    """طلب واحد يجمع كل ما يحتاجه الموقع (أخف على الاستضافة المجانية)."""
    gid = _api_guild_id(request)
    if not gid:
        return _missing_guild()
    players_total, games_total = db.totals(gid)
    return web.json_response({
        "ok": True, "status": _status_data(gid),
        "leaderboard": _leaderboard_data(gid, _limit(request, 10, 50)),
        "news": site_api.news_payload(db.list_news(gid, 6)),
        "history": site_api.games_payload(db.list_games(gid, 8)),
        "totals": {"players": players_total, "games": games_total},
        "site": {"banner": db.site_get(gid, "banner", ""),
                 "invite_url": db.site_get(gid, "invite", "") or DEFAULT_INVITE},
    })


async def api_public_roles(request):
    roles = []
    for key, info in ROLE_INFO.items():
        roles.append({"key": key, "name_ar": info[0], "name_en": info[1], "emoji": info[2], "description": info[3],
                      "image_url": f"/assets/cards/{key}.png",
                      "team": "الذئاب" if key in ("werewolf", "white_wolf") else "القرية"})
    return web.json_response({"ok": True, "product": "Merou Last", "roles": roles})


async def api_card_image(request):
    filename = request.match_info.get("filename", "")
    if filename not in {f"{key}.png" for key in ROLE_INFO}:
        raise web.HTTPNotFound()
    path = ASSETS / "cards" / filename
    if not path.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(path, headers={"Cache-Control": "public, max-age=86400"})


async def api_promo_image(request):
    path = ASSETS / "loup_garou_promo.png"
    if not path.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(path, headers={"Cache-Control": "public, max-age=86400"})


def build_web_app():
    app = web.Application(middlewares=[public_api_cors])
    app.router.add_get("/", lambda r: web.json_response({"ok": True, "service": "Merou Last • Loup-Garou API", "status": "running"}))
    app.router.add_get("/healthz", lambda r: web.Response(text="ok"))
    app.router.add_get("/api/public/summary", api_public_summary)
    app.router.add_get("/api/public/status", api_public_status)
    app.router.add_get("/api/public/leaderboard", api_public_leaderboard)
    app.router.add_get("/api/public/news", api_public_news)
    app.router.add_get("/api/public/history", api_public_history)
    app.router.add_get("/api/public/roles", api_public_roles)
    app.router.add_get("/assets/cards/{filename}", api_card_image)
    app.router.add_get("/assets/loup_garou_promo.png", api_promo_image)
    return app


async def start_health_server():
    port = os.getenv("PORT")
    if not port:
        return
    runner = web.AppRunner(build_web_app())
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(port)).start()
    log.info("Merou Last public API on :%s", port)


# ───────────────────────── إدارة الموقع من Discord ─────────────────────────
def _need_manager(interaction) -> bool:
    return is_manager(interaction) or interaction.user.guild_permissions.administrator


@tree.command(name="announce", description="نشر إعلان على موقع Blogger وفي قناة الإعلانات")
@app_commands.describe(title="عنوان الإعلان", message="نص الإعلان", pin="تثبيته في أعلى الأخبار",
                       discord_too="نشره أيضًا في قناة الإعلانات")
async def announce_cmd(interaction: discord.Interaction, title: app_commands.Range[str, 3, 100],
                       message: app_commands.Range[str, 3, 1500], pin: bool = False, discord_too: bool = True):
    if not _need_manager(interaction):
        return await interaction.response.send_message("🔒 هذا الأمر لمدير اللعبة أو مسؤول السيرفر.", ephemeral=True)
    title, message = site_api.clean(title, 100), site_api.clean(message, 1500)
    if len(title) < 3 or len(message) < 3:
        return await interaction.response.send_message("العنوان والنص قصيران جدًا.", ephemeral=True)
    nid = db.add_news(interaction.guild_id, title, message, interaction.user.display_name, pin)
    sent = ""
    if discord_too:
        ch = find_text(interaction.guild, CH_ANN)
        if ch:
            em = discord.Embed(title=f"📢 {title}", description=message, colour=discord.Colour.from_rgb(52, 88, 184))
            em.set_footer(text=f"إعلان #{nid} • {interaction.user.display_name}")
            await safe_send(ch, embed=em, allowed_mentions=discord.AllowedMentions.none())
            sent = f" ونُشر في {ch.mention}"
    await interaction.response.send_message(f"✅ نُشر الإعلان #{nid} على الموقع{sent}.", ephemeral=True)


@tree.command(name="news_delete", description="حذف إعلان من الموقع")
@app_commands.describe(news_id="رقم الإعلان (يظهر في ذيل الإعلان)")
async def news_delete_cmd(interaction: discord.Interaction, news_id: int):
    if not _need_manager(interaction):
        return await interaction.response.send_message("🔒 هذا الأمر لمدير اللعبة أو مسؤول السيرفر.", ephemeral=True)
    ok = db.delete_news(interaction.guild_id, news_id)
    await interaction.response.send_message("🗑️ حُذف الإعلان." if ok else "لا يوجد إعلان بهذا الرقم.", ephemeral=True)


@tree.command(name="site_banner", description="شريط تنبيه أعلى الموقع (اتركه فارغًا لحذفه)")
@app_commands.describe(text="مثال: جولة الليلة الساعة 9 مساءً — ادخلوا الصوت!")
async def site_banner_cmd(interaction: discord.Interaction, text: str = ""):
    if not _need_manager(interaction):
        return await interaction.response.send_message("🔒 هذا الأمر لمدير اللعبة أو مسؤول السيرفر.", ephemeral=True)
    text = site_api.clean(text, 200)
    db.site_set(interaction.guild_id, "banner", text)
    await interaction.response.send_message(f"✅ الشريط الحالي: {text}" if text else "✅ أُزيل الشريط.", ephemeral=True)


@tree.command(name="site_invite", description="تعيين رابط دعوة السيرفر الذي يظهر في الموقع")
@app_commands.describe(url="مثل https://discord.gg/xxxxxxx")
async def site_invite_cmd(interaction: discord.Interaction, url: str):
    if not _need_manager(interaction):
        return await interaction.response.send_message("🔒 هذا الأمر لمدير اللعبة أو مسؤول السيرفر.", ephemeral=True)
    url = url.strip()
    if not site_api.valid_invite(url):
        return await interaction.response.send_message("❌ الرابط يجب أن يكون https://discord.gg/… أو https://discord.com/invite/…", ephemeral=True)
    db.site_set(interaction.guild_id, "invite", url)
    await interaction.response.send_message("✅ حُفظ رابط الدعوة وسيظهر في الموقع.", ephemeral=True)


@tree.command(name="site", description="رابط موقع Merou Last")
async def site_cmd(interaction: discord.Interaction):
    if SITE_URL:
        await interaction.response.send_message(f"🌐 موقع القرية: {SITE_URL}", ephemeral=True)
    else:
        await interaction.response.send_message("لم يُضبط متغير SITE_URL على الاستضافة بعد.", ephemeral=True)


@tree.command(name="panel", description="نشر لوحة التحكم التفاعلية للعبة")
async def panel_cmd(interaction: discord.Interaction):
    if not (is_manager(interaction) or interaction.user.guild_permissions.administrator):
        return await interaction.response.send_message("🔒 نشر لوحة التحكم متاح لمدير اللعبة أو مسؤول السيرفر.", ephemeral=True)
    em = discord.Embed(
        title="🐺 LOUP-GAROU ULTIMATE • مركز القيادة",
        description="**كل ما تحتاجه لإدارة القرية من لوحة واحدة.**\n\nاستخدم الأزرار لمتابعة الجولة والتحكم بالمراحل. تبقى الأدوار سرية، وتُفحص صلاحيات الإدارة عند كل إجراء.",
        colour=discord.Colour.from_rgb(18, 28, 52))
    em.add_field(name="🎮 سير اللعب", value="التسجيل ← توزيع الأدوار سرًا ← الليل ← الفجر ← النقاش ← التصويت ← إعلان النتيجة", inline=False)
    em.add_field(name="🛡️ صلاحيات آمنة", value="أزرار البدء والتخطي والإيقاف محمية برتبة إدارة اللعبة أو صلاحية مسؤول السيرفر.", inline=False)
    em.set_footer(text="Loup-Garou Ultimate PRO • لوحة تفاعلية داخل Discord")
    banner = ASSETS / "loup_garou_promo.png"
    if banner.exists():
        em.set_image(url="attachment://panel.png")
        await interaction.channel.send(embed=em, view=ControlPanelView(), file=discord.File(banner, filename="panel.png"))
    else:
        await interaction.channel.send(embed=em, view=ControlPanelView())
    await interaction.response.send_message("✅ نُشرت لوحة القيادة في هذه القناة.", ephemeral=True)


@tree.command(name="setup", description="إنشاء قنوات ورولات Loup-Garou تلقائيًا")
@app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(administrator=True)
async def setup_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    guild = interaction.guild
    try:
        category = discord.utils.get(guild.categories, name=CAT_NAME) or await guild.create_category(CAT_NAME)
        made = {}
        for name, voice in [(CH_RULES, 0), (CH_ANN, 0), (CH_GAME, 0), (CH_ROLES, 0), (CH_VOTE, 0), ("🏆・المتصدرون", 0), ("📜・سجل-الجولة", 0), (CH_VOICE, 1), ("💀・المتفرجون", 2)]:
            ch = discord.utils.get(category.channels, name=name)
            if ch is None:
                ch = (await guild.create_voice_channel(name, category=category) if voice == 1
                      else await guild.create_text_channel(name, category=category))
            made[name] = ch
        await ensure_role(guild, ROLE_PLAYER, discord.Colour.blue())
        await ensure_role(guild, ROLE_MANAGER, discord.Colour.red())
        for threshold, label in LEVELS:
            await ensure_role(guild, f"المستوى {threshold}・{label}",
                              discord.Colour.gold() if threshold >= 15 else discord.Colour.blurple())
    except discord.Forbidden:
        return await interaction.followup.send("❌ ينقص البوت صلاحية **Manage Channels / Manage Roles**.", ephemeral=True)
    rules_embed = discord.Embed(
        title="📜 ميثاق القرية • Loup-Garou",
        description="**اقرأ القواعد قبل دخول الجولة.**\n\n"
                    "🌙 **الليل:** لا كلام في القناة الصوتية؛ البوت يمنح الميكروفون للأدوار المسموح بها فقط.\n"
                    "☀️ **النهار:** يتكلم لاعب واحد في كل مرة، ويمكن طلب دور إضافي بموافقة العمدة.\n"
                    "🎭 **السرية:** يمنع نشر بطاقة الدور أو الرسائل الخاصة.\n"
                    "🗳️ **التصويت:** صوت واحد لكل لاعب حي، والعمدة صوته مضاعف.\n"
                    "💀 **الموت:** يلتزم اللاعب الميت بالصمت حتى نهاية الجولة.\n"
                    "🤝 **الاحترام:** يمنع السب والتخريب واستخدام معلومات خارج اللعبة.",
        colour=discord.Colour.from_rgb(35, 48, 83))
    rules_embed.set_footer(text="Loup-Garou Ultimate • العب بذكاء، واحترم القرية")
    await safe_send(made[CH_RULES], embed=rules_embed)
    role_intro = discord.Embed(title="🎭 موسوعة الأدوار", description="كل بطاقة أدناه تشرح الهدف والقدرة. البطاقات السرية لا تُشارك أثناء اللعب.", colour=discord.Colour.from_rgb(35, 48, 83))
    await safe_send(made[CH_ROLES], embed=role_intro)
    for key, info in ROLE_INFO.items():
        role_embed_public = discord.Embed(title=f"{info[2]} {info[0]} • {info[1]}", description=info[3], colour=discord.Colour.from_rgb(35, 48, 83))
        role_embed_public.add_field(name="🎯 الهدف", value="نفّذ هدف فريقك دون كشف بطاقتك، والتزم بتعليمات مرحلة اللعب.", inline=False)
        card = ASSETS / "cards" / f"{key}.png"
        if card.exists():
            role_embed_public.set_image(url="attachment://role.png")
            await safe_send(made[CH_ROLES], embed=role_embed_public, file=discord.File(card, filename="role.png"))
        else:
            await safe_send(made[CH_ROLES], embed=role_embed_public)
    await safe_send(made[CH_ANN], "🌕 مرحبًا بكم في قرية Loup-Garou! استخدموا `/lobby` لنشر لوحة الانضمام بالأزرار ثم `/start` لبدء الجولة.")
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



@tree.command(name="lobby", description="نشر واجهة الانضمام الاحترافية بأزرار")
async def lobby_cmd(interaction: discord.Interaction):
    sess = get_session(interaction.guild_id)
    if sess.phase != "idle":
        return await interaction.response.send_message("هناك جولة نشطة؛ لا يمكن فتح تسجيل جديد.", ephemeral=True)
    channel = find_text(interaction.guild, CH_GAME) or interaction.channel
    names = [f"• {name_of(interaction.guild, uid)}" for uid in sess.players]
    embed = discord.Embed(
        title="🐺 LOUP-GAROU ULTIMATE",
        description=f"**بوابة القرية — التسجيل مفتوح**\n\nانضم إلى الجولة، استعد لدورك السري، ولا تكشف هويتك.\n\n"
                    f"**المسجلون: {len(sess.players)}/{MAX_PLAYERS}**\n" +
                    ("\n".join(names) if names else "لا أحد مسجل حتى الآن.") +
                    f"\n\nالحد الأدنى: **{MIN_PLAYERS} لاعبين**",
        colour=discord.Colour.from_rgb(24, 48, 92))
    embed.add_field(name="🎭 كيف تلعب؟", value="انضم من الزر، استلم دورك سرًا، ثم تعاون مع فريقك دون كشف هويتك.", inline=False)
    embed.add_field(name="🔒 الخصوصية", value="عند بدء الجولة يُغلق التسجيل تلقائيًا ولا يمكن تعديل القائمة.", inline=False)
    embed.set_footer(text="Loup-Garou Ultimate • Moonlit Village")
    banner = ASSETS / "loup_garou_promo.png"
    kwargs = {"embed": embed, "view": LobbyView(interaction.guild_id)}
    if banner.exists():
        kwargs["file"] = discord.File(banner, filename="lobby.png")
        embed.set_image(url="attachment://lobby.png")
    msg = await channel.send(**kwargs)
    sess.lobby_message_id, sess.lobby_channel_id = msg.id, channel.id
    await interaction.response.send_message(f"تم نشر واجهة الانضمام في {channel.mention}.", ephemeral=True)


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
    # اقفل الكتابة في غرفة اللعب أثناء الجولة مع إبقاء الأزرار التفاعلية فعالة.
    locked_channel = find_text(guild, CH_GAME)
    if locked_channel:
        try:
            await locked_channel.set_permissions(guild.default_role, send_messages=False,
                                                 reason="Loup-Garou: lock lobby during game")
        except discord.HTTPException:
            log.warning("تعذر قفل غرفة اللعبة تلقائيًا")
    await update_lobby_panel(guild, sess)
    members = []
    for uid in dict.fromkeys(sess.players):
        m = await get_member(guild, uid)
        if m and not m.bot:
            members.append(m)
    if len(members) < MIN_PLAYERS:
        sess.phase = "idle"
        if locked_channel:
            try:
                await locked_channel.set_permissions(guild.default_role, send_messages=None,
                                                     reason="Loup-Garou: cancel start")
            except discord.HTTPException:
                pass
        await update_lobby_panel(guild, sess)
        return await interaction.followup.send(f"تحتاج الجولة إلى {MIN_PLAYERS} لاعبين على الأقل. استخدموا `/lobby` أولًا.")

    role_list = engine.build_roles(len(members))
    sess.original_nicks = {m.id: m.nick for m in members}
    sess.death_causes = {}
    sess.game = Game(roles={m.id: r for m, r in zip(members, role_list)})
    sess.players = [m.id for m in members]
    sess.channel_id = interaction.channel_id
    sess.votes, sess.warned_mute = {}, False
    voice = discord.utils.get(guild.voice_channels, name=CH_VOICE)
    sess.voice_id = voice.id if voice else 0
    if voice:
        await lock_game_voice(guild, voice, members, locked=True)
    if voice and AUDIO:
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
    if not AUDIO:
        return await interaction.response.send_message("🔇 الصوت معطّل (DISABLE_AUDIO=1). الكتم التلقائي يعمل بدون دخول البوت.", ephemeral=True)
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
    prev = max((t for t, _ in LEVELS if t <= lvl), default=1)
    progress = 1.0 if nxt is None else max(0.0, min(1.0, (xp - prev) / max(1, nxt - prev)))
    bar = "🟦" * int(progress * 10) + "⬛" * (10 - int(progress * 10))
    em = discord.Embed(title=f"🐺 ملف اللاعب • {m.display_name}", description=f"**{label}**\n{bar}  **{int(progress*100)}%**", colour=discord.Colour.from_rgb(30, 45, 82))
    em.set_thumbnail(url=m.display_avatar.url)
    em.add_field(name="⭐ نقاط الخبرة", value=str(xp), inline=True)
    em.add_field(name="🎮 الجولات", value=str(games), inline=True)
    em.add_field(name="🏆 الانتصارات", value=str(wins), inline=True)
    em.add_field(name="🎯 التحدي التالي", value=f"{nxt} نقطة" if nxt else "👑 أعلى رتبة تم بلوغها", inline=False)
    badges = []
    if games >= 1: badges.append("🎲 أول جولة")
    if wins >= 1: badges.append("🏆 أول انتصار")
    if games >= 10: badges.append("🛡️ مخضرم القرية")
    if wins >= 5: badges.append("🐺 خمس انتصارات")
    if games >= 25: badges.append("🌙 حارس الليل")
    if wins >= 15: badges.append("👑 أسطورة المواسم")
    em.add_field(name="🏅 الإنجازات المفتوحة", value=" • ".join(badges) if badges else "ابدأ أول جولة لفتح إنجازك الأول!", inline=False)
    em.set_footer(text="استمر في اللعب النزيه لفتح ألقاب أعلى")
    await interaction.response.send_message(embed=em, ephemeral=True)


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
        "`/setup` تجهيز القنوات والرولات • `/setmanager` تعيين مدير • `/panel` لوحة القيادة\n"
        "`/join` `/leave` الانضمام/المغادرة • `/start` بدء الجولة (تلقائية بالكامل)\n"
        "`/skip` تخطي المرحلة • `/stop` إيقاف الجولة • `/connect` دخول قناة الصوت\n"
        "`/vote` تصويت (أو زر التصويت) • `/status` الحالة • `/roles` الأدوار\n"
        "`/rank` مستواك • `/top` المتصدرون • `/site` الموقع\n"
        "**إدارة الموقع (للمدير):** `/announce` `/news_delete` `/site_banner` `/site_invite`\n\n"
        "الليل والنهار والتصويت وقدرات الأدوار والكتم والفوز تتم تلقائيًا. النقاط محفوظة في قاعدة بيانات (SQLite أو MongoDB).",
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
