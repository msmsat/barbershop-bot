# barbershopbot.py
import asyncio
import logging

import database
import scheduler_service

# Импортируем ботов и диспетчеры
from BarberToClient import dp as dp_client, bot as bot_client
from ClientToBarber import dp as dp_barber, bot as bot_barber
from AdminBot import dp as dp_admin, bot as bot_admin

# Настраиваем логирование
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)


async def main():
    # Инициализация базы данных
    await database.init_db()
    logging.info("База данных инициализирована")

    # Запускаем планировщик как фоновую задачу
    scheduler_task = asyncio.create_task(scheduler_service.start_scheduler())

    # Запускаем polling для каждого бота как отдельные задачи
    # start_polling() — асинхронная функция, которая корректно работает в gather
    polling_tasks = [
        asyncio.create_task(dp_barber.start_polling(bot_barber, handle_signals=True)),
        asyncio.create_task(dp_admin.start_polling(bot_admin, handle_signals=True)),
        asyncio.create_task(dp_client.start_polling(bot_client, handle_signals=True)),
    ]

    try:
        # Ждём завершения всех задач
        await asyncio.gather(*polling_tasks, scheduler_task, return_exceptions=True)
    except KeyboardInterrupt:
        logging.info("Получен Ctrl+C → graceful shutdown")
    except Exception as e:
        logging.exception("Ошибка во время работы ботов:", exc_info=e)
    finally:
        # Принудительно отменяем все задачи, если они ещё живы
        for task in polling_tasks + [scheduler_task]:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        logging.info("Все боты и планировщик остановлены")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Остановка по Ctrl+C")
    except Exception as e:
        logging.exception("Критическая ошибка при запуске:", exc_info=e)
    finally:
        print("Бот(ы) полностью остановлены.")