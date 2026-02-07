import asyncio
import os

import aiofiles
from loguru import logger
from telethon import TelegramClient

from . import pathes

logger.info(f"Загружен модуль {__name__}!")


class Notes:
    def __init__(self, number: str | int, base_dir: str = pathes.notes) -> None:
        """Метод инициализации."""
        self.number = str(number)
        self.base_dir = base_dir
        self.user_dir = os.path.join(self.base_dir, self.number)
        logger.info(f"Инициализирован класс заметок для {self.number}")

    async def _ensure_user_dir(self) -> None:
        if not os.path.exists(self.user_dir):
            await asyncio.to_thread(os.makedirs, self.user_dir, exist_ok=True)

    def _normalize_name(self, name: str) -> str:
        if not name or "/" in name or "\\" in name:
            logger.warning("Сработала безопасность на патчи.")
            raise ValueError("Invalid name")
        return name.lower()

    async def add(self, name: str, text: str, media=None, client: TelegramClient = None) -> bool:
        try:
            norm_name = self._normalize_name(name)
            await self._ensure_user_dir()
            base_path = os.path.join(self.user_dir, norm_name)

            async with aiofiles.open(f"{base_path}.txt", "w", encoding="utf-8") as f:
                await f.write(text)

            img_path = f"{base_path}.jpg"
            if media and client:
                await client.download_media(media, file=img_path)
            elif media and not client:
                logger.error("Для сохранения фото не передан клиент!")
                return False
            else:
                if os.path.exists(img_path):
                    os.remove(img_path)
            return True
        except Exception:
            logger.trace("Ошибка в Notes.add")
            return False

    async def get(self, name: str) -> dict | None:
        try:
            norm_name = self._normalize_name(name)
            base_path = os.path.join(self.user_dir, norm_name)
            txt_path = f"{base_path}.txt"
            img_path = f"{base_path}.jpg"

            if not os.path.exists(txt_path):
                return None

            async with aiofiles.open(txt_path, encoding="utf-8") as f:
                text = await f.read()

            return {
                "text": text,
                "media": img_path if os.path.exists(img_path) else None,
            }
        except Exception:
            return None

    async def get_list(self) -> list[str]:
        if not os.path.isdir(self.user_dir):
            return []
        files = os.listdir(self.user_dir)
        return sorted([f[:-4] for f in files if f.endswith(".txt")])

    async def get_by_index(self, index: int) -> dict | None:
        names = await self.get_list()
        if 1 <= index <= len(names):
            return await self.get(names[index - 1])
        return None

    async def delete(self, name: str) -> bool:
        try:
            norm_name = self._normalize_name(name)
            base_path = os.path.join(self.user_dir, norm_name)
            for ext in [".txt", ".jpg"]:
                p = base_path + ext
                if os.path.exists(p):
                    os.remove(p)
            return True
        except Exception:
            return False
