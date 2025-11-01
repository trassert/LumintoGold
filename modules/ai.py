from google import genai
from google.genai import types
from loguru import logger

from . import config

logger.info(f"Загружен модуль {__name__}!")


class Client:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self._client_init()

    def _client_init(self) -> None:
        try:
            self.client = genai.Client(
                api_key=self.api_key,
                http_options=types.HttpOptions(
                    async_client_args={"proxy": config.tokens.proxy},
                    client_args={"proxy": config.tokens.proxy},
                ),
            )
            self.chat = self.client.aio.chats.create(
                model=config.config.ai_model,
            )
        except Exception:
            pass

    def change_api_key(self, api_key: str) -> None:
        self.api_key = api_key
        self._client_init()

    async def generate(self, prompt: str) -> str:
        return (await self.chat.send_message(prompt)).text
