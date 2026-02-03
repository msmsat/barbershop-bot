# services.py
import asyncio
import logging
import math
import re
import os
import aiohttp
import requests
from datetime import datetime, date, timedelta, time
from typing import Optional, List, Tuple, Union, Dict, Set

import database
import GoogleCalendar
from dotenv import load_dotenv

load_dotenv()

# --- КОНФИГУРАЦИЯ ---
CRYPTOPAY_TOKEN = os.getenv("CRYPTOPAY_TOKEN")
CRYPTOPAY_BASE = "https://testnet-pay.crypt.bot"
ADMIN_IDS_STR = os.getenv("ADMIN_IDS", "")
ADMINS = [int(x) for x in ADMIN_IDS_STR.split(",") if x]

logger = logging.getLogger(__name__)


# ==============================================================================
# 1. ОБЩИЕ УТИЛИТЫ (TIME & FORMATTING)
# ==============================================================================

def str_to_time(t: str) -> datetime:
    """Преобразует строку 'HH:MM' в объект datetime (дата игнорируется)."""
    return datetime.strptime(t, "%H:%M")


def time_to_str(dt: Union[datetime, time]) -> str:
    """Преобразует datetime или time в строку 'HH:MM'."""
    return dt.strftime("%H:%M")


def format_rub(amount: Union[int, float]) -> str:
    """Форматирует сумму в рубли."""
    try:
        return f"{int(amount)}₽"
    except Exception:
        return str(amount)


def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь администратором."""
    return user_id in ADMINS


# ==============================================================================
# 2. СЕРВИСЫ ПОЛЬЗОВАТЕЛЕЙ И БАРБЕРОВ (AUTH & INFO)
# ==============================================================================

async def get_barber_by_telegram_user(tg_id: int, username: Optional[str] = None) -> Optional[Tuple[int, str]]:
    """
    Возвращает (id, name) барбера по Telegram ID или Username.
    """
    try:
        # Поиск по ID
        res = await database.fetch_one("SELECT id, name FROM barbers WHERE telegram_id = ?", (tg_id,))
        if res:
            return res

        # Поиск по username (если ID не найден)
        if username:
            cleaned_username = username.replace("@", "")
            res = await database.fetch_one(
                "SELECT id, name FROM barbers WHERE telegram_usrname = ? OR telegram_usrname = ?",
                (cleaned_username, f"@{cleaned_username}")
            )
            return res
    except Exception as e:
        logger.error(f"Error finding barber: {e}")
    return None


async def create_barber(name: str, tg_id: Optional[int], phone: str, username: Optional[str]) -> None:
    """Создает нового барбера в БД."""
    await database.execute(
        "INSERT INTO barbers (name, telegram_id, telegram_number, telegram_usrname) VALUES (?, ?, ?, ?)",
        (name, tg_id, phone, username)
    )


async def count_offdays_in_next_6_months(barber_id: int, current_date: Optional[date] = None) -> int:
    """Считает количество выходных в текущем полугодии."""
    d = current_date or date.today()
    year = d.year
    if d.month <= 6:
        start, end = date(year, 1, 1), date(year, 6, 30)
    else:
        start, end = date(year, 7, 1), date(year, 12, 31)

    res = await database.fetch_one(
        "SELECT COUNT(*) FROM off_days WHERE barber_id = ? AND date BETWEEN ? AND ?",
        (barber_id, start.isoformat(), end.isoformat())
    )
    return int(res[0]) if res else 0


# ==============================================================================
# 3. СЕРВИСЫ БРОНИРОВАНИЯ (SLOTS & BOOKING)
# ==============================================================================

async def get_free_slots(
        barber_id: int,
        date_d: date,
        service_duration: int,
        service_id: Optional[int] = None
) -> List[str]:
    """
    Рассчитывает свободные слоты времени для записи.
    Поддерживает логику "Любой барбер" (barber_id=-1).
    """
    free_slots = set()

    # Определение списка барберов
    if barber_id == -1:
        if service_id is None:
            raise ValueError("Service ID required for 'Any' barber check")
        rows = await database.fetch_all(
            "SELECT b.id FROM barbers b JOIN barber_services bs ON b.id = bs.barber_id WHERE bs.service_id = ?",
            (service_id,)
        )
        barber_ids = [row[0] for row in rows]
    else:
        barber_ids = [barber_id]

    now = datetime.now()
    today_date = now.date()
    is_today = (date_d == today_date)

    # Вычисление минимального времени старта (через час, округленно до 30 мин)
    min_start_time = None
    if is_today:
        min_start = now + timedelta(hours=1)
        minutes_to_next = (30 - min_start.minute % 30) % 30
        if minutes_to_next == 0 and (min_start.second > 0 or min_start.microsecond > 0):
            minutes_to_next = 30
        min_start += timedelta(minutes=minutes_to_next)
        min_start = min_start.replace(second=0, microsecond=0)
        min_start_time = min_start.time()

    service_delta = timedelta(minutes=service_duration)
    step_delta = timedelta(minutes=30)

    for bid in barber_ids:
        # Пропуск, если у барбера выходной
        off_day = await database.fetch_one("SELECT id FROM off_days WHERE barber_id = ? AND date = ?",
                                           (bid, date_d.isoformat()))
        if off_day:
            continue

        # Рабочее время
        w_row = await database.fetch_one("SELECT work_start, work_end FROM barbers WHERE id=?", (bid,))
        if not w_row: continue
        work_start, work_end = map(str_to_time, w_row)

        # Существующие брони
        b_rows = await database.fetch_all(
            "SELECT start_time, end_time FROM bookings WHERE barber_id=? AND date=?",
            (bid, date_d.isoformat())
        )
        bookings = [(str_to_time(s), str_to_time(e)) for s, e in b_rows]

        # Перебор слотов
        current_t = work_start
        while current_t + service_delta <= work_end:
            # Проверка на прошедшее время сегодня
            if is_today and min_start_time and current_t.time() < min_start_time:
                current_t += step_delta
                continue

            # Проверка пересечений
            overlap = False
            slot_end = current_t + service_delta
            for bs, be in bookings:
                # Если слот пересекается с бронью (не заканчивается до начала брони И не начинается после конца брони)
                if not (slot_end <= bs or current_t >= be):
                    overlap = True
                    break

            if not overlap:
                free_slots.add(time_to_str(current_t))

            current_t += step_delta

    return sorted(list(free_slots))


async def get_available_barbers_for_slot(
        service_id: int,
        date_d: date,
        start_time_str: str,
        duration: int
) -> List[Tuple[int, str]]:
    """Возвращает список барберов, свободных в конкретный слот."""
    start_time = str_to_time(start_time_str)
    end_time = start_time + timedelta(minutes=duration)
    date_iso = date_d.isoformat()

    barbers = await database.fetch_all(
        """SELECT b.id, b.name, b.work_start, b.work_end 
           FROM barbers b JOIN barber_services bs ON b.id = bs.barber_id 
           WHERE bs.service_id = ?""",
        (service_id,)
    )

    available = []
    for bid, name, ws_str, we_str in barbers:
        # Проверка выходного
        if await database.fetch_one("SELECT id FROM off_days WHERE barber_id = ? AND date = ?", (bid, date_iso)):
            continue

        ws, we = str_to_time(ws_str), str_to_time(we_str)
        if start_time < ws or end_time > we:
            continue

        # Проверка броней
        rows = await database.fetch_all(
            "SELECT start_time, end_time FROM bookings WHERE barber_id = ? AND date = ?",
            (bid, date_iso)
        )
        overlap = False
        for s_curr, e_curr in [(str_to_time(s), str_to_time(e)) for s, e in rows]:
            if not (end_time <= s_curr or start_time >= e_curr):
                overlap = True
                break

        if not overlap:
            available.append((bid, name))

    return available


async def create_booking(
        user_id: int,
        date_str: str,
        time_str: str,
        booking_type: str = 'book',
        paid_method: Optional[str] = None
) -> Tuple[Optional[date], Optional[str], Optional[str], Optional[int]]:
    """
    Основная функция создания брони.
    Возвращает: (date_obj, end_time_str, barber_name, booking_id) или (None,...) при ошибке.
    """
    # 1. Получаем предпочтения пользователя
    user_data = await database.fetch_one("SELECT any_barber, any_service FROM users WHERE name = ?", (user_id,))
    if not user_data:
        return None, None, None, None

    pref_barber_id, service_id = map(int, user_data)

    # 2. Данные услуги
    srv_data = await database.fetch_one("SELECT duration, price, name FROM services WHERE id = ?", (service_id,))
    if not srv_data:
        return None, None, None, None
    duration, price, service_name = srv_data
    duration = int(duration)

    date_d = date.fromisoformat(date_str)

    # 3. Выбор барбера (если -1, ищем свободного)
    final_barber_id = pref_barber_id
    if pref_barber_id == -1:
        # Пробуем найти первого доступного
        available = await get_available_barbers_for_slot(service_id, date_d, time_str, duration)
        if not available:
            return None, None, None, None
        final_barber_id = available[0][0]

    # 4. Финальная проверка слота
    free_slots = await get_free_slots(final_barber_id, date_d, duration)
    if time_str not in free_slots:
        return None, None, None, None

    # 5. Получаем инфо о барбере
    barber_info = await database.fetch_one("SELECT name, telegram_id FROM barbers WHERE id = ?", (final_barber_id,))
    barber_name, barber_tg_id = barber_info

    # 6. Расчет времени окончания и уведомлений
    start_dt = str_to_time(time_str)
    end_dt = start_dt + timedelta(minutes=duration)
    end_time_str = time_to_str(end_dt)

    full_dt = datetime.combine(date_d, start_dt.time())
    delta_hours = int((full_dt - datetime.now()).total_seconds() // 3600)

    type_cond = '24' if delta_hours > 26 else ('12' if delta_hours > 15 else ('3' if delta_hours > 5 else '0'))
    sent_cond = 1 if type_cond == '0' else 0

    # 7. Запись в БД
    booking_id = await database.execute(
        """INSERT INTO bookings 
           (usr_id, barber_id, service_id, date, start_time, end_time, barber_name, service_name, 
            condition, price, duration, type, sent, timestamp_date, paid_think) 
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, final_barber_id, service_id, date_str, time_str, end_time_str, barber_name, service_name,
         booking_type, price, duration, type_cond, sent_cond, int(full_dt.timestamp()), paid_method)
    )

    # 8. Создание в Google Calendar
    if booking_type in ['book', 'paid']:
        event_id = await GoogleCalendar.create_event(
            barber_name, service_name, f"User ID: {user_id}", date_str, time_str, duration, price
        )
        if event_id:
            await database.execute("UPDATE bookings SET google_event_id = ? WHERE id = ?", (event_id, booking_id))

    return date_d, end_time_str, barber_name, booking_id


async def delete_booking(booking_id: int) -> bool:
    """Удаляет бронь и связанное событие в календаре."""
    try:
        res = await database.fetch_one("SELECT google_event_id FROM bookings WHERE id = ?", (booking_id,))
        if res and res[0]:
            await GoogleCalendar.delete_event(res[0])
        await database.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
        return True
    except Exception as e:
        logger.error(f"Error deleting booking {booking_id}: {e}")
        return False


# ==============================================================================
# 4. ФИНАНСОВЫЕ СЕРВИСЫ (PAYMENTS & REFUNDS)
# ==============================================================================

async def create_crypto_invoice(amount: float, desc: str, payload: str) -> Tuple[
    Optional[dict], Optional[int], Optional[str]]:
    """Создает инвойс через CryptoPay API."""
    headers = {"Crypto-Pay-API-Token": CRYPTOPAY_TOKEN, "Content-Type": "application/json"}
    body = {
        "currency_type": "fiat",
        "fiat": "RUB",
        "amount": f"{amount:.2f}",
        "accepted_assets": "USDT",
        "description": desc,
        "payload": payload
    }

    async with aiohttp.ClientSession() as session:  # Создаем сессию
        for endpoint in ("/api/createInvoice", "/api/create_invoice"):
            try:
                print('2')
                async with session.post(CRYPTOPAY_BASE + endpoint, json=body, headers=headers, timeout=10) as r:
                    if r.status == 200:
                        j = await r.json()
                        return j, j['result']['invoice_id'], j['result']['bot_invoice_url']
                    else:
                        print(r.status)
                        print('NOOOOOOOOOOOOOOOOOOOOOOOOO')
                        return 502, None, None
            except Exception as e:
                logger.error(f"Crypto invoice error: {e}")
        return None, None, None


async def process_refund(booking_id: int, chat_id: int) -> Tuple[bool, str]:
    """
    Обрабатывает возврат средств в зависимости от метода оплаты.
    Возвращает (Успех, Сообщение).
    """
    try:
        row = await database.fetch_one(
            "SELECT usr_id, telegram_payment_charge_id, price, paid_think, date, google_event_id FROM bookings WHERE id = ?",
            (booking_id,)
        )
        if not row:
            return False, "Бронь не найдена."

        usr_id, charge_id, price, method, date_str, gid = row

        # Удаление календаря
        if gid: await GoogleCalendar.delete_event(gid)

        if method == 'stars':
            # Звезды возвращаются через bot.refund_star_payment в хендлере,
            # здесь мы просто удаляем запись, но физический возврат должен вызвать бот.
            # *Примечание: Service слой не имеет доступа к bot instance для refund,
            # поэтому здесь мы помечаем success=True, но контроллер должен вызвать API Telegram.*
            pass

        elif method == 'crypto':
            # Логика трансфера
            url_ex = f"{CRYPTOPAY_BASE}/api/getExchangeRates"
            headers = {"Crypto-Pay-API-Token": CRYPTOPAY_TOKEN}
            try:
                async with aiohttp.ClientSession() as session:  # Создаем сессию
                    async with session.get(url_ex, headers=headers, timeout=10) as response:
                        if response.status != 200:
                            return False, "Ошибка получения курсов"
                        data = await response.json()
                        rates = data['result'][0]  # Берем данные
                        rate = float(rates['rate'])
                        usdt_amount = str(math.floor(price / rate * 100) / 100)

                        transfer_body = {
                            "user_id": str(usr_id),
                            "asset": "USDT",
                            "amount": usdt_amount,
                            "spend_id": f'{booking_id}{usr_id}{date_str}'
                        }
                        async with session.post(f"{CRYPTOPAY_BASE}/api/transfer", json=transfer_body, headers=headers) as tr:
                            if tr.status != 200: return False, "Ошибка перевода CryptoPay."
            except Exception as e:
                logger.error(f"Refund crypto error: {e}")
                return False, "Ошибка соединения с CryptoPay."

        elif method == 'card':
            # Логика Portmone (заглушка)
            if not charge_id:
                return False, "Нет ID транзакции."
            # implement portmone_refund(charge_id, price) here
            pass

        # Если дошли сюда — удаляем из БД
        await database.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
        return True, f"Деньги ({price}₽) возвращены."

    except Exception as e:
        logger.exception(f"Refund exception: {e}")
        return False, f"Ошибка возврата: {e}"


async def check_crypto_invoice_status(invoice_id: int) -> Optional[str]:
    """
    Асинхронно проверяет статус инвойса через CryptoPay API.
    Использует run_in_executor, чтобы aiohttp не блокировал основной цикл бота.
    """
    headers = {"Crypto-Pay-API-Token": CRYPTOPAY_TOKEN}
    
    try:
        # Получаем текущий цикл событий
        loop = asyncio.get_running_loop()
        
        # Запускаем синхронный запрос в отдельном потоке
        response = await loop.run_in_executor(
            None,
            lambda: requests.post(
                f"{CRYPTOPAY_BASE}/api/getInvoices",
                json={"invoice_ids": [int(invoice_id)]},
                headers=headers,
                timeout=10
            )
        )
        
        if response.status_code != 200:
            logger.error(f"CryptoPay API Error: Status {response.status_code}, Body: {response.text}")
            return None

        data = response.json()

        # Безопасное извлечение данных
        if (data.get('ok') and
                'result' in data and
                'items' in data['result'] and
                len(data['result']['items']) > 0):
            return data['result']['items'][0]['status']

        return None
    
    except Exception as e:
        logger.error(f"Crypto status check exception: {e}")
        return None


# ==============================================================================
# 5. АДМИНИСТРАТИВНЫЕ СЕРВИСЫ (STATS)
# ==============================================================================

async def get_general_stats(period: str = "all") -> Dict:
    """Собирает общую статистику по барбершопу."""
    now = datetime.now()
    start_date = None

    if period == "month":
        start_date = now.replace(day=1).date().isoformat()
    elif period == "week":
        start_date = (now.date() - timedelta(days=now.weekday())).isoformat()

    where_clause = " WHERE date >= ?" if start_date else ""
    params = (start_date,) if start_date else ()

    # 1. Total bookings
    total_b = (await database.fetch_all(f"SELECT COUNT(*) FROM bookings{where_clause}", params))[0][0]

    # 2. Paid stats
    paid_where = (where_clause + " AND") if where_clause else " WHERE"
    paid_res = await database.fetch_all(
        f"SELECT COUNT(*), COALESCE(SUM(price),0) FROM bookings{paid_where} condition = 'paid'",
        params
    )
    paid_count, total_income = paid_res[0]

    # 3. Active barbers
    active_b = (await database.fetch_all("SELECT COUNT(*) FROM barbers WHERE name IS NOT NULL AND name != ''"))[0][0]

    return {
        "period": period,
        "total_bookings": total_b,
        "paid_bookings": paid_count,
        "total_income": total_income,
        "active_barbers": active_b
    }


async def get_barbers_stats_list(period: str = "all") -> List[Tuple]:
    """Возвращает список статистики по каждому барберу."""
    now = datetime.now()
    start_date = None
    if period == "month":
        start_date = now.replace(day=1).date().isoformat()
    elif period == "week":
        start_date = (now.date() - timedelta(days=now.weekday())).isoformat()

    query = """
        SELECT b.id, b.name,
        COUNT(k.id) AS total_bookings,
        SUM(CASE WHEN k.condition='paid' THEN 1 ELSE 0 END) AS paid_bookings,
        SUM(CASE WHEN k.condition='refunded' THEN 1 ELSE 0 END) AS refunded_bookings,
        COALESCE(SUM(CASE WHEN k.condition='paid' THEN k.price ELSE 0 END),0) AS income,
        COALESCE(AVG(CASE WHEN k.condition='paid' THEN k.price ELSE NULL END),0) AS avg_price
        FROM barbers b
        LEFT JOIN bookings k ON b.id = k.barber_id {date_filter}
        WHERE b.name IS NOT NULL AND b.name != ''
        GROUP BY b.id, b.name ORDER BY income DESC
    """

    if start_date:
        query = query.replace("{date_filter}", "AND k.date >= ?")
        rows = await database.fetch_all(query, (start_date,))
    else:
        query = query.replace("{date_filter}", "")
        rows = await database.fetch_all(query)

    return rows


async def get_single_barber_stats(barber_id: int, period: str = "all") -> Dict:
    """Детальная статистика одного барбера."""
    now = datetime.now()
    start_date = None
    if period == "month":
        start_date = now.replace(day=1).date().isoformat()
    elif period == "week":
        start_date = (now.date() - timedelta(days=now.weekday())).isoformat()

    params = (barber_id, start_date) if start_date else (barber_id,)
    date_cond = " AND date >= ?" if start_date else ""

    total = (await database.fetch_all(f"SELECT COUNT(*) FROM bookings WHERE barber_id = ?{date_cond}", params))[0][0]

    paid_res = await database.fetch_all(
        f"SELECT COUNT(*), COALESCE(SUM(price),0), COALESCE(AVG(price),0) FROM bookings WHERE barber_id = ? AND condition = 'paid'{date_cond}",
        params
    )
    paid_count, income, avg = paid_res[0]

    refunded = (await database.fetch_all(
        f"SELECT COUNT(*) FROM bookings WHERE barber_id = ? AND condition = 'refunded'{date_cond}",
        params
    ))[0][0]

    off_count = await count_offdays_in_next_6_months(barber_id)

    # Info
    b_info = await database.fetch_one("SELECT name, telegram_id, work_start, work_end FROM barbers WHERE id = ?",
                                      (barber_id,))

    return {
        "name": b_info[0] if b_info else "Unknown",
        "tg_id": b_info[1] if b_info else "",
        "work_time": f"{b_info[2]} - {b_info[3]}" if b_info else "",
        "total": total,
        "paid": paid_count,
        "refunded": refunded,
        "income": income,
        "avg_price": avg,
        "off_days": off_count
    }


# --- Добавить в конец services.py ---

async def reschedule_booking(booking_id: int, new_date_str: str, new_time_str: str, duration: int, user_username: str) -> Optional[dict]:
    """
    Переносит бронь на новое время:
    1. Пересчитывает логику уведомлений.
    2. Обновляет Google Calendar (удаляет старое, создает новое).
    3. Обновляет запись в БД.
    Возвращает словарь с данными для уведомления барбера или None при ошибке.
    """
    try:
        # 1. Получаем старые данные
        old_row = await database.fetch_one(
            "SELECT barber_id, date, start_time, service_name, google_event_id, price, barber_name FROM bookings WHERE id = ?",
            (booking_id,)
        )
        if not old_row:
            return None

        barber_id, old_date_str, old_time_str, service_name, old_gid, price, barber_name = old_row

        # 2. Рассчитываем новое время и логику напоминаний
        new_date = date.fromisoformat(new_date_str)
        new_time_obj = str_to_time(new_time_str)
        timestamp_date = datetime.combine(new_date, new_time_obj.time())

        # Логика таймеров уведомлений
        delta_hours = int((timestamp_date - datetime.now()).total_seconds() // 3600)
        if delta_hours > 26:
            type_cond, sent_cond = '24', 0
        elif delta_hours > 15:
            type_cond, sent_cond = '12', 0
        elif delta_hours > 5:
            type_cond, sent_cond = '3', 0
        else:
            type_cond, sent_cond = '0', 1

        end_time_str = time_to_str(new_time_obj + timedelta(minutes=duration))

        # 3. Работа с Google Calendar
        if old_gid:
            await GoogleCalendar.delete_event(old_gid)

        new_gid = await GoogleCalendar.create_event(
            barber_name, service_name, f"@{user_username}",
            new_date_str, new_time_str, duration, price
        )

        # 4. Обновление БД (SQL запрос вынесен сюда)
        await database.execute(
            """UPDATE bookings SET 
               date = ?, start_time = ?, end_time = ?, type = ?, sent = ?, 
               timestamp_date = ?, google_event_id = ? 
               WHERE id = ?""",
            (new_date_str, new_time_str, end_time_str, type_cond, sent_cond,
             int(timestamp_date.timestamp()), new_gid, booking_id)
        )

        # 5. Возвращаем данные, необходимые для уведомления барбера
        return {
            "barber_id": barber_id,
            "service_name": service_name,
            "old_date": old_date_str,
            "old_time": old_time_str
        }

    except Exception as e:
        logger.error(f"Error rescheduling booking {booking_id}: {e}")
        return None


async def get_booking_details(booking_id: int) -> Optional[dict]:
    """Получает полные данные брони и барбера для отображения в меню."""
    row = await database.fetch_one(
        "SELECT barber_id, service_id, date, start_time, barber_name, condition, timestamp_date, price FROM bookings WHERE id = ?",
        (booking_id,)
    )
    if not row: return None

    barber_id, service_id, date_d, date_t, barber_name, condition, timestamp_date, price = row

    # Получаем контакты барбера
    barber_info = await database.fetch_one(
        "SELECT telegram_usrname, telegram_number FROM barbers WHERE id = ?", (barber_id,)
    )
    tg_usr, tg_phone = barber_info if barber_info else ("Unknown", "Unknown")

    return {
        "id": booking_id,
        "barber_id": barber_id,
        "date": date_d,
        "time": date_t,
        "barber_name": barber_name,
        "condition": condition,
        "timestamp": timestamp_date,
        "price": price,
        "barber_username": tg_usr,
        "barber_phone": tg_phone
    }