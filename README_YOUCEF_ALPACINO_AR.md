# Youcef Alpacino — الحزمة الموحدة

## محتويات الحزمة
- `merou_last_blogger/Merou_Last_Blogger_Theme.xml`: قالب Blogger المحدث.
- `merou_last_blogger/dashboard-embed.html`: نسخة للصفحة/ودجة HTML.
- `merou_last_blogger/src/`: مصدر HTML/CSS/JS للقالب.
- `firebase/firestore.rules`: قواعد Firestore.
- `firebase/functions/`: نقطة بداية للتحقق من عضوية Discord عبر خادم Firebase.
- `firebase/web/firebase-config.js`: إعداد الويب العام الذي زودتني به.
- `FIREBASE_SECURITY_AR.md`: خطوات إعداد الأمان والنشر.
- `loup_garou_discord_bot` في جذر هذه الحزمة هو نفس مشروع البوت القديم مع تحديث اسم/واجهة الموقع.

## الروابط المضبوطة
- Discord: https://discord.gg/sDBjcqcQjK
- Guild ID: `1564749301203079422`
- TikTok: https://www.tiktok.com/@youcefalpa22?_r=1&_t=ZS-9AwgfxwIywf7
- متجر الشحن: https://meroulast.online
- Firebase project: `youcefalpacino`

## تركيب القالب
1. افتح `merou_last_blogger/Merou_Last_Blogger_Theme.xml`.
2. قبل رفع القالب، عدّل `API_BASE` داخل كتلة `MEROU_CONFIG` قرب نهاية الملف إلى رابط خدمة البوت الحقيقية على Render. لا تترك `YOUR-SERVICE` إذا أردت إحصائيات حية.
3. في Blogger: المظهر → النسخ الاحتياطي أولًا → استعادة/تحميل القالب.
4. لا تضع توكن Discord أو أسرار Firebase في القالب.

## حالة التنفيذ
واجهة البوابة والروابط وقواعد الأمان الأساسية ودوال بداية تحقق Discord موجودة. محركات الألعاب الجديدة، تسجيل الدخول المدمج في القالب، والتحقق من الحركات من جهة الخادم لا تزال تحتاج إلى تنفيذ واختبار؛ لا تعتبر بطاقات الألعاب الخمس ألعابًا مكتملة حاليًا. الأوامر الجديدة مثل `/game-create` و`/game-setup` و`/game-start` ليست مضافة إلى البوت بعد.

اقرأ `FIREBASE_SECURITY_AR.md` قبل نشر قواعد الأمان أو الدوال.
