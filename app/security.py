import hashlib, hmac, json, time
from urllib.parse import parse_qsl
from fastapi import HTTPException
from app.config import BOT_TOKEN

def verify_init_data(init_data: str, max_age: int = 86400) -> dict:
    if not BOT_TOKEN or not init_data:
        raise HTTPException(401, "Telegram sessiyasi topilmadi")
    data = dict(parse_qsl(init_data, keep_blank_values=True))
    received = data.pop("hash", None)
    if not received:
        raise HTTPException(401, "initData hash yo'q")
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calculated = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated, received):
        raise HTTPException(401, "Telegram initData noto'g'ri")
    if time.time() - int(data.get("auth_date", "0")) > max_age:
        raise HTTPException(401, "Telegram sessiyasi eskirgan")
    try:
        return json.loads(data["user"])
    except Exception:
        raise HTTPException(401, "Telegram foydalanuvchisi aniqlanmadi")


def encrypt_secret(value: str) -> str:
    from cryptography.fernet import Fernet
    from app.config import FERNET_KEY
    if not FERNET_KEY:
        raise ValueError("FERNET_KEY .env faylida sozlanmagan")
    return Fernet(FERNET_KEY.encode()).encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    from cryptography.fernet import Fernet
    from app.config import FERNET_KEY
    if not FERNET_KEY:
        raise ValueError("FERNET_KEY .env faylida sozlanmagan")
    return Fernet(FERNET_KEY.encode()).decrypt(value.encode()).decode()
