import os
import random
import string
from curl_cffi.requests import AsyncSession
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI()

# ================= НАСТРОЙКИ =================
SMS_API_KEY = "1b8d7cc1c33d18031A4b81e7152fAd02"
BASE_API_URL = "https://hero-sms.com"
ADMIN_SECRET = "admin123"
MARKUP = 1.5

SB_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SB_KEY = os.environ.get("SUPABASE_ANON_KEY", "")

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

SB_HEADERS = {
    "apikey": SB_KEY,
    "Authorization": f"Bearer {SB_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

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
            if r.status_code == 200 and r.json():
                bal = float(r.json()[0]["balance"])
            elif r.status_code == 200:
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
        if r.status_code == 200 and r.json():
            amount = float(r.json()[0]["amount"])
            await client.delete(f"{SB_URL}/rest/v1/promocodes?code=eq.{code}", headers=SB_HEADERS)
            u = await client.get(f"{SB_URL}/rest/v1/users?user_id=eq.{user_id}", headers=SB_HEADERS)
            cur_bal = float(u.json()[0]["balance"]) if (u.status_code == 200 and u.json()) else 0.0
            new_bal = round(cur_bal + amount, 2)
            if u.status_code == 200 and u.json():
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
        bal = float(u.json()[0]["balance"]) if (u.status_code == 200 and u.json()) else 0.0
        if bal < price:
            return {"status": "error", "message": "Недостаточно средств на балансе!"}

        payload = {"service": service, "country": country, "amount": 1}
        resp = await client.post(f"{BASE_API_URL}/activations", json=payload, headers=API_HEADERS, cookies=COOKIES)
        if resp.status_code == 200:
            items = resp.json().get("data", [])
            if items:
                activation = items[0]
                order_id = str(activation["id"])
                phone = str(activation["phone"])
                new_bal = round(bal - price, 2)
                await client.patch(f"{SB_URL}/rest/v1/users?user_id=eq.{user_id}", json={"balance": new_bal}, headers=SB_HEADERS)
                formatted_phone = f"+{phone}" if not phone.startswith("+") else phone
                return {"status": "ok", "order_id": order_id, "phone": formatted_phone, "balance": new_bal}
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
            u = await client.get(f"{SB_URL}/rest/v1/users?user_id=eq.{user_id}", headers=SB_HEADERS)
            bal = float(u.json()[0]["balance"]) if (u.status_code == 200 and u.json()) else 0.0
            new_bal = round(bal + price, 2)
            await client.patch(f"{SB_URL}/rest/v1/users?user_id=eq.{user_id}", json={"balance": new_bal}, headers=SB_HEADERS)
            return {"status": "ok", "balance": new_bal}
        return {"status": "error", "message": f"Не удалось отменить ({resp.status_code}): {resp.text}"}
