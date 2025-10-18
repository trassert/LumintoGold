import asyncio
import time
import random
from datetime import datetime, time as dt_time, timedelta
from typing import Union, Callable, Optional, Literal, Dict, Any, Tuple
import aiofiles
import orjson


TaskType = Literal["interval", "daily"]
TaskParam = Union[int, str]
RandomDelay = Optional[Tuple[int, int]]


class Generator:
    _instances: Dict[str, "Generator"] = {}

    def __init__(self, key_name: str, filename: str = "tasks.json"):
        self.key_name = key_name
        self.filename = filename
        self._task: Optional[asyncio.Task] = None
        self._task_type: Optional[TaskType] = None
        self._task_param: Optional[TaskParam] = None
        self._random_delay: RandomDelay = None
        self._next_run_timestamp: Optional[float] = None
        Generator._instances[key_name] = self

    def _get_random_delay(self) -> float:
        if self._random_delay is None:
            return 0.0
        a, b = self._random_delay

        if a > b:
            a, b = b, a
        return random.uniform(a, b)

    async def create(
        self,
        func: Callable,
        task_param: TaskParam,
        random_delay: RandomDelay = None,
    ) -> None:
        self.stop()
        self._random_delay = random_delay

        if isinstance(task_param, int):
            self._task_type = "interval"
            self._task_param = task_param
            await self._create_interval_task(func, task_param)
        elif isinstance(task_param, str):
            self._task_type = "daily"
            self._task_param = task_param
            await self._create_daily_task(func, task_param)
        else:
            self._task_type = None
            self._task_param = None
            self._random_delay = None
            raise ValueError(
                "Параметр времени должен быть int (часы) или str (HH:MM)"
            )

    async def _create_interval_task(self, func: Callable, hours: int) -> None:
        """Создает задачу с интервальным выполнением"""
        interval_seconds = hours * 3600

        task_data = await self._get_task_data()
        last_run = task_data.get("last_run")
        current_time = time.time()

        if last_run is None or (current_time - last_run) >= interval_seconds:
            asyncio.create_task(self._safe_execute_with_delay(func))
            self._next_run_timestamp = current_time + interval_seconds
        else:
            self._next_run_timestamp = last_run + interval_seconds

        self._task = asyncio.create_task(
            self._interval_worker(func, interval_seconds)
        )

    async def _create_daily_task(self, func: Callable, time_str: str) -> None:
        """Создает задачу с ежедневным выполнением"""
        try:
            target_time = datetime.strptime(time_str, "%H:%M").time()
        except ValueError:
            raise ValueError("Неверный формат времени. Используйте 'HH:MM'.")

        self._next_run_timestamp = self._get_next_daily_run(target_time)

        task_data = await self._get_task_data()
        last_run = task_data.get("last_run")

        if last_run is None or last_run < self._next_run_timestamp - 86400:
            asyncio.create_task(self._safe_execute_with_delay(func))

        self._task = asyncio.create_task(self._daily_worker(func, target_time))

    async def _interval_worker(self, func: Callable, interval: int):
        while True:
            current_time = time.time()
            wait_time = self._next_run_timestamp - current_time

            if wait_time > 0:
                await asyncio.sleep(wait_time)

            await self._safe_execute_with_delay(func)

            self._next_run_timestamp = time.time() + interval

    async def _daily_worker(self, func: Callable, target_time: dt_time):
        """Рабочий для ежедневных задач"""
        while True:
            current_time = time.time()
            wait_time = self._next_run_timestamp - current_time

            if wait_time > 0:
                await asyncio.sleep(wait_time)

            await self._safe_execute_with_delay(func)

            self._next_run_timestamp = self._get_next_daily_run(target_time)

    async def _safe_execute_with_delay(self, func: Callable) -> None:
        """Добавляет случайную задержку, затем безопасно выполняет функцию"""

        delay = self._get_random_delay()
        if delay > 0:
            print(
                f"[{self.key_name}] Добавляем случайную задержку: {delay:.2f} сек."
            )
            await asyncio.sleep(delay)

        await self._safe_execute(func)

    async def _safe_execute(self, func: Callable) -> None:
        start_time = time.time()
        try:
            if asyncio.iscoroutinefunction(func):
                await func()
            else:
                await asyncio.get_event_loop().run_in_executor(None, func)
        except Exception as e:
            print(f"Ошибка выполнения задачи '{self.key_name}': {e}")
        finally:
            await self._update_task_data(start_time)

    def _get_next_daily_run(self, target_time: dt_time) -> float:
        """Вычисляет временную метку следующего запуска для ежедневной задачи"""
        now = datetime.now()
        target_datetime = datetime.combine(now.date(), target_time)

        if target_datetime <= now:
            target_datetime += timedelta(days=1)

        return target_datetime.timestamp()

    async def _get_all_data(self) -> Dict[str, Any]:
        """Получает все данные из файла"""
        try:
            async with aiofiles.open(self.filename, "rb") as f:
                content = await f.read()
                return orjson.loads(content)
        except (FileNotFoundError, orjson.JSONDecodeError):
            return {}

    async def _get_task_data(self) -> Dict[str, Any]:
        all_data = await self._get_all_data()
        return all_data.get(self.key_name, {})

    async def _update_task_data(self, last_run_time: float) -> None:
        all_data = await self._get_all_data()

        all_data[self.key_name] = {
            "last_run": last_run_time,
            "task_type": self._task_type,
            "task_param": self._task_param,
            "random_delay": self._random_delay,
        }

        async with aiofiles.open(self.filename, "wb") as f:
            await f.write(orjson.dumps(all_data))

    async def info(self) -> Optional[float]:
        if not self._task or not self._next_run_timestamp:
            task_data = await self._get_task_data()
            if not task_data:
                return None

            task_type = task_data.get("task_type")
            task_param = task_data.get("task_param")
            last_run = task_data.get("last_run")

            if not last_run or not task_type or not task_param:
                return None

            next_run = 0.0
            if task_type == "interval" and isinstance(task_param, int):
                interval_seconds = task_param * 3600
                next_run = last_run + interval_seconds
            elif task_type == "daily" and isinstance(task_param, str):
                try:
                    target_time = datetime.strptime(task_param, "%H:%M").time()
                    next_run = self._get_next_daily_run(target_time)
                except ValueError:
                    return None
            else:
                return None

            time_until_next = next_run - time.time()
            return max(0, time_until_next)

        time_until_next = self._next_run_timestamp - time.time()
        return max(0, time_until_next)

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        self._next_run_timestamp = None

    @classmethod
    async def cleanup(cls) -> None:
        for instance in list(cls._instances.values()):
            instance.stop()
            del cls._instances[instance.key_name]
