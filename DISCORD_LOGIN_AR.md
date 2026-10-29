# تسجيل الدخول بحساب Discord (الجزء 1: الخادم)

يعمل داخل البوت نفسه على Render المجاني. بدون Firebase وبدون قاعدة بيانات إضافية وبدون أي رسوم.

## كيف يعمل
1. الموقع يفتح `/auth/discord/start` ← يحوّلك إلى Discord للموافقة (صلاحية `identify` فقط).
2. يعود Discord إلى `/auth/discord/callback` ← **البوت يتحقق أنك عضو في السيرفر** (`GUILD_ID`).
3. يصدر الخادم جلسة موقّعة (HMAC) مدتها 7 أيام ويرسلها للموقع. لا يُحفظ شيء على الخادم.
4. الموقع يرسل الجلسة في ترويسة `Authorization: Bearer ...` إلى `/api/me`، والخادم يعيد فحص العضوية في كل مرة، فمن غادر السيرفر تنتهي جلسته.

## الإعداد (مرة واحدة)
1. **Discord Developer Portal ← تطبيق البوت ← OAuth2**
   - انسخ **Client ID**، وأنشئ **Client Secret** (سري).
   - في **Redirects** أضف بالضبط: `https://اسم-خدمتك.onrender.com/auth/discord/callback`
2. **Render ← Environment** أضف:

   | المتغير | القيمة |
   |---|---|
   | `DISCORD_CLIENT_ID` | Client ID |
   | `DISCORD_CLIENT_SECRET` | Client Secret (سري) |
   | `SESSION_SECRET` | نص عشوائي طوله 32 حرفًا أو أكثر (سري). يمكن توليده من أي مولّد كلمات مرور، أو بالأمر `python3 -c "import secrets;print(secrets.token_urlsafe(48))"` |
   | `SITE_ORIGINS` | رابط موقعك فقط، مثل `https://اسمك.blogspot.com` (بدون `/` في النهاية). **لا تتركه `*`** وإلا يتعطل الدخول عمدًا |
   | `GUILD_ID` | رقم السيرفر (موجود عندك أصلًا) |

   اختياري: `SESSION_DAYS` (1–30، الافتراضي 7) و`OAUTH_REDIRECT_URI` (فقط إن استعملت نطاقًا خاصًا مع Render).
3. أعد نشر الخدمة. في **Logs** ابحث عن `تسجيل الدخول بديسكورد مفعّل`. وإن ظهر `معطّل` فالسطر نفسه يذكر ما ينقص.

يجب أن يكون **Server Members Intent** مفعّلًا للبوت (كما في `INSTALL_AR.md`).

## اختبار قبل أن يصل زر الدخول (الجزء 2)
1. افتح `https://اسمك.onrender.com/auth/discord/status` ← يجب أن ترى `"enabled": true`.
2. افتح من المتصفح:
   `https://اسمك.onrender.com/auth/discord/start?origin=https://اسمك.blogspot.com&mode=redirect`
   وافق في Discord. ستعود إلى مدونتك وفي شريط العنوان `#ya_auth=...`. هذا هو رمز جلستك، فلا تشارك ذلك الرابط مع أحد.
3. جرّب بحساب ليس عضوًا في السيرفر ← تعود المدونة بـ `#ya_auth_error=not_member`.

أول طلب بعد نوم Render قد يتأخر نحو دقيقة.

## عقد الواجهة (للجزء 2)
`GET /auth/discord/start` بمعاملات: `origin` (إلزامي، أصل موقعك) و`mode` (`popup` الافتراضي أو `redirect`) و`return` (اختياري، رابط من نفس الأصل للعودة إليه).

- **popup**: النافذة تستدعي `window.opener.postMessage(msg, origin)` على موقعك فقط:
  - نجاح: `{type:"youcef-discord-auth", ok:true, token, expires_at, user:{id,name,avatar_url}}`
  - فشل: `{type:"youcef-discord-auth", ok:false, error}`
  - إن فقدت المتصفحات `window.opener` أثناء المرور بـ Discord، تتحول النافذة نفسها إلى موقعك مع `#ya_auth=` (يعالجها الموقع كما في وضع redirect).
- **redirect** (الأنسب للجوال): العودة إلى `return` مع `#ya_auth=<token>` أو `#ya_auth_error=<code>`.
- رموز الخطأ: `denied` و`not_member` و`unavailable` و`failed`.
- `GET /api/me` مع `Authorization: Bearer <token>`:
  - 200 `{ok, user:{id,name,avatar_url}, expires_at}`
  - 401 `unauthorized` (جلسة غير صالحة أو منتهية)
  - 403 `not_member` (غادر السيرفر)
  - 503 `unavailable` (البوت نائم أو غير جاهز: أعد المحاولة ولا تُخرج المستخدم)
- `GET /auth/discord/status` ← `{ok, enabled}` ليعرف الموقع هل يعرض الزر.

## الأمان
- الجلسة والـ `state` رموز موقّعة بـ HMAC-SHA256 ومفصولة بالغرض، فرمز لا يصلح مكان الآخر.
- الـ `state` مربوط بكوكي `HttpOnly` في متصفح صاحب المحاولة (يمنع تسجيل دخول بحساب مهاجم).
- النتيجة تُرسل إلى أصل موقعك المسموح في `SITE_ORIGINS` فقط، وروابط العودة يجب أن تكون من نفس الأصل.
- لا تُطبع الأسرار في السجل. لا تضع أي سر في القالب.

## حدود يجب أن تعرفها
- لا يمكن إلغاء جلسة واحدة بعينها. لإخراج الجميع غيّر `SESSION_SECRET`.
- Blogger يعرض صفحاته للجميع، فهذا الدخول يحمي ما يمر عبر هذا الخادم لاحقًا (الألعاب والغرف)، لا محتوى القالب نفسه.
- يجب أن يطابق `SITE_ORIGINS` العنوان الظاهر في المتصفح حرفيًا (`https` والنطاق بدون مسار).
- `prompt=none` يتجاوز شاشة الموافقة لمن وافق سابقًا. لم يُجرَّب على Discord الحقيقي.
