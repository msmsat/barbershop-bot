# barbershopbot.py
import asyncio
import logging
import database

# Импортируем ботов
from BarberToClient import dp as dp_client, bot as bot_client
from ClientToBarber import dp as dp_barber, bot as bot_barber
from AdminBot import dp as dp_admin, bot as bot_admin

# Импортируем наш новый сервис
import scheduler_service


async def main():
    # Инициализация БД (на всякий случай, если еще не создана)
    await database.init_db()
    
    # Запускаем всё параллельно: 3 бота + 1 планировщик
    await asyncio.gather(
        dp_barber.start_polling(bot_barber),
        dp_admin.start_polling(bot_admin),
        dp_client.start_polling(bot_client),
        scheduler_service.start_scheduler()  # <--- ДОБАВЛЕНО
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped.")