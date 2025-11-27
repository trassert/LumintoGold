import os
from typing import Any

import aiofiles
import orjson

default = {
    "typings": "..",
    "typing.delay": 0.05,
    "iris.farm": False,
    "block.voice": False,
    "mask.read": [],
    "luminto.reactions": True,
    "ai.token": None,
    "ai.proxy": None,
    "use.ipv6": False
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

    async def set(self, key: str, value: Any) -> None:
        await self._ensure_loaded()
        self._data[key] = value
        async with aiofiles.open(self.filename, "wb") as f:
            content = orjson.dumps(self._data, option=orjson.OPT_INDENT_2)
            await f.write(content)
