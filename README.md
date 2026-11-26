# OnlineXarid — yangilangan loyiha (MVP v3)

## Tarkib
- Telegram bot: `/start`, telefon kontaktini faqat egasidan qabul qilish, bitta xush kelibsiz xabari va Mini App tugmasi.
- Oddiy foydalanuvchi xabarlari o'chirilmaydi. Bot foydalanuvchi yuborgan matnlarni avtomatik o'chirishga urinmaydi.
- Telegram Mini App: katalog, qidiruv, kategoriya, mahsulot tafsiloti, savat, buyurtmalar, hamyon, profil va pochta filiallari.
- Admin API/UI: statistika, buyurtmalar va holatlari, mahsulotlar, filiallar, adminlar, foydalanuvchi qidiruvi.
- SQLite bazasi va oldingi order jadvallari uchun migratsiya.
- BTS rasmiy ofis sahifasidan foydalanuvchi taqdim etgan HTML manbadan ajratilgan 404 ta O‘zbekiston filiali `bts_offices_uzbekistan.csv` orqali birinchi ishga tushishda avtomatik bazaga yuklanadi; takroriy ishga tushishda filial kodi bo‘yicha yangilanadi. Filial koordinatalari, manzil, telefon, xarita va mavjud bo‘lsa video havolasi saqlanadi.
- Checkout: hamyon avval qo'llanadi; 100% yoki 40/60 to'lov rejasi hisoblanadi. 40/60 rejada birinchi 40% (hamyon ulushi chegirilgach) va keyingi 60% alohida ko'rsatiladi.
- Buyurtma to'liq to'langan deb admin tasdiqlaganda pickup code yaratiladi.

## Windows'da ishga tushirish
PowerShell'da `oxwork` papkasini oching:

```powershell
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

`.env` faylini to'ldiring:
- `BOT_TOKEN` — BotFather tokeni.
- `BOT_USERNAME` — bot username.
- `ADMIN_IDS` — birinchi admin Telegram ID raqami.
- `WEBAPP_URL` — internetda ochiladigan HTTPS Mini App manzili.
- `FERNET_KEY` — quyidagi buyruq bilan yaratiladi:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Backend:
```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Ikkinchi terminal:
```powershell
.venv\\Scripts\\Activate.ps1
python -m bot.main
```

## To'lov va yetkazib berish bo'yicha muhim holat
Bu kod to'lov summalarini va 40/60 bosqichlarini hisoblaydi, lekin **bank kartasidan pulni o'zi yechmaydi**. Karta to'lovini avtomatik tasdiqlash uchun bank/to'lov provayderining rasmiy API va webhook kerak. `@CardXabarBot` xabarlarini o'qish uchun Telegram user-account integratsiyasi (Telethon), API ID/hash, telefon va alohida xavfsiz sessiya sozlamalari kerak; bu ZIP'da hali ishlaydigan CardXabarBot monitori yo'q.

BTS/UzPost filiallari hozir demo ma'lumotlar. Haqiqiy filiallar, jo'natma yaratish, kuzatuv raqami va pickup kodini tashqi tizimga yuborish uchun yetkazib beruvchining rasmiy API hujjatlari va ruxsati kerak. Pickup code hozircha ichki kod bo'lib, BTS tizimida haqiqiy kod emas.

## Ishlab chiqarishga chiqarishdan oldin
- HTTPS domen va hosting sozlash.
- To'lov provayderi webhookini ulash va imzo tekshirish.
- BTS/pochta API ulash.
- Ombor zaxirasini to'lov tasdiqlanguncha band qilish/vaqti o'tsa bo'shatish.
- To'lov bekor bo'lsa hamyon mablag'ini qaytarish va audit log qo'shish.
- Admin va mijoz oqimlarini real Telegram akkauntlarda sinash.


## Karta xabarnomalarini avtomatik kuzatish (sinov moduli)
1. `.env` ichiga `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_PHONE` kiriting.
2. `pip install -r requirements.txt`
3. Backend ishlayotgan paytda alohida terminalda `python -m app.payment_listener` ni ishga tushiring.
4. Birinchi ishga tushishda Telegram login kodi va 2FA paroli so'raladi. Sessiya `storage/` ichida saqlanadi; uni hech kimga bermang va Git'ga yuklamang.

Listener 5 daqiqalik muddat ichida aynan bir kutilayotgan buyurtma summasi va xabardagi noyob tranzaksiya identifikatorini topishga urinadi. Takroriy tranzaksiya qayta hisoblanmaydi. Kechikkan yoki bir nechta buyurtmaga mos kelgan tushum admin tekshiruviga yuboriladi.

**Juda muhim:** bank xabarlari formati bank va karta turiga qarab farq qiladi. Parser umumiy naqshlardan foydalanadi; real xabarning shaxsiy ma'lumotlari yashirilgan namunasi bilan sinovdan o'tkazilmaguncha avtomatik tasdiqlashni production'da yoqmang. Listener rasmiy acquiring API emas. Bank xabari manbasi `@CardXabarBot` yoki boshqa manbadan kelayotganini tekshirish ham kerak; hozircha ulangan akkauntning yangi xabarlarini kuzatadi.

40/60 rejada birinchi bosqich to'lovi tasdiqlanadi, qolgan 60% buyurtmada qarzdorlik sifatida qoladi. BTS punktga yetib kelgach ikkinchi to'lovni boshlash/tekshirish oqimi hali to'liq avtomatlashtirilmagan.


## Card-notice admin configuration (v5 patch)
Admin panel now contains a card-notice configuration form:
- Receiving card number and cardholder name (shown to customers).
- Last four digits of that card (used as an additional notification match).
- Telegram API ID, API Hash and phone for the monitoring Telegram account.
- Notification source username (default `CardXabarBot`).

The API Hash is encrypted at rest with `FERNET_KEY`. The listener reads the settings from the database and decrypts the hash at startup. After changing settings, restart `python -m app.payment_listener`. The first login may ask for Telegram login code and 2FA password in the server console. Persist `storage/` between deploys; it contains the authorized Telethon session and must never be committed or shared.

### Important payment limitations
This is still a card-notification matching integration, not an official bank payment API. Automatic confirmation is allowed only when a notification contains an explicit incoming-credit marker, amount, transaction reference, configured card suffix, and exactly one pending payment match inside five minutes. Other messages are ignored or require manual review. Notification formats differ by bank; validate using redacted real samples before enabling automatic confirmation.

The existing checkout flow still needs a production-grade reservation/ledger and expiry/refund worker before public launch. In particular, wallet and stock reservation lifecycle, 40/60 second-stage collection, refunds, and concurrency-safe stock control are not fully implemented by this patch. Do not use this build to collect real customer payments until those workflows are completed and tested.


## v6 — funksional kengaytmalar va xavfsizlik holati

Ushbu paketda qo‘shilgan:
- Savat elementlari miqdorini PUT orqali yangilash va alohida o‘chirish.
- Sevimlilar uchun API va katalog kartasida tezkor tugma.
- Xarid qilgan foydalanuvchiga mahsulot sharhi yozish API (1–5 yulduz).
- Promokod yaratish va tekshirish API; checkout'da foizli/fiks chegirma hisoblash.
- Admin uchun mahsulotni arxivlash (tarixiy buyurtma yozuvlari saqlanadi).
- Admin uchun balansni qo‘lda o‘zgartirish va ledger yozuvi.
- Admin to‘lovlar ro‘yxati, tasdiqlash/rad etish amallari.
- Admin rolini saqlash (owner/manager/finance/catalog).
- 40/60 buyurtmada BTS punktiga yetgach ikkinchi to‘lovni yaratish endpointi.
- Checkout'da karta to‘lovi kutayotgan paytda hamyonni darhol yechmaslik; hamyon summasi rezerv sifatida buyurtmada qayd etiladi. Listener birinchi to‘lovni tasdiqlaganda hamyon yechimi va ombor kamayishi bajariladi.

### Ishlab chiqarishdan oldingi ochiq ishlar
Bu v6 hali production-ready emas:
- Card Notice parseri haqiqiy bank xabarining anonimlashtirilgan namunasi bilan sinovdan o‘tkazilmagan. Shaxsiy ma’lumotlar, to‘liq karta raqami, SMS-kod, Telegram login kodi yoki 2FA parolini yubormang.
- Card Notice — bank acquiring API emas; xabar kechikishi, noto‘g‘ri format va Telegram sessiyasi uzilishi mumkin.
- BTS/UzPost filiallarining rasmiy to‘liq ma’lumotlari, xaritasi va tracking API ulanmagan. `/api/admin/orders/{id}/arrived` endpointini admin qo‘lda chaqiradi; haqiqiy BTS hodisasi avtomatik kelmaydi.
- 40/60 ikkinchi bosqichni boshlash uchun admin buyurtmani BTS punktiga yetgan deb belgilashi kerak. Haqiqiy BTS webhook integratsiyasi yo‘q.
- Ombor qoldig‘i to‘lov tasdiqlanguncha kamaytirilmaydi, ammo parallel checkoutlar uchun to‘liq atomik stock-reservation/expiry worker hali yo‘q. Bir vaqtning o‘zida bir dona qolgan mahsulotga bir nechta buyurtma tushishining oldini production DB lock/rezerv jadvali bilan kuchaytirish kerak.
- Admin rollari saqlanadi, lekin hozircha endpointlar bo‘yicha granular ruxsat matritsasi to‘liq qo‘llanmagan; barcha adminlar umumiy admin tekshiruvidan o‘tadi.
- Sharh yozish API mavjud, lekin sharhlarni ko‘rsatish va moderatsiya UI to‘liq ulanmagan.
- Sevimlilar API va kartadagi tugma bor; alohida sevimlilar sahifasi hali yo‘q.
- Promokod API va checkout hisob-kitobi bor; admin uchun promokodlarni tahrirlash/o‘chirish UI hali yo‘q.
- Cashback, referral, taqqoslash, mahsulot video galereyasi, Telegram kanalga avtomatik post, qo‘llab-quvvatlash chati, Excel import/export, audit log va rang/razmer kesimidagi alohida ombor bu paketda hali to‘liq ishlab chiqilmagan.
- Bank to‘lovi muvaffaqiyatli bo‘lmagan yoki buyurtma muddati tugagan holatda hamyon rezervini va ombor bandligini avtomatik bo‘shatadigan expiry/refund worker hali yo‘q.

Sinov: Python fayllari compileall sintaksis tekshiruvidan o‘tdi. Bu real Telegram, Card Notice, bank yoki BTS integratsiyasi sinovi degani emas.


## v7 qo‘shimcha API qatlamlari
- Taqqoslash ro‘yxati (4 tagacha mahsulot).
- Mahsulot media URLlari (rasm/video) va rang/razmer variantlari uchun ombor jadvallari.
- Referral ro‘yxatga olish (bonus avtomatik berilmaydi).
- Xaridor/admin support xabarlari uchun saqlash API.
- BTS jo‘natmasini admin qo‘lda kiritish va xaridor uchun holatni ko‘rish API.
- To‘liq to‘lovdan keyin pickup code yaratish endpointi.
- Admin audit loglarini ko‘rish endpointi va mahsulot CSV eksporti.

## v7 cheklovlari — production deb hisoblamang
Ushbu yangilanish qo‘shimcha backend endpointlari va jadvallarini beradi; ularning barchasi Mini App'da to‘liq sahifalar/tugmalar bilan ulanmagan. BTS filiallarining haqiqiy ro‘yxati/koordinatalari va xaritasi kiritilmagan; BTS statusi admin tomonidan qo‘lda yangilanadi, tashqi BTS tracking API emas. Telegram kanalga avtomatik post, Excel import, cashback/referral bonusini avtomatik berish, admin role-based permission enforcement, variant tanlovini checkout ombori bilan bog‘lash, xabarlarni Telegram admin shaxsiy chatiga yetkazish, to‘lov rezervini timeout/refund bilan atomik boshqarish hali tugallanmagan. CSV eksport bor, XLSX import/export to‘liq emas. Card Notice parseri haqiqiy bank xabari bilan tasdiqlanmagan.


## v8 — qo‘shimcha API ish oqimlari (2026-11)
v8 paketi quyidagi qo‘shimcha backend endpointlarini qo‘shadi:
- Taqqoslash: `GET/POST/DELETE /api/compare`.
- Mahsulot media va variantlari: `GET /api/products/{id}/media`, `GET /api/products/{id}/variants`, admin CRUD endpointlari.
- BTS jo‘natmasi: `GET /api/shipments/{order_id}`, admin `PUT /api/admin/orders/{id}/shipment`; admin holat o‘zgartirganda mijozga Telegram xabari yuborishga urinadi.
- Muammo/murojaat: `POST/GET /api/support/messages`, admin `GET /api/admin/support` va `POST /api/admin/support/{tg_id}`. Yangi murojaat barcha adminlarga Telegram orqali yuboriladi.
- Referral: `POST /api/referral/apply/{inviter_tg_id}` va `GET /api/referral`. Bonus faqat admin buyurtmani yetkazildi deb belgilaganda, sozlangan `referral_bonus` qiymati bo‘yicha beriladi.
- Cashback: admin `POST /api/admin/orders/{id}/delivered` chaqirganda `cashback_percent` sozlamasi bo‘yicha bonus bir marta yoziladi.
- CSV import/export: mahsulotlar va filiallar uchun admin endpointlari.
- Audit: admin `GET /api/admin/audit`.
- Filial koordinatalari, ish vaqti va telefoni uchun DB migratsiyasi va CSV import.
- Ayrim admin amallari role bo‘yicha cheklangan: owner, manager, finance, catalog.

### Cashback/referral sozlamalari
Admin sozlamalar jadvaliga `cashback_percent` va `referral_bonus` kalitlarini qo‘lda kiritish mumkin. `cashback_percent` 0–50 oralig‘idagi butun foiz, `referral_bonus` so‘mdagi butun summa.

### BTS filiallari va xarita ma’lumoti
BTS filiallarining manzil/ish vaqti rasmiy katalogi: https://bts.uz/uz/nashi-ofisi
Filiallar ro‘yxatini CSV orqali import qilish mumkin. CSV ustunlari:
`title,address,city,latitude,longitude,work_hours,phone`
Rasmiy katalogdagi matnli manzillar koordinata bermasligi mumkin; koordinatalarni ishonchli geokodlash yoki rasmiy manbadan olish kerak. Kod koordinatasi yo‘q filial uchun xarita nuqtasini to‘qib yaratmaydi. Xarita ma’lumotlari `GET /api/branches/map` orqali beriladi; bu endpoint ma’lumot beradi, xarita interfeysi emas.

### Ochiq qolgan integratsiya va production cheklovlari
- BTS rasmiy katalogidagi filiallar to‘liq avtomatik sinxron qilinmaydi; CSV ma’lumotini admin tayyorlab import qiladi. BTS rasmiy tracking API/webhooki mavjudligi va ruxsati tasdiqlanmagan, shuning uchun status admin tomonidan kiritiladi. Ichki pickup code BTS operatorining haqiqiy pochta kodi emas.
- Referral start deep-link avtomatik qo‘llash va to‘liq Mini App UI hali ulanmagan; foydalanuvchi referral endpointini chaqirishi kerak.
- Taqqoslash, sharhlar, media, support, filial xaritasi, cashback va referral uchun API mavjud; Mini App'dagi barcha sahifalar va boshqaruv panellari hali to‘liq UI bilan ulanmagan.
- CSV qo‘llab-quvvatlanadi; XLSX format emas.
- Variant ombori jadvali va API mavjud, lekin barcha eski buyurtma/to‘lov yo‘llarida variant qoldig‘ini atomik rezerv qilish yakunlanmagan.
- Checkout uchun parallel so‘rovlarni xavfsiz atomik rezerv qilish, timeout worker, wallet refund va to‘liq idempotency hali production darajasida emas. Haqiqiy pul bilan ishlatishdan oldin mustaqil audit va integratsion test shart.
- Card Notice parseri bankning anonimlashtirilgan real xabarlari bilan tekshirilmagan.
- Render'da bot va listener alohida worker sifatida ishga tushirilishi, persistent session storage va PostgreSQL sozlanishi kerak.


## v9 — non-postal interface integration pass

This pass adds customer screens for favorites, comparison, product reviews, and support messages,
plus admin controls for role assignment, promo-code creation, reward settings, audit log viewing,
and CSV product import/export. It also fixes variant-stock decrement paths when wallet-only
checkout or manual payment approval completes.

Postal/BTS integration is intentionally unchanged and remains outside this release scope.

### Important operational notes
- Reviews are accepted only from users with a fully paid order containing that product.
- Cashback/referral rewards are credited when an admin marks an order delivered; configure the
  percentages/amounts from the admin reward settings.
- Support messages are stored in the app inbox. A live operator notification to an admin's
  private Telegram chat still requires an explicitly configured admin username/ID and bot
  notification workflow.
- CSV is supported; native XLSX import/export is not included in this pass.
- Real payment confirmation still requires testing against actual, redacted bank notifications
  or a signed payment-provider webhook. Do not enable unattended payment auto-approval before
  that validation.
- This code has not been verified against a production database, Telegram deployment, or bank.


## v10 requested workflows (non-postal additions)

Added:
- Customer wallet/cashback ledger endpoint and profile history panel.
- Referral panel with a real Telegram deep-link when BOT_USERNAME is configured.
- Admin channel publishing endpoint (text or photo URL) using the configured bot token.
- Admin support inbox list and reply UI.
- Admin product media URL and color/size variant controls.
- Native XLSX product export/import endpoints; requires openpyxl.
- Admin XLSX controls in the Mini App.

Operational limitations:
- Telegram channel publishing requires the bot to be an administrator in the destination channel and a valid channel username/ID.
- Product media is added by URL in this release; binary file upload/storage is not implemented.
- Referral link generation is provided, but bonus eligibility, anti-abuse and payout reconciliation still need production testing.
- Cashback history is visible; applying bonus balance as a checkout tender is not yet implemented.
- BTS tariff calculation from the supplied 2026 tariff matrices is not included in this release; BTS/postal workflow remains separate.
- XLSX import appends new products; it does not update existing products by ID.
- Admin permissions should be reviewed before production; role checks are not yet exhaustive on every sensitive route.
- No production Telegram, payment, or database integration tests have been run.

## BTS filiallari (v11)
- Mijoz savatda filial nomi, shahar/tuman, manzil, mo'ljal va filial kodi bo'yicha qidiradi; tanlangan filial tafsilotlari, ish vaqti, telefon va xarita havolasi ko'rsatiladi.
- Admin panelda `BTS filiallari bazasi` bo'limi orqali CSV import/export mavjud. `bts_branches_template.csv` ustunlar namunasi.
- CSV ustunlari: `branch_code,title,city,address,landmark,work_hours,phone,latitude,longitude,map_url`.
- Filial kodi, aniq manzil, mo'ljal, ish vaqti, telefon va koordinatalar BTS rasmiy ofislar sahifasidan tekshirilgan ma'lumot bilan to'ldirilishi kerak. Bo'sh koordinata yoki noma'lum ma'lumot taxmin bilan kiritilmaydi.
- Rasmiy manba: https://bts.uz/uz/nashi-ofisi . Sahifa filiallar bo'yicha o'zgarishi mumkin; admin CSV'ni yangilab qayta import qilishi mumkin.
- Ushbu v11 paketi filiallarni boshqarish va import qilish imkoniyatini qo'shadi; BTS'ning barcha filiallari to'liq CSV ma'lumotlari ushbu paketga hali joylanmagan. Import qilingandan keyin mijozlar ro'yxatida paydo bo'ladi.


## v12 — 40/60 BTS-arrival action
- Admin order list now shows a dedicated `BTS filialiga yetdi` action for orders with a remaining balance.
- Admin action marks the order as arrived at the BTS branch, creates/re-activates the second-stage payment request idempotently, and sends the customer a Telegram message with the remaining amount and configured store card details.
- The Card Notice listener applies a five-day deadline to the second-stage payment request. A notice arriving after the deadline is sent to admin review and is not automatically confirmed.
- Pickup code remains withheld until the order is fully paid. The generated code is an internal OnlineXarid code, not a BTS-issued collection code.
- Python syntax checks passed for `app/main.py`, `app/db.py`, and `app/payment_listener.py`. This is not an end-to-end payment test.

## Still not completed / must not be represented as complete
- This package still does NOT include a verified full nationwide BTS branch dataset. The CSV is a template only. The official directory is the source of truth and branch data needs a full extraction/reconciliation pass before import.
- BTS tariff matrix calculator is not yet connected to checkout. The customer weight rule is one product = 1 kg, but shipping price is not yet added to the order total in this package.
- Five-day expiry is enforced when a Card Notice is processed; there is no background worker that automatically expires unpaid second-stage payments or sends reminders.
- Card Notice remains a message parser, not a bank acquiring API. Do not use automatic confirmation with real money until validated against redacted real notification examples and manually reconciled.
- Binary product image upload, checkout cashback spending, full admin permission matrix, PostgreSQL deployment, atomic inventory reservation, refunds, and production integration tests remain outstanding.


## v12.1 — stability and BTS setup updates

- 40/60 deadline now starts from `orders.second_payment_requested_at`, set when admin marks BTS branch arrival. The second-payment 5-minute Card Notice matching window is reset at that moment.
- Added `cashback_used` reservation/ledger support. Checkout accepts `use_cashback=true`; cashback is deducted only when the first card stage is confirmed (or immediately if wallet/cashback covers the whole first stage).
- Added product media upload endpoint `POST /api/admin/products/{product_id}/upload` (JPG/PNG/WEBP/MP4, max 12 MB). Uploaded files are served from `/uploads/`.
- Added BTS tariff CSV import and quote endpoint. Import CSV columns: `origin_city,destination_city,kg_min,kg_max,price,delivery_days`. The confirmed rule 1 product = 1 kg is used. Checkout includes the matching tariff in the order total and refuses checkout if no exact tariff row exists.
- Added async PostgreSQL driver support and a separate `worker` process in Procfile for Card Notice listener.

### BTS tariff import requirement
The ZIP does not contain the official tariff screenshots/table values, so no prices or delivery times are fabricated. Admin must import the verified BTS tariff CSV before checkout can be completed. Set `bts_origin_city` in the `settings` table to the shop's actual dispatch city; if absent, the app uses `Toshkent`. Tariff values must be transcribed from BTS's official tariff sheet.

### Production requirements still requiring owner data / external verification
- Full BTS branch catalogue and coordinates must be imported from BTS's current official directory; the ZIP contains a CSV template only.
- Card Notice listener requires valid Telegram API credentials, session login, and real redacted test messages. It is not bank acquiring and must be supervised.
- PostgreSQL hosting, persistent uploaded-file storage, HTTPS domain, bot webhook/polling and worker process must be configured by the operator.
- Product upload is a server-local disk store; use persistent volume or object storage on production hosting.
- Admin must supply real BTS sender account/contract data and BTS-issued pickup codes where applicable. Internal pickup code is only an internal store code.


## v12.2 — BTS qo‘lda tracking boshqaruvi

- Admin buyurtma ichida tashuvchi, BTS tracking kodi, taxminiy yetib borish sanasi va yetkazish narxini kiritadi.
- Holatlar: Qabul qilindi, Tayyorlanmoqda, BTS ga topshirildi, Yo‘lda, BTS filialiga yetib keldi, Mijozga topshirildi, Yetkazildi, Muammo yuz berdi, Bekor qilindi.
- Saqlashda buyurtma holati yangilanadi, audit logga yoziladi va mijozga Telegram xabari yuboriladi.
- Mijoz buyurtmalar sahifasida tracking ma’lumotlarini ko‘radi.
- Ichki olish kodi admin tomonidan kiritiladi va faqat buyurtma to‘liq to‘langan bo‘lsa mijozga ko‘rsatiladi.
- Ichki kod BTS operatori bergan rasmiy kod emas; u do‘kon kiritgan kod sifatida ko‘rsatiladi.
- Avtomatik BTS tracking API ishlatilmaydi; holatlar admin tomonidan qo‘lda yangilanadi.


## v13 — workflow completion additions (code-level)

### Added
- Review moderation: new reviews default to `pending`; public review listing returns approved reviews only; owner/manager can approve or reject.
- Refund workflow: customer can request a refund; owner/finance can approve/reject; wallet refunds are credited with a ledger entry; card refunds are deliberately marked `processing` because a real card refund must be performed through the payment provider and then marked complete.
- Scheduled channel posts: owner/manager can schedule, list, and cancel posts; maintenance worker sends due posts through the Telegram bot.
- Maintenance worker: starts with the FastAPI lifespan, expires first-installment payment windows after five minutes and marks orders cancelled / payments expired.
- SQLite migration adds review moderation columns to existing databases.
- BTS remains manual: no BTS API is assumed or required.

### Operational limits that cannot be truthfully marked complete from source code alone
- Official BTS branch data and tariff values must be imported from verified source tables. No branch or tariff records have been fabricated.
- Card Notice requires a real redacted notification sample and staging payment tests.
- PostgreSQL must be configured with a real DATABASE_URL and tested on the target server. asyncpg support is included, but deployment is not performed here.
- Card refunds are not automatically sent to a bank; the configured payment provider must support them.
- Scheduled posts require BOT_TOKEN and bot posting permission in the target channel.
- End-to-end concurrency, payment, and deployment tests must run against a staging database before production.

### New endpoints
- POST /api/refunds
- GET /api/admin/refunds
- POST /api/admin/refunds/{refund_id}/decision
- GET /api/admin/reviews
- POST /api/admin/reviews/{review_id}/decision
- POST /api/admin/channel-posts
- GET /api/admin/channel-posts
- DELETE /api/admin/channel-posts/{post_id}
- POST /api/admin/orders/{order_id}/cancel

These additions are source-code implementation, not a claim that external integrations or production deployment have been tested.


## v15 — admin, BTS media, pickup-code and channel publishing

### Admin panel
- Open the bot and use the **Admin panel** Web App button (the Telegram ID must be in `ADMIN_IDS` / `admins`).
- Admin panel URL is `WEBAPP_URL/admin`.
- Product form creates a product, optionally uploads a photo/video, then publishes it to the configured Telegram channel.
- Set `product_channel_id` in Admin → Kanal sozlamalari (`@channel` or `-100...`).
- Add the bot to that channel as an administrator with permission to post messages/photos.
- Channel post template variables: `{title}`, `{description}`, `{price}`, `{old_price}`, `{stock}`, `{category}`, `{product_id}`.

### BTS shipment management
- Admin → BTS jo‘natmalar: enter tracking code, shipment status, ETA, delivery amount, and upload a shipment photo (receipt/parcel evidence).
- When the admin marks an order as arrived at the BTS branch, the bot sends the tracking/photo information to the customer.
- 40/60 orders: arrival triggers the remaining 60% payment request; pickup code is blocked until that payment is confirmed.
- 100% orders: after the parcel is marked arrived, the internal store pickup code is generated and sent to the customer.
- The pickup code is an **internal OnlineXarid code**, not a code issued by BTS.

### Important launch requirements
This archive is a code update, not a deployed or independently certified production service. Before real customer use:
1. Set real `BOT_TOKEN`, `BOT_USERNAME`, `ADMIN_IDS`, `WEBAPP_URL` (HTTPS), `DATABASE_URL`, card details, and `FERNET_KEY`.
2. Configure the channel ID and grant the bot channel-admin posting rights.
3. Test the admin Mini App inside Telegram with an admin account and a customer account.
4. Test photo uploads, channel post permissions, payment matching, and both payment plans using redacted test data.
5. Card notification parsing is not a bank acquiring API. It must be validated against the actual bank notification format; a bank/payment provider webhook is preferable.
6. BTS shipment creation and tracking are still manually entered by the admin. No BTS API credentials or official API connection were supplied.
7. The 5-day second-payment deadline and payment listener require a persistent worker process. Run the `worker` process from `Procfile` alongside the web process, and persist `storage/` for the Telethon session.

The customer-facing wallet/cashback/referral bonus controls were removed from the Mini App UI and checkout defaults to card-only payment. Legacy database columns/tables remain for backward compatibility; they are not used as a checkout discount source in the new UI.

## Promokodlar
Admin panelida foizli promokod yaratish, tahrirlash, tugash sanasini belgilash, foydalanish limitini sozlash, faolsizlantirish/faollashtirish va butunlay o‘chirish bor. Minimal buyurtma summasi yo‘q. Limit 0 — cheksiz. Foydalanish soni buyurtma ochilganda emas, birinchi to‘lov muvaffaqiyatli tasdiqlanganda hisoblanadi.


## BTS tariflari — 2026-09-01 hujjatidan kiritilgan
- `bts_tariffs_2026-09-01.csv` foydalanuvchi yuborgan BTS tarif rasmlaridan tuzildi.
- 14 ta MVO shahri bo‘yicha 14×14 ofis-ofis yo‘nalishlari, 0–5 zonalar, 1–20 kg va barcha MVO shaharlaridan Toshkent MVOga alohida tarif jadvali kiritilgan.
- Har bir yo‘nalish/og‘irlik/tarif turi uchun standart yetkazish kunlari MVO muddatlari jadvalidan kiritilgan.
- Narxlar so‘mda va QQS bilan; amal qilish sanasi 2026-09-01.
- Admin panelidagi “BTS tariflari” bo‘limidan CSV import qilinadi. Import mavjud BTS tariflarini to‘liq almashtiradi.
- `bts_origin_city` va `bts_tariff_type` sozlamalari checkout va shipping quote hisobida ishlatiladi.
- Og‘irlik: savatdagi mahsulotlar soni (1 dona = 1 kg). 20 kg dan ortiq buyurtmaga jadvalda tarif yo‘q; qo‘lda admin ko‘rib chiqishi kerak.
- Rasmda keltirilgan istisnolar standart kunlarga avtomatik qo‘shilmaydi: yomon ob-havo/yo‘l +2 kun; MVOdan 100 km dan ortiq olis hudud +2 ish kuni; ofisdan 50 km dan ortiq olis kuryer +2 ish kuni; kelishuvli jo‘natma va qo‘shimcha qadoqlash shartga qarab +1 ish kuni. Bular buyurtma sharoitiga qarab admin tomonidan ETAga qo‘shilishi lozim.
- Dam olish va bayram kunlari standart muddatga kiritilmaydi. Hozirgi kod standart `delivery_days` qiymatini qaytaradi; kalendar bo‘yicha ish kunlarini avtomatik sanash alohida ish bo‘lib qolmoqda.
- Filial `city` qiymati 14 ta MVO shahar nomlaridan biriga mos bo‘lishi kerak. Boshqa tuman/qishloq nomlari uchun MVO shahrini admin to‘g‘ri belgilashi lozim.


## v18 — audit bo‘yicha qo‘shimcha tuzatishlar
- Admin panelga to‘lovlar, karta kuzatuv sozlamalari, refund so‘rovlari, sharh moderatsiyasi, support murojaatlari, mijoz qidiruvi/hamyon tuzatishi, dashboard va cashback/referral sozlamalari bo‘limlari qo‘shildi.
- Karta xabari parseri foydalanuvchi bergan `Perevod na kartu / ➕ ... UZS / ***2151 / GNK CASHBACK` formatini taniydi.
- `GNK CASHBACK` xabarlari xaridor to‘lovi sifatida hisoblanmaydi.
- Kasrli UZS summalari integer so‘mli to‘lov bilan avtomatik moslashtirilmaydi; qo‘lda tekshiruvga qoldiriladi.
- Xabarda bank tranzaksiya ID bo‘lmasa, xabar matnidan barqaror fingerprint yaratiladi. Bu bankning haqiqiy tranzaksiya identifikatori emas, faqat aynan bir xil bildirishnomani takroran qayta ishlashdan saqlaydi.
- Checkout vaqtida mahsulot/variant ombori band qilinadi; 5 daqiqada to‘lov tasdiqlanmasa, rezerv bekor qilinib qoldiq qaytariladi. To‘lov tasdiqlansa rezerv commit qilinadi.
- Oddiy bekor qilingan buyurtmada ombor rezervi qaytariladi.
- Parser uchun 3 ta avtomatik test qo‘shildi.

## v18 da ham alohida real sinov talab qiladiganlar
- Bank acquiring API mavjud emas; Telegram xabaridan aniqlash faqat yordamchi mexanizm. Fingerprint bank tranzaksiyasini huquqiy/texnik jihatdan tasdiqlamaydi.
- Telegram MTProto akkaunt sessiyasini birinchi marta avtorizatsiya qilish va doimiy worker ishlashini serverda sinash kerak.
- OCR/QR yuk xati avtomatik o‘qish hali qo‘shilmagan.
- Dam olish/bayram kalendari va BTS istisno muddatlarini avtomatik hisoblash hali yakunlanmagan.
- Banner/reklama moduli, o‘lcham jadvali muharriri, to‘liq ombor harakatlar jurnali, to‘liq role-permission matritsasi, backup rotatsiyasi/tiklash va production monitoring hali to‘liq emas.
- PostgreSQL hamda SQLite migratsiyalarini real bazada sinash kerak.
- `pytest` parser testlari muvaffaqiyatli; barcha API, Telegram bot, Mini App va to‘lov integratsiyalari uchun end-to-end testlar bajarilmagan.


## v19 — BTS 60% payment deep link
- When an admin confirms that a 40/60 order has arrived at the BTS branch, the Telegram notification now includes an inline **“To‘lovni yakunlash”** Mini App button.
- The button opens the configured Mini App URL with the exact `order_id` query parameter.
- Mini App reads that parameter, opens **Buyurtmalarim**, scrolls to the matching order and highlights it.
- The arrival notification includes the remaining amount, five-day deadline and support/admin contact guidance.
- Regression tests cover the order-specific link and Mini App deep-link handling.


## v20 — BTS Telegram xabarlarini avtomatik qabul qilish

- `app/bts_listener.py` alohida Telethon MTProto listener sifatida qo‘shildi.
- `@btsrobot` dan kelgan `ID: ...`, `Qabul qilish uchun KOD: ...`, manzil va havola matnlarini o‘qiydi.
- Pochta ID `shipments.tracking_code` bilan aniq teng bo‘lgandagina buyurtmani topadi; mos kelmagan xabarlar buyurtmaga biriktirilmaydi.
- Topilgan buyurtma BTS filialiga yetib kelgan deb belgilanadi. 40/60 buyurtmada 60% uchun to‘lov so‘rovi va aynan shu buyurtmani ochadigan Mini App tugmasi yuboriladi.
- BTS xabari `shipments.bts_message` maydonida saqlanadi. Qolgan 60% to‘lov Card Notice orqali tasdiqlangach, saqlangan BTS xabari va olish kodi xaridorga yuboriladi.
- 100% to‘langan buyurtmaga BTS xabari darhol yuboriladi.
- Eski SQLite bazalar uchun `shipments.bts_message` ustuniga migratsiya qo‘shildi.

### BTS listener sozlash
1. `.env` ichida `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `BTS_BOT_SOURCE=@btsrobot`, `BTS_MONITOR_SESSION=storage/bts_monitor` ni kiriting.
2. Shu Telegram foydalanuvchi akkaunti `@btsrobot` bilan chatni ochib, botdan keladigan BTS xabarlarini olishi kerak.
3. Serverda alohida doimiy worker sifatida `python -m app.bts_listener` ni ishga tushiring va birinchi marta kelgan Telegram login kodini terminalda kiriting.
4. `shipments.tracking_code` maydonida BTS xabaridagi `ID` bilan bir xil pochta raqami oldindan saqlangan bo‘lishi shart.

**Cheklovlar:** oddiy BotFather tokeni boshqa botning chat xabarlarini o‘qiy olmaydi; bu MTProto foydalanuvchi sessiyasi talab qiladi. Listenerning real ishlashi faqat akkaunt bilan login qilib, BTS’dan haqiqiy test xabari kelgach tasdiqlanadi. Ushbu worker hozircha `@btsrobot` matnli xabarlarini tinglaydi; BTS ilovasi/SMS yoki rasmli xabar OCR/QR oqimini avtomatik o‘qimaydi. Bir xil ID takror kelsa qayta xabar yubormaslikka harakat qiladi.


## BTS avtomatik xabar tinglovchisi (v21 tuzatishlari)

- Deploy platformasida `web`, `worker` bilan birga `bts` processini ham ishga tushiring (`Procfile`ga qo‘shilgan).
- `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `BTS_BOT_SOURCE=@btsrobot` va `BTS_MONITOR_SESSION` qiymatlarini kiriting.
- Bu BotFather bot tokeni emas: `BTS_MONITOR_SESSION` uchun `@btsrobot` bilan yozishmalarni ko‘ra oladigan Telegram foydalanuvchi akkaunti MTProto sessiyasi kerak. Sessiyani birinchi marta interaktiv tarzda autentifikatsiya qilish talab qilinishi mumkin.
- BTS xabari `ID:` qiymatini `shipments.tracking_code` bilan aynan solishtiradi. Tracking raqami admin panelda oldindan to‘g‘ri saqlangan bo‘lishi shart.
- BTS xabaridagi qabul qilish kodi `shipments.pickup_code`ga saqlanadi. 40/60 rejimida qolgan to‘lov tugmasi faqat to‘lov kutilayotgan holatda yuboriladi; to‘liq to‘langan buyurtmaga BTS xabari va BTS kodi yuboriladi.
- Agar BTS kvitansiya rasmi `shipments.photo_url`da mavjud bo‘lsa, xabar bilan birga yuborishga urinadi.
- BTS API integratsiyasi emas: xabarlarni Telegram foydalanuvchi sessiyasi orqali o‘qiydi. Telegram sessiyasi uzilsa yoki akkaunt `@btsrobot` xabarini ko‘rmasa, avtomatik ishlamaydi.


## v22 additions
- Payment amounts are allocated uniquely across active pending payments. If the base amount is already in use, the system steps down by 1 UZS until an unused amount is found.
- Checkout shows the exact amount prominently, provides a copy action, and warns customers to pay exactly that amount. Other amounts may require manual admin review.
- Wallet, cashback and referral are removed from the customer checkout flow and admin UI. Legacy database columns/tables are retained for backward-compatible migration; they are not used for new checkouts.
- Daily database backup worker: `python -m app.backup`. It creates SQLite online backups with an integrity check, or PostgreSQL custom dumps via `pg_dump`, and removes files older than 30 days. Configure `BACKUP_DIR` and `BACKUP_RETENTION_DAYS` if needed. Start the `backup` process in the hosting dashboard; adding it to Procfile alone does not scale it automatically.
- Backups must be stored on persistent storage. For PostgreSQL, `pg_dump` must be installed in the worker image.

Payment note: this project continues to use the Telegram bank-notification listener and admin review flow. It does not claim to use Click/Payme/Uzum acquiring webhooks.


## v24 — qaytarish izohi va mijozga xabar
- Adminning har bir qaytarish so‘rovi kartasida izoh yozish maydoni qo‘shildi.
- Tasdiqlash, rad etish yoki yakunlash qarorida izoh `RefundRequest.admin_note` maydoniga saqlanadi.
- Bot mijozga qaror holati va admin izohini Telegram orqali yuborishga urinadi. Telegram xabari yetkazilmasa, server jurnalida xato qayd etiladi; refund qarori bazada saqlanadi.
- Karta orqali qaytarish bank provayderida qo‘lda bajariladi; bot pul o‘tkazmaydi.

Ushbu v24 patch faqat qaytarish izohi va xabarnoma qismini yakunlaydi. Telegram login kodi/2FA UI, yagona BTS/to‘lov akkaunt sessiyasi, to‘liq backup tiklash UI va granular admin ruxsatlari hali alohida ishlab chiqish hamda real integratsiya sinovini talab qiladi.


## v25 — admin bildirishnomalari (2026-11-27)

- Yangi buyurtma yaratilgach, barcha ro‘yxatdan o‘tgan adminlarga Telegram bot orqali batafsil xabar yuboriladi: mijoz, telefon, buyurtma raqami, mahsulotlar, rang, razmer, soni, narx, asosiy mahsulot rasmi URL manzili, to‘lov rejasi va summalari, BTS pochta filiali va manzili.
- Mijoz qo‘llab-quvvatlashga xabar yuborganda adminlarga Telegram bildirishnomasi yuboriladi.
- Admin panel orqali yozilgan qo‘llab-quvvatlash javobi mijozga Telegram bot orqali yuboriladi.
- Bildirishnoma yuborishdagi xato mijozning buyurtma yoki xabar saqlanishini bekor qilmaydi.

Eslatma: Telegram akkauntni API ID/HASH, login kodi va 2FA bilan to‘liq ulash UI, rangga xos alohida rasm biriktirish, BTS/40-60 jarayonining real muhitdagi to‘liq sinovi, backup restore UI va kengaytirilgan admin ruxsatlari hali alohida yakunlanishi kerak. Bildirishnomalar kelishi uchun BOT_TOKEN sozlangan va admin foydalanuvchilari botni kamida bir marta /start qilgan bo‘lishi kerak.
