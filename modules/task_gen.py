import asyncio
import random
import time
from collections.abc import Callable
from datetime import datetime, timedelta
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
        self.key_name = key_name
        self.filename = filename
        self._task: asyncio.Task | None = None
        self._task_type: TaskType | None = None
        self._task_param: TaskParam | None = None
        self._random_delay: RandomDelay = None
        self._next_run_timestamp: float | None = None
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
                interval = task_param * 3600
            elif unit == "seconds":
                interval = task_param
            else:
                raise ValueError("unit must be 'hours' or 'seconds'")
            self._task_type = "interval"
            self._task_param = task_param
            await self._schedule_task(func, interval)
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
        except ValueError:
            raise ValueError("Неверный формат времени. Используйте 'HH:MM'.")

        self._next_run_timestamp = self._get_next_daily_run(target_time)
        data = await self._get_task_data()
        last_run = data.get("last_run")

        if last_run is None or last_run < self._next_run_timestamp - 86400:
            asyncio.create_task(self._safe_execute_with_delay(func))

        self._task = asyncio.create_task(self._daily_worker(func, target_time))

    async def _worker(self, func: Callable, interval: float) -> None:
        while True:
            await asyncio.sleep(max(0, self._next_run_timestamp - time.time()))
            await self._safe_execute_with_delay(func)
            self._next_run_timestamp = time.time() + interval

    async def _daily_worker(self, func: Callable, target_time) -> None:
        while True:
            await asyncio.sleep(max(0, self._next_run_timestamp - time.time()))
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
                await asyncio.get_event_loop().run_in_executor(None, func)
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

    async def _get_all_data(self) -> dict[str, Any]:
        try:
            async with aiofiles.open(self.filename, "rb") as f:
                return orjson.loads(await f.read())
        except (FileNotFoundError, orjson.JSONDecodeError):
            return {}

    async def _get_task_data(self) -> dict[str, Any]:
        return (await self._get_all_data()).get(self.key_name, {})

    async def _update_task_data(self, last_run: float) -> None:
        data = await self._get_all_data()
        data[self.key_name] = {
            "last_run": last_run,
            "task_type": self._task_type,
            "task_param": self._task_param,
            "random_delay": self._random_delay,
        }
        async with aiofiles.open(self.filename, "wb") as f:
            await f.write(orjson.dumps(data))

    async def info(self) -> float | None:
        data = await self._get_task_data()
        if not self._task or not self._next_run_timestamp:
            if not data:
                return None
            task_type = data.get("task_type")
            task_param = data.get("task_param")
            last_run = data.get("last_run")
            if not all((task_type, task_param, last_run)):
                return None
            if task_type == "interval":
                next_run = last_run + (task_param * 3600)
            else:
                try:
                    tm = datetime.strptime(task_param, "%H:%M").time()
                    next_run = self._get_next_daily_run(tm)
                except ValueError:
                    return None
            return max(0, next_run - time.time())
        return max(0, self._next_run_timestamp - time.time())

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        self._next_run_timestamp = None

    @classmethod
    async def cleanup(cls) -> None:
        for key in list(cls._instances):
            cls._instances[key].stop()
            del cls._instances[key]
