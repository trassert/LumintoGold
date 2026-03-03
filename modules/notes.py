import asyncio
from typing import TYPE_CHECKING

import aiofiles
from loguru import logger
from telethon import TelegramClient

from . import pathes

if TYPE_CHECKING:
    from pathlib import Path

logger.info(f"Загружен модуль {__name__}!")


class Notes:
    def __init__(self, number: str | int, base_dir: Path = pathes.notes) -> None:
        """Метод инициализации."""
        self.number = str(number)
        self.base_dir = base_dir
        self.user_dir = self.base_dir / self.number
        logger.info(f"Инициализирован класс заметок для {self.number}")

    async def _ensure_user_dir(self) -> None:
        if not self.user_dir.exists():
            await asyncio.to_thread(self.user_dir.mkdir, parents=True, exist_ok=True)

    def _normalize_name(self, name: str) -> str:
        if not name or "/" in name or "\\" in name:
            logger.warning("Сработала безопасность на патчи.")
            raise ValueError("Invalid name")
        return name.lower()

    async def add(self, name: str, text: str, client: TelegramClient, media=None) -> bool:
        try:
            norm_name = self._normalize_name(name)
            await self._ensure_user_dir()
            base_path = self.user_dir / f"{norm_name}.txt"

            async with aiofiles.open(base_path, "w", encoding="utf-8") as f:
                await f.write(text)

            img_path = self.user_dir / f"{norm_name}.jpg"
            if media and client:
                await client.download_media(media, file=img_path)
            elif media and not client:
                logger.error("Для сохранения фото не передан клиент!")
                return False
            else:
                if img_path.exists():
                    img_path.unlink()
            return True
        except Exception:
            logger.trace("Ошибка в Notes.add")
            return False

    async def get(self, name: str) -> dict | None:
        try:
            norm_name = self._normalize_name(name)
            base_path = self.user_dir / norm_name
            txt_path = base_path.with_suffix(".txt")
            img_path = base_path.with_suffix(".jpg")

            if not txt_path.exists():
                return None

            async with aiofiles.open(txt_path, encoding="utf-8") as f:
                text = await f.read()

            return {
                "text": text,
                "media": img_path if img_path.exists() else None,
            }
        except Exception:
            return None

    async def get_list(self) -> list[str]:
        if not self.user_dir.exists():
            return []
        return sorted(f.stem for f in self.user_dir.iterdir() if f.suffix == ".txt")

    async def get_by_index(self, index: int) -> dict | None:
        names = await self.get_list()
        if 1 <= index <= len(names):
            return await self.get(names[index - 1])
        return None

    async def delete(self, name: str) -> bool:
        try:
            norm_name = self._normalize_name(name)
            base_path = self.user_dir / norm_name
            for ext in [".txt", ".jpg"]:
                p = base_path.with_suffix(ext)
                if p.exists():
                    p.unlink()
            return True
        except Exception:
            return False
