#!/usr/bin/env python3
"""يبني ملفين من نفس المصدر:
  ../Merou_Last_Blogger_Theme.xml  (قالب Blogger كامل: لوحة + مدونة)
  ../dashboard-embed.html          (نسخة احتياطية تُلصق في صفحة/ودجة HTML)
التشغيل:  python3 build.py   (لا يحتاج أي مكتبة)."""
from pathlib import Path
from xml.dom import minidom

SRC = Path(__file__).parent
OUT = SRC.parent
css = (SRC / "style.css").read_text("utf-8")
home = (SRC / "home.html").read_text("utf-8").rstrip()
js = (SRC / "app.js").read_text("utf-8")

NAV = [("status", "حالة اللعبة"), ("news", "الأخبار"), ("ranking", "المتصدرون"), ("roles", "الأدوار"), ("rules", "طريقة اللعب"), ("blog", "المدونة")]
FONT = "https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;800;900&amp;display=swap"

CONFIG = """/* ═══════════ الإعدادات — عدّل هذه القيم فقط ═══════════ */
window.MEROU_CONFIG = {
  API_BASE: "https://YOUR-SERVICE.onrender.com",   /* رابط خدمة البوت (Render) بدون / في النهاية */
  DISCORD_INVITE: "https://discord.gg/YOUR_INVITE", /* رابط دعوة احتياطي؛ يمكن تغييره لاحقًا من ديسكورد بأمر /site_invite */
  GUILD_ID: ""                                      /* اتركه فارغًا إذا ضبطت GUILD_ID على الاستضافة */
};
/* ═══════════════════════════════════════════════════ */"""

def nav_links(blogger):
    out = []
    for k, label in NAV:
        if blogger:
            out.append("<a expr:href='data:blog.homepageUrl + &quot;#%s&quot;'>%s</a>" % (k, label))
        else:
            out.append('<a href="#%s">%s</a>' % (k, label))
    return "".join(out)

def top(blogger):
    brand_href = "expr:href='data:blog.homepageUrl'" if blogger else 'href="#home"'
    return ('<div class="banner" hidden="hidden" id="banner" role="status"></div>'
            '<div class="demo" hidden="hidden" id="demo">👀 وضع المعاينة: هذه بيانات تجريبية. عدّل <b>API_BASE</b> في القالب لربط البوت.</div>'
            '<header class="nav"><div class="wrap navin"><a class="brand" %s><span class="brandmark">🐺</span>'
            '<span>MEROU LAST<small>LOUP-GAROU ULTIMATE</small></span></a>'
            '<nav aria-label="القائمة الرئيسية" class="navlinks">%s</nav>'
            '<a class="btn" data-invite="1" href="#" rel="noopener" target="_blank">انضم إلى السيرفر ↗</a></div></header>'
            % (brand_href, nav_links(blogger)))

FOOTER = ('<footer class="footer"><div class="wrap footin"><span>© <span id="year"></span> Merou Last — Loup-Garou Ultimate</span>'
          '<span>صُممت لعشاق الغموض والاستراتيجية 🐺</span></div></footer><div class="toast" id="toast" role="status"></div>')

BLOG_WIDGET = """<b:section class='main' id='main' maxwidgets='1' showaddelement='no'>
<b:widget id='Blog1' locked='true' title='المنشورات' type='Blog' version='1'>
<b:includable id='main' var='top'>
<div class='blog-posts hfeed'>
  <b:if cond='data:blog.pageType != &quot;item&quot;'>
    <b:if cond='data:blog.searchLabel'><div class='pagehead'><h1>🏷️ <data:blog.searchLabel/></h1></div></b:if>
    <b:if cond='data:blog.searchQuery'><div class='pagehead'><h1>🔎 نتائج: <data:blog.searchQuery/></h1></div></b:if>
  </b:if>
  <b:loop values='data:posts' var='post'>
    <b:include data='post' name='post'/>
  </b:loop>
</div>
<b:include name='nextprev'/>
</b:includable>

<b:includable id='post' var='post'>
<article class='panel post-card' expr:id='&quot;post-&quot; + data:post.id'>
  <b:if cond='data:blog.pageType != &quot;item&quot; and data:post.firstImageUrl'>
    <a expr:href='data:post.url'><img alt='' class='thumb' expr:src='data:post.firstImageUrl' loading='lazy'/></a>
  </b:if>
  <div class='post-inner'>
    <b:if cond='data:post.title != &quot;&quot;'>
      <b:if cond='data:blog.pageType == &quot;item&quot;'>
        <h1 class='post-title entry-title'><data:post.title/></h1>
      <b:else/>
        <h2 class='post-title entry-title'><a expr:href='data:post.url'><data:post.title/></a></h2>
      </b:if>
    </b:if>
    <div class='post-meta'><span>📅 <data:post.timestamp/></span><span>✍️ <data:post.author/></span></div>
    <b:if cond='data:blog.pageType == &quot;item&quot;'>
      <div class='post-body entry-content'><data:post.body/></div>
    <b:else/>
      <p class='post-snippet'><b:eval expr='data:post.body snippet {length: 240, links: false, linebreaks: false, ellipsis: true}'/></p>
      <a class='btn small secondary' expr:href='data:post.url'>اقرأ المزيد ←</a>
    </b:if>
    <b:if cond='data:post.labels'>
      <div class='labels'><b:loop values='data:post.labels' var='label'><a expr:href='data:label.url' rel='tag'>#<data:label.name/></a></b:loop></div>
    </b:if>
    <b:if cond='data:blog.pageType == &quot;item&quot;'>
      <div class='share'>
        <a class='btn small secondary' expr:href='&quot;https://wa.me/?text=&quot; + data:post.url' rel='noopener' target='_blank'>واتساب</a>
        <a class='btn small secondary' expr:href='&quot;https://t.me/share/url?url=&quot; + data:post.url' rel='noopener' target='_blank'>تيليجرام</a>
        <a class='btn small secondary' expr:href='&quot;https://twitter.com/intent/tweet?url=&quot; + data:post.url' rel='noopener' target='_blank'>X</a>
        <button class='btn small secondary' expr:data-copy='data:post.url' type='button'>نسخ الرابط</button>
      </div>
    </b:if>
  </div>
</article>
<b:if cond='data:blog.pageType == &quot;item&quot;'><b:include data='post' name='comments'/></b:if>
</b:includable>

<b:includable id='comments' var='post'>
<b:if cond='data:post.allowComments'>
<section class='panel comments' id='comments'>
  <h3>💬 التعليقات</h3>
  <b:if cond='data:post.comments'>
    <b:loop values='data:post.comments' var='comment'>
      <div class='comment'><b><data:comment.author/></b> <span class='sub'>• <data:comment.timestamp/></span><div><data:comment.body/></div></div>
    </b:loop>
  </b:if>
  <a class='btn small' expr:href='data:post.addCommentUrl'>✍️ أضف تعليقًا</a>
</section>
</b:if>
</b:includable>

<b:includable id='nextprev'>
<div class='blog-pager' id='blog-pager'>
  <b:if cond='data:newerPageUrl'><a class='btn secondary' expr:href='data:newerPageUrl' rel='next'>→ الأحدث</a><b:else/><span></span></b:if>
  <b:if cond='data:blog.pageType != &quot;static_page&quot;'><a class='btn secondary' expr:href='data:blog.homepageUrl'>🏠 الرئيسية</a></b:if>
  <b:if cond='data:olderPageUrl'><a class='btn secondary' expr:href='data:olderPageUrl' rel='prev'>الأقدم ←</a><b:else/><span></span></b:if>
</div>
</b:includable>
</b:widget>
</b:section>"""

def theme():
    nav = top(True)
    search = ("<form class='searchbox' expr:action='data:blog.homepageUrl + &quot;search&quot;' method='get' role='search'>"
              "<input aria-label='بحث' name='q' placeholder='ابحث في المدونة…' type='search'/><button class='btn small' type='submit'>بحث</button></form>")
    return f"""<?xml version="1.0" encoding="UTF-8" ?>
<!DOCTYPE html>
<html b:version='2' class='v2' dir='rtl' lang='ar' xmlns='http://www.w3.org/1999/xhtml' xmlns:b='http://www.google.com/2005/gml/b' xmlns:data='http://www.google.com/2005/gml/data' xmlns:expr='http://www.google.com/2005/gml/expr'>
<head>
  <meta content='width=device-width, initial-scale=1' name='viewport'/>
  <meta content='#080b14' name='theme-color'/>
  <link href='https://fonts.googleapis.com' rel='preconnect'/>
  <link crossorigin='anonymous' href='https://fonts.gstatic.com' rel='preconnect'/>
  <link href='{FONT}' rel='stylesheet'/>
  <b:include data='blog' name='all-head-content'/>
  <title><data:blog.pageTitle/></title>
  <b:skin><![CDATA[
/* Merou Last — قالب Blogger للعبة Loup-Garou (مبني من src/ بواسطة build.py) */
{css}
]]></b:skin>
</head>
<body expr:class='&quot;pagetype-&quot; + data:blog.pageType'>
{nav}
<b:if cond='data:blog.url == data:blog.homepageUrl'>
{home}
</b:if>
<div class='wrap' id='blog'>
  <div class='section'>
    <b:if cond='data:blog.url == data:blog.homepageUrl'>
      <div class='sectionhead'><div><h2>📰 المدونة</h2><p>مقالات وأدلة واستراتيجيات من مجتمع اللعبة.</p></div></div>
    </b:if>
    {search}
  </div>
{BLOG_WIDGET}
</div>
{FOOTER}
<script type='text/javascript'>
//<![CDATA[
{CONFIG}
{js}
//]]>
</script>
</body>
</html>
"""

def embed():
    return f"""<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
<meta charset="UTF-8"/><meta content="width=device-width, initial-scale=1" name="viewport"/>
<meta content="#080b14" name="theme-color"/><title>Merou Last | Loup-Garou</title>
<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;800;900&display=swap" rel="stylesheet"/>
<style>
{css}
</style></head><body>
{top(False)}
{home}
{FOOTER}
<script>
{CONFIG}
{js}
</script></body></html>
"""

if __name__ == "__main__":
    t = theme()
    minidom.parseString(t.encode("utf-8"))        # يتأكد أن القالب XML سليم
    (OUT / "Merou_Last_Blogger_Theme.xml").write_text(t, "utf-8")
    (OUT / "dashboard-embed.html").write_text(embed(), "utf-8")
    print("built:", len(t) // 1024, "KB theme,", len(embed()) // 1024, "KB embed")
