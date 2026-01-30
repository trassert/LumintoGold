from pathlib import Path
from typing import List, Dict
import orjson
import aiofiles
import aiohttp

from . import config, pathes
from loguru import logger

logger.info(f"Загружен модуль {__name__}!")


class Chat:
    def __init__(
        self,
        chat_id: str,
        api_key: str = None,
        chats_dir: Path = None,
        model: str = None,
    ):
        self.model = model or config.config.ai_model
        self.chat_id = chat_id
        self.chats_dir = chats_dir or Path(pathes.ai)
        self.api_key: str = api_key
        self._history: List[Dict[str, str]] = []
        self._path = self.chats_dir / f"{self.chat_id}.json"
        self.chats_dir.mkdir(parents=True, exist_ok=True)

    async def load(self) -> None:
        """Загружает историю из файла."""
        if not self._path.exists():
            self._history = []
            return
        async with aiofiles.open(self._path, "rb") as f:
            content = await f.read()
            self._history = orjson.loads(content) if content else []

    async def _save(self) -> None:
        """Сохраняет текущую историю в файл."""
        data = orjson.dumps(self._history)
        async with aiofiles.open(self._path, "wb") as f:
            await f.write(data)

    async def send(self, user_message: str) -> str:
        """Отправляет сообщение и возвращает ответ ИИ."""
        if not self.api_key:
            return "Нет токена ИИ."
        if not self._history:
            await self.load()

        self._history.append({"role": "user", "content": user_message})

        payload = {
            "model": self.model,
            "messages": self._history,
            "temperature": 0.7,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://t.me/lumintogold",  # убран лишний пробел
            "X-Title": "lumintogold",
            "Content-Type": "application/json",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    config.config.url.openrouter, json=payload, headers=headers
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        raise RuntimeError(
                            f"OpenRouter error {resp.status}: {error_text}"
                        )
                    data = await resp.json()
        except Exception as e:
            ai_reply = f"[Ошибка ИИ: {e}]"
            self._history.append({"role": "assistant", "content": ai_reply})
            await self._save()
            return ai_reply

        ai_reply = data["choices"][0]["message"]["content"].strip()
        self._history.append({"role": "assistant", "content": ai_reply})
        await self._save()
        return ai_reply

    async def clear(self) -> None:
        """Очищает историю и удаляет файл."""
        self._history = []
        if self._path.exists():
            self._path.unlink()

    @property
    def history(self) -> List[Dict[str, str]]:
        """Текущая история (только для чтения)."""
        return self._history.copy()
