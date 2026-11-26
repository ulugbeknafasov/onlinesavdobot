"""Pure parser for BTS Telegram arrival notifications."""
import re
PARCEL_RE = re.compile(r"\bID\s*:\s*([A-Za-z0-9-]{6,40})", re.I)
CODE_RE = re.compile(r"(?:Qabul qilish uchun\s*KOD|KOD)\s*:\s*([A-Za-z0-9-]{3,20})", re.I)
ADDRESS_RE = re.compile(r"Manzil\s*:\s*(.+?)(?=\s+https?://|\s+T-n:|$)", re.I)
URL_RE = re.compile(r"https?://\S+", re.I)

def parse_bts_message(text):
    text = text or ""
    parcel = PARCEL_RE.search(text)
    if not parcel: return None
    code, address, url = CODE_RE.search(text), ADDRESS_RE.search(text), URL_RE.search(text)
    return {"parcel_id": parcel.group(1), "pickup_code": code.group(1) if code else "",
            "address": address.group(1).strip() if address else "",
            "url": url.group(0) if url else "", "raw_message": text[:3000]}
