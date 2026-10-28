# Merou Last — واجهة Blogger وربطها ببوت Loup-Garou

## قبل البدء
هذه الواجهة تقرأ البيانات العامة فقط من البوت عبر API للقراءة. لا توجد واجهة ويب للتحكم في اللعبة، ولا يتم كشف الأدوار السرية أو توكن البوت.

## 1) تحديث مستودع GitHub
1. فك ضغط الحزمة الكاملة وافتح مجلد `loup_garou_discord_bot`.
2. ارفع محتوياته إلى **نفس مستودع GitHub** الذي يتصل بخدمة Render، مع استبدال الملفات القديمة عند الطلب. لا ترفع ملف `.env` ولا أي توكن.
3. تأكد أن الملفات `bot.py`, `db.py`, `engine.py`, `requirements.txt`, `Dockerfile`, `render.yaml` موجودة في جذر المستودع (وليس داخل مجلد متداخل إضافي).
4. اعمل Commit باسم `Add Merou Last public API and Blogger dashboard` ثم Push. Render سيبدأ النشر تلقائيًا إذا كان Auto-Deploy مفعّلًا.
5. في Render → Environment تأكد من `DISCORD_TOKEN`, `MONGODB_URI`, `GUILD_ID`. لا تغيّر القيم السرية. أعد النشر إن لم يبدأ تلقائيًا.

## 2) اختبر API قبل Blogger
استبدل `YOUR-SERVICE.onrender.com` بعنوان خدمة Render الحقيقي، و`YOUR_GUILD_ID` بمعرّف سيرفرك: `https://YOUR-SERVICE.onrender.com/api/public/status?guild_id=YOUR_GUILD_ID`
ثم جرّب: `/api/public/leaderboard?guild_id=YOUR_GUILD_ID&limit=10` و`/api/public/roles`. يجب أن ترى JSON مع `ok: true`.

## 3) رفع قالب Blogger
1. افتح Blogger → المظهر (Theme) → السهم بجانب تخصيص → الاحتفاظ بنسخة احتياطية ثم استعادة (Restore).
2. ارفع الملف `Merou_Last_Blogger_Theme.xml`.
3. افتح ملف XML وابحث عن `const CONFIG = { API_BASE: ... , GUILD_ID: ... , DISCORD_INVITE: ... }`، ثم عدّل القيم الثلاث قبل الرفع، أو ارفع القالب بعد التعديل.
4. `API_BASE` يجب أن يكون أصل Render فقط مثل `https://your-service.onrender.com` دون `/` في النهاية. `GUILD_ID` رقم سيرفر Discord. `DISCORD_INVITE` رابط دعوة السيرفر.
5. افتح المدونة على الهاتف والكمبيوتر، واختبر حالة اللعبة والترتيب وبطاقات الأدوار.

## 4) إذا كان القالب لا يقبل الرفع
بعض قوالب Blogger القديمة تتعارض مع قوالب XML الحديثة. احتفظ بنسخة احتياطية، ثم جرّب الرفع من متصفح سطح المكتب. ملف `dashboard-embed.html` نسخة بديلة يمكن وضعها في صفحة Blogger عبر عرض HTML، لكن يجب تعديل `CONFIG` فيه أيضًا.

## حدود واقعية مهمة
- لا يمكن ضمان عمل الخدمة 100% قبل النشر على حسابك واختبارها على رابط Render الحقيقي وسيرفرك؛ صلاحيات Discord، إعدادات Render، ونوم الخطة المجانية عوامل خارج الملفات.
- واجهة Blogger تعرض الحالة العامة والترتيب والأدوار والصور، لكنها لا تستطيع التحكم في الجولة من دون إضافة نظام تسجيل دخول آمن وواجهة تحكم موقعة. لا نضع أي توكن Discord أو مفتاح إداري في Blogger.
- في MongoDB تأكد أن البوت يعرض الإحصائيات المطلوبة. إذا كان البوت يستخدم SQLite بدل MongoDB فستكون بيانات الترتيب مختلفة عن قاعدة MongoDB. راجع Render Logs وابحث عن `متصل بـ MongoDB`.
