"""محاكاة كاملة لجولة كاملة بمكتبة discord وهمية (بدون شبكة) لكشف أخطاء التدفق."""
import asyncio, os, sys, types, logging, tempfile, random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.update(NIGHT_SECONDS="1", WITCH_SECONDS="1", DAY_SECONDS="1", VOTE_SECONDS="2",
                  HUNTER_SECONDS="2", START_DELAY="0", DB_PATH=tempfile.mktemp(suffix=".db"))

# ───────── discord وهمية ─────────
d = types.ModuleType("discord")
class HTTPException(Exception): pass
class Forbidden(HTTPException): pass
class LoginFailure(Exception): pass
class PrivilegedIntentsRequired(Exception): pass
d.HTTPException, d.Forbidden, d.LoginFailure, d.PrivilegedIntentsRequired = HTTPException, Forbidden, LoginFailure, PrivilegedIntentsRequired
class Colour:
    def __init__(s, v=0): pass
    @classmethod
    def blurple(c): return c()
    blue = red = gold = dark_purple = blurple
d.Colour = Colour
class Embed:
    def __init__(s, **kw): s.title=kw.get("title"); s.description=kw.get("description"); s.fields=[]
    def add_field(s, **kw): s.fields.append(kw)
    def clear_fields(s): s.fields=[]
    def set_footer(s, **kw): pass
    def set_image(s, **kw): pass
d.Embed = Embed
class File:
    def __init__(s, path, filename=None): s.path=path
d.File = File
class Intents:
    @classmethod
    def default(c): return c()
d.Intents = Intents
class Object:
    def __init__(s, id): s.id=id
d.Object = Object
class SelectOption:
    def __init__(s, label, value): s.label=label; s.value=value
d.SelectOption = SelectOption
class ButtonStyle: primary=secondary=success=danger=1
d.ButtonStyle = ButtonStyle
class PermissionOverwrite:
    def __init__(s, **kw): pass
d.PermissionOverwrite = PermissionOverwrite
class VoiceChannel: pass
d.VoiceChannel = VoiceChannel
class Message: pass
d.Message = Message
class Member: pass
d.Member = Member
class Interaction: pass
d.Interaction = Interaction
class FFmpegPCMAudio:
    def __init__(s, p): pass
class PCMVolumeTransformer:
    def __init__(s, src, volume=1): pass
d.FFmpegPCMAudio, d.PCMVolumeTransformer = FFmpegPCMAudio, PCMVolumeTransformer
class Client:
    def __init__(s, intents=None): pass
d.Client = Client
utils = types.ModuleType("discord.utils")
def uget(it, **kw):
    for x in it:
        if all(getattr(x, k, None) == v for k, v in kw.items()): return x
utils.get = uget
d.utils = utils
ui = types.ModuleType("discord.ui")
class View:
    def __init__(s, timeout=180): s.children=[]
    def add_item(s, i): s.children.append(i)
class Button:
    def __init__(s, label=None, style=None): s.label=label
class Select:
    def __init__(s, placeholder=None, min_values=1, max_values=1, options=None): s.options=options; s.values=[]; s.placeholder=placeholder
ui.View, ui.Button, ui.Select = View, Button, Select
d.ui = ui
ac = types.ModuleType("discord.app_commands")
class AppCommandError(Exception): pass
class MissingPermissions(AppCommandError): pass
class CommandTree:
    commands = {}
    def __init__(s, client): pass
    def command(s, name=None, description=None):
        def deco(f): CommandTree.commands[name]=f; return f
        return deco
    def copy_global_to(s, guild): pass
    async def sync(s, guild=None): return list(CommandTree.commands)
ac.AppCommandError, ac.MissingPermissions, ac.CommandTree = AppCommandError, MissingPermissions, CommandTree
ac.default_permissions = lambda **k: (lambda f: f)
ac.describe = lambda **k: (lambda f: f)
ac.checks = types.SimpleNamespace(has_permissions=lambda **k: (lambda f: f))
d.app_commands = ac
sys.modules.update({"discord": d, "discord.utils": utils, "discord.ui": ui, "discord.app_commands": ac})
aio = types.ModuleType("aiohttp"); web = types.ModuleType("aiohttp.web"); aio.web = web
sys.modules.update({"aiohttp": aio, "aiohttp.web": web})
dot = types.ModuleType("dotenv"); dot.load_dotenv = lambda: None; sys.modules["dotenv"] = dot

# ───────── عالم وهمي ─────────
class Msg:
    def __init__(s, ch, content=None, view=None, embed=None): s.channel=ch; s.content=content; s.view=view; s.embed=embed; s.handled=False
    async def edit(s, content=None, view="keep"):
        if content is not None: s.content=content
        if view != "keep": s.view=view
class Text:
    _id = 1000
    def __init__(s, name): Text._id+=1; s.id=Text._id; s.name=name; s.msgs=[]; s.mention=f"<#{s.id}>"
    async def send(s, content=None, view=None, embed=None, **kw):
        m = Msg(s, content, view, embed); s.msgs.append(m); return m
    async def delete(s, reason=None): s.deleted=True
class FVC:
    def __init__(s, ch): s.channel=ch; s.playing=False; s.plays=0; s.after=None
    def is_connected(s): return True
    def is_playing(s): return s.playing
    def play(s, src, after=None): s.playing=True; s.plays+=1; s.after=after
    def stop(s):
        s.playing=False
        if s.after: a=s.after; s.after=None; a(None)
    async def move_to(s, ch): s.channel=ch
class Voice(VoiceChannel):
    def __init__(s, guild): Text._id+=1; s.id=Text._id; s.name="🔊・قرية-الصوت"; s.members=[]; s.guild=guild; s.mention="<#v>"
    async def connect(s, **kw): vc=FVC(s); s.guild.voice_client=vc; return vc
class VS:
    def __init__(s, ch): s.mute=False; s.channel=ch
class Mem(Member):
    def __init__(s, guild, uid, name):
        s.guild=guild; s.id=uid; s.display_name=name; s.bot=False; s.roles=[]; s.dms=[]
        s.voice=VS(guild.voice); guild.voice.members.append(s)
        s.guild_permissions=types.SimpleNamespace(administrator=False); s.mention=f"<@{uid}>"
    async def edit(s, mute=None, reason=None): s.voice.mute = mute
    async def send(s, **kw): s.dms.append(kw)
    async def add_roles(s, *r, reason=None): s.roles += list(r)
    async def remove_roles(s, *r, reason=None): pass
class Guild:
    id = 1
    def __init__(s):
        s.voice = Voice(s); s.voice_client=None; s.members={}; s.text=[Text("🎮・غرفة-اللعبة"), Text("🗳️・التصويت"), Text("📢・الإعلانات")]
        s.roles=[]; s.categories=[]; s.default_role=object(); s.me=object()
    text_channels = property(lambda s: s.text)
    voice_channels = property(lambda s: [s.voice])
    def get_member(s, u): return s.members.get(u)
    async def fetch_member(s, u): return s.members.get(u)
    def get_channel(s, i):
        for c in s.text + [s.voice]:
            if c.id == i: return c
    async def create_text_channel(s, name, **kw): c=Text(name); s.text.append(c); return c

class Resp:
    def __init__(s): s.done=False; s.sent=None
    def is_done(s): return s.done
    async def send_message(s, content=None, view=None, ephemeral=False, **kw): s.done=True; s.sent=(content, view)
    async def edit_message(s, content=None, view=None): s.done=True; s.sent=(content, view)
    async def defer(s, **kw): s.done=True
class FU:
    def __init__(s): s.sent=[]
    async def send(s, content=None, **kw): s.sent.append((content, kw))
class Inter(Interaction):
    def __init__(s, guild, user, channel=None):
        s.guild=guild; s.guild_id=guild.id; s.user=user; s.channel_id=channel.id if channel else 0
        s.response=Resp(); s.followup=FU()

import bot  # noqa

errors = []
class H(logging.Handler):
    def emit(s, r):
        if r.levelno >= logging.ERROR: errors.append(r.getMessage())
logging.getLogger().addHandler(H())

async def click(guild, user, button):
    i = Inter(guild, user); await button.callback(i); return i

async def play_views(guild, members, rng, report):
    """يتصرف كاللاعبين: يضغط الأزرار المعروضة ويختار من القوائم."""
    game_ch = guild.text[0]
    sess = bot.get_session(1)
    while sess.phase != "idle" or sess.game:
        for ch in list(guild.text):
            for m in list(ch.msgs):
                if m.view is None or m.handled: continue
                m.handled = True
                btn = m.view.children[0]
                label = btn.label or ""
                g = sess.game
                if g is None: continue
                for u in list(members):
                    if u.id not in g.roles: continue
                    i = await click(guild, u, btn)
                    sent = i.response.sent
                    if sent and sent[1] is not None:
                        view = sent[1]
                        if "🌙" in label or "التصويت" in label or "صوّت" in label or "الصياد" in label or "هدفك" in label:
                            sel = [c for c in view.children if isinstance(c, Select)]
                            for s in sel:
                                role = g.roles[u.id]
                                opts = [o for o in s.options]
                                if s.placeholder and "صوّتك" in s.placeholder:
                                    wolves = [o for o in opts if o.value!="skip" and g.is_wolf(int(o.value))]
                                    pool = wolves if (not g.is_wolf(u.id) and wolves and rng.random()<0.8) else opts
                                    s.values=[rng.choice(pool).value]
                                else:
                                    s.values=[rng.choice(opts).value]
                                i2 = Inter(guild, u); await s.callback(i2)
                                report.append((role, s.placeholder, i2.response.sent[0] if i2.response.sent else None))
                            for b in [c for c in view.children if isinstance(c, Button)]:
                                await click(guild, u, b)   # الطفلة/الساحرة
                        elif "الساحرة" in label:
                            for b in [c for c in view.children if isinstance(c, Button)]:
                                if b.label.startswith("💚") or b.label.startswith("☠️"):
                                    i3 = await click(guild, u, b)
                                    sv = i3.response.sent
                                    if sv and sv[1] is not None:
                                        for s in [c for c in sv[1].children if isinstance(c, Select)]:
                                            s.values=[s.options[0].value]; await s.callback(Inter(guild, u))
                                    report.append(("witch", b.label, None)); break
        await asyncio.sleep(0.05)

async def one_game(n, seed):
    rng = random.Random(seed)
    guild = Guild(); bot.sessions.clear()
    members = [Mem(guild, 100+k, f"P{k}") for k in range(n)]
    for m in members: guild.members[m.id]=m
    admin = Mem(guild, 1, "Admin"); admin.guild_permissions=types.SimpleNamespace(administrator=True); guild.members[1]=admin
    admin.voice.channel = None; guild.voice.members.remove(admin)
    for m in members:
        i = Inter(guild, m); m.roles=[]; await CommandTree.commands["join"](i)
    # لاعب غير مشارك داخل الصوت (متفرج)
    spec = Mem(guild, 999, "Spectator"); guild.members[999]=spec
    report = []
    i = Inter(guild, admin, guild.text[0]); await CommandTree.commands["start"](i)
    sess = bot.get_session(1)
    assert sess.game, "الجولة لم تبدأ"
    roles = dict(sess.game.roles)
    await asyncio.wait_for(play_views(guild, members, rng, report), timeout=60)
    return guild, members, spec, roles, report

Select, Button = ui.Select, ui.Button

async def main():
    results = []
    for n, seed in [(5, 1), (5, 2), (7, 3), (9, 4), (12, 5), (12, 6), (25, 7), (10, 8), (8, 9), (6, 10)]:
        guild, members, spec, roles, report = await one_game(n, seed)
        txt = "\n".join((m.content or "") + ((m.embed.title or "") + (m.embed.description or "") if m.embed else "") for ch in guild.text for m in ch.msgs)
        assert "انتهت الجولة" in txt, f"n={n} seed={seed}: لا رسالة نهاية\n{txt[-800:]}"
        assert all(not m.voice.mute for m in members + [spec]), "بقي لاعب مكتومًا بعد النهاية"
        assert guild.voice_client is None or not guild.voice_client.playing, "المؤثر ما زال يعمل بعد النهاية"
        total_xp = sum(bot.db.stats(1, m.id)[0] for m in members)
        assert total_xp >= n * bot.XP_PLAY, "لم تُحتسب الخبرة"
        lair = [c for c in guild.text if c.name == bot.CH_LAIR]
        assert not lair or getattr(lair[0], "deleted", False), "عرين الذئاب لم يُحذف"
        kinds = sorted({r[0] for r in report})
        results.append((n, seed, "OK", kinds))
        print(f"n={n:2d} seed={seed:2d}  ✅ انتهت الجولة | أدوار استخدمت قدراتها: {','.join(kinds)}")
    assert not errors, f"أخطاء مسجّلة: {errors}"
    print("\nكل المحاكاة نجحت بدون أخطاء مسجّلة.")

asyncio.run(main())
