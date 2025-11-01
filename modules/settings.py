import os
from typing import Any

import aiofiles
import orjson


class UBSettings:
    def __init__(self, number: str, path: str = "") -> None:
        self.filename = os.path.join(path, f"{number}.json")
        self._data = None

    async def _ensure_loaded(self) -> None:
        if self._data is None:
            if os.path.exists(self.filename):
                async with aiofiles.open(self.filename, "rb") as f:
                    contents = await f.read()
                    self._data = orjson.loads(contents)
            else:
                self._data = {}

    async def make(self, api_id: int, api_hash: str) -> None:
        self._data = {"api_id": api_id, "api_hash": api_hash}
        async with aiofiles.open(self.filename, "wb") as f:
            content = orjson.dumps(self._data)
            await f.write(content)

    async def get(self, name_setting: str, if_none: Any = None) -> Any:
        await self._ensure_loaded()
        return self._data.get(name_setting, if_none)

    async def set(self, key: str, value: Any) -> None:
        await self._ensure_loaded()
        self._data[key] = value
        async with aiofiles.open(self.filename, "wb") as f:
            content = orjson.dumps(self._data)
            await f.write(content)
