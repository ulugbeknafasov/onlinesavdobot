
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, Float, Boolean, DateTime, Text, ForeignKey, func, select
from app.config import DATABASE_URL

engine = create_async_engine(DATABASE_URL, echo=False)
Session = async_sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase): pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tg_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    username: Mapped[str] = mapped_column(String(100), default="")
    full_name: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str] = mapped_column(String(30), default="")
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    cash_balance: Mapped[int] = mapped_column(Integer, default=0)
    bonus_balance: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())

class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    price: Mapped[int] = mapped_column(Integer)
    old_price: Mapped[int] = mapped_column(Integer, default=0)
    image_url: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(100), default="Boshqa")
    stock: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class CartItem(Base):
    __tablename__ = "cart_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_tg_id: Mapped[int] = mapped_column(Integer, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    color: Mapped[str] = mapped_column(String(50), default="")
    size: Mapped[str] = mapped_column(String(30), default="")

class Branch(Base):
    __tablename__ = "branches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    address: Mapped[str] = mapped_column(String(300), default="")
    city: Mapped[str] = mapped_column(String(100), default="Toshkent")
    latitude: Mapped[float] = mapped_column(Float, default=0)
    longitude: Mapped[float] = mapped_column(Float, default=0)
    work_hours: Mapped[str] = mapped_column(String(120), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    branch_code: Mapped[str] = mapped_column(String(30), default="")
    landmark: Mapped[str] = mapped_column(String(250), default="")
    map_url: Mapped[str] = mapped_column(String(500), default="")
    video_url: Mapped[str] = mapped_column(String(500), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class UserBranch(Base):
    __tablename__ = "user_branches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_tg_id: Mapped[int] = mapped_column(Integer, index=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"))
    label: Mapped[str] = mapped_column(String(100), default="")

class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_tg_id: Mapped[int] = mapped_column(Integer, index=True)
    total: Mapped[int] = mapped_column(Integer)
    promo_code: Mapped[str] = mapped_column(String(40), default="")
    delivery_price: Mapped[int] = mapped_column(Integer, default=0)
    weight_kg: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(40), default="Yangi")
    payment_status: Mapped[str] = mapped_column(String(40), default="Kutilmoqda")
    payment_plan: Mapped[str] = mapped_column(String(20), default="100")
    address: Mapped[str] = mapped_column(Text, default="")
    wallet_used: Mapped[int] = mapped_column(Integer, default=0)
    cashback_used: Mapped[int] = mapped_column(Integer, default=0)
    card_due: Mapped[int] = mapped_column(Integer, default=0)
    remaining_due: Mapped[int] = mapped_column(Integer, default=0)
    second_payment_requested_at: Mapped[str] = mapped_column(DateTime(timezone=True), nullable=True)
    pickup_code: Mapped[str] = mapped_column(String(30), default="")
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    expected_amount: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), default="Kutilmoqda")
    transaction_id: Mapped[str] = mapped_column(String(120), unique=True, nullable=True)
    raw_message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
    confirmed_at: Mapped[str] = mapped_column(DateTime(timezone=True), nullable=True)

class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")

class Admin(Base):
    __tablename__ = "admins"
    tg_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    role: Mapped[str] = mapped_column(String(30), default="owner")
    added_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())



class Favorite(Base):
    __tablename__ = "favorites"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_tg_id: Mapped[int] = mapped_column(Integer, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)

class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_tg_id: Mapped[int] = mapped_column(Integer, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(Text, default="")
    moderation_status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    moderation_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())

class PromoCode(Base):
    __tablename__ = "promo_codes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    discount_percent: Mapped[int] = mapped_column(Integer, default=0)
    discount_amount: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    usage_limit: Mapped[int] = mapped_column(Integer, default=0)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[str] = mapped_column(DateTime(timezone=True), nullable=True)

class WalletLedger(Base):
    __tablename__ = "wallet_ledger"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_tg_id: Mapped[int] = mapped_column(Integer, index=True)
    amount: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(30))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())

class OrderLine(Base):
    __tablename__ = "order_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    product_id: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[int] = mapped_column(Integer)
    color: Mapped[str] = mapped_column(String(50), default="")
    size: Mapped[str] = mapped_column(String(30), default="")



class ProductVariant(Base):
    __tablename__ = "product_variants"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    color: Mapped[str] = mapped_column(String(50), default="")
    size: Mapped[str] = mapped_column(String(30), default="")
    stock: Mapped[int] = mapped_column(Integer, default=0)

class ProductMedia(Base):
    __tablename__ = "product_media"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    media_type: Mapped[str] = mapped_column(String(20), default="image")
    url: Mapped[str] = mapped_column(Text)

class Comparison(Base):
    __tablename__ = "comparisons"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_tg_id: Mapped[int] = mapped_column(Integer, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)

class Referral(Base):
    __tablename__ = "referrals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inviter_tg_id: Mapped[int] = mapped_column(Integer, index=True)
    invited_tg_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    bonus_paid: Mapped[bool] = mapped_column(Boolean, default=False)

class Shipment(Base):
    __tablename__ = "shipments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), unique=True, index=True)
    carrier: Mapped[str] = mapped_column(String(30), default="BTS")
    tracking_code: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[str] = mapped_column(String(100), default="Tayyorlanmoqda")
    estimated_date: Mapped[str] = mapped_column(String(40), default="")
    delivery_price: Mapped[int] = mapped_column(Integer, default=0)
    pickup_code: Mapped[str] = mapped_column(String(30), default="")
    photo_url: Mapped[str] = mapped_column(String(500), default="")
    bts_message: Mapped[str] = mapped_column(String(3000), default="")
    updated_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class BTSTariff(Base):
    __tablename__ = "bts_tariffs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    origin_city: Mapped[str] = mapped_column(String(100), index=True)
    destination_city: Mapped[str] = mapped_column(String(100), index=True)
    kg_min: Mapped[int] = mapped_column(Integer, default=1)
    kg_max: Mapped[int] = mapped_column(Integer, default=20)
    price: Mapped[int] = mapped_column(Integer)
    delivery_days: Mapped[int] = mapped_column(Integer, default=1)
    tariff_type: Mapped[str] = mapped_column(String(40), default="office_to_office")
    zone: Mapped[int] = mapped_column(Integer, default=0)
    effective_from: Mapped[str] = mapped_column(String(20), default="2026-09-01")
    vat_included: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

class SupportMessage(Base):
    __tablename__ = "support_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_tg_id: Mapped[int] = mapped_column(Integer, index=True)
    order_id: Mapped[int] = mapped_column(Integer, nullable=True)
    sender_role: Mapped[str] = mapped_column(String(20), default="user")
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_tg_id: Mapped[int] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(100))
    target: Mapped[str] = mapped_column(String(120), default="")
    details: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Backward-compatible SQLite migration for databases created by earlier starter versions.
        if DATABASE_URL.startswith("sqlite"):
            result = await conn.exec_driver_sql("PRAGMA table_info(orders)")
            cols = {r[1] for r in result.fetchall()}
            if "cashback_used" not in cols:
                await conn.exec_driver_sql("ALTER TABLE orders ADD COLUMN cashback_used INTEGER NOT NULL DEFAULT 0")
            if "wallet_used" not in cols:
                await conn.exec_driver_sql("ALTER TABLE orders ADD COLUMN wallet_used INTEGER NOT NULL DEFAULT 0")
            if "card_due" not in cols:
                await conn.exec_driver_sql("ALTER TABLE orders ADD COLUMN card_due INTEGER NOT NULL DEFAULT 0")
            if "remaining_due" not in cols:
                await conn.exec_driver_sql("ALTER TABLE orders ADD COLUMN remaining_due INTEGER NOT NULL DEFAULT 0")
            if "delivery_price" not in cols:
                await conn.exec_driver_sql("ALTER TABLE orders ADD COLUMN delivery_price INTEGER NOT NULL DEFAULT 0")
            if "weight_kg" not in cols:
                await conn.exec_driver_sql("ALTER TABLE orders ADD COLUMN weight_kg INTEGER NOT NULL DEFAULT 0")
            if "second_payment_requested_at" not in cols:
                await conn.exec_driver_sql("ALTER TABLE orders ADD COLUMN second_payment_requested_at DATETIME")
            if "pickup_code" not in cols:
                await conn.exec_driver_sql("ALTER TABLE orders ADD COLUMN pickup_code VARCHAR(30) NOT NULL DEFAULT ''")
            result = await conn.exec_driver_sql("PRAGMA table_info(orders)")
            order_cols = {row[1] for row in result.fetchall()}
            if "promo_code" not in order_cols:
                await conn.exec_driver_sql("ALTER TABLE orders ADD COLUMN promo_code VARCHAR(40) NOT NULL DEFAULT ''")
            result = await conn.exec_driver_sql("PRAGMA table_info(shipments)")
            shipment_cols = {row[1] for row in result.fetchall()}
            if "bts_message" not in shipment_cols:
                await conn.exec_driver_sql("ALTER TABLE shipments ADD COLUMN bts_message VARCHAR(3000) NOT NULL DEFAULT ''")
            result = await conn.exec_driver_sql("PRAGMA table_info(bts_tariffs)")
            tariff_cols = {row[1] for row in result.fetchall()}
            for col, ddl in {
                "tariff_type": "ALTER TABLE bts_tariffs ADD COLUMN tariff_type VARCHAR(40) NOT NULL DEFAULT 'office_to_office'",
                "zone": "ALTER TABLE bts_tariffs ADD COLUMN zone INTEGER NOT NULL DEFAULT 0",
                "effective_from": "ALTER TABLE bts_tariffs ADD COLUMN effective_from VARCHAR(20) NOT NULL DEFAULT '2026-09-01'",
                "vat_included": "ALTER TABLE bts_tariffs ADD COLUMN vat_included BOOLEAN NOT NULL DEFAULT 1",
            }.items():
                if col not in tariff_cols:
                    await conn.exec_driver_sql(ddl)
            result = await conn.exec_driver_sql("PRAGMA table_info(bts_tariffs)")
            tariff_cols = {row[1] for row in result.fetchall()}
            for col, ddl in {
                "tariff_type": "ALTER TABLE bts_tariffs ADD COLUMN tariff_type VARCHAR(40) NOT NULL DEFAULT 'office_to_office'",
                "zone": "ALTER TABLE bts_tariffs ADD COLUMN zone INTEGER NOT NULL DEFAULT 0",
                "effective_from": "ALTER TABLE bts_tariffs ADD COLUMN effective_from VARCHAR(20) NOT NULL DEFAULT '2026-09-01'",
                "vat_included": "ALTER TABLE bts_tariffs ADD COLUMN vat_included BOOLEAN NOT NULL DEFAULT 1",
            }.items():
                if col not in tariff_cols:
                    await conn.exec_driver_sql(ddl)
            result = await conn.exec_driver_sql("PRAGMA table_info(shipments)")
            shipment_cols = {r[1] for r in result.fetchall()}
            if "photo_url" not in shipment_cols:
                await conn.exec_driver_sql("ALTER TABLE shipments ADD COLUMN photo_url VARCHAR(500) NOT NULL DEFAULT ''")
            result = await conn.exec_driver_sql("PRAGMA table_info(reviews)")
            review_cols = {r[1] for r in result.fetchall()}
            if "moderation_status" not in review_cols:
                await conn.exec_driver_sql("ALTER TABLE reviews ADD COLUMN moderation_status VARCHAR(20) NOT NULL DEFAULT 'pending'")
            if "moderation_note" not in review_cols:
                await conn.exec_driver_sql("ALTER TABLE reviews ADD COLUMN moderation_note TEXT NOT NULL DEFAULT ''")
            result = await conn.exec_driver_sql("PRAGMA table_info(admins)")
            admin_cols = {r[1] for r in result.fetchall()}
            if "role" not in admin_cols:
                await conn.exec_driver_sql("ALTER TABLE admins ADD COLUMN role VARCHAR(30) NOT NULL DEFAULT 'owner'")
            result = await conn.exec_driver_sql("PRAGMA table_info(branches)")
            branch_cols = {r[1] for r in result.fetchall()}
            for col, ddl in {
                "latitude": "ALTER TABLE branches ADD COLUMN latitude FLOAT NOT NULL DEFAULT 0",
                "longitude": "ALTER TABLE branches ADD COLUMN longitude FLOAT NOT NULL DEFAULT 0",
                "work_hours": "ALTER TABLE branches ADD COLUMN work_hours VARCHAR(120) NOT NULL DEFAULT ''",
                "phone": "ALTER TABLE branches ADD COLUMN phone VARCHAR(40) NOT NULL DEFAULT ''",
                "branch_code": "ALTER TABLE branches ADD COLUMN branch_code VARCHAR(30) NOT NULL DEFAULT ''",
                "landmark": "ALTER TABLE branches ADD COLUMN landmark VARCHAR(250) NOT NULL DEFAULT ''",
                "map_url": "ALTER TABLE branches ADD COLUMN map_url VARCHAR(500) NOT NULL DEFAULT ''",
                "video_url": "ALTER TABLE branches ADD COLUMN video_url VARCHAR(500) NOT NULL DEFAULT ''",
            }.items():
                if col not in branch_cols:
                    await conn.exec_driver_sql(ddl)
    async with Session() as s:
        demo = await s.scalar(select(Product.id).limit(1))
        if demo is None:
            s.add_all([
                Product(title="Oversize hoodie", description="Yumshoq mato, kundalik uslub", price=319000, old_price=399000, category="Erkaklar", stock=20, image_url=""),
                Product(title="Basic futbolka", description="Paxtali, qulay fason", price=99000, category="Erkaklar", stock=35),
                Product(title="Jinsi shim", description="Kundalik klassik model", price=229000, category="Ayollar", stock=15),
            ])
        # BTS Uzbekistan offices are seeded from the user-provided official directory CSV by app.main.
        await s.commit()


class InventoryReservation(Base):
    __tablename__ = "inventory_reservations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    product_id: Mapped[int] = mapped_column(Integer, index=True)
    variant_id: Mapped[int] = mapped_column(Integer, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="held", index=True)
    expires_at: Mapped[str] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())

class RefundRequest(Base):
    __tablename__ = "refund_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    user_tg_id: Mapped[int] = mapped_column(Integer, index=True)
    amount: Mapped[int] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String(20), default="wallet")
    status: Mapped[str] = mapped_column(String(30), default="pending")
    reason: Mapped[str] = mapped_column(Text, default="")
    admin_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[str] = mapped_column(DateTime(timezone=True), nullable=True)

class ScheduledChannelPost(Base):
    __tablename__ = "scheduled_channel_posts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[str] = mapped_column(String(120))
    message: Mapped[str] = mapped_column(Text)
    scheduled_at: Mapped[str] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    error: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
