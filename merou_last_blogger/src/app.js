/* Merou Last — واجهة الموقع. تعتمد على الـ API العام للبوت (قراءة فقط). */
(function () {
  var C = window.MEROU_CONFIG || {};
  var API = String(C.API_BASE || "").replace(/\/+$/, "");
  var DEMO = !API || API.indexOf("YOUR-SERVICE") !== -1;
  var GUILD = String(C.GUILD_ID || "").replace(/\D/g, "");
  var $ = function (id) { return document.getElementById(id); };
  var safe = function (s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); };
  var num = function (n) { try { return Number(n || 0).toLocaleString("ar-EG"); } catch (e) { return String(n || 0); } };
  var url = function (u) { u = String(u || ""); return /^https:\/\//i.test(u) ? safe(u) : ""; };

  var ROLES = [
    ["werewolf", "الذئب", "Werewolf", "🐺", "في الليل اتفق مع بقية الذئاب على ضحية. هدفك إقصاء القرويين دون كشف هويتك.", "الذئاب"],
    ["villager", "القروي", "Villager", "🧑‍🌾", "لا تملك قدرة ليلية. ناقش الأدلة وصوّت نهارًا لاكتشاف الذئاب.", "القرية"],
    ["seer", "العرافة", "Seer", "🔮", "كل ليلة افحص لاعبًا لتعرف هل هو ذئب أم لا (الذئب الأبيض يظهر ذئبًا).", "القرية"],
    ["doctor", "الطبيب", "Doctor", "🩺", "كل ليلة اختر لاعبًا لحمايته من الذئاب. يجوز أن تحمي نفسك.", "القرية"],
    ["hunter", "الصياد", "Hunter", "🏹", "عند خروجك من اللعبة لأي سبب، تطلق سهمًا أخيرًا على لاعب حي.", "القرية"],
    ["guardian", "الحارس", "Guardian", "🛡️", "كل ليلة احمِ لاعبًا من الذئاب. لا تحمِ الشخص نفسه ليلتين متتاليتين.", "القرية"],
    ["witch", "الساحرة", "Witch", "🧙‍♀️", "جرعة إنقاذ وجرعة سم لكل لعبة (جرعة واحدة في الليلة). ترين ضحية الذئاب كل ليلة.", "القرية"],
    ["little_girl", "الطفلة", "Little Girl", "👧", "يمكنك التجسس ليلًا فتحصلين على 3 أسماء بينها ذئب، لكن بنسبة 20% تُكشفين فتموتين.", "القرية"],
    ["mayor", "العمدة", "Mayor", "🎖️", "صوتك في التصويت النهاري يُحسب بصوتين.", "القرية"],
    ["white_wolf", "الذئب الأبيض", "White Wolf", "🤍", "ذئب يلعب مع الذئاب، وفي الليالي الزوجية يمكنه قتل رفيق منهم. يفوز وحده إن بقي آخر لاعب حي.", "الذئاب"]
  ].map(function (r) { return { key: r[0], name_ar: r[1], name_en: r[2], emoji: r[3], description: r[4], team: r[5], image_url: "/assets/cards/" + r[0] + ".png" }; });

  var DEMO_DATA = {
    status: { bot_online: true, phase: "day", phase_label: "النقاش", night: 2, waiting_players: 0, alive_players: 6, dead_players: 2, min_players: 5, guild_name: "قرية Merou Last", member_count: 128, updated_at: new Date().toISOString() },
    totals: { players: 64, games: 37 },
    site: { banner: "", invite_url: "" },
    leaderboard: [["نور", 118, 31, 19], ["ريان", 96, 28, 15], ["لينا", 84, 25, 13], ["سامي", 61, 20, 8], ["هديل", 48, 17, 7], ["مازن", 37, 14, 5], ["جود", 26, 11, 3]].map(function (p, i) { return { rank: i + 1, name: p[0], xp: p[1], games: p[2], wins: p[3], level: 20, level_name: "👑 أسطورة القرية", avatar_url: "" }; }),
    news: [{ id: 2, title: "بطولة نهاية الأسبوع 🏆", body: "جولات متتالية يوم الجمعة الساعة 9 مساءً بتوقيت مكة. الجائزة: رتبة ذهبية خاصة!", author: "الإدارة", pinned: true, created_at: new Date(Date.now() - 36e5 * 5).toISOString() }, { id: 1, title: "أدوار جديدة", body: "أضفنا الطفلة والعمدة والذئب الأبيض. اقرأوا شرحها في قسم الأدوار.", author: "الإدارة", pinned: false, created_at: new Date(Date.now() - 864e5 * 3).toISOString() }],
    history: [{ winner: "wolves", winner_label: "الذئاب", players: 8, nights: 3, winners: ["نور", "سامي"], ended_at: new Date(Date.now() - 36e5 * 2).toISOString() }, { winner: "villagers", winner_label: "القرويون", players: 7, nights: 4, winners: ["ريان", "لينا", "هديل", "جود", "مازن"], ended_at: new Date(Date.now() - 864e5).toISOString() }]
  };

  var state = { filter: "all", roles: ROLES, wakeTimer: 0, data: null };

  function ago(iso) {
    if (!iso) return "";
    var s = (new Date(iso).getTime() - Date.now()) / 1000, a = Math.abs(s);
    try {
      var f = new Intl.RelativeTimeFormat("ar", { numeric: "auto" });
      if (a < 3600) return f.format(Math.round(s / 60), "minute");
      if (a < 86400) return f.format(Math.round(s / 3600), "hour");
      if (a < 2592000) return f.format(Math.round(s / 86400), "day");
      return new Date(iso).toLocaleDateString("ar", { day: "numeric", month: "long", year: "numeric" });
    } catch (e) { return new Date(iso).toLocaleDateString(); }
  }

  function toast(msg) { var t = $("toast"); if (!t) return; t.textContent = msg; t.style.display = "block"; setTimeout(function () { t.style.display = "none"; }, 3500); }

  function getJSON(path, ms) {
    var ctl = typeof AbortController !== "undefined" ? new AbortController() : null;
    var timer = setTimeout(function () { if (ctl) ctl.abort(); }, ms || 70000);
    var q = path + (GUILD ? (path.indexOf("?") > -1 ? "&" : "?") + "guild_id=" + GUILD : "");
    return fetch(API + q, { cache: "no-store", signal: ctl ? ctl.signal : undefined }).then(function (r) {
      if (!r.ok) throw new Error("API " + r.status);
      return r.json();
    }).then(function (d) { clearTimeout(timer); return d; }, function (e) { clearTimeout(timer); throw e; });
  }

  /* ───── رسم الأقسام ───── */
  function setLive(ok, text) {
    ["botDot", "heroDot"].forEach(function (id) { var d = $(id); if (d) { d.className = "dot" + (ok === true ? "" : ok === false ? " off" : " wait"); } });
    if ($("heroLive")) $("heroLive").textContent = text;
    if ($("botStatus")) $("botStatus").textContent = ok === true ? "البوت متصل" : ok === false ? "البوت غير متصل" : "جارٍ الاتصال بالبوت…";
  }

  function renderStatus(s, totals) {
    var online = !!s.bot_online;
    setLive(online, online ? ((s.active ? "جولة جارية • " + s.phase_label : "التسجيل مفتوح") + (s.waiting_players ? " • " + num(s.waiting_players) + " بالانتظار" : "")) : "البوت غير متصل حاليًا");
    if (!$("phaseValue")) return;
    $("phaseValue").textContent = s.phase_label || "—";
    $("nightNo").textContent = s.active && s.night ? "• الليلة " + num(s.night) : "";
    $("waitingValue").textContent = num(s.waiting_players);
    $("aliveValue").textContent = num(s.alive_players);
    $("deadValue").textContent = num(s.dead_players);
    $("minPlayers").textContent = num(s.min_players || 5);
    $("guildName").textContent = s.guild_name || "Loup-Garou";
    var map = { night: "night", witch: "night", dawn: "dawn", day: "day", vote: "vote", dusk: "vote" };
    Array.prototype.forEach.call(document.querySelectorAll("#phases .phase"), function (el) { el.classList.toggle("on", s.active && map[s.phase] === el.getAttribute("data-p")); });
    $("lastUpdate").textContent = "آخر تحديث: " + new Date(s.updated_at || Date.now()).toLocaleTimeString("ar") + (DEMO ? " (بيانات تجريبية)" : "");
    if ($("statMembers")) { $("statMembers").textContent = s.member_count ? num(s.member_count) : "—"; $("statGames").textContent = totals ? num(totals.games) : "—"; $("statPlayers").textContent = totals ? num(totals.players) : "—"; }
  }

  function avatar(p, cls) { var u = url(p.avatar_url); return u ? '<img class="avatar ' + (cls || "") + '" src="' + u + '" alt="" loading="lazy" referrerpolicy="no-referrer"/>' : '<span class="avatar ' + (cls || "") + '"></span>'; }

  function renderBoard(list) {
    var root = $("leaderboard"), pod = $("podium"); if (!root) return;
    if (!list || !list.length) { pod.innerHTML = ""; root.innerHTML = '<div class="empty">لا توجد إحصائيات بعد. العبوا أول جولة لتظهروا هنا.</div>'; return; }
    var medals = ["🥇", "🥈", "🥉"];
    pod.innerHTML = list.slice(0, 3).map(function (p, i) {
      return '<div class="panel pod p' + (i + 1) + '"><div class="medal">' + medals[i] + '</div>' + avatar(p) + '<span class="name">' + safe(p.name) + '</span><div class="sub">⭐ ' + num(p.xp) + ' • 🏆 ' + num(p.wins) + '</div></div>';
    }).join("");
    root.innerHTML = list.map(function (p) {
      return '<div class="playerrow"><span class="ranknum">' + (p.rank <= 3 ? medals[p.rank - 1] : num(p.rank)) + '</span><div class="playername">' + avatar(p) + '<div style="min-width:0"><div class="name">' + safe(p.name) + '</div><div class="sub">' + safe(p.level_name || "مبتدئ") + ' • ' + num(p.games) + ' جولة</div></div></div><span class="score">⭐ ' + num(p.xp) + '</span><span class="score">🏆 ' + num(p.wins) + '</span></div>';
    }).join("");
  }

  function renderNews(list) {
    var root = $("newsGrid"); if (!root) return;
    if (!list || !list.length) { root.innerHTML = '<div class="panel empty" style="grid-column:1/-1">لا أخبار حاليًا. استخدم <bdi>/announce</bdi> في ديسكورد لنشر أول إعلان.</div>'; return; }
    root.innerHTML = list.slice(0, 6).map(function (n) {
      return '<article class="panel news"><h3>' + safe(n.title) + (n.pinned ? '<span class="pin">📌 مثبّت</span>' : "") + '</h3><p>' + safe(n.body) + '</p><div class="meta">' + safe(n.author || "الإدارة") + " • " + safe(ago(n.created_at)) + "</div></article>";
    }).join("");
  }

  function renderHistory(list) {
    var root = $("historyGrid"); if (!root) return;
    if (!list || !list.length) { root.innerHTML = '<div class="panel empty" style="grid-column:1/-1">لم تُسجَّل جولات بعد.</div>'; return; }
    root.innerHTML = list.map(function (g) {
      var ico = g.winner === "wolves" ? "🐺" : g.winner === "white_wolf" ? "🤍" : "🏡";
      var names = (g.winners || []).slice(0, 5).map(safe).join("، ") + ((g.winners || []).length > 5 ? "…" : "");
      return '<div class="panel game ' + safe(g.winner) + '"><span class="ico">' + ico + '</span><div><b>فاز ' + safe(g.winner_label) + "</b><span class=\"sub\">" + num(g.players) + " لاعبين • " + num(g.nights) + " ليالٍ • " + safe(ago(g.ended_at)) + '</span><div class="sub">' + names + "</div></div></div>";
    }).join("");
  }

  function renderRoles() {
    var root = $("rolesGrid"); if (!root) return;
    var list = state.roles.filter(function (r) { return state.filter === "all" || r.team === state.filter; });
    root.innerHTML = list.map(function (r) {
      var img = DEMO ? "" : '<img src="' + safe(API + r.image_url) + '" alt="بطاقة ' + safe(r.name_ar) + '" loading="lazy"/>';
      return '<button type="button" class="panel rolecard" data-key="' + safe(r.key) + '"><div class="roleimage">' + (img || safe(r.emoji)) + '</div><div class="rolebody"><span class="pill' + (r.team === "الذئاب" ? " wolf" : "") + '">' + safe(r.team) + "</span><h3>" + safe(r.emoji) + " " + safe(r.name_ar) + "</h3></div></button>";
    }).join("");
    Array.prototype.forEach.call(root.querySelectorAll("img"), function (im) { im.addEventListener("error", function () { var box = im.parentNode, k = im.closest("[data-key]").getAttribute("data-key"); var r = state.roles.filter(function (x) { return x.key === k; })[0]; box.textContent = r ? r.emoji : "🐺"; }); });
  }

  function openRole(key) {
    var r = state.roles.filter(function (x) { return x.key === key; })[0]; if (!r) return;
    $("rmImg").innerHTML = DEMO ? safe(r.emoji) : '<img src="' + safe(API + r.image_url) + '" alt=""/>';
    $("rmTeam").textContent = r.team; $("rmTeam").className = "pill" + (r.team === "الذئاب" ? " wolf" : "");
    $("rmTitle").textContent = r.emoji + " " + r.name_ar + " / " + r.name_en; $("rmDesc").textContent = r.description;
    $("roleModal").hidden = false; $("rmClose").focus();
  }
  function closeRole() { $("roleModal").hidden = true; }

  function applySite(site) {
    var invite = (site && site.invite_url) || C.DISCORD_INVITE || "";
    var ok = /^https:\/\/(discord\.gg|discord\.com\/invite)\//.test(invite);
    Array.prototype.forEach.call(document.querySelectorAll("[data-invite]"), function (a) { a.href = ok ? invite : "#"; });
    var b = $("banner"); if (b) { var t = site && site.banner; b.hidden = !t; b.textContent = t ? "📣 " + t : ""; }
  }

  function renderAll(d) {
    state.data = d; renderStatus(d.status, d.totals); renderBoard(d.leaderboard); renderNews(d.news); renderHistory(d.history); applySite(d.site);
  }

  /* ───── التحميل ───── */
  var inflight = false;
  function load(first) {
    if (inflight) return; inflight = true;
    var wake = first ? setTimeout(function () { setLive(null, "البوت يستيقظ… قد يستغرق حتى دقيقة (استضافة مجانية)"); if ($("lastUpdate")) $("lastUpdate").textContent = "⏳ الاستضافة المجانية تنام عند الخمول؛ انتظر قليلًا."; }, 5000) : 0;
    getJSON("/api/public/summary?limit=10").then(function (d) { clearTimeout(wake); renderAll(d); }).catch(function (e) {
      clearTimeout(wake);
      setLive(false, "تعذّر الاتصال بالبوت");
      if ($("lastUpdate")) $("lastUpdate").innerHTML = '<span class="error">' + safe(e.name === "AbortError" ? "انتهت مهلة الاتصال" : e.message) + "</span> — تحقق من API_BASE ومن أن الخدمة تعمل.";
      if (first) { renderBoard(null); renderNews(null); renderHistory(null); applySite({}); }
    }).then(function () { inflight = false; });
  }

  function reveal() {
    var els = document.querySelectorAll(".reveal");
    if (!("IntersectionObserver" in window)) { Array.prototype.forEach.call(els, function (e) { e.classList.add("in"); }); return; }
    var io = new IntersectionObserver(function (en) { en.forEach(function (x) { if (x.isIntersecting) { x.target.classList.add("in"); io.unobserve(x.target); } }); }, { threshold: .08 });
    Array.prototype.forEach.call(els, function (e) { io.observe(e); });
  }

  function init() {
    if ($("year")) $("year").textContent = new Date().getFullYear();
    applySite({});
    if (!$("status")) return;                                  /* صفحات المدونة: لا توجد لوحة */
    reveal();
    var demo = $("demo"); if (demo && DEMO) demo.hidden = false;
    Array.prototype.forEach.call(document.querySelectorAll(".chip"), function (c) { c.addEventListener("click", function () { state.filter = c.getAttribute("data-f"); Array.prototype.forEach.call(document.querySelectorAll(".chip"), function (x) { x.setAttribute("aria-pressed", x === c ? "true" : "false"); }); renderRoles(); }); });
    $("rolesGrid").addEventListener("click", function (e) { var b = e.target.closest("[data-key]"); if (b) openRole(b.getAttribute("data-key")); });
    $("rmClose").addEventListener("click", closeRole);
    $("roleModal").addEventListener("click", function (e) { if (e.target === this) closeRole(); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeRole(); });
    $("refreshBtn").addEventListener("click", function () { if (DEMO) { renderAll(DEMO_DATA); toast("هذه بيانات تجريبية — اربط البوت لعرض بياناتك."); } else { load(false); toast("جارٍ التحديث…"); } });
    renderRoles();
    if (DEMO) { renderAll(DEMO_DATA); return; }
    getJSON("/api/public/roles", 20000).then(function (d) { if (d.roles && d.roles.length) { state.roles = d.roles; renderRoles(); } }).catch(function () {});
    load(true);
    setInterval(function () { if (!document.hidden) load(false); }, 30000);
    document.addEventListener("visibilitychange", function () { if (!document.hidden) load(false); });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
  /* نسخ رابط المنشور */
  document.addEventListener("click", function (e) { var inv = e.target.closest && e.target.closest("a[data-invite]"); if (inv && inv.getAttribute("href") === "#") { e.preventDefault(); toast("لم يُضبط رابط الدعوة بعد (DISCORD_INVITE)."); return; } var b = e.target.closest && e.target.closest("[data-copy]"); if (b && navigator.clipboard) { navigator.clipboard.writeText(b.getAttribute("data-copy")).then(function () { toast("تم نسخ الرابط ✓"); }); } });
})();
