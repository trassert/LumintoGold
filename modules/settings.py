import os
from typing import Any
from loguru import logger

import aiofiles
import orjson

logger.info(f"Загружен модуль {__name__}!")

default = {
    "typings": "..",
    "typing.delay": 0.05,
    "iris.farm": False,
    "iceyes.bonus": False,
    "block.voice": False,
    "mask.read": [],
    "luminto.reactions": True,
    "ai.token": None,
    "use.ipv6": False,
    "auto.online": False,
    "token.geoapify": "",
    "token.openweathermap": "",
    "flood.msg": "Варн\nФлуд",
    "autochat.chats": [],
    "autochat.ad_chat": -1002783775634,
    "autochat.ad_id": 474,
    "autochat.delay": 3600,
    "autochat.enabled": False,
    "tg2vk.enabled": False,
    "tg2vk.chat": None,
    "tg2vk.vk_token": None,
    "tg2vk.vk_group": None,
    "battery.status": False,
    "battery.chat": None,
    "battery.msg_no": "❌ : Нет зарядки!",
    "battery.msg_yes": "✅ : Зарядка восстановлена."
}


class UBSettings:
    def __init__(self, number: str, path: str = "") -> None:
        self.filename = os.path.join(path, f"{number}.json")
        self._data = None

    async def _ensure_loaded(self, forced=False) -> None:
        if self._data is None or forced:
            if os.path.exists(self.filename):
                async with aiofiles.open(self.filename, "rb") as f:
                    contents = await f.read()
                    self._data = orjson.loads(contents)
            else:
                self._data = {}

    def _sync_ensure_loaded(self, forced=False) -> None:
        if self._data is None or forced:
            if os.path.exists(self.filename):
                with open(self.filename, "rb") as f:
                    self._data = orjson.loads(f.read())
            else:
                self._data = {}

    async def make(self, api_id: int, api_hash: str) -> None:
        self._data = {"api_id": api_id, "api_hash": api_hash}
        async with aiofiles.open(self.filename, "wb") as f:
            content = orjson.dumps(self._data, option=orjson.OPT_INDENT_2)
            await f.write(content)

    async def get(self, name_setting: str, if_none: Any = None) -> Any:
        await self._ensure_loaded()
        if if_none is not None:
            return self._data.get(name_setting, if_none)
        return self._data.get(name_setting, default[name_setting])

    def sync_get(self, name_setting: str, if_none: Any = None) -> Any:
        self._sync_ensure_loaded()
        if if_none is not None:
            return self._data.get(name_setting, if_none)
        return self._data.get(name_setting, default[name_setting])

    async def set(self, key: str, value: Any) -> None:
        await self._ensure_loaded()
        self._data[key] = value
        async with aiofiles.open(self.filename, "wb") as f:
            content = orjson.dumps(self._data, option=orjson.OPT_INDENT_2)
            await f.write(content)

    async def remove(self, key: str):
        await self._ensure_loaded()
        del self._data[key]
        async with aiofiles.open(self.filename, "wb") as f:
            content = orjson.dumps(self._data, option=orjson.OPT_INDENT_2)
            await f.write(content)