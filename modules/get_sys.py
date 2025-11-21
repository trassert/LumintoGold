import asyncio
import platform
from time import time

import psutil
from loguru import logger

logger.info(f"Загружен модуль {__name__}!")

if platform.system() == "Windows":
    import WinTmp # type: ignore

    logger.info("Система - Windows, использую WinTMP")

    def get_temperature() -> str:
        try:
            temp = WinTmp.CPU_Temps()
            return f"{round(max(temp))} | {round(sum(temp) / len(temp))} | {round(min(temp))}"
        except Exception:
            return "Неизвестно"
else:
    logger.info("Система - Linux, использую psutil")

    def get_temperature() -> str | None:
        try:
            temps_data = psutil.sensors_temperatures()
            current_temps = []

            for name, entries in temps_data.items():
                for entry in entries:
                    temp = entry.current

                    if temp is not None and temp >= 0:
                        current_temps.append(temp)

            if not current_temps:
                return "Нет данных о температуре"

            return f"{round(max(current_temps))} | {round(sum(current_temps) / len(current_temps))} | {round(min(current_temps))}"

        except Exception as e:
            return f"Ошибка получения: {e}"


async def get_current_speed():
    start_counters = psutil.net_io_counters()
    await asyncio.sleep(0.5)
    end_counters = psutil.net_io_counters()
    delta_bytes_sent = end_counters.bytes_sent - start_counters.bytes_sent
    delta_bytes_recv = end_counters.bytes_recv - start_counters.bytes_recv
    upload_speed_mbps = (delta_bytes_sent / 0.5 * 8) / (1000 * 1000)
    download_speed_mbps = (delta_bytes_recv / 0.5 * 8) / (1000 * 1000)
    return [round(download_speed_mbps, 2), round(upload_speed_mbps, 2)]


async def get_system_info() -> str:
    boot_time = psutil.boot_time()
    current_time = time()
    uptime_seconds = current_time - boot_time
    days = int(uptime_seconds / (24 * 3600))
    hours = int((uptime_seconds % (24 * 3600)) / 3600)
    minutes = int((uptime_seconds % 3600) / 60)
    result = ""
    if days > 0:
        result += f"{days} дн. "
    if hours > 0:
        result += f"{hours:02} ч. "
    result += f"{minutes} мин."
    mem = psutil.virtual_memory()
    mem_total = mem.total / (1024 * 1024 * 1024)
    mem_avail = mem.available / (1024 * 1024 * 1024)
    mem_used = mem.used / (1024 * 1024 * 1024)

    network = await get_current_speed()
    return f"""⚙️ : Информация о хостинге:
    Время работы: {result}
    ОС: {platform.system()} {platform.release()}
    Процессор:
        Частота: {int(psutil.cpu_freq().current)} МГц
        Ядра/Потоки: {psutil.cpu_count(logical=False)}/{psutil.cpu_count(logical=True)}
        Загрузка: {psutil.cpu_percent(0.5)} %
        Температура ↑|≈|↓: {get_temperature()}
    Память:
        Объём: {mem_total:.1f} ГБ
        Доступно: {mem_avail:.1f} ГБ
        Используется: {mem_used:.1f} ГБ
        Загрузка: {mem.percent} %
    Сеть:
        Загрузка: {network[0]} Мбит/с
        Выгрузка: {network[1]} Мбит/с
    """
