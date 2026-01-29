import asyncio
import random
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Optional, Union

import aiofiles
import orjson
from loguru import logger

from . import pathes


logger.info(f"Загружен модуль {__name__}!")

TaskType = Literal["interval", "daily"]
TaskUnit = Literal["hours", "seconds"]
TaskParam = Union[int, str]
RandomDelay = Optional[tuple[int, int]]


class Generator:
    _instances: dict[str, "Generator"] = {}

    def __init__(self, key_name: str, filename: str = pathes.tasks) -> None:
        logger.info(f"Инициализирован таск-ген {key_name}")
        self.key_name: str = key_name
        self.filename: str = filename
        self._task: Optional[asyncio.Task] = None
        self._task_type: Optional[TaskType] = None
        self._task_param: Optional[TaskParam] = None
        self._random_delay: RandomDelay = None
        self._next_run_timestamp: Optional[float] = None
        Generator._instances[key_name] = self

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
        data = await self._get_task_data()
        now = time.time()
        last_run = data.get("last_run")

        if last_run is None or (now - last_run) >= interval:
            asyncio.create_task(self._safe_execute_with_delay(func))
            self._next_run_timestamp = now + interval
        else:
            self._next_run_timestamp = last_run + interval

        self._task = asyncio.create_task(self._worker(func, interval))

    async def _schedule_daily_task(self, func: Callable, time_str: str) -> None:
        try:
            target_time = datetime.strptime(time_str, "%H:%M").time()
        except ValueError as e:
            raise ValueError(
                "Неверный формат времени. Используйте 'HH:MM'."
            ) from e

        self._next_run_timestamp = self._get_next_daily_run(target_time)
        data = await self._get_task_data()
        last_run = data.get("last_run")

        if last_run is None or last_run < self._next_run_timestamp - 86400:
            asyncio.create_task(self._safe_execute_with_delay(func))

        self._task = asyncio.create_task(self._daily_worker(func, target_time))

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
            await self._update_task_data(start)

    def _get_next_daily_run(self, target_time) -> float:
        now = datetime.now()
        target = datetime.combine(now.date(), target_time)
        if target <= now:
            target += timedelta(days=1)
        return target.timestamp()

    async def _ensure_directory_exists(self) -> None:
        directory = Path(self.filename).parent
        directory.mkdir(parents=True, exist_ok=True)

    async def _get_all_data(self) -> dict[str, Any]:
        await self._ensure_directory_exists()
        try:
            async with aiofiles.open(self.filename, "rb") as f:
                content = await f.read()
                if not content:
                    return {}
                return orjson.loads(content)
        except (FileNotFoundError, orjson.JSONDecodeError):
            return {}

    async def _get_task_data(self) -> dict[str, Any]:
        return (await self._get_all_data()).get(self.key_name, {})

    async def _update_task_data(self, last_run: float) -> None:
        await self._ensure_directory_exists()
        data = await self._get_all_data()
        data[self.key_name] = {
            "last_run": last_run,
            "task_type": self._task_type,
            "task_param": self._task_param,
            "random_delay": self._random_delay,
        }
        async with aiofiles.open(self.filename, "wb") as f:
            await f.write(orjson.dumps(data, option=orjson.OPT_INDENT_2))

    async def info(self) -> Optional[float]:
        data = await self._get_task_data()
        if not self._task or self._next_run_timestamp is None:
            if not data:
                return None
            task_type = data.get("task_type")
            task_param = data.get("task_param")
            last_run = data.get("last_run")
            if not all(
                (task_type, task_param is not None, last_run is not None)
            ):
                return None
            if task_type == "interval":
                if not isinstance(task_param, int):
                    return None
                next_run = last_run + (task_param * 3600)
            elif task_type == "daily":
                if not isinstance(task_param, str):
                    return None
                try:
                    tm = datetime.strptime(task_param, "%H:%M").time()
                    next_run = self._get_next_daily_run(tm)
                except ValueError:
                    return None
            else:
                return None
            return max(0.0, next_run - time.time())
        return max(0.0, self._next_run_timestamp - time.time())

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        self._next_run_timestamp = None

    @classmethod
    async def cleanup(cls) -> None:
        for key in list(cls._instances):
            instance = cls._instances[key]
            instance.stop()
            del cls._instances[key]
