from app.payment_parser import parse_notice

def test_user_supplied_bank_credit_notice():
    parsed = parse_notice("""🟢 Perevod na kartu
➕ 8 000.00 UZS
💳 ***2151
📍 AIT IPAK YULI BANKI CHILONZOR FILIALI, UZ
🕓 26.11.26 18:55
💵 34 289.33 UZS""")
    assert parsed["amount"] == 8000
    assert parsed["card4"] == "2151"
    assert parsed["transaction_id"].startswith("FP-")
    assert not parsed["manual_review"]

def test_gnk_cashback_is_not_customer_payment():
    assert parse_notice("""🟢 Perevod na kartu
➕ 1 692.65 UZS
💳 ***2151
📍 GNK CASHBACK, UZ
🕓 26.11.26 15:09
💵 31 289.33 UZS""") is None

def test_fractional_uzs_is_manual_review():
    parsed = parse_notice("""🟢 Perevod na kartu
➕ 1 692.65 UZS
💳 ***2151
📍 BANK, UZ
🕓 26.11.26 15:09
💵 31 289.33 UZS""")
    assert parsed["manual_review"] is True
