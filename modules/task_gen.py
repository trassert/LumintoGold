from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import aiofiles
import orjson
from loguru import logger

from . import pathes

logger.info(f"Загружен модуль {__name__}!")

TaskType = Literal["interval", "daily"]
TaskUnit = Literal["hours", "seconds"]
TaskParam = int | str
RandomDelay = tuple[int, int] | None

# Задержка первого сброса после старта (чтобы накопить несколько записей)
_FLUSH_INTERVAL = 30.0
_FIRST_FLUSH_DELAY = 5.0


class Generator:
    _instances: dict[str, Generator] = {}

    def __init__(self, key_name: str, filename: Path = pathes.tasks) -> None:
        logger.info(f"Инициализирован таск-ген {key_name}")
        self.key_name: str = key_name
        self.filename: Path = filename
        self._task: asyncio.Task | None = None
        self._task_type: TaskType | None = None
        self._task_param: TaskParam | None = None
        self._random_delay: RandomDelay = None
        self._next_run_timestamp: float = None
        # In-memory состояние, синхронизируется с файлом периодически.
        self._last_run: float | None = None
        self._flush_task: asyncio.Task | None = None
        Generator._instances[key_name] = self

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def _get_random_delay(self) -> float:
        if self._random_delay is None:
            return 0.0
        a, b = sorted(self._random_delay)
        return random.uniform(a, b)

    async def create(
        self,
        func: Callable,
        task_param: TaskParam,
        random_delay: RandomDelay = None,
        unit: TaskUnit = "hours",
    ) -> None:
        self.stop()
        self._random_delay = random_delay

        if isinstance(task_param, int):
            if unit == "hours":
                interval_seconds = task_param * 3600
            elif unit == "seconds":
                interval_seconds = task_param
            else:
                raise ValueError("unit must be 'hours' or 'seconds'")
            self._task_type = "interval"
            self._task_param = task_param
            await self._schedule_task(func, interval_seconds)
        elif isinstance(task_param, str):
            self._task_type = "daily"
            self._task_param = task_param
            await self._schedule_daily_task(func, task_param)
        else:
            raise ValueError("task_param must be int (interval) or str (HH:MM)")

    async def _schedule_task(self, func: Callable, interval: float) -> None:
        now = time.time()
        last_run = self._last_run

        if last_run is None or (now - last_run) >= interval:
            asyncio.create_task(self._safe_execute_with_delay(func))
            self._next_run_timestamp = now + interval
        else:
            self._next_run_timestamp = last_run + interval

        self._task = asyncio.create_task(self._worker(func, interval))
        self._ensure_flush_timer()

    async def _schedule_daily_task(self, func: Callable, time_str: str) -> None:
        try:
            target_time = datetime.strptime(time_str, "%H:%M").time()
        except ValueError as e:
            raise ValueError(
                "Неверный формат времени. Используйте 'HH:MM'."
            ) from e

        self._next_run_timestamp = self._get_next_daily_run(target_time)
        last_run = self._last_run

        if last_run is None or last_run < self._next_run_timestamp - 86400:
            asyncio.create_task(self._safe_execute_with_delay(func))

        self._task = asyncio.create_task(self._daily_worker(func, target_time))
        self._ensure_flush_timer()

    async def _worker(self, func: Callable, interval: float) -> None:
        while True:
            sleep_duration = max(0.0, self._next_run_timestamp - time.time())
            await asyncio.sleep(sleep_duration)
            await self._safe_execute_with_delay(func)
            self._next_run_timestamp = time.time() + interval

    async def _daily_worker(self, func: Callable, target_time) -> None:
        while True:
            sleep_duration = max(0.0, self._next_run_timestamp - time.time())
            await asyncio.sleep(sleep_duration)
            await self._safe_execute_with_delay(func)
            self._next_run_timestamp = self._get_next_daily_run(target_time)

    async def _safe_execute_with_delay(self, func: Callable) -> None:
        delay = self._get_random_delay()
        if delay > 0:
            await asyncio.sleep(delay)
        await self._safe_execute(func)

    async def _safe_execute(self, func: Callable) -> None:
        start = time.time()
        try:
            if asyncio.iscoroutinefunction(func):
                await func()
            else:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, func)
        except Exception:
            pass
        finally:
            self._last_run = start
            # Запись в файл не обязательна мгновенно — таймер сделает это позже.

    def _get_next_daily_run(self, target_time) -> float:
        now = datetime.now()
        target = datetime.combine(now.date(), target_time)
        if target <= now:
            target += timedelta(days=1)
        return target.timestamp()

    def _ensure_flush_timer(self) -> None:
        """Запускает периодический сброс in-memory состояния в файл."""
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(self._flush_loop())

    async def _flush_loop(self) -> None:
        """Ждёт первый flush и затем periodically пишет изменения."""
        await asyncio.sleep(_FIRST_FLUSH_DELAY)
        while True:
            await asyncio.sleep(_FLUSH_INTERVAL)
            await self._flush_once()

    async def _flush_once(self) -> None:
        """Атомарно читает файл, объединяет со своим состоянием, пишет обратно."""
        try:
            data = await self._read_all()
        except Exception:
            data = {}
        entry: dict[str, Any] = {
            "last_run": self._last_run,
            "task_type": self._task_type,
            "task_param": self._task_param,
            "random_delay": self._random_delay,
        }
        data[self.key_name] = entry
        try:
            async with aiofiles.open(self.filename, "wb") as f:
                await f.write(orjson.dumps(data, option=orjson.OPT_INDENT_2))
        except Exception:
            pass

    async def _read_all(self) -> dict[str, Any]:
        try:
            async with aiofiles.open(self.filename, "rb") as f:
                content = await f.read()
                if not content:
                    return {}
                return orjson.loads(content)
        except (FileNotFoundError, orjson.JSONDecodeError):
            return {}

    async def info(self) -> float | None:
        if self._task and self._next_run_timestamp is not None:
            return max(0.0, self._next_run_timestamp - time.time())
        # Fallback на чтение из файла только если in-memory пусто.
        if self._last_run is None:
            try:
                data = await self._read_all()
                entry = data.get(self.key_name, {})
            except Exception:
                return None
            task_type = entry.get("task_type")
            task_param = entry.get("task_param")
            last_run = entry.get("last_run")
        else:
            task_type = self._task_type
            task_param = self._task_param
            last_run = self._last_run
        if not task_type or task_param is None or last_run is None:
            return None
        if task_type == "interval" and isinstance(task_param, int):
            next_run = last_run + task_param * 3600
        elif task_type == "daily" and isinstance(task_param, str):
            try:
                target = datetime.strptime(task_param, "%H:%M").time()
            except ValueError:
                return None
            next_run = self._get_next_daily_run(target)
        else:
            return None
        return max(0.0, next_run - time.time())

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        self._next_run_timestamp = None
        # При остановке обязательно.flush — чтобы не потерять last_run.
        if self._last_run is not None:
            asyncio.create_task(self._flush_once())
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            self._flush_task = None

    @classmethod
    async def cleanup(cls) -> None:
        for instance in list(cls._instances.values()):
            instance.stop()
        cls._instances.clear()
