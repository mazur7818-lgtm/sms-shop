import os
import random
import string
from curl_cffi.requests import AsyncSession
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI()

# ================= НАСТРОЙКИ =================
SMS_API_KEY = "0438dedf43288baac4f1e0f8db986b77"
SMS_API_URL = "https://api.grizzlysms.com/stubs/handler_api.php"
ADMIN_SECRET = "admin123"
MARKUP = 1.5

SB_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SB_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
# =============================================

SB_HEADERS = {
    "apikey": SB_KEY,
    "Authorization": f"Bearer {SB_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

GRIZZLY_HEADERS = {
    "Accept": "text/plain, */*",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def first_item(data):
    if isinstance(data, list) and len(data) > 0:
        return next(iter(data))
    if isinstance(data, dict):
        return data
    return None

@app.get("/", response_class=HTMLResponse)
async def index():
    file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()

@app.get("/api/init")
async def init_data(user_id: str = "demo_user"):
    bal = 0.0
    if SB_URL and SB_KEY:
        async with AsyncSession() as client:
            r = await client.get(f"{SB_URL}/rest/v1/users?user_id=eq.{user_id}", headers=SB_HEADERS)
            if r.status_code == 200:
                row = first_item(r.json())
                if row:
                    bal = float(row.get("balance", 0.0))
                else:
                    await client.post(f"{SB_URL}/rest/v1/users", json={"user_id": user_id, "balance": 0.0}, headers=SB_HEADERS)

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
    if not (SB_URL and SB_KEY):
        return {"status": "error", "message": "База Supabase не настроена"}
    async with AsyncSession() as client:
        r = await client.get(f"{SB_URL}/rest/v1/promocodes?code=eq.{code}", headers=SB_HEADERS)
        if r.status_code == 200:
            promo = first_item(r.json())
            if promo:
                amount = float(promo.get("amount", 0.0))
                await client.delete(f"{SB_URL}/rest/v1/promocodes?code=eq.{code}", headers=SB_HEADERS)
                u = await client.get(f"{SB_URL}/rest/v1/users?user_id=eq.{user_id}", headers=SB_HEADERS)
                user_row = first_item(u.json()) if u.status_code == 200 else None
                cur_bal = float(user_row.get("balance", 0.0)) if user_row else 0.0
                new_bal = round(cur_bal + amount, 2)
                if user_row:
                    await client.patch(f"{SB_URL}/rest/v1/users?user_id=eq.{user_id}", json={"balance": new_bal}, headers=SB_HEADERS)
                else:
                    await client.post(f"{SB_URL}/rest/v1/users", json={"user_id": user_id, "balance": new_bal}, headers=SB_HEADERS)
                return {"status": "ok", "added": amount, "balance": new_bal}
    return {"status": "error", "message": "Неверный или уже использованный промокод"}

@app.get("/api/admin/create-promo")
async def create_promo(secret: str, amount: float):
    if secret != ADMIN_SECRET:
        return {"status": "error", "message": "Неверный пароль админа"}
    new_code = "SMS-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    async with AsyncSession() as client:
        r = await client.post(f"{SB_URL}/rest/v1/promocodes", json={"code": new_code, "amount": amount}, headers=SB_HEADERS)
        if r.status_code in (200, 201):
            return {"status": "ok", "promo_code": new_code, "amount": amount}
        return {"status": "error", "message": f"Ошибка БД ({r.status_code}): {r.text}"}

@app.post("/api/order")
async def create_order(service: str, country: int, price: float, user_id: str = "demo_user"):
    async with AsyncSession() as client:
        u = await client.get(f"{SB_URL}/rest/v1/users?user_id=eq.{user_id}", headers=SB_HEADERS)
        user_row = first_item(u.json()) if u.status_code == 200 else None
        bal = float(user_row.get("balance", 0.0)) if user_row else 0.0
        if bal < price:
            return {"status": "error", "message": "Недостаточно средств на балансе!"}

        url = f"{SMS_API_URL}?api_key={SMS_API_KEY}&action=getNumber&service={service}&country={country}"
        resp = await client.get(url, headers=GRIZZLY_HEADERS)
        text = resp.text.strip()
        if "ACCESS_NUMBER" in text:
            parts = text.split(":")
            order_id = parts[1]
            phone = parts[2]
            new_bal = round(bal - price, 2)
            await client.patch(f"{SB_URL}/rest/v1/users?user_id=eq.{user_id}", json={"balance": new_bal}, headers=SB_HEADERS)
            formatted_phone = f"+{phone}" if not phone.startswith("+") else phone
            return {"status": "ok", "order_id": order_id, "phone": formatted_phone, "balance": new_bal}
        return {"status": "error", "message": f"Ответ GrizzlySMS: {text}"}

@app.get("/api/status/{order_id}")
async def check_status(order_id: str):
    async with AsyncSession() as client:
        url = f"{SMS_API_URL}?api_key={SMS_API_KEY}&action=getStatus&id={order_id}"
        resp = await client.get(url, headers=GRIZZLY_HEADERS)
        text = resp.text.strip()
        if "STATUS_OK" in text:
            parts = text.split(":")
            code = parts[1]
            await client.get(f"{SMS_API_URL}?api_key={SMS_API_KEY}&action=setStatus&status=6&id={order_id}", headers=GRIZZLY_HEADERS)
            return {"status": "received", "code": code}
        return {"status": "waiting"}

@app.post("/api/cancel/{order_id}")
async def cancel_order(order_id: str, price: float, user_id: str = "demo_user"):
    async with AsyncSession() as client:
        url = f"{SMS_API_URL}?api_key={SMS_API_KEY}&action=setStatus&status=8&id={order_id}"
        resp = await client.get(url, headers=GRIZZLY_HEADERS)
        if "ACCESS_CANCEL" in resp.text:
            u = await client.get(f"{SB_URL}/rest/v1/users?user_id=eq.{user_id}", headers=SB_HEADERS)
            user_row = first_item(u.json()) if u.status_code == 200 else None
            bal = float(user_row.get("balance", 0.0)) if user_row else 0.0
            new_bal = round(bal + price, 2)
            await client.patch(f"{SB_URL}/rest/v1/users?user_id=eq.{user_id}", json={"balance": new_bal}, headers=SB_HEADERS)
            return {"status": "ok", "balance": new_bal}
        return {"status": "error", "message": f"Не удалось отменить: {resp.text}"}
