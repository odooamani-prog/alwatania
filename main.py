import json
import requests
import re
import os
import base64
import uuid
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.utils import secure_filename

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
MANAGER_PASSWORD = "1282"

# ─── إعدادات بوت تيليجرام ───────────────────────────────────────────
TELEGRAM_BOT_TOKEN = config.get("TELEGRAM_BOT_TOKEN") or "8934774619:AAEELQfe6o5q6Lwe9FPApcM4zK1NQPsMJwQ"
TELEGRAM_API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# ─── قاعدة البيانات ─────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "data.json")

DEFAULT_CONTACTS = [
    {"id": "1", "name": "أحمد خالد", "phone": "055 1234 567"},
    {"id": "2", "name": "حمد حسن", "phone": "055 1234 567", "avatar": "https://i.pravatar.cc/150?img=33"}
]

DEFAULT_WORKERS = [
    {"id": "1", "name": "أحمد علي محمود", "startDate": "2024-01-01", "monthlySalary": 12000, "avatarUrl": "https://i.pravatar.cc/150?img=11"}
]

def default_poultry():
    return {"app_settings": {"is_configured": False, "role": None}, "tokens": {"workers": [], "managers": []}, "next_house_id": 1, "houses": {}}

def default_feed_factory():
    return {
        "ingredients": {
            "bread": {"name": "عيش", "stockKg": 15000, "formulaKg": 650, "defaultBagWeight": 50, "icon": "wheat", "color": "#F59E0B"},
            "umbaz": {"name": "امباز", "stockKg": 8000, "formulaKg": 280, "defaultBagWeight": 50, "icon": "peanut", "color": "#B45309"},
            "center": {"name": "مركز", "stockKg": 3500, "formulaKg": 50, "defaultBagWeight": 50, "icon": "percent", "color": "#3B82F6"}
        },
        "history": {"bread": [], "umbaz": [], "center": []}
    }

def default_debts():
    return {"people": [], "transactions": [], "synced_bank_tx_ids": []}

def default_telegram():
    return {"chat_ids": []}

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
    if not os.path.exists(DATA_FILE):
        data = default_data()
        save_data(data)
        return data
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = default_data()
        save_data(data)
        return data

    data.setdefault("contacts", [])
    data.setdefault("workers", [])
    data.setdefault("transactions", [])
    data.setdefault("poultry", default_poultry())
    data.setdefault("feed_factory", default_feed_factory())
    data.setdefault("debts", default_debts())
    data.setdefault("telegram", default_telegram())
    return data

def save_data(data):
    tmp_path = DATA_FILE + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    os.replace(tmp_path, DATA_FILE)

def renumber(items):
    for idx, item in enumerate(items, start=1):
        item["id"] = str(idx)
    return items

def clean_acc(s):
    return str(s or "").replace(" ", "").strip()

def parse_amount(s):
    cleaned = str(s or "").replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        match = re.search(r'[\d.]+', cleaned)
        return float(match.group()) if match else 0.0

def get_direction(result, my_account):
    if not my_account:
        return "in"
    my = clean_acc(my_account)
    from_acc = clean_acc(result.get("من_حساب", ""))
    if from_acc == my:
        return "out"
    return "in"

# ─── دالة إرسال التليجرام ──────────────────────────────────────────────
def send_telegram_message(text):
    try:
        data = load_data()
        chat_ids = data.get("telegram", {}).get("chat_ids", [])
    except Exception as e:
        print("❌ خطأ أثناء قراءة بيانات تيليجرام:", e)
        return

    if not chat_ids:
        print("⚠️ لا يوجد مستخدمين مسجلين في البوت بعد.")
        return

    for chat_id in chat_ids:
        try:
            requests.post(
                f"{TELEGRAM_API_BASE}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
                timeout=10
            )
        except Exception as e:
            print(f"❌ فشل الإرسال لـ {chat_id}:", e)

# ─── TELEGRAM WEBHOOK ────────────────────────────────────────────────
@app.route('/telegram/webhook', methods=['POST'])
def telegram_webhook():
    try:
        update = request.get_json(force=True, silent=True) or {}
        msg = update.get("message") or update.get("channel_post")
        if msg:
            chat_id = msg.get("chat", {}).get("id")
            if chat_id is not None:
                data = load_data()
                tg = data.setdefault("telegram", default_telegram())
                if chat_id not in tg["chat_ids"]:
                    tg["chat_ids"].append(chat_id)
                    data["telegram"] = tg
                    save_data(data)
                    
                    requests.post(
                        f"{TELEGRAM_API_BASE}/sendMessage",
                        json={
                            "chat_id": chat_id,
                            "text": "✅ <b>تم تفعيل الإشعارات بنجاح!</b>\nستصلك كافة العمليات والتقارير على هذه المحادثة فور حدوثها.",
                            "parse_mode": "HTML"
                        },
                        timeout=10
                    )
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ─── GROQ OCR SYSTEM ────────────────────────────────────────────────
GROQ_SYSTEM_PROMPT = """أنت نظام متخصص في استخراج بيانات إيصالات التحويل البنكي لبنك الخرطوم.
أرجع JSON فقط بالشكل التالي:
{
  "رقم_العملية": "12345678901",
  "التاريخ_والزمن": "15-Jan-2025 10:30:00",
  "من_حساب": "1003080673540001",
  "الى_حساب": "1003077763320001",
  "اسم_المرسل_إليه": "محمد أحمد علي",
  "القسم": "خاص",
  "النوع": "شخصي",
  "المبلغ": "1,500.00"
}"""

def ocr_image_groq(image_path):
    with open(image_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("utf-8")

    payload = {
        "model": "qwen/qwen3.6-27b",
        "max_tokens": 1024,
        "messages": [
            {"role": "system", "content": GROQ_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                    {"type": "text", "text": "استخرج البيانات بتنسيق JSON فقط."}
                ]
            }
        ]
    }
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    response = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=30)
    
    if response.status_code != 200:
        raise Exception(f"Groq API error {response.status_code}: {response.text}")
        
    raw_text = response.json()["choices"][0]["message"]["content"].strip()
    clean_text = re.sub(r'```(?:json)?', '', raw_text).strip().strip('`').strip()
    return raw_text, json.loads(clean_text)

# ─── ENDPOINTS (تطبيق الجوال + التليجرام) ───────────────────────────────

@app.route('/', methods=['GET'])
def home():
    return jsonify({"status": "running", "service": "Alwatania Unified Backend"})

# 1. جلب المعاملات لتطبيق الجوال (تم إصلاح الخطأ 404 هنا)
@app.route('/dashboard/api/transactions', methods=['GET'])
def get_transactions_for_mobile():
    account = request.args.get('account', '').strip()
    data = load_data()
    records = data.get("transactions", [])

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

    return jsonify({"success": True, "transactions": formatted_transactions}), 200

# 2. حفظ معاملة بنكية
@app.route('/dashboard/api/transactions/save', methods=['POST'])
def save_transaction():
    try:
        req_data = request.get_json(force=True, silent=True) or {}
        data = load_data()
        req_data["وقت_الحفظ"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data["transactions"].append(req_data)
        renumber(data["transactions"])
        save_data(data)

        send_telegram_message(
            "🏦 <b>حفظ معاملة بنكية جديدة</b>\n"
            f"المرسل إليه: {req_data.get('اسم_المرسل_إليه', '-')}\n"
            f"المبلغ: {req_data.get('المبلغ', '-')}\n"
            f"القسم: {req_data.get('القسم', '-')} | النوع: {req_data.get('النوع', '-')}\n"
            f"التاريخ: {req_data.get('التاريخ_والزمن', '-')}"
        )
        return jsonify({"success": True, "total": len(data["transactions"])}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# 3. OCR فحص صورة
@app.route('/dashboard/api/ocr/upload', methods=['POST'])
def upload_and_ocr():
    try:
        if 'image' not in request.files:
            return jsonify({"success": False, "error": "لم يتم إرسال صورة"}), 400
        file = request.files['image']
        filename = secure_filename(f"{uuid.uuid4()}_{file.filename}")
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        raw_text, parsed = ocr_image_groq(filepath)

        send_telegram_message(
            "📷 <b>تم فحص إيصال بنكي جديد (OCR)</b>\n"
            f"👤 المرسل إليه: {parsed.get('اسم_المرسل_إليه', '-')}\n"
            f"💰 المبلغ: {parsed.get('المبلغ', '-')}\n"
            f"🆔 رقم العملية: {parsed.get('رقم_العملية', '-')}"
        )

        return jsonify({"success": True, "data": parsed}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# 4. جهات الاتصال
@app.route('/dashboard/api/contacts', methods=['GET', 'POST'])
def handle_contacts():
    data = load_data()
    if request.method == 'POST':
        req = request.get_json(force=True, silent=True) or {}
        new_c = {"id": "0", "name": req.get("name"), "phone": req.get("phone")}
        data["contacts"].insert(0, new_c)
        renumber(data["contacts"])
        save_data(data)

        send_telegram_message(f"👤 <b>إضافة جهة اتصال جديدة</b>\nالاسم: {new_c['name']}\nالهاتف: {new_c['phone']}")
        return jsonify({"success": True, "contact": new_c}), 201

    return jsonify({"success": True, "contacts": data["contacts"]})

@app.route('/dashboard/api/contacts/<cid>', methods=['DELETE'])
def delete_contact(cid):
    data = load_data()
    orig = len(data["contacts"])
    data["contacts"] = [c for c in data["contacts"] if str(c.get("id")) != str(cid)]
    if len(data["contacts"]) < orig:
        renumber(data["contacts"])
        save_data(data)
        send_telegram_message(f"🗑️ <b>تم حذف جهة اتصال</b> (المعرف: {cid})")
        return jsonify({"success": True}), 200
    return jsonify({"success": False, "error": "غير موجود"}), 404

# 5. إدارة العمال
@app.route('/dashboard/api/workers', methods=['GET', 'POST'])
def handle_workers():
    data = load_data()
    if request.method == 'POST':
        req = request.get_json(force=True, silent=True) or {}
        new_w = {
            "id": "0",
            "name": req.get("name"),
            "monthlySalary": float(req.get("monthlySalary", 0)),
            "startDate": req.get("startDate", datetime.now().strftime("%Y-%m-%d"))
        }
        data["workers"].append(new_w)
        renumber(data["workers"])
        save_data(data)

        send_telegram_message(f"👷 <b>إضافة عامل جديد</b>\nالاسم: {new_w['name']}\nالمرتب: {new_w['monthlySalary']:,.2f}")
        return jsonify({"success": True, "worker": new_w}), 201

    return jsonify({"success": True, "workers": data["workers"]})

# 6. تسجيل حركة ديون
@app.route('/transactions', methods=['POST'])
def add_debt_transaction():
    try:
        req = request.get_json(force=True, silent=True) or {}
        data = load_data()
        debts = data.setdefault("debts", default_debts())
        debts["transactions"].append(req)
        save_data(data)

        send_telegram_message(
            "💳 <b>تسجيل حركة دين جديدة</b>\n"
            f"الشخص: {req.get('person_name', '-')}\n"
            f"المبلغ: {req.get('amount', 0):,.2f}\n"
            f"النوع: {req.get('type', '-')}"
        )
        return jsonify({"success": True}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# 7. تحديثات مصنع العلف
@app.route('/api/transaction', methods=['POST'])
def feed_factory_transaction():
    try:
        req = request.get_json(force=True, silent=True) or {}
        ing_key = req.get("ingredient")
        qty = req.get("quantity")
        action = req.get("action")

        data = load_data()
        ff = data.get("feed_factory", default_feed_factory())
        
        if ing_key in ff["ingredients"]:
            if action == "add":
                ff["ingredients"][ing_key]["stockKg"] += qty
            else:
                ff["ingredients"][ing_key]["stockKg"] -= qty

            log = {"date": datetime.now().strftime("%Y/%m/%d %H:%M"), "qty": qty, "type": action}
            ff["history"].setdefault(ing_key, []).append(log)
            save_data(data)

            send_telegram_message(
                "🌾 <b>حركة في مخزون العلف</b>\n"
                f"الصنف: {ff['ingredients'][ing_key]['name']}\n"
                f"الكمية: {qty} كجم\n"
                f"نوع الحركة: {'زيادة ➕' if action == 'add' else 'سحب ➖'}"
            )
            return jsonify({"success": True, "new_stock": ff["ingredients"][ing_key]["stockKg"]})
        return jsonify({"success": False, "error": "المادة غير موجودة"}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
