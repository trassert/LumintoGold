import asyncio
import os
import platform
import shutil
from pathlib import Path
from time import time

import psutil
from loguru import logger

logger.info(f"Загружен модуль {__name__}!")

if platform.system() == "Windows":
    try:
        import WinTmp  # type: ignore

        logger.info("Система - Windows, использую WinTmp")

        def get_temperature() -> str:
            try:
                temps = WinTmp.CPU_Temps()
                if not temps:
                    return None
                mx, avg, mn = max(temps), sum(temps) / len(temps), min(temps)
                return f"{round(mx)} | {round(avg)} | {round(mn)}"
            except Exception:
                logger.opt(exception=True).debug(
                    "Ошибка при чтении температуры (WinTmp)"
                )
                return None
    except ImportError:
        logger.warning(
            "WinTmp не установлен, температура недоступна на Windows"
        )

        def get_temperature() -> str:
            return None
else:
    logger.info("Система - Linux, использую psutil")

    def get_temperature() -> str:
        try:
            temps_data = psutil.sensors_temperatures()
            current_temps = [
                entry.current
                for entries in temps_data.values()
                for entry in entries
                if entry.current is not None and entry.current >= 0
            ]
            if not current_temps:
                return None
            mx, avg, mn = (
                max(current_temps),
                sum(current_temps) / len(current_temps),
                min(current_temps),
            )
            return f"{round(mx)} | {round(avg)} | {round(mn)}"
        except Exception:
            logger.warning("Не могу прочитать температуру.")
            return None


async def get_current_speed() -> list[str | float]:
    try:
        start = psutil.net_io_counters()
        await asyncio.sleep(0.5)
        end = psutil.net_io_counters()

        upload_mbps = round(
            (end.bytes_sent - start.bytes_sent) * 8 / 0.5 / 1_000_000, 2
        )
        download_mbps = round(
            (end.bytes_recv - start.bytes_recv) * 8 / 0.5 / 1_000_000, 2
        )
        return [download_mbps, upload_mbps]
    except PermissionError:
        return ["Недоступно", "Недоступно"]
    except Exception:
        logger.opt(exception=True).error("Ошибка при измерении скорости сети")
        return ["Ошибка", "Ошибка"]


def get_boottime() -> str:
    try:
        uptime_sec = time() - psutil.boot_time()
        days, remainder = divmod(uptime_sec, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes = int(remainder // 60)

        parts = []
        if days:
            parts.append(f"{int(days)} дн.")
        if hours:
            parts.append(f"{int(hours):02} ч.")
        parts.append(f"{minutes} мин.")
        return " ".join(parts)
    except PermissionError:
        return "Нет доступа"
    except Exception:
        logger.opt(exception=True).error("Ошибка при получении времени работы")
        return "Неизвестно"


async def get_cpu_load() -> str:
    try:
        loop = asyncio.get_running_loop()
        load = await loop.run_in_executor(None, psutil.cpu_percent, 0.5)
        return f"{load} %"
    except Exception:
        return "Недоступно"


def human(n: int) -> str:
    units = ["б", "Кб", "Мб", "Гб", "Тб", "Пб"]
    x = float(n)
    for u in units:
        if x < 1024 or u == units[-1]:
            return f"{x:.2f} {u}"
        x /= 1024


def default_path() -> Path:
    if os.name == "nt":
        drive = os.environ.get("SystemDrive", "C:")
        return Path(drive + "\\")
    if "ANDROID_ROOT" in os.environ or "ANDROID_DATA" in os.environ:
        # for p in ("/storage/emulated/0", "/sdcard", str(Path.home())):
        #     if os.path.exists(p):
        #         return Path(p)
        return Path.cwd()
    return Path("/")


def disk_free(path: str | None = None) -> None:
    p = Path(path) if path else default_path()
    p = p if p.exists() else Path.cwd()

    total, used, free = shutil.disk_usage(p)
    return [human(total), human(used), human(free)]


async def get_system_info() -> str:
    mem = psutil.virtual_memory()
    cpu_freq = psutil.cpu_freq()
    cpu_cores_phys = psutil.cpu_count(logical=False) or "?"
    cpu_cores_logical = psutil.cpu_count(logical=True) or "?"

    boottime_task = await asyncio.create_task(
        asyncio.to_thread(lambda: get_boottime())
    )
    cpu_load_task = await asyncio.create_task(get_cpu_load())
    network_task = await asyncio.create_task(get_current_speed())
    temp_task = await asyncio.create_task(asyncio.to_thread(get_temperature))

    temp = f"Температура ↑|≈|↓: {temp_task}" if temp_task is not None else ""

    mem_total = mem.total / (1024**3)
    mem_avail = mem.available / (1024**3)
    mem_used = mem.used / (1024**3)

    disk = disk_free()

    return f"""⚙️ : Информация о хостинге:
    Время работы: {boottime_task}
    ОС: {platform.system()} {platform.release()}
    Процессор:
        Частота: {int(cpu_freq.current) if cpu_freq else "N/A"} МГц
        Ядра/Потоки: {cpu_cores_phys}/{cpu_cores_logical}
        Загрузка: {cpu_load_task}
        {temp}
    ОЗУ:
        Объём: {mem_total:.1f} ГБ
        Доступно: {mem_avail:.1f} ГБ
        Используется: {mem_used:.1f} ГБ
        Загрузка: {mem.percent} %
    Память:
        Всего: {disk[0]}
        Использовано: {disk[1]}
        Свободно: {disk[2]}
    Сеть:
        Загрузка: {network_task[0]} Мбит/с
        Выгрузка: {network_task[1]} Мбит/с
    """
