from google import genai
from google.genai import types
from loguru import logger

from . import config

logger.info(f"Загружен модуль {__name__}!")


class Client:
    def __init__(self, api_key: str, proxy_string: str = None) -> None:
        self.api_key = api_key
        self.proxy_string = proxy_string
        self._client_init()

    def _client_init(self) -> None:
        http_options = None
        if self.proxy_string:
            http_options = types.HttpOptions(
                async_client_args={"proxy": self.proxy_string},
                client_args={"proxy": self.proxy_string},
            )
        try:
            self.client = genai.Client(
                api_key=self.api_key,
                http_options=http_options,
            )
            self.chat = self.client.aio.chats.create(
                model=config.config.ai_model,
            )
        except Exception as e:
            logger.error(f"Ошибка инициализации ИИ: {e}")

    def change_api_key(self, api_key: str) -> None:
        self.api_key = api_key
        self._client_init()

    def change_proxy(self, proxy_string: str) -> None:
        self.proxy_string = proxy_string
        self._client_init()

    async def generate(self, prompt: str) -> str:
        return (await self.chat.send_message(prompt)).text
