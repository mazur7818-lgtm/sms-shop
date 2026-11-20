import random
import string
from curl_cffi.requests import AsyncSession
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI()

# ================= НАСТРОЙКИ =================
SMS_API_KEY = "1b8d7cc1c33d18031A4b81e7152fAd02"
BASE_API_URL = "https://hero-sms.com/api/v1"
ADMIN_SECRET = "admin123"
MARKUP = 1.5

# Кука защиты Cloudflare из твоего браузера
CF_COOKIE = "Cv7CEVdQVA15xbZ_AO5xVhUnbCH22tdnVRnv9s5oheLJ1NJ42UEs1elf5ylh4o3Xw8k9TU1S2oVgAw1lAQyFG_P2XqWBBv6cFWD6u4qNf9SCj3ypHf6K73BoQlUORq8OWTH_jjTevzRBJfJtelNOnykjJMWu14i1Vj5PIX-1AZlCaYZ67zFCHBpNeLsNxO-vUeVFcuTzkgXhAJDkQjuA4l_Fg44dEAeKBWjSv31-bUcVnbM-tIu4kG6lq8fqsjwGC43A6XL8BXZD3GMzGHp9cJ3F3rDEYDQU8vhDguS2chIeaI-I2Ezm"
# =============================================

API_HEADERS = {
    "Authorization": f"ApiKey {SMS_API_KEY}",
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": "https://hero-sms.com",
    "Referer": "https://hero-sms.com/ru/api",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36"
}

COOKIES = {"cf_clearance": CF_COOKIE}

user_balances = {"demo_user": 0.0}
promocodes = {"TEST1": 1.00}

@app.get("/", response_class=HTMLResponse)
async def index():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/api/init")
async def init_data():
    items = [
        {"id": "tg", "name": "Telegram", "country": 6, "country_name": "Индонезия (дешево)", "base_price": 0.25},
        {"id": "tg", "name": "Telegram", "country": 187, "country_name": "США", "base_price": 0.60},
        {"id": "wa", "name": "WhatsApp", "country": 6, "country_name": "Индонезия", "base_price": 0.30},
        {"id": "go", "name": "Google / YouTube", "country": 16, "country_name": "Великобритания", "base_price": 0.35},
        {"id": "ig", "name": "Instagram", "country": 22, "country_name": "Индия", "base_price": 0.15},
    ]
    for item in items:
        item["price"] = round(item["base_price"] * MARKUP, 2)
    return {"balance": round(user_balances["demo_user"], 2), "services": items}

@app.post("/api/redeem")
async def redeem_promo(code: str):
    code = code.strip().upper()
    if code in promocodes:
        amount = promocodes.pop(code)
        user_balances["demo_user"] += amount
        return {"status": "ok", "added": amount, "balance": round(user_balances["demo_user"], 2)}
    return {"status": "error", "message": "Неверный или уже использованный промокод"}

@app.get("/api/admin/create-promo")
async def create_promo(secret: str, amount: float):
    if secret != ADMIN_SECRET:
        return {"status": "error", "message": "Неверный пароль админа"}
    new_code = "SMS-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    promocodes[new_code] = amount
    return {"status": "ok", "promo_code": new_code, "amount": amount}

@app.post("/api/order")
async def create_order(service: str, country: int, price: float):
    if user_balances["demo_user"] < price:
        return {"status": "error", "message": "Недостаточно средств на балансе. Введите промокод TEST1 вверху!"}

    payload = {
        "service": service,
        "country": country,
        "amount": 1
    }
    async with AsyncSession() as client:
        resp = await client.post(f"{BASE_API_URL}/activations", json=payload, headers=API_HEADERS, cookies=COOKIES)
        
        if resp.status_code == 200:
            res_json = resp.json()
            items = res_json.get("data", [])
            if items:
                activation = items
                order_id = str(activation["id"])
                phone = str(activation["phone"])
                user_balances["demo_user"] -= price
                formatted_phone = f"+{phone}" if not phone.startswith("+") else phone
                return {
                    "status": "ok",
                    "order_id": order_id,
                    "phone": formatted_phone,
                    "balance": round(user_balances["demo_user"], 2)
                }
        return {"status": "error", "message": f"Ответ API ({resp.status_code}): {resp.text}"}

@app.get("/api/status/{order_id}")
async def check_status(order_id: str):
    async with AsyncSession() as client:
        resp = await client.get(f"{BASE_API_URL}/activations/{order_id}/otp", headers=API_HEADERS, cookies=COOKIES)
        if resp.status_code == 200:
            res_json = resp.json()
            otp_list = res_json.get("data", [])
            if isinstance(otp_list, list) and len(otp_list) > 0:
                code = otp_list[-1].get("smsCode")
                if code:
                    return {"status": "received", "code": code}
            elif isinstance(otp_list, dict) and otp_list.get("smsCode"):
                return {"status": "received", "code": otp_list["smsCode"]}
        return {"status": "waiting"}

@app.post("/api/cancel/{order_id}")
async def cancel_order(order_id: str, price: float):
    async with AsyncSession() as client:
        resp = await client.delete(f"{BASE_API_URL}/activations/{order_id}", headers=API_HEADERS, cookies=COOKIES)
        if resp.status_code in (200, 204):
            user_balances["demo_user"] += price
            return {"status": "ok", "balance": round(user_balances["demo_user"], 2)}
        return {"status": "error", "message": f"Не удалось отменить ({resp.status_code}): {resp.text}"}
