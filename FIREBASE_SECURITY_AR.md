# دليل إعداد Firebase والأمان — Youcef Alpacino

هذا الملف جزء من الحزمة. المشروع الحالي يستخدم Firestore في قواعد الأمان المقترحة، بينما بوت Loup-Garou الحالي يحتفظ بواجهته/API منفصلين. **قواعد Firestore وحدها لا تجعل الألعاب متعددة اللاعبين مكتملة**؛ يلزم نشر محرك ألعاب موثوق في الخادم ليُطبّق الأدوار والحركات ويتحقق منها.

## 1) إنشاء Firestore وتثبيت القواعد
1. افتح https://console.firebase.google.com/ واختر مشروع **youcefalpacino**.
2. من **Build → Firestore Database** اضغط **Create database**. اختر الموقع الأقرب لك؛ موقع قاعدة البيانات لا يمكن تغييره لاحقًا بسهولة.
3. اختر وضع **Production**.
4. بعد إنشاء قاعدة البيانات افتح **Firestore Database → Rules**.
5. افتح الملف `firebase/firestore.rules` من هذه الحزمة، وانسخ محتواه كاملًا إلى محرر Rules في Firebase.
6. اضغط **Publish**.
7. هذه القواعد تمنع الكتابة المباشرة إلى حالة اللعبة. لا تفتح القواعد بـ `allow read, write: if true` ولا تستخدم وضع الاختبار في الإنتاج.

> مهم: إذا نشرت هذه القواعد قبل نشر تسجيل دخول Discord، فسيُمنع الزوار من قراءة/كتابة بيانات Firestore، وهذا مقصود وآمن. لا تُخفّف القواعد كي تتجاوز رسالة Permission denied؛ أكمل تسجيل الدخول أولًا.

## 2) إعداد Discord OAuth
1. افتح https://discord.com/developers/applications وأنشئ تطبيقًا أو اختر تطبيق البوت الحالي.
2. من **OAuth2 → General** انسخ **Client ID**. أنشئ/انسخ **Client Secret** ولا ترسله في الدردشة ولا تضفه إلى Blogger.
3. في صفحة **OAuth2 → Redirects** أضف رابط callback بعد نشر الدالة. شكله:
   `https://us-central1-youcefalpacino.cloudfunctions.net/discordCallback`
   إذا نشرت الدوال في منطقة أخرى، استعمل الرابط الذي تعرضه Firebase CLI بدل هذا المثال.
4. تأكد أن بوت Discord موجود في السيرفر `1564749301203079422`، وأن **Server Members Intent** مفعّل من **Bot → Privileged Gateway Intents**. نقطة التحقق تستخدم توكن البوت على الخادم، لا على الموقع.

## 3) نشر دوال التحقق
تحتاج Node.js 20 وFirebase CLI. من الطرفية:
```bash
npm install -g firebase-tools
firebase login
cd firebase
firebase use youcefalpacino
cd functions
npm install
cd ..
firebase functions:secrets:set DISCORD_CLIENT_SECRET
firebase functions:secrets:set DISCORD_BOT_TOKEN
```

أدخل Client Secret عند طلبه، ثم توكن البوت عند طلبه. لا تضعهما داخل ملف JavaScript أو Blogger أو GitHub.

قبل النشر، عيّن معرّف تطبيق Discord وأصل الموقع. أسهل طريقة لملفات Firebase الجديدة هي إعداد متغيرات الدوال عند النشر. افتح `firebase/functions/index.js` وتأكد أن قيم `DISCORD_CLIENT_ID` و`SITE_ORIGIN` تُعرّف عند أول نشر. عند مطالبة Firebase بقيم `defineString` أدخل:
- `DISCORD_CLIENT_ID`: Client ID من Discord Developer Portal.
- `DISCORD_GUILD_ID`: `1564749301203079422`.
- `SITE_ORIGIN`: رابط مدونتك بالضبط، مثل `https://YOURBLOG.blogspot.com` (من دون `/` في النهاية).

ثم:
```bash
cd firebase
firebase deploy --only functions,firestore:rules
```

بعد النشر، افتح رابط `discordStart` الذي تعرضه Firebase CLI لاختبار تدفق OAuth. يجب أن يكون Redirect URL المسجل في Discord مطابقًا تمامًا لرابط `discordCallback` المنشور.

### ملاحظات مهمة على النسخة الحالية
- `discordStart` و`discordCallback` هي نقطة بداية آمنة للتحقق من العضوية من جهة الخادم، لكنها ليست زر تسجيل دخول مدمجًا تلقائيًا في قالب Blogger بعد؛ يجب ربطها بواجهة العميل عبر Firebase Auth `signInWithCustomToken` ونافذة popup تستخدم `postMessage` من نفس `SITE_ORIGIN`.
- لا يُسمح للمتصفح بكتابة حالة اللوحة/الدور مباشرة. يجب أن يستقبل محرك اللعبة الأفعال ويتحقق من الدور واللاعب والمرحلة قبل تعديل Firestore عبر Admin SDK.
- لا تخزن توكن البوت أو Client Secret في `firebase-config.js`؛ ملف إعداد الويب يحوي معلومات عامة فقط.
- إذا ظهر خطأ في نشر `defineString` أو لم يُطلب منك إدخال القيم، راجع متغيرات Firebase Functions الحالية واضبطها عبر Firebase CLI وفق إصدار CLI لديك.

## 4) صور أعضاء Discord
صور الأعضاء الخاصة باللاعبين الذين سجلوا الدخول يمكن عرضها من بيانات OAuth/ملف اللاعب بعد التحقق. لا يمكن جلب صور كل أعضاء السيرفر من Blogger وحده؛ ذلك يحتاج API آمنًا من جهة الخادم واحترام إعدادات الخصوصية.

## 5) ما الموجود في هذه الحزمة
- قالب Blogger مُعاد تسميته إلى **Youcef Alpacino** مع رابط Discord، TikTok، ومتجر Merou Last.
- واجهة ساحة للألعاب Jackaroo وUNO وDominoes وLudo وWho Is the Spy وLoup-Garou.
- قواعد Firestore مقيدة وملفات بداية لدوال تحقق عضوية Discord.
- مشروع البوت القديم وملفاته الأصلية.

**بشفافية:** ألعاب Jackaroo وUNO وDominoes وLudo وWho Is the Spy معروضة في الواجهة فقط في هذه النسخة، ومحركات اللعب الجماعي وأوامر Discord الجديدة الخاصة بها لم تُنفّذ أو تُختبر بعد. لعبة Loup-Garou هي اللعبة الموجودة في مشروع البوت الأصلي. لا تفتح الموقع على أنه يحتوي ألعابًا جاهزة قبل استكمال المحركات وربط تسجيل الدخول واختبارها.
