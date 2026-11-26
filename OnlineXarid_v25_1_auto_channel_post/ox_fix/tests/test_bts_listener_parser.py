from app.bts_message_parser import parse_bts_message


def test_parse_bts_sms_fields():
    sample = "BTS_UZ: Sizga pochta keldi. ID: 012016324829 Qabul qilish uchun KOD: 21810 Manzil: Beruniy k 20-uy https://bts.uz/p/zyxzyrqxwaxb T-n: 1230"
    result = parse_bts_message(sample)
    assert result["parcel_id"] == "012016324829"
    assert result["pickup_code"] == "21810"
    assert result["address"] == "Beruniy k 20-uy"
    assert result["url"] == "https://bts.uz/p/zyxzyrqxwaxb"


def test_unmatched_text_has_no_parcel_id():
    assert parse_bts_message("Salom, pochta haqida ma'lumot") is None


def test_parser_keeps_leading_zero_in_parcel_id():
    result = parse_bts_message("ID: 001234567890 KOD: 98765 Manzil: Toshkent https://bts.uz/p/abc")
    assert result["parcel_id"] == "001234567890"


def test_parser_handles_missing_optional_fields():
    result = parse_bts_message("BTS_UZ: Sizga pochta keldi. ID: 012016324705")
    assert result["parcel_id"] == "012016324705"
    assert result["pickup_code"] == ""
    assert result["address"] == ""
    assert result["url"] == ""
