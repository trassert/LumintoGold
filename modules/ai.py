from __future__ import annotations

import os
from pathlib import Path

import aiofiles
import orjson
from loguru import logger
from openai import AsyncOpenAI

from . import pathes

logger.info(f"Загружен модуль {__name__}!")


class AllModelsFailed(RuntimeError):
    """Модель не ответила."""


class AIClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "auto",
        voice_model: str = "whisper-large-v3-turbo",
        temperature: float = 1.0,
        max_tokens: int = 2048,
        request_timeout: int = 60,
        chats_dir: Path = pathes.ai,
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.model = (
            model if model in ("auto", "auto:fast", "auto:smart") else "auto"
        )
        self.voice_model = voice_model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.request_timeout = request_timeout
        self.chats_dir = (chats_dir or Path(pathes.ai)).resolve()
        self.chats_dir.mkdir(parents=True, exist_ok=True)
        self.client: AsyncOpenAI | None = None

    def init_client(self) -> bool:
        if not self.api_key or not self.base_url:
            return False
        try:
            import httpx2

            http_client = httpx2.AsyncClient(trust_env=False)
            self.client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.request_timeout,
                max_retries=0,
                http_client=http_client,
            )
            return True
        except Exception:
            logger.exception("Не удалось инициализировать AI-клиент")
            self.client = None
            return False

    async def close(self) -> None:
        if self.client is not None:
            await self.client.close()
            self.client = None

    def chat(self, chat_id: str) -> AIChatSession:
        return AIChatSession(chat_id=chat_id, client=self)

    async def complete(
        self, messages: list[dict[str, str]], model: str
    ) -> tuple[str, str]:
        self._require()
        response = await self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        answer = response.choices[0].message.content or ""
        # router may echo back the model alias it used
        used_model = response.model or model
        return answer, used_model

    async def transcribe_voice(self, number: str, voice_id: int) -> str:
        self._require()
        file_path = pathes.voice / number / f"voice_{voice_id}.ogg"
        async with aiofiles.open(file_path, "rb") as f:
            audio_bytes = await f.read()
        res = await self.client.audio.transcriptions.create(
            model=self.voice_model,
            file=("voice.ogg", audio_bytes),
            response_format="text",
        )
        await aiofiles.os.unlink(file_path)
        return str(res).strip()

    def _require(self) -> None:
        if self.client is None:
            raise RuntimeError(
                "AI-клиент не инициализирован. Проверьте ai.api_key в config.yml"
            )


class AIChatSession:
    def __init__(self, chat_id: str, client: AIClient):
        self.chat_id = chat_id
        self.client = client
        self.history_path = client.chats_dir / f"{chat_id}.json"
        self.history: list[dict[str, str]] = []
        self._load_history()

    def _load_history(self) -> None:
        if not self.history_path.exists():
            return
        try:
            data = orjson.loads(self.history_path.read_bytes())
            if isinstance(data, list):
                self.history = [m for m in data if m.get("role")]
        except Exception:
            self.history = []

    async def _save_history(self) -> None:
        try:
            serialized = orjson.dumps(self.history)
            async with aiofiles.open(self.history_path, "wb") as f:
                await f.write(serialized)
        except Exception:
            pass

    async def send(self, user_message: str) -> tuple[str, str]:
        system_prompt = os.environ.get("AI_SYSTEM_PROMPT", "")
        messages: list[dict[str, str]] = (
            [{"role": "system", "content": system_prompt}]
            if system_prompt
            else []
        )
        # Keep last 50 turns to avoid overwhelming context
        recent = self.history[-100:]
        messages += [m for m in recent if m["role"] in ("user", "assistant")]
        messages.append({"role": "user", "content": user_message})
        model = getattr(self.client, "model", "auto")
        try:
            reply, model_used = await self.client.complete(messages, model)
        except AllModelsFailed:
            raise
        except Exception as e:
            raise AllModelsFailed(str(e)) from e
        self.history.append({"role": "user", "content": user_message})
        self.history.append({"role": "assistant", "content": reply})
        await self._save_history()
        return reply, model_used

    async def clear(self) -> None:
        self.history = []
        await self._save_history()
