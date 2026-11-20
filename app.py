import os
import random
import string
from urllib.parse import urlparse
import pg8000.native
from curl_cffi.requests import AsyncSession
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI()

# ================= НАСТРОЙКИ =================
SMS_API_KEY = "1b8d7cc1c33d18031A4b81e7152fAd02"
BASE_API_URL = "https://hero-sms.com"
ADMIN_SECRET = "admin123"
MARKUP = 1.5
DATABASE_URL = os.environ.get("POSTGRES_URL") or os.environ.get("DATABASE_URL")

CF_COOKIE = "Cv7CEVdQVA15xbZ_AO5xVhUnbCH22tdnVRnv9s5oheLJ1NJ42UEs1elf5ylh4o3Xw8k9TU1S2oVgAw1lAQyFG_P2XqWBBv6cFWD6u4qNf9SCj3ypHf6K73BoQlUORq8OWTH_jjTevzRBJfJtelNOnykjJMWu14i1Vj5PIX-1AZlCaYZ67zFCHBpNeLsNxO-vUeVFcuTzkgXhAJDkQjuA4l_Fg44dEAeKBWjSv31-bUcVnbM-tIu4kG6lq8fqsjwGC43A6XL8BXZD3GMzGHp9cJ3F3rDEYDQU8vhDguS2chIeaI-I2Ezm"
# =============================================

API_HEADERS = {
    "Authorization": f"ApiKey {SMS_API_KEY}",
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": "https://hero-sms.com",
    "Referer": "https://hero-sms.com",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36"
}
COOKIES = {"cf_clearance": CF_COOKIE}

def get_db():
    if not DATABASE_URL:
        return None
    u = urlparse(DATABASE_URL)
    conn = pg8000.native.Connection(
        user=u.username,
        password=u.password,
        host=u.hostname,
        port=u.port or 5432,
        database=u.path.lstrip("/"),
        ssl_context=True
    )
    conn.run("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            balance DOUBLE PRECISION DEFAULT 0.0
        );
    """)
    conn.run("""
        CREATE TABLE IF NOT EXISTS promocodes (
            code TEXT PRIMARY KEY,
            amount DOUBLE PRECISION
        );
    """)
    return conn

@app.get("/", response_class=HTMLResponse)
async def index():
    file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()

@app.get("/api/init")
async def init_data(user_id: str = "demo_user"):
    bal = 0.0
    conn = get_db()
    if conn:
        conn.run("INSERT INTO users (user_id, balance) VALUES (:uid, 0.0) ON CONFLICT (user_id) DO NOTHING;", uid=user_id)
        rows = conn.run("SELECT balance FROM users WHERE user_id = :uid;", uid=user_id)
        if rows:
            bal = float(rows)
        conn.close()

    items = [
        {"id": "tg", "name": "Telegram", "country": 6, "country_name": "Индонезия (дешево)", "base_price": 0.25},
        {"id": "tg", "name": "Telegram", "country": 187, "country_name": "США", "base_price": 0.60},
        {"id": "wa", "name": "WhatsApp", "country": 6, "country_name": "Индонезия", "base_price": 0.30},
        {"id": "go", "name": "Google / YouTube", "country": 16, "country_name": "Великобритания", "base_price": 0.35},
        {"id": "ig", "name": "Instagram", "country": 22, "country_name": "Индия", "base_price": 0.15},
    ]
    for item in items:
        item["price"] = round(item["base_price"] * MARKUP, 2)
    return {"balance": round(bal, 2), "services": items}

@app.post("/api/redeem")
async def redeem_promo(code: str, user_id: str = "demo_user"):
    code = code.strip().upper()
    conn = get_db()
    if not conn:
        return {"status": "error", "message": "База данных не подключена (проверь POSTGRES_URL в Vercel)"}
    rows = conn.run("SELECT amount FROM promocodes WHERE code = :c;", c=code)
    if rows:
        amount = float(rows)
        conn.run("DELETE FROM promocodes WHERE code = :c;", c=code)
        res = conn.run(
            "INSERT INTO users (user_id, balance) VALUES (:uid, :amt) ON CONFLICT (user_id) DO UPDATE SET balance = users.balance + :amt RETURNING balance;",
            uid=user_id, amt=amount
        )
        new_bal = float(res)
        conn.close()
        return {"status": "ok", "added": amount, "balance": round(new_bal, 2)}
    conn.close()
    return {"status": "error", "message": "Неверный или уже использованный промокод"}

@app.get("/api/admin/create-promo")
async def create_promo(secret: str, amount: float):
    if secret != ADMIN_SECRET:
        return {"status": "error", "message": "Неверный пароль админа"}
    conn = get_db()
    if not conn:
        return {"status": "error", "message": "База данных не подключена"}
    new_code = "SMS-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    conn.run("INSERT INTO promocodes (code, amount) VALUES (:c, :amt);", c=new_code, amt=amount)
    conn.close()
    return {"status": "ok", "promo_code": new_code, "amount": amount}

@app.post("/api/order")
async def create_order(service: str, country: int, price: float, user_id: str = "demo_user"):
    conn = get_db()
    if not conn:
        return {"status": "error", "message": "База данных не подключена"}
    rows = conn.run("SELECT balance FROM users WHERE user_id = :uid;", uid=user_id)
    bal = float(rows) if rows else 0.0
    if bal < price:
        conn.close()
        return {"status": "error", "message": "Недостаточно средств на балансе!"}

    payload = {"service": service, "country": country, "amount": 1}
    async with AsyncSession() as client:
        resp = await client.post(f"{BASE_API_URL}/activations", json=payload, headers=API_HEADERS, cookies=COOKIES)
        if resp.status_code == 200:
            items = resp.json().get("data", [])
            if items:
                activation = items
                order_id = str(activation["id"])
                phone = str(activation["phone"])
                res = conn.run("UPDATE users SET balance = balance - :p WHERE user_id = :uid RETURNING balance;", p=price, uid=user_id)
                new_bal = float(res)
                conn.close()
                formatted_phone = f"+{phone}" if not phone.startswith("+") else phone
                return {"status": "ok", "order_id": order_id, "phone": formatted_phone, "balance": round(new_bal, 2)}
    conn.close()
    return {"status": "error", "message": f"Ответ API ({resp.status_code}): {resp.text}"}

@app.get("/api/status/{order_id}")
async def check_status(order_id: str):
    async with AsyncSession() as client:
        resp = await client.get(f"{BASE_API_URL}/activations/{order_id}/otp", headers=API_HEADERS, cookies=COOKIES)
        if resp.status_code == 200:
            otp_list = resp.json().get("data", [])
            if isinstance(otp_list, list) and len(otp_list) > 0:
                code = otp_list[-1].get("smsCode")
                if code:
                    return {"status": "received", "code": code}
            elif isinstance(otp_list, dict) and otp_list.get("smsCode"):
                return {"status": "received", "code": otp_list["smsCode"]}
        return {"status": "waiting"}

@app.post("/api/cancel/{order_id}")
async def cancel_order(order_id: str, price: float, user_id: str = "demo_user"):
    async with AsyncSession() as client:
        resp = await client.delete(f"{BASE_API_URL}/activations/{order_id}", headers=API_HEADERS, cookies=COOKIES)
        if resp.status_code in (200, 204):
            conn = get_db()
            if conn:
                res = conn.run("UPDATE users SET balance = balance + :p WHERE user_id = :uid RETURNING balance;", p=price, uid=user_id)
                new_bal = float(res)
                conn.close()
                return {"status": "ok", "balance": round(new_bal, 2)}
        return {"status": "error", "message": f"Не удалось отменить ({resp.status_code}): {resp.text}"}
