web: uvicorn app.main:app --host 0.0.0.0 --port $PORT
worker: python -m app.payment_listener
bts: python -m app.bts_listener
backup: python -m app.backup
