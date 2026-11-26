from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_arrival_message_has_order_specific_webapp_payment_button():
    source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert 'InlineKeyboardButton(text="💳 To‘lovni yakunlash"' in source
    assert 'order_url=f"{WEBAPP_URL}{separator}order_id={order_id}"' in source
    assert 'if due>0:' in source


def test_mini_app_opens_requested_order_and_highlights_it():
    source = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert 'new URLSearchParams(window.location.search).get(\'order_id\')' in source
    assert 'show(\'orders\');await loadOrders(Number(requestedOrder))' in source
    assert 'id="order-card-${o.id}"' in source
