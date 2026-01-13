# AdminBot.py
# Админ-бот для управления barbershop.db
# Интеграция и соглашения по БД/функциям взяты из существующих скриптов:
# BarberToClient.py и ClientToBarber.py. См. исходники для деталей схемы и вспомогательных функций.
# Источники: :contentReference[oaicite:0]{index=0} :contentReference[oaicite:1]{index=1}

import asyncio
import logging
import time
from datetime import datetime, date, timedelta
from calendar import monthrange
import re

from aiogram import Bot, Dispatcher, F, types
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
import os
from dotenv import load_dotenv

import database
import services
from keyboards import admin_kb

from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# Определяем состояния для добавления Барбера
class AddBarber(StatesGroup):
    waiting_for_name = State()       # Ждем имя
    waiting_for_tg_id = State()      # Ждем ID телеграма
    waiting_for_phone = State()      # Ждем телефон
    waiting_for_username = State()   # Ждем юзернейм

# Определяем состояния для добавления Услуги
class AddService(StatesGroup):
    waiting_for_name = State()
    waiting_for_price = State()
    waiting_for_duration = State()

# Определяем состояние для смены Цены
class ChangePrice(StatesGroup):
    waiting_for_new_price = State()


# Загружаем переменные из .env
load_dotenv()

# ------------------------
# Конфигурация
TOKEN = os.getenv("ADMIN_BOT_TOKEN")
admin_ids_str = os.getenv("ADMIN_IDS", "")
ADMINS = [int(x) for x in admin_ids_str.split(",") if x]


# ------------------------
# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ------------------------
# DB
DB_NAME = "barbershop.db"

# ------------------------
# Бот и диспетчер
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ------------------------
# Основное меню
# ------------------------

@dp.message(F.text == "/start")
async def cmd_start(message: Message):
    uid = message.from_user.id
    if not services.is_admin(uid):
        logger.info("Unauthorized admin access attempt: %s (%s)", uid, getattr(message.from_user, "username", ""))
        await message.answer("Доступ запрещен.")
        return
    await message.answer("Админ-меню:", reply_markup=admin_kb.main_menu())

# ------------------------
# Callback router
# ------------------------
@dp.callback_query()
async def callbacks(call: CallbackQuery, state: FSMContext):
    uid = call.from_user.id
    if not services.is_admin(uid):
        logger.info("Unauthorized callback attempt: %s -> %s", uid, call.data)
        await call.answer("Доступ запрещен.", show_alert=True)
        return

    data = call.data or ""
    logger.info("Admin %s called %s", uid, data)

    try:
        # Main menu callbacks
        if data == "menu_stats":
            await show_stats_menu(call, period="all")
            return
        if data.startswith("stats_period_"):
            # stats_period_all / stats_period_month / stats_period_week
            period, page = data[len("stats_period_"):].split("_")
            await show_stats_menu(call, period=period, page=int(page))
            return
        if data.startswith("stats_barber_"):
            # stats_barber_{barber_id}_{period}
            bid_s, period, page = data[len("stats_barber_"):].split("_")
            await show_barber_stats(call, int(bid_s), period, page)
            return
        if data == "stats_back":
            await call.message.edit_text("Админ-меню:", reply_markup=admin_kb.main_menu())
            return

        # Barbers
        if data == "menu_barbers":
            await show_barbers_list(call)
            return
        if data == "barber_add":
            await state.set_state(AddBarber.waiting_for_name)
            await call.message.edit_text("Добавление барбера — введите имя (текст).", reply_markup=admin_kb.cancel('barber_add_cancel'))
            return
        if data == "barber_add_cancel":
            await state.clear()
            await show_barbers_list(call)
            return
        if data.startswith("barber_delete_confirm_"):
            bid = int(data[len("barber_delete_confirm_"):])
            try:
                await database.execute("DELETE FROM barbers WHERE id = ?", (bid,))
                await call.message.edit_text(f"Барбер id={bid} удалён.", reply_markup=admin_kb.back_custom("menu_barbers"))
            except Exception as e:
                logger.exception("Failed to delete barber %s", bid)
                await call.message.edit_text(f"Ошибка: не удалось удалить барбера: {str(e)}", reply_markup=admin_kb.back_custom("menu_barbers"))
            return
        elif data.startswith("barber_delete_"):
            print(data)
            bid = int(data[len("barber_delete_"):])
            await call.message.edit_text(f"Вы уверены, что хотите удалить барбера id={bid}? Это удалит связанные записи (если настроен CASCADE).", reply_markup = admin_kb.confirm_delete(f"barber_delete_confirm_{bid}", "menu_barbers"))
            return

        if data.startswith("barber_service_add_"):
            bid, sid = map(int, data.replace("barber_service_add_", "").split("_"))
            await database.execute("INSERT OR IGNORE INTO barber_services (barber_id, service_id) VALUES (?, ?)", (bid, sid))
            all_services = await database.fetch_all("SELECT id, name FROM services ORDER BY name")
            assigned_ids = {x[0] for x in await database.fetch_all("SELECT service_id FROM barber_services WHERE barber_id = ?", (bid,))}
            reply_markup = admin_kb.manage_barber_services(bid, all_services, assigned_ids)
            await call.message.edit_text("🛠️ Услуги барбера\n\n➕ добавить • ❌ убрать", reply_markup=reply_markup)

        if data.startswith("barber_service_remove_"):
            bid, sid = map(int, data.replace("barber_service_remove_", "").split("_"))
            await database.execute("DELETE FROM barber_services WHERE barber_id = ? AND service_id = ?", (bid, sid))
            all_services = await database.fetch_all("SELECT id, name FROM services ORDER BY name")
            assigned_ids = {x[0] for x in await database.fetch_all("SELECT service_id FROM barber_services WHERE barber_id = ?", (bid,))}
            reply_markup = admin_kb.manage_barber_services(bid, all_services, assigned_ids)
            await call.message.edit_text("🛠️ Услуги барбера\n\n➕ добавить • ❌ убрать", reply_markup=reply_markup)

        if data.startswith("barber_services_"):
            bid = int(data.replace("barber_services_", ""))
            all_services = await database.fetch_all("SELECT id, name FROM services ORDER BY name")
            assigned_ids = {s[0] for s in await database.fetch_all("SELECT service_id FROM barber_services WHERE barber_id = ?", (bid,))}
            reply_markup = admin_kb.manage_barber_services(bid, all_services, assigned_ids)
            await call.message.edit_text("🛠️ Услуги барбера\n\n➕ добавить • ❌ убрать", reply_markup=reply_markup)
            return

        # Services
        if data == "menu_services":
            await show_services_list(call)
            return
        if data == "service_add":
            await state.set_state(AddService.waiting_for_name)
            await call.message.edit_text("Добавление услуги — введите название услуги (текст).", reply_markup=admin_kb.cancel("service_add_cancel"))
            return
        if data == "service_add_cancel":
            await state.clear()
            await show_services_list(call)
            return
        if data.startswith("service_delete_confirm_"):
            sid = int(data[len("service_delete_confirm_"):])
            try:
                await database.execute("DELETE FROM services WHERE id = ?", (sid,))
                await call.message.edit_text(f"Услуга id={sid} удалена.", reply_markup=admin_kb.back_custom("menu_services"))
            except Exception as e:
                logger.exception("Failed to delete service %s", sid)
                await call.message.edit_text(f"Ошибка: не удалось удалить услугу: {str(e)}", reply_markup=admin_kb.back_custom("menu_services"))
            return
        elif data.startswith("service_delete_"):
            sid = int(data[len("service_delete_"):])
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Да, удалить", callback_data=f"service_delete_confirm_{sid}"),
                 InlineKeyboardButton(text="Нет", callback_data="menu_services")]
            ])
            await call.message.edit_text(f"Вы уверены, что хотите удалить услугу id={sid}? Это удалит связанные записи (если настроен CASCADE).", reply_markup=admin_kb.confirm_delete(f"service_delete_confirm_{sid}", "menu_services"))
            return

        # Prices
        if data == "menu_prices":
            await show_prices_list(call)
            return
        if data.startswith("price_change_"):
            sid = int(data[len("price_change_"):])
            # --- ВАЖНО: СОХРАНЯЕМ ID В ПАМЯТЬ ---
            await state.update_data(service_id=sid)
            # ------------------------------------
            await state.set_state(ChangePrice.waiting_for_new_price)
            await call.message.edit_text(f"Введите новую цену (целое число) для услуги id={sid}:", reply_markup=admin_kb.cancel("menu_prices"))
            return

        # Вспомогательные возвраты в меню
        if data == "back_main":
            await call.message.edit_text("Админ-меню:", reply_markup=admin_kb.main_menu())
            return

        # Если не сопоставлено
        await call.answer()
    except Exception as e:
        logger.exception("Unhandled callback exception: %s", e)
        try:
            await call.message.edit_text(f"Ошибка: {str(e)}", reply_markup=admin_kb.main_menu())
        except Exception:
            await call.answer("Произошла ошибка.", show_alert=True)

# Показ статистики
# ------------------------

@dp.callback_query(lambda c: c.data.startswith("stats:"))
async def stats_callback(call: CallbackQuery):
    _, period, page = call.data.split(":")
    await show_stats_menu(call, period, int(page))

async def show_stats_menu(call: CallbackQuery, period: str = "all", page: int = 0):
    try:
        # 1. Общая статистика
        stats = await services.get_general_stats(period)

        period_label = {"all": "За всё время", "month": "За текущий месяц", "week": "За текущую неделю"}.get(period, "За всё время")

        text = (f"📊 Статистика — {period_label}\n\n"
                f"Всего броней: <b>{stats['total_bookings']}</b>\n"
                f"Оплаченных броней: <b>{stats['paid_bookings']}</b>\n"
                f"Общий доход (paid): <b>{services.format_rub(stats['total_income'])}</b>\n"
                f"Активных барберов: <b>{stats['active_barbers']}</b>\n\n"
                f"Статистика по барберам:")

        # 2. Список барберов
        rows = await services.get_barbers_stats_list(period)

        # Пагинация
        PER_PAGE = 10
        start_idx = page * PER_PAGE
        end_idx = start_idx + PER_PAGE
        displayed_rows = rows[start_idx:end_idx]

        if displayed_rows:
            for r in displayed_rows:
                bid, bname, total_b, paid_b, refunded_b, income, avg_price = r
                # Считаем выходные через сервис
                off_count = await services.count_offdays_in_next_6_months(bid)
                text += f"\n\n• {bname} (id:{bid}) — броней: {total_b} (опл: {paid_b}, отм: {refunded_b}), доход: {services.format_rub(income)}, ср.цена: {int(avg_price)}₽, выходных: {off_count}"
        else:
            text += "\n\nНет барберов для отображения."

        displayed_barbers = [(r[0], r[1]) for r in displayed_rows]
        has_prev = page > 0
        has_next = end_idx < len(rows)

        try:
            await call.message.edit_text(text, reply_markup=admin_kb.stats_menu(period, page, displayed_barbers, has_prev, has_next), parse_mode="HTML")
        except Exception:
            await call.answer(text='Ничего не изменилось', show_alert=True)

    except Exception as e:
        logger.exception("show_stats_menu failed: %s", e)
        await call.message.edit_text(f"Ошибка получения статистики: {str(e)}", reply_markup=admin_kb.back_custom("back_main"))

async def show_barber_stats(call: CallbackQuery, barber_id: int, period: str, page: int):
    try:
        s = await services.get_single_barber_stats(barber_id, period)

        period_label = {"all": "За всё время", "month": "За месяц", "week": "За неделю"}.get(period, "За всё время")

        text = (f"📋 Подробная статистика — {s['name']} ({period_label})\n\n"
                f"Всего броней: <b>{s['total']}</b>\n"
                f"Оплаченных: <b>{s['paid']}</b>\n"
                f"Возвратов: <b>{s['refunded']}</b>\n"
                f"Доход (paid): <b>{services.format_rub(s['income'])}</b>\n"
                f"Средняя цена (paid): <b>{int(s['avg_price'])}₽</b>\n"
                f"Выходных в блоке (6 мес): <b>{s['off_days']}</b>\n\n"
                f"Рабочее время: {s['work_time']}\n"
                f"Telegram ID: {s['tg_id']}\n")

        await call.message.edit_text(text, reply_markup=admin_kb.barber_stats_back(period, page), parse_mode="HTML")
    except Exception as e:
        logger.exception("show_barber_stats failed: %s", e)
        await call.message.edit_text(f"Ошибка: {str(e)}", reply_markup=admin_kb.back_custom("stats_back"))

# ------------------------
# Показ списков — барберы / услуги / цены
# ------------------------
async def show_barbers_list(call: CallbackQuery):
    try:
        rows = await database.fetch_all("SELECT id, name, telegram_id, work_start, work_end FROM barbers ORDER BY id")
        if not rows:
            text = "Список барберов пуст."
        else:
            text = "👥 Список барберов:\n"
            for r in rows:
                bid, name, tg, ws, we = r
                text += f"\n• {name} (id:{bid}) — {ws}–{we} — tg_id:{tg}"
        barbers_data_for_kb = [(r[0], r[1]) for r in rows]
        await call.message.edit_text(text, reply_markup=admin_kb.barbers_list(barbers_data_for_kb), parse_mode="HTML")
    except Exception as e:
        logger.exception("show_barbers_list failed: %s", e)
        await call.message.edit_text("Ошибка при получении списка барберов.", reply_markup=admin_kb.back_to_main())

async def show_services_list(call: CallbackQuery):
    try:
        rows = await database.fetch_all("SELECT id, name, price, duration FROM services ORDER BY id")
        if not rows:
            text = "Список услуг пуст."
        else:
            text = "🛠️ Список услуг:\n"
            for r in rows:
                sid, name, price, dur = r
                text += f"\n• {name} (id:{sid}) — {services.format_rub(price)} — {dur} мин."
        services_for_kb = [(r[0], r[1]) for r in rows]
        await call.message.edit_text(text, reply_markup=admin_kb.services_list(services_for_kb), parse_mode="HTML")
    except Exception as e:
        logger.exception("show_services_list failed: %s", e)
        await call.message.edit_text("Ошибка при получении списка услуг.", reply_markup=admin_kb.back_to_main())

async def show_prices_list(call: CallbackQuery):
    try:
        rows = await database.fetch_all("SELECT id, name, price FROM services ORDER BY id")
        if not rows:
            text = "Список услуг пуст."
        else:
            text = "💰 Цены услуг:\n"
            for r in rows:
                sid, name, price = r
                text += f"\n• {name} (id:{sid}) — {services.format_rub(price)}"
        prices_for_kb = [(r[0], r[1]) for r in rows]
        await call.message.edit_text(text, reply_markup=admin_kb.prices_list(prices_for_kb), parse_mode="HTML")
    except Exception as e:
        logger.exception("show_prices_list failed: %s", e)
        await call.message.edit_text("Ошибка при получении цен.", reply_markup=admin_kb.back_to_main())

# ==========================================
#      ЛОГИКА ДОБАВЛЕНИЯ (FSM)
# ==========================================
# --- ЛОВИМ ИМЯ ---
@dp.message(AddBarber.waiting_for_name)  # Сработает ТОЛЬКО если ждем имя
async def barber_name_step(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name:
        await message.answer("Введите имя текстом.")
        return
    # Сохраняем имя в "черновик"
    await state.update_data(barber_name=name)
    # Переходим к следующему шагу
    await state.set_state(AddBarber.waiting_for_tg_id)
    await message.answer("Введите telegram_id (число) или любой текст для пропуска.", reply_markup=admin_kb.cancel("barber_add_cancel"))


# --- 1. TG ID (Цифры или 0) ---
@dp.message(AddBarber.waiting_for_tg_id)
async def barber_tg_id_step(message: Message, state: FSMContext):
    txt = message.text.strip()
    # Если прочерк/0 -> 0, если цифры -> int, иначе -> None (ошибка)
    tg_id = 0 if txt in ["0", "-", "нет"] else (int(txt) if txt.isdigit() else None)

    if tg_id is None: return await message.answer("❌ Только цифры или 0 для пропуска!", reply_markup=admin_kb.cancel("barber_add_cancel"))

    await state.update_data(barber_tg_id=tg_id)
    await state.set_state(AddBarber.waiting_for_phone)
    await message.answer("Телефон (+380...):", reply_markup=admin_kb.cancel("barber_add_cancel"))


# --- 2. ТЕЛЕФОН (Regex в одну строку) ---
# --- 2. ТЕЛЕФОН (Обязательно с +) ---
@dp.message(AddBarber.waiting_for_phone)
async def barber_phone_step(message: Message, state: FSMContext):
    # Убрали '?' после '+', теперь плюс обязателен
    if not re.match(r"^\+\d{10,15}$", message.text.strip()): return await message.answer("❌ Номер должен начинаться с + (напр. +380...)", reply_markup=admin_kb.cancel("barber_add_cancel"))
    await state.update_data(barber_phone=message.text.strip())
    await state.set_state(AddBarber.waiting_for_username)
    await message.answer("Username (без @):", reply_markup=admin_kb.cancel("barber_add_cancel"))


# --- 3. USERNAME И СОХРАНЕНИЕ ---
@dp.message(AddBarber.waiting_for_username)
async def barber_username_step(message: Message, state: FSMContext):
    u = message.text.strip().replace("@", "")
    # Если прочерк -> None, иначе сам юзернейм
    usr = None if u in ["-", "0", "нет"] else u

    # Если юзернейм есть, но (короткий ИЛИ плохие символы) -> Ошибка
    if usr and (len(usr) < 5 or not re.match(r'^[a-zA-Z0-9_]+$', usr)): return await message.answer("❌ Латиница, цифры, >5 симв.", reply_markup=admin_kb.cancel("barber_add_cancel"))

    data = await state.get_data()
    try:
        await services.create_barber(data['barber_name'], data['barber_tg_id'], data['barber_phone'], usr)
        await message.answer(f"✅ Барбер {data['barber_name']} добавлен!", reply_markup=admin_kb.main_menu())
    except Exception as e:
        await message.answer(f"Ошибка БД: {e}", reply_markup=admin_kb.main_menu())

    await state.clear()


# --- ШАГ 1: ЛОВИМ НАЗВАНИЕ ---
@dp.message(AddService.waiting_for_name)
async def service_name_step(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name:
        await message.answer("Введите название услуги текстом.")
        return
    # Сохраняем
    await state.update_data(service_name=name)
    # Следующий шаг
    await state.set_state(AddService.waiting_for_price)
    await message.answer("Введите цену (целое число, например 1500):", reply_markup=admin_kb.cancel("service_add_cancel"))


# --- 1. ЛОВИМ ЦЕНУ (При создании услуги) ---
@dp.message(AddService.waiting_for_price)
async def service_price_step(message: Message, state: FSMContext):
    # Если не число или меньше 0 -> Ошибка
    if not message.text.strip().isdigit(): return await message.answer("❌ Цена должна быть числом!", reply_markup=admin_kb.cancel("service_add_cancel"))

    await state.update_data(service_price=int(message.text.strip()))
    await state.set_state(AddService.waiting_for_duration)
    await message.answer("Длительность в минутах (число):", reply_markup=admin_kb.cancel("service_add_cancel"))


# --- 2. ЛОВИМ ДЛИТЕЛЬНОСТЬ И СОХРАНЯЕМ ---
@dp.message(AddService.waiting_for_duration)
async def service_duration_step(message: Message, state: FSMContext):
    if not message.text.strip().isdigit(): return await message.answer("❌ Длительность должна быть числом!", reply_markup=admin_kb.cancel("service_add_cancel"))

    data = await state.get_data()
    try:
        # Пишем в базу в одну строку
        await database.execute("INSERT INTO services (name, price, duration) VALUES (?, ?, ?)", (data['service_name'], data['service_price'], int(message.text.strip())))
        await message.answer(f"✅ Услуга «{data['service_name']}» добавлена!", reply_markup=admin_kb.main_menu())
    except Exception as e:
        await message.answer(f"Ошибка: {e}", reply_markup=admin_kb.main_menu())

    await state.clear()


# --- 3. ИЗМЕНЕНИЕ ЦЕНЫ (Логика обновления) ---
@dp.message(ChangePrice.waiting_for_new_price)
async def change_price_step(message: Message, state: FSMContext):
    if not message.text.strip().isdigit(): return await message.answer("❌ Введите целое число!", reply_markup=admin_kb.cancel("menu_prices"))

    data = await state.get_data()
    # Если вдруг потеряли ID услуги (редко, но бывает) -> сброс
    if not data.get('service_id'): return await state.clear() or await message.answer("Ошибка: потерян ID.", reply_markup=admin_kb.main_menu())

    try:
        await database.execute("UPDATE services SET price = ? WHERE id = ?", (int(message.text.strip()), data['service_id']))
        await message.answer(f"✅ Цена успешно обновлена!", reply_markup=admin_kb.main_menu())
    except Exception as e:
        await message.answer(f"Ошибка БД: {e}")
    await state.clear()

# ------------------------
# Запуск
# ------------------------
async def main():
    logger.info("Starting AdminBot.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("AdminBot stopped by user.")
