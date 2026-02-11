# database.py
import aiosqlite
import logging
import os
from datetime import datetime

# Путь к БД
DB_NAME = "barbershop.db"
logger = logging.getLogger(__name__)


async def ensure_connection():
    """Проверка соединения и включение WAL режима для скорости."""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.commit()


async def init_db():
    """Создание всех таблиц в одном месте."""
    async with aiosqlite.connect(DB_NAME) as db:
        # 1. Таблица Users
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name INTEGER NOT NULL,
                any_service TEXT,
                my_book TEXT,
                crypto_invoice TEXT,
                crypto_adress TEXT,
                any_barber TEXT,
                choose TEXT,
                chat_id INTEGER
            )
        """)
        
        # 2. Таблица Barbers
        await db.execute("""
            CREATE TABLE IF NOT EXISTS barbers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                work_start TEXT NOT NULL DEFAULT '10:00',
                work_end TEXT NOT NULL DEFAULT '22:00',
                telegram_usrname TEXT NOT NULL,
                telegram_number INTEGER NOT NULL,
                telegram_id INTEGER NOT NULL
            )
        """)
        
        # 3. Таблица Services
        await db.execute("""
            CREATE TABLE IF NOT EXISTS services (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                price INTEGER,
                duration INTEGER NOT NULL
            )
        """)
        
        # 4. Таблица Barber Services (связь)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS barber_services (
                barber_id INTEGER NOT NULL REFERENCES barbers(id) ON DELETE CASCADE,
                service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
                PRIMARY KEY (barber_id, service_id)
            )
        """)
        
        # 5. Таблица Bookings
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usr_id INTEGER NOT NULL,
                barber_id INTEGER NOT NULL,
                service_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                barber_name TEXT NOT NULL,
                service_name TEXT NOT NULL,
                condition TEXT NOT NULL,
                price INTEGER NOT NULL,
                duration INTEGER NOT NULL,
                sent INTEGER DEFAULT 0,
                type TEXT NOT NULL,
                timestamp_date INTEGER NOT NULL,
                telegram_payment_charge_id TEXT DEFAULT NULL,
                crypto_invoice TEXT DEFAULT NULL,
                crypto_bot_url TEXT DEFAULT NULL,
                crypto_status TEXT DEFAULT 'pending',
                paid_think TEXT DEFAULT NULL,
                book_for TEXT DEFAULT NULL,
                google_event_id TEXT,
                FOREIGN KEY (barber_id) REFERENCES barbers(id),
                FOREIGN KEY (service_id) REFERENCES services(id)
            )
        """)
        
        # 6. Таблицы для Админки (Off days, Extra hours)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS off_days (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                barber_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                UNIQUE(barber_id, date),
                FOREIGN KEY (barber_id) REFERENCES barbers(id) ON DELETE CASCADE
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS extra_hours (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                barber_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                duration INTEGER NOT NULL,
                FOREIGN KEY (barber_id) REFERENCES barbers(id) ON DELETE CASCADE,
                UNIQUE(barber_id, date, start_time, end_time)
            )
        """)
        
        try:
            await db.execute("ALTER TABLE barbers ADD COLUMN reminders INTEGER DEFAULT 1")
        except Exception:
            pass
        
        # Заполнение данными по умолчанию (если пусто)
        await _seed_data(db)
        
        await db.commit()
        logger.info("База данных инициализирована.")


async def _seed_data(db):
    """Заполнение начальными данными"""
    # Сервисы
    await db.execute("INSERT OR IGNORE INTO services (name, price, duration) VALUES ('💈 Стрижка', 2000, 60), ('✂️ Окрашивание', 5000, 90), ('💈 Бритьё с мойкой', 1000, 30)")
    
    # Барберы (Пример)
    await db.execute("INSERT OR IGNORE INTO barbers (name, telegram_usrname, telegram_number, telegram_id) VALUES"
                     " ('Иван','MatSadovskiy',380507509240,620994031),('Пётр','MatSadovskiy',380507509240,620994031),('Алексей','MatSadovskiy',380507509240,620994031),"
                     "('Дмитрий','MatSadovskiy',380507509240,620994031),('Сергей','MatSadovskiy',380507509240,620994031)")

    # Связи (Пример для Ивана id=1)
    await db.execute("INSERT OR IGNORE INTO barber_services (barber_id, service_id) VALUES (1,1),(1,3),(2,1),(2,2),(3,2),(3,3),(4,1),(4,2),(4,3),(5,3)")


# --- УНИВЕРСАЛЬНЫЕ МЕТОДЫ (Используй их в ботах) ---

async def fetch_one(query: str, params: tuple = ()):
    """Возвращает одну строку или None"""
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row  # Позволяет обращаться по именам колонок, если нужно
        async with db.execute(query, params) as cursor:
            row = await cursor.fetchone()
            # Возвращаем кортеж для совместимости со старым кодом, или None
            return tuple(row) if row else None


async def fetch_all(query: str, params: tuple = ()):
    """Возвращает список строк"""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return rows


async def execute(query: str, params: tuple = ()):
    """Выполняет запрос (INSERT, UPDATE, DELETE) и возвращает lastrowid"""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        async with db.execute(query, params) as cursor:
            await db.commit()
            return cursor.lastrowid


async def execute_script(script: str):
    """Выполняет SQL скрипт"""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.executescript(script)
        await db.commit()


# Метод для Vacuum и обслуживания
async def vacuum_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("VACUUM")