import json
import requests
import re
import os
import base64
import uuid
from datetime import datetime, date
from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.utils import secure_filename
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)
CORS(app)

# ─── إعدادات عامة ──────────────────────────────────────────────────
UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 26 * 1024 * 1024

config = {}
if os.path.exists("config.json"):
    with open("config.json", "r", encoding="utf-8") as f:
        config = json.load(f)

GROQ_API_KEY = config.get("GROQ_API_KEY") or "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"
MANAGER_PASSWORD = "1282"  # كلمة مرور المدير لتطبيق المزرعة
EXPO_PUSH_URL = 'https://exp.host/--/api/v2/push/send'

# ─── بوت تيليجرام (تقارير وإشعارات المعاملات) ──────────────────────
TELEGRAM_BOT_TOKEN = config.get("TELEGRAM_BOT_TOKEN") or "8934774619:AAEELQfe6o5q6Lwe9FPApcM4zK1NQPsMJwQ"
TELEGRAM_API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# ─── ملف بيانات واحد موحّد لكل شيء ──────────────────────────────────
# (جهات الاتصال + العمال + المعاملات البنكية + بيانات مزرعة الدواجن)
# مسار مطلق بناءً على مكان هذا الملف نفسه - يضمن إنه دائمًا نفس الملف
# بغض النظر عن المجلد اللي تشغّل منه "python merged_app.py"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "data.json")

DEFAULT_CONTACTS = [
    {"id": "1", "name": "أحمد خالد", "phone": "055 1234 567"},
    {"id": "2", "name": "حمد حسن", "phone": "055 1234 567", "avatar": "https://i.pravatar.cc/150?img=33"},
    {"id": "3", "name": "سارة محمود", "phone": "055 1234 567", "avatar": "https://i.pravatar.cc/150?img=47"},
    {"id": "4", "name": "عمر أحمد", "phone": "055 1234 567"},
    {"id": "5", "name": "مريم يوسف", "phone": "055 1234 567", "avatar": "https://i.pravatar.cc/150?img=44"}
]

DEFAULT_WORKERS = [
    {
        "id": "1",
        "name": "أحمد علي محمود",
        "startDate": "2024-01-01",
        "monthlySalary": 12000,
        "avatarUrl": "https://i.pravatar.cc/150?img=11"
    },
    {
        "id": "2",
        "name": "محمد عبد الله خليل",
        "startDate": "2024-02-15",
        "monthlySalary": 15000,
        "avatarUrl": "https://i.pravatar.cc/150?img=12"
    }
]

def default_alert_schedules():
    return [
        {"id": 1, "time": "09:00", "title": "تنبيه التسجيل الصباحي", "target": "worker"},
        {"id": 2, "time": "11:00", "title": "تذكير التسجيل الثاني", "target": "worker"},
        {"id": 3, "time": "13:00", "title": "تنبيه هام قبل رفع التقرير", "target": "worker"},
        {"id": 4, "time": "14:00", "title": "إشعار عدم الإدخال للمسؤول", "target": "manager"}
    ]

def default_poultry():
    return {
        "app_settings": {
            "is_configured": False,
            "role": None
        },
        "tokens": {
            "workers": [],
            "managers": []
        },
        "next_house_id": 1,
        "houses": {}
    }

def default_feed_factory():
    return {
        "ingredients": {
            "bread": {"name": "عيش", "stockKg": 15000, "formulaKg": 650, "defaultBagWeight": 50, "icon": "wheat", "color": "#F59E0B"},
            "umbaz": {"name": "امباز", "stockKg": 8000, "formulaKg": 280, "defaultBagWeight": 50, "icon": "peanut", "color": "#B45309"},
            "center": {"name": "مركز", "stockKg": 3500, "formulaKg": 50, "defaultBagWeight": 50, "icon": "percent", "color": "#3B82F6"},
            "lime": {"name": "حجر جيري", "stockKg": 2000, "formulaKg": 17, "defaultBagWeight": 25, "icon": " पर्वत", "color": "#94A3B8"},
            "antiToxin": {"name": "مضاد سموم", "stockKg": 450, "formulaKg": 1, "defaultBagWeight": 25, "icon": "shield-bug", "color": "#10B981"},
            "others": {"name": "أخرى", "stockKg": 800, "formulaKg": 2, "defaultBagWeight": 10, "icon": "dots-horizontal", "color": "#6B7280"}
        },
        "history": {
            "bread": [], "umbaz": [], "center": [], "lime": [], "antiToxin": [], "others": []
        }
    }

def default_debts():
    return {
        "people": [],
        "transactions": [],
        "synced_bank_tx_ids": []
    }

def default_telegram():
    return {
        "chat_ids": [],
        "update_offset": 0
    }

def default_data():
    return {
        "contacts": [dict(c) for c in DEFAULT_CONTACTS],
        "workers": [dict(w) for w in DEFAULT_WORKERS],
        "transactions": [],
        "poultry": default_poultry(),
        "feed_factory": default_feed_factory(),
        "debts": default_debts(),
        "telegram": default_telegram()
    }

def load_data():
    """تحميل ملف البيانات الموحّد. ينشئه بالقيم الافتراضية فقط إذا لم يكن
    موجودًا إطلاقًا. لو الملف موجود لكن تالف/فيه خطأ قراءة، لا يتم أبدًا
    استبدال بياناتك الحقيقية بالبيانات الافتراضية بصمت - بدلاً من ذلك يتم
    أخذ نسخة احتياطية من الملف التالف وإرجاع بيانات فارغة مع رسالة واضحة
    في الطرفية عشان تلاحظ المشكلة فورًا."""
    if not os.path.exists(DATA_FILE):
        data = default_data()
        save_data(data)
        return data
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        backup_path = DATA_FILE + f".corrupted_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        try:
            os.replace(DATA_FILE, backup_path)
        except Exception:
            pass
        print("=" * 50)
        print(f"⚠️  تحذير: ملف {DATA_FILE} كان تالفًا وتعذّرت قراءته: {e}")
        print(f"⚠️  تم حفظ نسخة منه في: {backup_path}")
        print("⚠️  تم البدء بقاعدة بيانات فارغة (وليست البيانات التجريبية الافتراضية)")
        print("=" * 50)
        data = {"contacts": [], "workers": [], "transactions": [], "poultry": default_poultry(), "feed_factory": default_feed_factory(), "debts": default_debts(), "telegram": default_telegram()}
        save_data(data)
        return data

    # التأكد من وجود كل الأقسام حتى لو الملف قديم/ناقص (بدون مسح أي قسم موجود)
    changed = False
    if "contacts" not in data:
        data["contacts"] = []
        changed = True
    if "workers" not in data:
        data["workers"] = []
        changed = True
    if "transactions" not in data:
        data["transactions"] = []
        changed = True
    if "poultry" not in data:
        data["poultry"] = default_poultry()
        changed = True
    else:
        p = data["poultry"]
        p.setdefault("app_settings", {"is_configured": False, "role": None})
        p.setdefault("tokens", {"workers": [], "managers": []})
        p.setdefault("next_house_id", 1)
        p.setdefault("houses", {})
    if "feed_factory" not in data:
        data["feed_factory"] = default_feed_factory()
        changed = True
    else:
        ff = data["feed_factory"]
        ff.setdefault("ingredients", default_feed_factory()["ingredients"])
        ff.setdefault("history", {k: [] for k in ff.get("ingredients", {}).keys()})
    if "debts" not in data:
        data["debts"] = default_debts()
        changed = True
    else:
        d = data["debts"]
        d.setdefault("people", [])
        d.setdefault("transactions", [])
        d.setdefault("synced_bank_tx_ids", [])
    if "telegram" not in data:
        data["telegram"] = default_telegram()
        changed = True
    else:
        t = data["telegram"]
        t.setdefault("chat_ids", [])
        t.setdefault("update_offset", 0)
    if changed:
        save_data(data)
    return data

def save_data(data):
    """كتابة ذرية (atomic write): يكتب لملف مؤقت ثم يستبدل الملف الأصلي
    دفعة واحدة، عشان أي انقطاع أثناء الكتابة (تصادم طلبات متزامنة) ما
    يخرّب الملف ويخلي القراءة القادمة تفشل."""
    tmp_path = DATA_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    os.replace(tmp_path, DATA_FILE)

def renumber(items):
    """إعادة ترقيم العناصر بأرقام بسيطة متسلسلة 1، 2، 3 ..."""
    for idx, item in enumerate(items, start=1):
        item["id"] = str(idx)
    return items


# ══════════════════════════════════════════════════════════════════
# القسم الأول: جهات الاتصال + العمال + إيصالات بنك الخرطوم (OCR)
# ══════════════════════════════════════════════════════════════════

GROQ_SYSTEM_PROMPT = """أنت نظام متخصص في استخراج بيانات إيصالات التحويل البنكي لبنك الخرطوم.

مهمتك: استخراج البيانات من صورة الإيصال وإرجاعها بتنسيق JSON فقط بدون أي نص إضافي أو backticks.

الحقول المطلوبة:
- رقم_العملية: رقم المعاملة أو الإيصال كما يظهر بالصورة بالكامل، أرقام فقط بدون فراغات (عادةً 11 رقم)
- التاريخ_والزمن: تاريخ ووقت العملية بصيغة DD-Mon-YYYY HH:MM:SS
- من_حساب: رقم الحساب المُرسِل كما يظهر بالصورة بالكامل، أرقام فقط بدون فراغات أو رموز (عادةً 16 رقم)
- الى_حساب: رقم الحساب المُرسَل إليه كما يظهر بالصورة بالكامل، أرقام فقط بدون فراغات أو رموز (عادةً 16 رقم)
- اسم_المرسل_إليه: اسم صاحب الحساب المُرسَل إليه
- القسم: الجزء الأول من التعليق او الشئ المكتوب قبل علامة الترقيم او العلامة/ (مثل: تحويل، راتب، دفع)اذا لم تجدة او كان N/A في التعليق اكتب غير مصنف
- النوع: الجزء الثاني من التعليق إن وُجد وان لم يوجد(N/A)، وإلا اكتب غير مصنف
- المبلغ: المبلغ بالأرقام فقط بصيغة 1,500.00

أمثلة للمخرجات:
{
  "رقم_العملية": "12345678901",
  "التاريخ_والزمن": "15-Jan-2025 10:30:00",
  "من_حساب": "1003080673540001",
  "الى_حساب": "1003077763320001",
  "اسم_المرسل_إليه": "محمد أحمد علي",
  "التعليق": "خاص/شخصي",
  "القسم": "خاص",
  "النوع": "شخصي",
  "المبلغ": "1,500.00"
}

قواعد صارمة:
1. أرجع JSON فقط — لا مقدمة، لا شرح، لا backticks.
2. إذا لم تجد قيمة لحقل ما، ضع "غير مصنف".
3. المبلغ يجب أن يكون أرقاماً بفاصلة إن وُجدت ونقطة عشرية.
4. لا تخترع بيانات غير موجودة في الصورة.
5. إذا لم تتعرف على الصورة كإيصال بنكي، أرجع: {"error": "ليست صورة إيصال بنك الخرطوم"}"""

def clean_acc(s):
    return str(s or "").replace(" ", "").strip()

def reverse_groups(s):
    cleaned = clean_acc(s)
    if not cleaned:
        return ""
    groups = re.findall(r'.{1,4}', cleaned)
    if not groups:
        return cleaned
    groups.reverse()
    return "".join(groups)

def get_direction(result, my_account):
    if not my_account:
        return "in"
    my = clean_acc(my_account)
    from_acc = clean_acc(result.get("من_حساب", ""))
    to_acc = clean_acc(result.get("الى_حساب", ""))
    if from_acc == my or reverse_groups(from_acc) == my:
        return "out"
    if to_acc == my or reverse_groups(to_acc) == my:
        return "in"
    return "in"

def parse_amount(s):
    cleaned = str(s or "").replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        match = re.search(r'[\d.]+', cleaned)
        if match:
            try:
                return float(match.group())
            except ValueError:
                return 0.0
        return 0.0

def extract_account_code(raw_account):
    digits = re.sub(r'\D', '', str(raw_account or ''))
    if len(digits) > 9:
        return digits[5:-4]
    return digits

def extract_last4(raw_number):
    digits = re.sub(r'\D', '', str(raw_number or ''))
    if len(digits) > 4:
        return digits[-4:]
    return digits

def encode_image_base64(image_path):
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

def get_image_media_type(filename):
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'jpeg'
    mapping = {
        'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png',
        'gif': 'image/gif', 'bmp': 'image/bmp', 'tiff': 'image/tiff', 'webp': 'image/webp',
    }
    return mapping.get(ext, 'image/jpeg')

def ocr_image_groq(image_path):
    image_b64 = encode_image_base64(image_path)
    media_type = get_image_media_type(os.path.basename(image_path))

    payload = {
        "model": "qwen/qwen3.6-27b",
        "max_tokens": 1024,
        "reasoning_effort": "none",
        "messages": [
            {"role": "system", "content": GROQ_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{image_b64}"}},
                    {"type": "text", "text": "استخرج بيانات هذا الإيصال البنكي وأرجعها بتنسيق JSON فقط."}
                ]
            }
        ]
    }

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=30
    )

    if response.status_code != 200:
        raise Exception(f"Groq API error {response.status_code}: {response.text}")

    resp_data = response.json()
    raw_text = resp_data["choices"][0]["message"]["content"].strip()
    clean_text = re.sub(r'```(?:json)?', '', raw_text).strip().strip('`').strip()

    try:
        parsed = json.loads(clean_text)
    except json.JSONDecodeError:
        json_match = re.search(r'\{.*\}', clean_text, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group())
        else:
            raise Exception(f"لم يُرجع Groq JSON صالح: {clean_text}")

    return raw_text, parsed

def parse_groq_result(parsed_dict):
    if "error" in parsed_dict:
        return {
            "error": parsed_dict["error"],
            "suggestions": ["تأكد أن الصورة لإيصال تحويل بنك الخرطوم"]
        }

    parsed_dict["وقت_المعالجة"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if "من_حساب" in parsed_dict:
        parsed_dict["من_حساب"] = extract_account_code(parsed_dict["من_حساب"])
    if "الى_حساب" in parsed_dict:
        parsed_dict["الى_حساب"] = extract_account_code(parsed_dict["الى_حساب"])
    if "رقم_العملية" in parsed_dict:
        parsed_dict["رقم_العملية"] = extract_last4(parsed_dict["رقم_العملية"])

    required_fields = [
        "رقم_العملية", "التاريخ_والزمن", "من_حساب", "الى_حساب",
        "اسم_المرسل_إليه", "رقم_الموبايل", "القسم", "النوع", "المبلغ"
    ]
    for field in required_fields:
        if field not in parsed_dict:
            parsed_dict[field] = "N/A"

    return parsed_dict

def save_transaction_record(new_data):
    data = load_data()
    transactions = data["transactions"]
    new_data["وقت_الحفظ"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    transactions.append(new_data)
    renumber(transactions)
    data["transactions"] = transactions
    save_data(data)

    send_telegram_message(
        "🏦 <b>معاملة بنكية جديدة</b>\n"
        f"المرسل إليه: {new_data.get('اسم_المرسل_إليه', '-')}\n"
        f"المبلغ: {new_data.get('المبلغ', '-')}\n"
        f"القسم: {new_data.get('القسم', '-')} | النوع: {new_data.get('النوع', '-')}\n"
        f"التاريخ: {new_data.get('التاريخ_والزمن', '-')}"
    )

    return len(transactions), transactions[-1]["id"]


# ─── دوال بوت تيليجرام (@Alwatania_Reports_bot) ────────────────────

def send_telegram_message(text):
    """يرسل رسالة نصية لكل المحادثات المسجّلة (اللي بعتت /start للبوت)."""
    try:
        data = load_data()
        chat_ids = data.get("telegram", {}).get("chat_ids", [])
    except Exception as e:
        print("❌ خطأ أثناء قراءة بيانات تيليجرام:", e)
        return
    if not chat_ids:
        print("⚠️ لم يتم إرسال رسالة تيليجرام: لا توجد أي محادثة مسجّلة بعد "
              "(لازم ترسل /start للبوت @Alwatania_Reports_bot أولاً).")
        return
    for chat_id in chat_ids:
        try:
            resp = requests.post(
                f"{TELEGRAM_API_BASE}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
                timeout=10
            )
            if resp.status_code != 200:
                print(f"❌ فشل إرسال رسالة تيليجرام للمحادثة {chat_id}: "
                      f"{resp.status_code} - {resp.text}")
        except Exception as e:
            print(f"❌ استثناء أثناء إرسال رسالة تيليجرام للمحادثة {chat_id}:", e)

def poll_telegram_updates():
    """يستطلع تحديثات البوت بشكل دوري لتسجيل أي محادثة جديدة بعتت /start،
    بدل الحاجة لإدخال chat_id يدويًا. يخزن آخر update_id عشان ما يعالج
    نفس الرسالة مرتين."""
    try:
        data = load_data()
        tg = data.setdefault("telegram", default_telegram())
        offset = tg.get("update_offset", 0)

        resp = requests.get(
            f"{TELEGRAM_API_BASE}/getUpdates",
            params={"offset": offset + 1, "timeout": 5},
            timeout=15
        )
        if resp.status_code != 200:
            print(f"❌ فشل استطلاع تحديثات تيليجرام: {resp.status_code} - {resp.text}")
            return

        updates = resp.json().get("result", [])
        if not updates:
            return

        changed = False
        for update in updates:
            tg["update_offset"] = update["update_id"]
            changed = True
            msg = update.get("message") or update.get("channel_post")
            if not msg:
                continue
            chat_id = msg.get("chat", {}).get("id")
            if chat_id is None:
                continue
            if chat_id not in tg["chat_ids"]:
                tg["chat_ids"].append(chat_id)
                try:
                    requests.post(
                        f"{TELEGRAM_API_BASE}/sendMessage",
                        json={
                            "chat_id": chat_id,
                            "text": "✅ تم تفعيل استلام إشعارات وتقارير النظام على هذه المحادثة."
                        },
                        timeout=10
                    )
                except Exception:
                    pass

        if changed:
            data["telegram"] = tg
            save_data(data)
    except Exception as e:
        print("❌ خطأ أثناء استطلاع تحديثات تيليجرام:", e)

def send_daily_telegram_report():
    """يبني ويرسل تقريرًا يوميًا موجزًا بكل المعاملات (بنكية / ديون / مصنع علف)."""
    try:
        data = load_data()
        today_str = datetime.now().strftime("%Y-%m-%d")

        bank_txs = [t for t in data.get("transactions", [])
                    if str(t.get("وقت_الحفظ", "")).startswith(today_str) and "error" not in t]
        total_bank_amount = sum(parse_amount(t.get("المبلغ", "0")) for t in bank_txs)

        debts = data.get("debts", {})
        today_debt_txs = [t for t in debts.get("transactions", [])
                          if str(t.get("date_created", "")) == today_str]

        factory = data.get("feed_factory", {})
        today_factory_moves = []
        today_slash = datetime.now().strftime("%Y/%m/%d")
        for ing_key, logs in factory.get("history", {}).items():
            for log in logs:
                if str(log.get("date", "")).startswith(today_slash):
                    today_factory_moves.append((ing_key, log))

        lines = [f"📊 <b>التقرير اليومي</b> - {today_str}", ""]
        lines.append(f"🏦 معاملات بنكية: {len(bank_txs)} | إجمالي المبالغ: {total_bank_amount:,.2f}")
        lines.append(f"💳 حركات ديون: {len(today_debt_txs)}")
        lines.append(f"🌾 حركات مصنع العلف: {len(today_factory_moves)}")

        if not bank_txs and not today_debt_txs and not today_factory_moves:
            lines.append("")
            lines.append("لا توجد أي معاملات مسجّلة اليوم.")

        send_telegram_message("\n".join(lines))
    except Exception as e:
        print("خطأ أثناء إنشاء/إرسال التقرير اليومي:", e)


@app.route('/', methods=['GET'])
def home():
    return jsonify({
        "message": "خدمة موحّدة: OCR / جهات اتصال / عمال / مزرعة دواجن",
        "endpoints": {
            "upload": "/dashboard/api/ocr/upload",
            "save": "/dashboard/api/transactions/save",
            "transactions": "/dashboard/api/transactions",
            "workers": "/dashboard/api/workers",
            "contacts": "/dashboard/api/contacts",
            "poultry_houses": "/api/houses",
            "feed_factory_dashboard": "/api/dashboard",
            "feed_factory_transaction": "/api/transaction",
            "persons": "/persons",
            "person_transactions": "/persons/<id>/transactions",
            "add_debt_transaction": "/transactions",
            "telegram_status": "/api/telegram/status",
            "telegram_send_test": "/api/telegram/test",
            "telegram_send_daily_report_now": "/api/telegram/report/send"
        }
    })

# --- بوت تيليجرام: حالة ومحادثات مسجّلة + اختبار الإرسال ---

@app.route('/api/telegram/status', methods=['GET'])
def telegram_status():
    data = load_data()
    tg = data.get("telegram", default_telegram())
    return jsonify({
        "success": True,
        "registered_chats": len(tg.get("chat_ids", [])),
        "chat_ids": tg.get("chat_ids", [])
    })

@app.route('/api/telegram/test', methods=['POST'])
def telegram_test():
    req_data = request.get_json(force=True, silent=True) or {}
    text = req_data.get("text", "🔔 رسالة اختبار من نظام الوطنية.")
    data = load_data()
    chat_count = len(data.get("telegram", {}).get("chat_ids", []))
    if chat_count == 0:
        return jsonify({
            "success": False,
            "error": "لا توجد أي محادثة مسجّلة بعد. أرسل /start للبوت @Alwatania_Reports_bot أولاً."
        }), 400
    send_telegram_message(text)
    return jsonify({"success": True, "sent_to": chat_count})

@app.route('/api/telegram/report/send', methods=['POST'])
def telegram_send_report_now():
    send_daily_telegram_report()
    return jsonify({"success": True, "message": "تم إرسال التقرير اليومي."})

# --- جهات الاتصال ---

@app.route('/dashboard/api/contacts', methods=['GET'])
def get_contacts():
    data = load_data()
    return jsonify({"success": True, "contacts": data["contacts"]}), 200

@app.route('/dashboard/api/contacts', methods=['POST'])
def add_contact():
    try:
        req_data = request.get_json(force=True, silent=True) or {}
        if not req_data.get("name") or not req_data.get("phone"):
            return jsonify({"success": False, "error": "الاسم ورقم الهاتف مطلوبان"}), 400

        data = load_data()
        contacts = data["contacts"]
        new_contact = {
            "id": "0",
            "name": str(req_data.get("name")).strip(),
            "phone": str(req_data.get("phone")).strip(),
            "avatar": req_data.get("avatar", "")
        }
        contacts.insert(0, new_contact)
        renumber(contacts)
        data["contacts"] = contacts
        save_data(data)
        send_telegram_message(
            "👤 <b>جهة اتصال جديدة</b>\n"
            f"الاسم: {new_contact['name']}\nالهاتف: {new_contact['phone']}"
        )
        return jsonify({"success": True, "contact": contacts[0]}), 201
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/dashboard/api/contacts/<contact_id>', methods=['PUT'])
def update_contact(contact_id):
    try:
        req_data = request.get_json(force=True, silent=True) or {}
        data = load_data()
        contacts = data["contacts"]
        updated_contact = None

        for idx, c in enumerate(contacts):
            if str(c.get("id")) == str(contact_id):
                if "name" in req_data: c["name"] = str(req_data["name"]).strip()
                if "phone" in req_data: c["phone"] = str(req_data["phone"]).strip()
                if "avatar" in req_data: c["avatar"] = str(req_data["avatar"]).strip()
                contacts[idx] = c
                updated_contact = c
                break

        if not updated_contact:
            return jsonify({"success": False, "error": "جهة الاتصال غير موجودة"}), 404

        data["contacts"] = contacts
        save_data(data)
        send_telegram_message(
            "✏️ <b>تعديل جهة اتصال</b>\n"
            f"الاسم: {updated_contact.get('name','-')}\nالهاتف: {updated_contact.get('phone','-')}"
        )
        return jsonify({"success": True, "contact": updated_contact}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/dashboard/api/contacts/<contact_id>', methods=['DELETE'])
def delete_contact(contact_id):
    try:
        data = load_data()
        contacts = data["contacts"]
        target_id = str(contact_id).strip()

        deleted_contact = next((c for c in contacts if str(c.get("id")).strip() == target_id), None)
        new_contacts = [c for c in contacts if str(c.get("id")).strip() != target_id]

        if len(new_contacts) == len(contacts):
            return jsonify({"success": False, "error": f"جهة الاتصال برقم ({target_id}) غير موجودة"}), 404

        renumber(new_contacts)
        data["contacts"] = new_contacts
        save_data(data)
        send_telegram_message(
            f"🗑️ <b>حذف جهة اتصال</b>\nالاسم: {deleted_contact.get('name','-') if deleted_contact else '-'}"
        )
        return jsonify({"success": True, "message": "تم الحذف بنجاح"}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# --- العمال ---

@app.route('/dashboard/api/workers', methods=['GET'])
def get_workers():
    data = load_data()
    return jsonify({"success": True, "workers": data["workers"]})

@app.route('/dashboard/api/workers', methods=['POST'])
def add_worker():
    try:
        req_data = request.get_json(force=True, silent=True) or {}
        if not req_data.get("name") or not req_data.get("monthlySalary"):
            return jsonify({"success": False, "error": "اسم العامل والمرتب مطلوبان"}), 400

        data = load_data()
        workers = data["workers"]
        new_worker = {
            "id": "0",
            "name": str(req_data.get("name")).strip(),
            "startDate": req_data.get("startDate", datetime.now().strftime("%Y-%m-%d")),
            "monthlySalary": float(req_data.get("monthlySalary", 0)),
            "avatarUrl": req_data.get("avatarUrl", "")
        }
        workers.append(new_worker)
        renumber(workers)
        data["workers"] = workers
        save_data(data)
        send_telegram_message(
            "👷 <b>عامل جديد</b>\n"
            f"الاسم: {new_worker['name']}\nالمرتب الشهري: {new_worker['monthlySalary']:,.2f}"
        )
        return jsonify({"success": True, "worker": workers[-1]}), 201
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/dashboard/api/workers/<worker_id>', methods=['PUT'])
def update_worker(worker_id):
    try:
        req_data = request.get_json(force=True, silent=True) or {}
        data = load_data()
        workers = data["workers"]
        updated = False
        updated_worker = None

        for idx, w in enumerate(workers):
            if str(w.get("id")) == str(worker_id):
                if "name" in req_data: w["name"] = str(req_data["name"]).strip()
                if "startDate" in req_data: w["startDate"] = str(req_data["startDate"]).strip()
                if "monthlySalary" in req_data: w["monthlySalary"] = float(req_data["monthlySalary"])
                if "avatarUrl" in req_data: w["avatarUrl"] = str(req_data["avatarUrl"])
                workers[idx] = w
                updated = True
                updated_worker = w
                break

        if not updated:
            return jsonify({"success": False, "error": "العامل غير موجود"}), 404

        data["workers"] = workers
        save_data(data)
        send_telegram_message(
            "✏️ <b>تعديل بيانات عامل</b>\n"
            f"الاسم: {updated_worker.get('name','-')}\nالمرتب: {updated_worker.get('monthlySalary','-')}"
        )
        return jsonify({"success": True, "worker": updated_worker})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/dashboard/api/workers/<worker_id>', methods=['DELETE'])
def delete_worker(worker_id):
    try:
        data = load_data()
        workers = data["workers"]
        orig_len = len(workers)
        deleted_worker = next((w for w in workers if str(w.get("id")) == str(worker_id)), None)
        workers = [w for w in workers if str(w.get("id")) != str(worker_id)]

        if len(workers) == orig_len:
            return jsonify({"success": False, "error": "العامل غير موجود"}), 404

        renumber(workers)
        data["workers"] = workers
        save_data(data)
        send_telegram_message(
            f"🗑️ <b>حذف عامل</b>\nالاسم: {deleted_worker.get('name','-') if deleted_worker else '-'}"
        )
        return jsonify({"success": True, "message": "تم حذف العامل بنجاح"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# --- OCR وإيصالات ومعاملات بنك الخرطوم ---

@app.route('/dashboard/api/ocr/upload', methods=['POST'])
def upload_and_ocr():
    try:
        if 'image' not in request.files:
            return jsonify({"success": False, "error": "لم يتم إرسال صورة"}), 400
        file = request.files['image']
        if file.filename == '':
            return jsonify({"success": False, "error": "لم يتم اختيار ملف"}), 400
        allowed = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'tiff', 'webp'}
        ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
        if ext not in allowed:
            return jsonify({"success": False, "error": "نوع الملف غير مدعوم"}), 400

        filename = secure_filename(f"{uuid.uuid4()}_{file.filename}")
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        try:
            raw_text, groq_dict = ocr_image_groq(filepath)
        except Exception as e:
            if os.path.exists(filepath):
                os.remove(filepath)
            return jsonify({"success": False, "error": f"فشل معالجة الصورة: {str(e)}"}), 500

        parsed = parse_groq_result(groq_dict)

        if "error" in parsed:
            return jsonify({
                "success": False,
                "error": parsed["error"],
                "raw_text": raw_text,
                "hint": "تأكد من وضوح الإيصال"
            }), 422

        parsed["file_name"] = filename
        parsed["raw_text"] = raw_text

        return jsonify({
            "success": True,
            "message": "تم استخراج البيانات بنجاح",
            "data": parsed
        }), 200

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/dashboard/api/transactions/save', methods=['POST'])
def save_transaction():
    try:
        req_data = request.get_json(force=True, silent=True)
        if not req_data or not isinstance(req_data, dict):
            return jsonify({"success": False, "error": "بيانات غير صالحة"}), 400
        if not str(req_data.get("المبلغ", "")).strip():
            return jsonify({"success": False, "error": "المبلغ مطلوب"}), 400

        required_fields = [
            "رقم_العملية", "التاريخ_والزمن", "من_حساب", "الى_حساب",
            "اسم_المرسل_إليه", "رقم_الموبايل", "القسم", "النوع", "المبلغ"
        ]
        for field in required_fields:
            if field not in req_data:
                req_data[field] = "غير مصنف"

        count, saved_id = save_transaction_record(req_data)
        return jsonify({"success": True, "id": saved_id, "total_records": count}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/dashboard/api/transactions', methods=['GET'])
def get_transactions_for_mobile():
    account = request.args.get('account', '').strip()
    data = load_data()
    records = data["transactions"]

    formatted_transactions = []
    for r in records:
        if "error" in r or not r.get("المبلغ"):
            continue

        direction = get_direction(r, account)
        tx = {
            "id": r.get("id"),
            "direction": direction,
            "amount": parse_amount(r.get("المبلغ")),
            "savedAt": r.get("وقت_الحفظ", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            "result": r
        }
        formatted_transactions.append(tx)

    formatted_transactions.reverse()
    return jsonify({"success": True, "transactions": formatted_transactions})

@app.route('/dashboard/api/records', methods=['GET'])
def get_all_records():
    data = load_data()
    records = list(data["transactions"])
    records.reverse()
    return jsonify({"success": True, "total_records": len(records), "data": records})

@app.route('/dashboard/api/transactions/<transaction_id>', methods=['PUT'])
def update_transaction(transaction_id):
    data = load_data()
    records = data["transactions"]

    req_data = request.get_json(force=True, silent=True)
    if not req_data or not isinstance(req_data, dict):
        return jsonify({"success": False, "error": "بيانات غير صالحة"}), 400

    updated = False
    updated_record = None
    for i, r in enumerate(records):
        if str(r.get("id")) == str(transaction_id):
            for key, value in req_data.items():
                r[key] = value
            r["وقت_التعديل"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            records[i] = r
            updated = True
            updated_record = r
            break

    if not updated:
        return jsonify({"success": False, "error": "المعاملة غير موجودة"}), 404

    data["transactions"] = records
    save_data(data)
    send_telegram_message(
        "✏️ <b>تعديل معاملة بنكية</b>\n"
        f"المرسل إليه: {updated_record.get('اسم_المرسل_إليه','-')}\n"
        f"المبلغ: {updated_record.get('المبلغ','-')}"
    )
    return jsonify({"success": True, "message": "تم التعديل بنجاح", "data": updated_record})

@app.route('/dashboard/api/transactions/<transaction_id>', methods=['DELETE'])
def delete_transaction(transaction_id):
    data = load_data()
    records = data["transactions"]

    original_len = len(records)
    deleted_record = next((r for r in records if str(r.get("id")) == str(transaction_id)), None)
    records = [r for r in records if str(r.get("id")) != str(transaction_id)]
    if len(records) == original_len:
        return jsonify({"success": False, "error": "المعاملة غير موجودة"}), 404

    renumber(records)
    data["transactions"] = records
    save_data(data)
    send_telegram_message(
        "🗑️ <b>حذف معاملة بنكية</b>\n"
        f"المرسل إليه: {deleted_record.get('اسم_المرسل_إليه','-') if deleted_record else '-'}\n"
        f"المبلغ: {deleted_record.get('المبلغ','-') if deleted_record else '-'}"
    )
    return jsonify({"success": True, "message": "تم الحذف بنجاح"})

@app.route('/dashboard/api/records/<record_id>', methods=['GET'])
def get_record(record_id):
    data = load_data()
    records = data["transactions"]
    record = next((item for item in records if str(item.get("id")) == str(record_id)), None)
    if record:
        return jsonify({"success": True, "data": record})
    return jsonify({"success": False, "error": "غير موجود"}), 404


# ══════════════════════════════════════════════════════════════════
# القسم الثاني: مزرعة الدواجن (حظائر، تسجيلات يومية، تنبيهات)
# ══════════════════════════════════════════════════════════════════

def send_push_notification(tokens, title, body):
    if not tokens:
        return
    headers = {
        'Accept': 'application/json',
        'Accept-encoding': 'gzip, deflate',
        'Content-Type': 'application/json',
    }
    messages = []
    for token in set(tokens):
        if token and token.startswith('ExponentPushToken'):
            messages.append({
                'to': token,
                'sound': 'default',
                'title': title,
                'body': body,
                'priority': 'high'
            })
    if messages:
        try:
            requests.post(EXPO_PUSH_URL, headers=headers, json=messages, timeout=10)
        except Exception as e:
            print("خطأ أثناء إرسال الإشعار:", e)

def is_today_recorded(house):
    today_str = datetime.now().strftime("%Y-%m-%d")
    for r in house.get("daily_records", []):
        if r.get("date") == today_str:
            if r.get("morning_mortality", 0) > 0 or r.get("evening_mortality", 0) > 0 or r.get("feed_kg", 0) > 0:
                return True
    return False

scheduler = BackgroundScheduler()

def trigger_custom_alert(house_id, target, title):
    data = load_data()
    poultry = data["poultry"]
    house = poultry["houses"].get(house_id)
    if not house:
        return  # الحظيرة ربما حُذفت بعد جدولة التنبيه
    if not is_today_recorded(house):
        tokens = poultry["tokens"]["managers"] if target == 'manager' else poultry["tokens"]["workers"]
        house_name = house.get("name", "الحظيرة")
        if target == 'manager':
            body = f"تحذير: لم يتم تسجيل بيانات اليوم في حظيرة ({house_name})!"
        else:
            body = f"يرجى تسجيل بيانات النفوق والعلف لليوم في حظيرة ({house_name})."
        send_push_notification(tokens, title, body)

def reconfigure_scheduler():
    # نحذف فقط وظائف تنبيهات الحظائر، حتى لا نمسح وظائف بوت تيليجرام
    # (الاستطلاع الدوري والتقرير اليومي) المسجّلة بشكل منفصل.
    for job in scheduler.get_jobs():
        if job.id.startswith("house_"):
            scheduler.remove_job(job.id)
    data = load_data()
    poultry = data["poultry"]
    for house_id, house in poultry.get("houses", {}).items():
        schedules = house.get("alert_schedules", [])
        for alert in schedules:
            try:
                time_str = alert.get("time", "")
                time_parts = time_str.replace(" ص", "").replace(" م", "").strip().split(":")
                hour = int(time_parts[0])
                minute = int(time_parts[1])
                target = alert.get("target", "worker")
                title = alert.get("title", "تنبيه المزرعة")
                job_id = f"house_{house_id}_alert_{alert.get('id')}"

                scheduler.add_job(
                    trigger_custom_alert,
                    'cron',
                    hour=hour,
                    minute=minute,
                    args=[house_id, target, title],
                    id=job_id,
                    replace_existing=True
                )
            except Exception as e:
                print(f"خطأ أثناء جدولة التنبيه {alert} للحظيرة {house_id}:", e)

def build_house_summary(house_id, house):
    records = house.get("daily_records", [])
    total_mortality = sum(r.get("morning_mortality", 0) + r.get("evening_mortality", 0) for r in records)
    cycle_info = house.get("cycle_info", {})
    remaining = cycle_info.get("initial_birds_count", 0) - total_mortality - cycle_info.get("slaughtered_count", 0)
    total_feed_consumed_kg = sum(float(r.get("feed_kg", 0)) for r in records)
    latest_avg_weight_g = records[-1].get("avg_weight_g", 0) if records else 0

    start_date = datetime.strptime(cycle_info.get("start_date", datetime.now().strftime("%Y-%m-%d")), "%Y-%m-%d").date()
    today_date = datetime.now().date()
    current_cycle_day = max(1, (today_date - start_date).days + 1)

    return {
        "id": house_id,
        "name": house.get("name", ""),
        "cycle_start_date": cycle_info.get("start_date"),
        "initial_birds_count": cycle_info.get("initial_birds_count", 0),
        "slaughtered_count": cycle_info.get("slaughtered_count", 0),
        "remaining_count": remaining,
        "total_mortality": total_mortality,
        "total_feed_consumed_kg": total_feed_consumed_kg,
        "current_cycle_day": current_cycle_day,
        "latest_avg_weight_g": latest_avg_weight_g
    }

reconfigure_scheduler()
scheduler.start()

# استطلاع دوري لتسجيل أي محادثة جديدة بعتت /start للبوت
scheduler.add_job(
    poll_telegram_updates, 'interval', seconds=20,
    id='telegram_poll', replace_existing=True
)
# التقرير اليومي - يرسل الساعة 22:00 كل يوم (عدّل الوقت حسب رغبتك)
scheduler.add_job(
    send_daily_telegram_report, 'cron', hour=22, minute=0,
    id='telegram_daily_report', replace_existing=True
)

# --- إعدادات التطبيق العامة (تُضبط مرة واحدة فقط) ---

@app.route('/api/app_settings', methods=['GET'])
def get_app_settings():
    data = load_data()
    return jsonify(data["poultry"].get("app_settings", {"is_configured": False, "role": None}))

@app.route('/api/app_setup', methods=['POST'])
def app_setup():
    req = request.get_json() or {}
    data = load_data()
    poultry = data["poultry"]

    role = req.get('role', 'worker')
    password = req.get('password', '')

    if role == 'manager' and password != MANAGER_PASSWORD:
        return jsonify({"status": "error", "message": "كلمة المرور غير صحيحة!"}), 403

    poultry["app_settings"]["role"] = role
    poultry["app_settings"]["is_configured"] = True

    push_token = req.get('push_token')
    if push_token:
        target_list = poultry["tokens"]["managers"] if role == 'manager' else poultry["tokens"]["workers"]
        if push_token not in target_list:
            target_list.append(push_token)

    data["poultry"] = poultry
    save_data(data)
    send_telegram_message(
        f"⚙️ <b>إعداد تطبيق جديد</b>\nالدور: {'مدير' if role == 'manager' else 'عامل'}"
    )
    return jsonify({"status": "success", "message": "تم حفظ إعدادات التطبيق بنجاح!", "role": role})

# --- إدارة الحظائر ---

@app.route('/api/houses', methods=['GET'])
def list_houses():
    data = load_data()
    poultry = data["poultry"]
    summaries = [build_house_summary(hid, h) for hid, h in poultry.get("houses", {}).items()]
    summaries.sort(key=lambda x: int(x["id"]))
    return jsonify({"houses": summaries})

@app.route('/api/houses', methods=['POST'])
def create_house():
    req = request.get_json() or {}
    data = load_data()
    poultry = data["poultry"]

    name = (req.get('name') or '').strip()
    if not name:
        return jsonify({"status": "error", "message": "اسم الحظيرة مطلوب!"}), 400

    start_date = req.get('start_date') or datetime.now().strftime("%Y-%m-%d")
    try:
        initial_birds_count = int(req.get('initial_birds_count', 0))
    except (TypeError, ValueError):
        initial_birds_count = 0

    house_id = str(poultry.get("next_house_id", 1))
    poultry["next_house_id"] = int(house_id) + 1

    poultry["houses"][house_id] = {
        "id": house_id,
        "name": name,
        "cycle_info": {
            "start_date": start_date,
            "initial_birds_count": initial_birds_count,
            "slaughtered_count": 0
        },
        "alert_schedules": default_alert_schedules(),
        "daily_records": []
    }

    data["poultry"] = poultry
    save_data(data)
    reconfigure_scheduler()

    send_telegram_message(
        f"🏠 <b>حظيرة جديدة</b>\nالاسم: {name}\nعدد الطيور: {initial_birds_count}"
    )

    return jsonify({
        "status": "success",
        "message": "تمت إضافة الحظيرة بنجاح!",
        "house": build_house_summary(house_id, poultry["houses"][house_id])
    })

@app.route('/api/houses/<house_id>', methods=['PUT'])
def update_house_info(house_id):
    req = request.get_json() or {}
    data = load_data()
    poultry = data["poultry"]
    house = poultry["houses"].get(house_id)
    if not house:
        return jsonify({"status": "error", "message": "الحظيرة غير موجودة!"}), 404

    if 'name' in req and req['name']:
        house['name'] = req['name'].strip()
    if 'start_date' in req and req['start_date']:
        house['cycle_info']['start_date'] = req['start_date']
    if 'initial_birds_count' in req:
        house['cycle_info']['initial_birds_count'] = int(req['initial_birds_count'])
    if 'slaughtered_count' in req:
        house['cycle_info']['slaughtered_count'] = int(req['slaughtered_count'])

    data["poultry"] = poultry
    save_data(data)
    send_telegram_message(f"✏️ <b>تعديل بيانات حظيرة</b>\nالاسم: {house.get('name','-')}")
    return jsonify({"status": "success", "message": "تم تحديث بيانات الحظيرة بنجاح!"})

@app.route('/api/houses/<house_id>', methods=['DELETE'])
def delete_house(house_id):
    data = load_data()
    poultry = data["poultry"]
    deleted_house = poultry["houses"].pop(house_id, None)
    if deleted_house is None:
        return jsonify({"status": "error", "message": "الحظيرة غير موجودة!"}), 404
    data["poultry"] = poultry
    save_data(data)
    reconfigure_scheduler()
    send_telegram_message(f"🗑️ <b>حذف حظيرة</b>\nالاسم: {deleted_house.get('name','-')}")
    return jsonify({"status": "success", "message": "تم حذف الحظيرة بنجاح!"})

# --- بيانات لوحة تحكم حظيرة محددة ---

@app.route('/api/houses/<house_id>/dashboard', methods=['GET'])
def get_house_dashboard(house_id):
    data = load_data()
    poultry = data["poultry"]
    house = poultry["houses"].get(house_id)
    if not house:
        return jsonify({"status": "error", "message": "الحظيرة غير موجودة!"}), 404

    records = house.get("daily_records", [])
    last_record = records[-1] if records else {}

    feed_totals_by_type = {}
    total_feed_consumed_kg = 0.0
    for r in records:
        f_type = r.get("feed_type", "بادئ")
        f_kg = float(r.get("feed_kg", 0))
        feed_totals_by_type[f_type] = feed_totals_by_type.get(f_type, 0.0) + f_kg
        total_feed_consumed_kg += f_kg

    summary = build_house_summary(house_id, house)

    return jsonify({
        **summary,
        "today_morning_mortality": last_record.get("morning_mortality", 0),
        "today_evening_mortality": last_record.get("evening_mortality", 0),
        "latest_avg_weight_g": last_record.get("avg_weight_g", 0),
        "daily_feed_kg": last_record.get("feed_kg", 0),
        "current_feed_type": last_record.get("feed_type", "بادئ"),
        "feed_totals_by_type": feed_totals_by_type,
        "total_feed_consumed_kg": total_feed_consumed_kg,
        "alert_schedules": house.get("alert_schedules", []),
        "records": records
    })

@app.route('/api/houses/<house_id>/record', methods=['POST'])
def add_house_record(house_id):
    req = request.get_json() or {}
    data = load_data()
    poultry = data["poultry"]
    house = poultry["houses"].get(house_id)
    if not house:
        return jsonify({"status": "error", "message": "الحظيرة غير موجودة!"}), 404

    # ✅ ضمان وجود daily_records حتى لا يحدث KeyError في الحظائر القديمة
    house.setdefault("daily_records", [])

    start_date = datetime.strptime(house["cycle_info"]["start_date"], "%Y-%m-%d").date()
    today_date = datetime.now().date()
    current_day = max(1, (today_date - start_date).days + 1)

    existing_record = next((r for r in house["daily_records"] if r["day"] == current_day), None)

    if not existing_record:
        existing_record = {
            "day": current_day,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "morning_mortality": 0,
            "evening_mortality": 0,
            "avg_weight_g": 0,
            "feed_kg": 0,
            "feed_type": "بادئ"
        }
        house["daily_records"].append(existing_record)

    if 'morning_mortality' in req:
        existing_record['morning_mortality'] = int(req['morning_mortality'])
    if 'evening_mortality' in req:
        existing_record['evening_mortality'] = int(req['evening_mortality'])
    if 'avg_weight_g' in req and float(req['avg_weight_g']) > 0:
        existing_record['avg_weight_g'] = float(req['avg_weight_g'])
    if 'feed_kg' in req and float(req['feed_kg']) > 0:
        existing_record['feed_kg'] = float(req['feed_kg'])
    if 'feed_type' in req and req['feed_type']:
        existing_record['feed_type'] = req['feed_type']

    data["poultry"] = poultry
    save_data(data)
    send_telegram_message(
        "📋 <b>تسجيل يومي جديد</b>\n"
        f"الحظيرة: {house.get('name','-')} (يوم {current_day})\n"
        f"نفوق صباحي: {existing_record['morning_mortality']} | نفوق مسائي: {existing_record['evening_mortality']}\n"
        f"متوسط الوزن: {existing_record['avg_weight_g']} جم | العلف: {existing_record['feed_kg']} كجم ({existing_record['feed_type']})"
    )
    return jsonify({"status": "success", "message": "تم الحفظ بنجاح!"})

@app.route('/api/houses/<house_id>/alerts', methods=['POST'])
def update_house_alerts(house_id):
    req = request.get_json() or {}
    data = load_data()
    poultry = data["poultry"]
    house = poultry["houses"].get(house_id)
    if not house:
        return jsonify({"status": "error", "message": "الحظيرة غير موجودة!"}), 404

    house["alert_schedules"] = req.get('alert_schedules', [])
    data["poultry"] = poultry
    save_data(data)
    reconfigure_scheduler()

    send_telegram_message(f"🔔 <b>تحديث تنبيهات حظيرة</b>\nالحظيرة: {house.get('name','-')}")

    return jsonify({"status": "success", "message": "تم تحديث وإضافة تنبيهات الحظيرة بنجاح!"})



# ══════════════════════════════════════════════════════════════════
# القسم الثالث: مصنع العلف (المكونات، المخزون، حركات الوارد/المنصرف)
# ══════════════════════════════════════════════════════════════════

@app.route('/api/dashboard', methods=['GET'])
def get_factory_dashboard():
    data = load_data()
    return jsonify(data["feed_factory"])

@app.route('/api/transaction', methods=['POST'])
def add_factory_transaction():
    req_data = request.get_json()

    ingredient_key = req_data.get('ingredient_key')
    trans_type = req_data.get('type')  # وارد أو منصرف
    bags_count = int(req_data.get('bags_count', 0))
    bag_weight = float(req_data.get('bag_weight', 0))

    # حساب إجمالي الوزن بالكيلوجرام المستهدف لهذه العملية
    total_kg = bags_count * bag_weight

    data = load_data()
    factory = data["feed_factory"]

    if ingredient_key in factory['ingredients']:
        # تعديل تراكمي للمخزون بالكيلوجرام
        if trans_type == 'وارد':
            factory['ingredients'][ingredient_key]['stockKg'] += total_kg
        elif trans_type == 'منصرف':
            factory['ingredients'][ingredient_key]['stockKg'] -= total_kg
            if factory['ingredients'][ingredient_key]['stockKg'] < 0:
                factory['ingredients'][ingredient_key]['stockKg'] = 0

        # تسجيل الحركة متضمنة تخصيص الشكائر وأوزانها كمرجع في السجل
        new_log = {
            "id": str(len(factory['history'][ingredient_key]) + 1),
            "date": datetime.now().strftime("%Y/%m/%d %I:%M %p"),
            "type": trans_type,
            "bags_count": bags_count,
            "bag_weight": bag_weight,
            "totalKg": total_kg
        }

        factory['history'][ingredient_key].insert(0, new_log)
        data["feed_factory"] = factory
        save_data(data)

        ing_name = factory['ingredients'][ingredient_key].get('name', ingredient_key)
        send_telegram_message(
            "🌾 <b>حركة مصنع علف جديدة</b>\n"
            f"المكوّن: {ing_name}\n"
            f"النوع: {trans_type}\n"
            f"عدد الشكائر: {bags_count} × {bag_weight} كجم = {total_kg:,.2f} كجم"
        )

    return jsonify(data["feed_factory"])


# ══════════════════════════════════════════════════════════════════
# القسم الرابع: متابعة الديون/الأشخاص (الأرصدة والمعاملات)
# ══════════════════════════════════════════════════════════════════

def sync_debt_payments_from_bank(data):
    """يبحث في معاملات إيصالات البنك عن أي معاملة القسم فيها 'الديون' والنوع فيه
    اسم شخص مسجّل في نظام الديون، ويضيفها تلقائياً كدفعة تُخصم من دين ذلك الشخص
    (بدون تكرار الخصم لنفس الإيصال مرتين)."""
    debts = data["debts"]
    people = debts["people"]
    if not people:
        return False

    already_synced = set(debts.get("synced_bank_tx_ids", []))
    changed = False

    for bank_tx in data.get("transactions", []):
        section = str(bank_tx.get("القسم", "")).strip()
        if section != "الديون" and "ديون" not in section:
            continue

        # معرّف ثابت لهذه المعاملة البنكية (رقم العملية من الإيصال نفسه)
        source_id = str(bank_tx.get("رقم_العملية", "")).strip()
        if not source_id or source_id in already_synced:
            continue

        type_field = str(bank_tx.get("النوع", "")).strip()
        if not type_field:
            continue

        matched_person = None
        for p in people:
            person_name = str(p.get("name", "")).strip()
            if person_name and (type_field in person_name or person_name in type_field):
                matched_person = p
                break

        if not matched_person:
            continue

        amount = parse_amount(bank_tx.get("المبلغ", "0"))
        if amount == 0:
            continue

        new_tx = {
            "id": len(debts["transactions"]) + 1,
            "person_id": matched_person["id"],
            "amount": -abs(amount),
            "note": f"دفعة تلقائية من إيصال بنكي (مرسل: {bank_tx.get('اسم_المرسل_إليه', '')})",
            "date_created": str(date.today())
        }
        debts["transactions"].append(new_tx)
        already_synced.add(source_id)
        changed = True

    if changed:
        debts["synced_bank_tx_ids"] = list(already_synced)
        data["debts"] = debts
        save_data(data)

    return changed


@app.route('/persons', methods=['GET'])
def get_persons():
    data = load_data()
    sync_debt_payments_from_bank(data)
    data = load_data()  # إعادة القراءة بعد التزامن للحصول على أحدث نسخة
    debts = data["debts"]
    result = []
    for p in debts["people"]:
        txs = [t for t in debts["transactions"] if t["person_id"] == p["id"]]
        total_balance = sum(t["amount"] for t in txs)
        person_data = p.copy()
        person_data["balance"] = total_balance
        result.append(person_data)
    return jsonify(result), 200

@app.route('/persons', methods=['POST'])
def create_person():
    req_data = request.get_json() or {}
    name = req_data.get('name')
    phone = req_data.get('phone')
    initial_amount = float(req_data.get('initial_amount', 0.0))
    note = req_data.get('note', 'إضافة أولية')
    if not name or not phone:
        return jsonify({"error": "الاسم ورقم الهاتف مطلوبة"}), 400

    data = load_data()
    debts = data["debts"]

    new_p_id = len(debts["people"]) + 1
    new_person = {
        "id": new_p_id,
        "name": name,
        "phone": phone
    }
    debts["people"].append(new_person)

    if initial_amount != 0:
        debts["transactions"].append({
            "id": len(debts["transactions"]) + 1,
            "person_id": new_p_id,
            "amount": initial_amount,
            "note": note,
            "date_created": str(date.today())
        })

    data["debts"] = debts
    save_data(data)
    send_telegram_message(
        "🧑‍🤝‍🧑 <b>شخص جديد في نظام الديون</b>\n"
        f"الاسم: {name}\nالهاتف: {phone}"
        + (f"\nرصيد ابتدائي: {initial_amount:,.2f}" if initial_amount else "")
    )
    return jsonify(new_person), 201

@app.route('/persons/<int:person_id>', methods=['DELETE'])
def delete_person(person_id):
    data = load_data()
    debts = data["debts"]
    deleted_person = next((p for p in debts["people"] if p["id"] == person_id), None)
    debts["people"] = [p for p in debts["people"] if p["id"] != person_id]
    debts["transactions"] = [t for t in debts["transactions"] if t["person_id"] != person_id]
    data["debts"] = debts
    save_data(data)
    send_telegram_message(
        f"🗑️ <b>حذف شخص من نظام الديون</b>\nالاسم: {deleted_person.get('name','-') if deleted_person else '-'}"
    )
    return jsonify({"status": "deleted"}), 200

@app.route('/persons/<int:person_id>/transactions', methods=['GET'])
def get_person_transactions(person_id):
    data = load_data()
    sync_debt_payments_from_bank(data)
    data = load_data()
    debts = data["debts"]
    person_txs = [t for t in debts["transactions"] if t["person_id"] == person_id]
    return jsonify(person_txs), 200

@app.route('/transactions', methods=['POST'])
def add_debt_transaction():
    req_data = request.get_json() or {}
    person_id = req_data.get('person_id')
    amount = req_data.get('amount')
    note = req_data.get('note', '')
    if person_id is None or amount is None:
        return jsonify({"error": "بيانات المعاملة غير مكتملة"}), 400

    data = load_data()
    debts = data["debts"]
    new_tx = {
        "id": len(debts["transactions"]) + 1,
        "person_id": int(person_id),
        "amount": float(amount),
        "note": note,
        "date_created": str(date.today())
    }
    debts["transactions"].append(new_tx)
    data["debts"] = debts
    save_data(data)

    person = next((p for p in debts["people"] if p["id"] == new_tx["person_id"]), None)
    person_name = person["name"] if person else str(new_tx["person_id"])
    send_telegram_message(
        "💳 <b>معاملة دين جديدة</b>\n"
        f"الشخص: {person_name}\n"
        f"المبلغ: {new_tx['amount']:,.2f}\n"
        f"ملاحظة: {new_tx.get('note', '-')}"
    )

    return jsonify(new_tx), 201


if __name__ == '__main__':
    print("=" * 50)
    print("🚀 السيرفر الموحّد جاهز (جهات اتصال / عمال / OCR / مزرعة دواجن)")
    print(f"📁 ملف البيانات: {DATA_FILE}")
    print("📍 يعمل على المنفذ 5000")
    print("=" * 50)
    app.run(host='0.0.0.0', port=8080, debug=False)
