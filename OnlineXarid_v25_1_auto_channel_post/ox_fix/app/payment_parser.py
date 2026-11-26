import re

def parse_notice(text):
    """Parse supported card-credit notification formats.

    Supports the supplied Uzbek/Russian notice:
      🟢 Perevod na kartu
      ➕ 8 000.00 UZS
      💳 ***2151
      📍 BANK, UZ
      🕓 26.11.26 18:55
      💵 34 289.33 UZS

    GNK CASHBACK is deliberately excluded from customer payment matching.
    If a provider transaction id is absent, a deterministic message fingerprint
    is used for deduplication; this is not a bank-side transaction reference.
    """
    import hashlib
    if not text:
        return None
    upper = text.upper()
    if "GNK CASHBACK" in upper or "CASHBACK" in upper:
        return None
    # Never accept an outgoing transfer. The supplied format uses a green
    # incoming marker and a plus sign before the credited amount.
    if re.search(r"(chiqim|списан|перевод отправлен|outgoing|debit|➖)", text, re.I):
        return None
    incoming = bool(re.search(r"(➕|kirim|поступлен|зачислен|incoming|credit|perevod na kartu)", text, re.I))
    if not incoming:
        return None
    amount_match = re.search(
        r"(?:➕|kirim|поступлен[оиея]?|зачислен[оиея]?|incoming|credit)[^\d]{0,24}"
        r"([\d][\d ]*(?:[.,]\d{1,2})?)\s*(?:UZS|so['’]?m|сум)?",
        text, re.I
    )
    if not amount_match:
        return None
    raw_amount = amount_match.group(1).replace(" ", "").replace(",", ".")
    try:
        from decimal import Decimal
        amount_decimal = Decimal(raw_amount)
    except Exception:
        return None
    if amount_decimal <= 0:
        return None
    # The current DB stores expected UZS amounts as integer so'm. Fractional
    # amounts are not auto-confirmed; they need manual review, not rounding.
    if amount_decimal != amount_decimal.to_integral_value():
        return {"amount": None, "transaction_id": "", "card4": "", "manual_review": True,
                "reason": "Kasrli UZS summasi; integer to‘lov bilan avtomatik moslashtirib bo‘lmaydi"}
    amount = int(amount_decimal)
    card = re.search(r"(?:\*{2,}|x{2,}|•{2,}|…)(\d{4})", text, re.I)
    if not card:
        return None
    tx = re.search(r"(?:RRN|ref(?:erence)?|tranzaksiya|transaction|операци[яи]|ID)[\s:#№-]*([A-Za-z0-9-]{5,})", text, re.I)
    if tx:
        txid = tx.group(1)
    else:
        # Stable fingerprint: duplicate delivery of the same notification
        # produces the same key. It cannot prove uniqueness at the bank.
        normalized = re.sub(r"\s+", " ", text.strip()).casefold()
        txid = "FP-" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:48]
    return {"amount": amount, "transaction_id": txid, "card4": card.group(1),
            "manual_review": False, "reason": ""}

