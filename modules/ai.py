from __future__ import annotations

from pathlib import Path

import aiofiles
import orjson
from groq import AsyncGroq
from httpx import AsyncClient
from loguru import logger

from . import pathes

logger.info(f"Загружен модуль {__name__}!")

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta"


class AllModelsFailed(RuntimeError):
    """Ни одна включённая модель не дала ответ."""


class AIClient:
    def __init__(
        self,
        groq_key: str | None = None,
        gemini_key: str | None = None,
        groq_proxy: str | None = None,
        gemini_proxy: str | None = None,
        chats_dir: Path = pathes.ai,
        models: list[tuple[str, str]] | None = None,
        disabled_models: list[str] | None = None,
        voice_model: str = "whisper-large-v3-turbo",
        temperature: float = 1.0,
        max_tokens: int = 2048,
        request_timeout: int = 60,
    ):
        self.groq_key = groq_key
        self.gemini_key = gemini_key
        self.groq_proxy = groq_proxy
        self.gemini_proxy = gemini_proxy
        self.models = list(models or [])
        self.disabled = set(disabled_models or [])
        self.voice_model = voice_model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.request_timeout = request_timeout
        self.chats_dir = chats_dir or Path(pathes.ai)
        self.chats_dir.mkdir(parents=True, exist_ok=True)
        self.groq: AsyncGroq | None = None
        self.gemini: AsyncClient | None = None

    def init_client(self) -> None:
        """Инициализирует клиентов провайдеров, для которых есть токен."""
        if self.groq_key:
            try:
                http_client = (
                    AsyncClient(proxy=self.groq_proxy)
                    if self.groq_proxy
                    else None
                )
                self.groq = AsyncGroq(
                    api_key=self.groq_key, http_client=http_client
                )
            except Exception:
                logger.exception("Не удалось инициализировать Groq-клиент")
                self.groq = None
        if self.gemini_key:
            try:
                self.gemini = AsyncClient(
                    base_url=GEMINI_API_URL,
                    headers={"x-goog-api-key": self.gemini_key},
                    timeout=self.request_timeout,
                    proxy=self.gemini_proxy or None,
                )
            except Exception:
                logger.exception("Не удалось инициализировать Gemini-клиент")
                self.gemini = None

    async def close(self) -> None:
        """Закрывает клиентов и HTTP-сессии."""
        if self.groq:
            await self.groq.close()
            self.groq = None
        if self.gemini:
            await self.gemini.aclose()
            self.gemini = None

    def enabled_models(self) -> list[tuple[str, str]]:
        """Модели с токеном, которые не отключены для этого клиента."""
        keys = {"groq": self.groq_key, "gemini": self.gemini_key}
        return [
            (provider, model)
            for provider, model in self.models
            if keys.get(provider) and f"{provider}:{model}" not in self.disabled
        ]

    def chat(self, chat_id: str) -> AIChatSession:
        """Создаёт сессию чата для конкретного chat_id."""
        return AIChatSession(
            chat_id=chat_id,
            client=self,
            chats_dir=self.chats_dir,
        )

    async def complete(
        self,
        provider: str,
        model: str,
        messages: list[dict[str, str]],
    ) -> str:
        """Запрашивает ответ у конкретной модели."""
        if provider == "groq":
            return await self._groq_complete(model, messages)
        if provider == "gemini":
            return await self._gemini_complete(model, messages)
        raise ValueError(f"Неизвестный AI-провайдер: {provider}")

    async def transcribe_voice(self, number: str, voice_id: str) -> str:
        """Транскрибирует OGG-файл через Whisper."""
        client = self._require_groq()
        voice_path = pathes.voice / number / f"voice_{voice_id}.ogg"
        if not voice_path.exists():
            raise FileNotFoundError(f"Voice file not found: {voice_path}")
        async with aiofiles.open(voice_path, "rb") as f:
            audio_data = await f.read()
        try:
            transcription = await client.audio.transcriptions.create(
                file=("audio.ogg", audio_data),
                model=self.voice_model,
                temperature=0.0,
                response_format="verbose_json",
            )
            return transcription.text.strip()
        finally:
            voice_path.unlink(missing_ok=True)

    async def _groq_complete(
        self, model: str, messages: list[dict[str, str]]
    ) -> str:
        response = await self._require_groq().chat.completions.create(
            model=model,
            messages=messages,
            temperature=self.temperature,
            max_completion_tokens=self.max_tokens,
            top_p=1,
            stop=None,
            timeout=self.request_timeout,
        )
        return (response.choices[0].message.content or "").strip()

    async def _gemini_complete(
        self, model: str, messages: list[dict[str, str]]
    ) -> str:
        contents = [
            {
                "role": "model" if item["role"] == "assistant" else "user",
                "parts": [{"text": item["content"]}],
            }
            for item in messages
        ]
        response = await self._require_gemini().post(
            f"/models/{model}:generateContent",
            json={
                "contents": contents,
                "generationConfig": {
                    "temperature": self.temperature,
                    "maxOutputTokens": self.max_tokens,
                },
            },
            timeout=self.request_timeout,
        )
        response.raise_for_status()
        data = response.json()
        candidates = data.get("candidates") or []
        if not candidates:
            reason = (data.get("promptFeedback") or {}).get("blockReason")
            raise RuntimeError(
                f"Gemini: нет кандидатов ({reason or 'unknown'})"
            )
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(
            part.get("text") or "" for part in parts if not part.get("thought")
        ).strip()
        if not text:
            raise RuntimeError("Gemini: пустой ответ")
        return text

    def _require_groq(self) -> AsyncGroq:
        if self.groq is None:
            raise RuntimeError("Groq не инициализирован: нет токена.")
        return self.groq

    def _require_gemini(self) -> AsyncClient:
        if self.gemini is None:
            raise RuntimeError("Gemini не инициализирован: нет токена.")
        return self.gemini


class AIChatSession:
    def __init__(self, chat_id: str, client: AIClient, chats_dir: Path):
        self.chat_id = chat_id
        self.client = client
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

    async def send(self, user_message: str) -> tuple[str, str]:
        if not self._history:
            await self.load()
        messages = [
            *self._history,
            {"role": "user", "content": user_message},
        ]
        models = self.client.enabled_models()
        if not models:
            raise AllModelsFailed("Нет включённых моделей с токеном.")
        for provider, model in models:
            try:
                ai_reply = await self.client.complete(provider, model, messages)
            except Exception as exc:
                logger.warning(f"AI: {provider}:{model} — {exc}")
                continue
            if not ai_reply.strip():
                logger.warning(f"AI: {provider}:{model} — пустой ответ")
                continue
            self._history = [
                *messages,
                {"role": "assistant", "content": ai_reply},
            ]
            await self._save()
            return ai_reply, model
        raise AllModelsFailed(f"Все модели недоступны: {len(models)}")

    async def clear(self) -> None:
        self._history = []
        if self._path.exists():
            self._path.unlink()

    @property
    def history(self) -> list[dict[str, str]]:
        return self._history.copy()
