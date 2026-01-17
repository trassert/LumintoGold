import os
import asyncio
from typing import List, Optional, Union
import aiofiles
from loguru import logger

from . import pathes

logger.info(f"Загружен модуль {__name__}!")


class Notes:
    def __init__(
        self, number: Union[str, int], base_dir: str = pathes.notes
    ) -> None:
        self.number = str(number)
        self.base_dir = base_dir
        self.user_dir = os.path.join(self.base_dir, self.number)

    async def _ensure_user_dir(self) -> None:
        if not os.path.exists(self.user_dir):
            await asyncio.to_thread(os.makedirs, self.user_dir, exist_ok=True)

    def _normalize_name(self, name: str) -> str:
        """Приводит имя к нижнему регистру и проверяет на безопасность."""
        if not name or "/" in name or "\\" in name:
            logger.warning(f"{name} не прошла path-inject проверку!")
            raise ValueError("Invalid note name")
        return name.lower()

    async def add(self, name: str, text: str) -> bool:
        try:
            norm_name = self._normalize_name(name)
        except ValueError:
            return False
        await self._ensure_user_dir()
        filepath = os.path.join(self.user_dir, f"{norm_name}.txt")
        try:
            async with aiofiles.open(filepath, "w", encoding="utf-8") as f:
                await f.write(text)
            return True
        except (OSError, IOError):
            logger.warning(f"Не удалось записать в {filepath}.")
            return False

    async def delete(self, name: str) -> bool:
        try:
            norm_name = self._normalize_name(name)
        except ValueError:
            return False
        filepath = os.path.join(self.user_dir, f"{norm_name}.txt")
        try:
            if os.path.isfile(filepath):
                await asyncio.to_thread(os.remove, filepath)
                return True
            return False
        except (OSError, IOError):
            return False

    async def get(self, name: str) -> Optional[str]:
        try:
            norm_name = self._normalize_name(name)
        except ValueError:
            return None
        filepath = os.path.join(self.user_dir, f"{norm_name}.txt")
        try:
            if os.path.isfile(filepath):
                async with aiofiles.open(filepath, "r", encoding="utf-8") as f:
                    return await f.read()
            return None
        except (OSError, IOError):
            return None

    async def get_list(self) -> List[str]:
        """Возвращает список имён заметок в нижнем регистре, отсортированный по алфавиту."""
        try:
            if not os.path.isdir(self.user_dir):
                return []
            files = await asyncio.to_thread(os.listdir, self.user_dir)
            names = [
                f[:-4]
                for f in files
                if f.endswith(".txt")
                and os.path.isfile(os.path.join(self.user_dir, f))
            ]
            return sorted(names)
        except (OSError, IOError):
            logger.warning("Ошибка IO / OS")
            return []

    async def get_by_index(self, index: int) -> Optional[str]:
        if index < 1:
            return None
        names = await self.get_list()
        if index > len(names):
            return None
        note_name = names[index - 1]
        return await self.get(note_name)
