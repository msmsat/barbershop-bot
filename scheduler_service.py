# scheduler_service.py
import asyncio
import logging
import time
from datetime import datetime, date
import database
import GoogleCalendar
from loader import bot_client, bot_barber

logger = logging.getLogger(__name__)
CHECK_INTERVAL = 300
VACUUM_EVERY = 10
NEXT_STEP = {24: 12, 12: 3, 3: 0}  # Логика переключения времени


async def _safe_send(bot, user_id: int, text: str):
    """Отправка сообщения без прерывания работы при ошибке (например, блок бота)"""
    try:
        await bot.send_message(user_id, text, parse_mode="HTML")
    except Exception:
        pass


async def _delete_gcal(event_id: str):
    """Фоновое удаление из календаря"""
    if event_id: asyncio.create_task(GoogleCalendar.delete_event(event_id))


async def _clean_expired(now: int):
    """1. Удаление просроченных броней"""
    rows = await database.fetch_all("SELECT id, usr_id, date, start_time, google_event_id FROM bookings WHERE timestamp_date < ?", (now,))
    if not rows: return 0
    
    for bid, uid, d, t, gid in rows:
        await _delete_gcal(gid)
        await _safe_send(bot_client, uid, f"⏳ Бронь (ID {bid}) на {d} {t} истекла и удалена.")
        await database.execute("DELETE FROM bookings WHERE id = ?", (bid,))
    return len(rows)


async def _clean_offdays():
    """2. Удаление прошедших выходных"""
    today = date.today().isoformat()
    rows = await database.fetch_all("SELECT id, barber_id, date FROM off_days WHERE date < ?", (today,))
    
    for oid, bid, dstr in rows:
        await database.execute("DELETE FROM off_days WHERE id = ?", (oid,))
        # Уведомляем барбера, если найдем
        if (tb := await database.fetch_one("SELECT telegram_id, reminders FROM barbers WHERE id = ?", (bid,))) and tb[0] and tb[1]:
            await _safe_send(bot_barber, tb[0], f"📆 Прошедший выходной {dstr} удален.")


async def _process_reminders(now: int):
    """3. Обработка напоминаний и старта броней"""
    # Берем брони, где подошло время (текущее время > время записи - время уведомления)
    rows = await database.fetch_all("""
        SELECT id, usr_id, barber_id, barber_name, service_name, date, start_time, type, timestamp_date, google_event_id
        FROM bookings WHERE sent = 0 AND timestamp_date - 3600 * type < ?
    """, (now,))
    
    for row in rows:
        bid, uid, bar_id, b_name, s_name, d_date, d_time, type_h, ts, gid = row
        type_h = int(type_h)
        
        # Если время записи уже наступило (type=0 обрабатывается тут)
        if type_h == 0:
            await _delete_gcal(gid)
            await database.execute("DELETE FROM bookings WHERE id = ?", (bid,))
            await _safe_send(bot_client, uid, f"✂️ Ваша стрижка началась!\nМастер: {b_name}\nУслуга: {s_name}")
            continue
        
        # Переход к следующему этапу напоминания
        new_type = NEXT_STEP.get(type_h)
        if new_type is not None:
            # Если переключаем на 0 (старт), ставим sent=1, чтобы в след. раз сработал блок выше (type==0)
            # Иначе sent=0, чтобы сработал этот же блок для следующего напоминания
            sent_status = 1 if new_type == 0 else 0
            await database.execute("UPDATE bookings SET type = ?, sent = ? WHERE id = ?", (new_type, sent_status, bid))
            
            # Формируем и отправляем напоминания
            dd = datetime.strptime(d_date, '%Y-%m-%d')
            nice_date = f"{dd.day}.{dd.month}.{dd.year}"
            
            await _safe_send(bot_client, uid, f"⏰ <b>Напоминание!</b>\nЧерез {type_h} час(а) запись!\n💈 {b_name}\n🗓 {nice_date} в {d_time}")
            
            if bar_id and (tb := await database.fetch_one("SELECT telegram_id, reminders FROM barbers WHERE id = ?", (bar_id,))) and tb[0] and tb[1]:
                await _safe_send(bot_barber, tb[0], f"🔔 <b>Мастеру:</b> Через {type_h} час(а) клиент:\nID: {uid} | {s_name} | {d_time}")


async def start_scheduler():
    logger.info("📅 Scheduler Service started")
    vacuum_counter = 0
    
    while True:
        try:
            now = int(time.time())
            
            # Выполняем задачи последовательно
            cleaned_count = await _clean_expired(now)
            await _clean_offdays()
            await _process_reminders(now)
            
            # Обслуживание базы
            if cleaned_count > 0:
                vacuum_counter += 1
                if vacuum_counter >= VACUUM_EVERY:
                    await database.vacuum_db()
                    vacuum_counter = 0
        
        except Exception as e:
            logger.exception(f"Scheduler loop error: {e}")
            await asyncio.sleep(60)  # Пауза при ошибке
        
        await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    asyncio.run(start_scheduler())