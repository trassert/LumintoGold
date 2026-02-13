from __future__ import annotations

from pathlib import Path

import aiofiles
import orjson
from groq import AsyncGroq
from httpx import AsyncClient
from loguru import logger

from . import pathes

logger.info(f"Загружен модуль {__name__}!")


class GroqClient:
    def __init__(
        self,
        api_key: str = None,
        proxy: str = None,
        chats_dir: Path = pathes.ai,
        chat_model: str = "openai/gpt-oss-120b",
        voice_model: str = "whisper-large-v3-turbo",
    ):
        self.api_key = api_key
        self.proxy = proxy
        self.chat_model = chat_model
        self.voice_model = voice_model
        self.chats_dir = chats_dir or Path(pathes.ai)
        self.chats_dir.mkdir(parents=True, exist_ok=True)
        self.client: AsyncGroq | None = None

    def init_client(self) -> None:
        """Инициализирует AsyncGroq с прокси (если указан)."""
        if not self.api_key:
            raise ValueError("API key is required to initialize Groq client.")
        http_client = AsyncClient(proxy=self.proxy) if self.proxy else None
        self.client = AsyncGroq(api_key=self.api_key, http_client=http_client)

    async def close(self) -> None:
        """Закрывает клиент и HTTP-сессию."""
        if self.client:
            await self.client.close()
            self.client = None

    def chat(self, chat_id: str) -> GroqChatSession:
        """Создаёт сессию чата для конкретного chat_id."""
        if self.client is None:
            raise RuntimeError("Groq client not initialized. Call init_client() first.")
        return GroqChatSession(
            chat_id=chat_id,
            client=self.client,
            chats_dir=self.chats_dir,
            model=self.chat_model,
        )

    async def transcribe_voice(self, number: str, voice_id: str) -> str:
        """Транскрибирует OGG-файл через Whisper."""
        if self.client is None:
            raise RuntimeError("Groq client not initialized. Call init_client() first.")
        voice_path = pathes.voice / number / f"voice_{voice_id}.ogg"
        if not voice_path.exists():
            raise FileNotFoundError(f"Voice file not found: {voice_path}")
        async with aiofiles.open(voice_path, "rb") as f:
            audio_data = await f.read()
        try:
            transcription = await self.client.audio.transcriptions.create(
                file=("audio.ogg", audio_data),
                model=self.voice_model,
                temperature=0.0,
                response_format="verbose_json",
            )
            return transcription.text.strip()
        finally:
            voice_path.unlink(missing_ok=True)


class GroqChatSession:
    def __init__(
        self,
        chat_id: str,
        client: AsyncGroq,
        chats_dir: Path,
        model: str,
    ):
        self.chat_id = chat_id
        self.client = client
        self.model = model
        self._path = chats_dir / f"{chat_id}.json"
        self._history: list[dict[str, str]] = []

    async def load(self) -> None:
        if not self._path.exists():
            self._history = []
            return
        async with aiofiles.open(self._path, "rb") as f:
            content = await f.read()
            self._history = orjson.loads(content) if content else []

    async def _save(self) -> None:
        data = orjson.dumps(self._history)
        async with aiofiles.open(self._path, "wb") as f:
            await f.write(data)

    async def send(self, user_message: str) -> str:
        if not self._history:
            await self.load()
        self._history.append({"role": "user", "content": user_message})
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=self._history,
                temperature=0.7,
                max_tokens=8192,
                top_p=1.0,
            )
            ai_reply = response.choices[0].message.content.strip()
        except Exception as e:
            ai_reply = f"[Ошибка Groq: {e}]"
        self._history.append({"role": "assistant", "content": ai_reply})
        await self._save()
        return ai_reply

    async def clear(self) -> None:
        self._history = []
        if self._path.exists():
            self._path.unlink()

    @property
    def history(self) -> list[dict[str, str]]:
        return self._history.copy()
