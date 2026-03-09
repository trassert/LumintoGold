import asyncio
import json
from dataclasses import asdict, dataclass, field
from typing import Any

import aiohttp
from aiohttp import ClientResponseError, ClientSession


@dataclass
class UserInfo:
    username: str
    current_connections: int = 0
    total_octets: int = 0
    user_ad_tag: str | None = None
    max_tcp_conns: int | None = None
    expiration_rfc3339: str | None = None
    data_quota_bytes: int | None = None
    max_unique_ips: int | None = None
    active_unique_ips: int = 0
    recent_unique_ips: int = 0
    active_unique_ips_list: list[str] = field(default_factory=list)
    recent_unique_ips_list: list[str] = field(default_factory=list)
    links: dict | None = None

    def __post_init__(self):
        """Гарантируем, что списки всегда являются списками, даже если API вернет null"""
        if self.active_unique_ips_list is None:
            self.active_unique_ips_list = []
        if self.recent_unique_ips_list is None:
            self.recent_unique_ips_list = []
        if self.links is None:
            self.links = {}


@dataclass
class CreateUserRequest:
    username: str
    secret: str | None = None
    user_ad_tag: str | None = None
    max_tcp_conns: int | None = None
    expiration_rfc3339: str | None = None
    data_quota_bytes: int | None = None
    max_unique_ips: int | None = None


@dataclass
class ApiError:
    code: str
    message: str
    request_id: int | None = None


class TelemtAPIError(Exception):
    def __init__(self, error: ApiError, status_code: int):
        self.error = error
        self.status_code = status_code
        super().__init__(f"[{status_code}] {error.code}: {error.message}")


class TelemtClient:
    def __init__(
        self,
        base_url: str,
        auth_token: str | None = None,
        whitelist_check: bool = True,
    ):
        """
        Инициализация клиента.
        :param base_url: URL API, например 'http://127.0.0.1:9091'
        :param auth_token: Значение для заголовка Authorization (если настроено в конфиге сервера)
        """
        self.base_url = base_url.rstrip("/")
        self.auth_token = auth_token
        self.session: ClientSession | None = None
        self.api_prefix = "/v1"

    async def _get_session(self) -> ClientSession:
        if self.session is None or self.session.closed:
            self.session = ClientSession()
        return self.session

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def _request(
        self,
        method: str,
        endpoint: str,
        payload: dict | None = None,
        revision: str | None = None,
    ) -> Any:
        session = await self._get_session()
        url = f"{self.base_url}{self.api_prefix}{endpoint}"
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if self.auth_token:
            headers["Authorization"] = self.auth_token
        if revision:
            headers["If-Match"] = revision
        try:
            async with session.request(
                method, url, json=payload, headers=headers
            ) as resp:
                text = await resp.text()
                if not text:
                    data = {}
                else:
                    data = json.loads(text)
                if resp.status >= 400:
                    if "error" in data:
                        err_data = data["error"]
                        raise TelemtAPIError(
                            ApiError(
                                code=err_data.get("code", "unknown"),
                                message=err_data.get("message", "No message"),
                                request_id=data.get("request_id"),
                            ),
                            resp.status,
                        )
                    raise ClientResponseError(
                        resp.request_info,
                        resp.history,
                        status=resp.status,
                        message=text,
                    )
                if isinstance(data, dict) and data.get("ok") is True:
                    return data.get("data"), data.get("revision")
                return data, None
        except aiohttp.ClientError as e:
            raise Exception(f"Network error: {e}")

    async def health_check(self) -> dict:
        """Проверка статуса API (/v1/health)"""
        data, _ = await self._request("GET", "/health")
        return data

    async def get_system_info(self) -> dict:
        """Получение информации о системе (/v1/system/info)"""
        data, _ = await self._request("GET", "/system/info")
        return data

    async def list_users(self) -> list[UserInfo]:
        """
        Получить список всех пользователей (/v1/users).
        Возвращает список объектов UserInfo.
        """
        data, _ = await self._request("GET", "/users")
        users = []
        for user_dict in data:
            try:
                user_obj = UserInfo(**user_dict)
                users.append(user_obj)
            except TypeError as e:
                print(
                    f"⚠️ Предупреждение: Пропущено неизвестное поле у пользователя {user_dict.get('username')}: {e}"
                )
                safe_data = {
                    k: v
                    for k, v in user_dict.items()
                    if k in UserInfo.__dataclass_fields__
                }
                users.append(UserInfo(**safe_data))
        return users

    async def get_user(self, username: str) -> UserInfo:
        """Получить конкретного пользователя (/v1/users/{username})"""
        endpoint = f"/users/{username}"
        data, _ = await self._request("GET", endpoint)
        return UserInfo(**data)

    async def create_user(self, user_req: CreateUserRequest) -> tuple[UserInfo, str]:
        """
        Создать нового пользователя (/v1/users POST).
        Возвращает (UserInfo, secret).
        Примечание: В ответе сервера поле secret лежит отдельно от объекта user.
        """
        payload = {k: v for k, v in asdict(user_req).items() if v is not None}
        data, revision = await self._request("POST", "/users", payload=payload)
        user_data = data.get("user")
        secret = data.get("secret")
        return UserInfo(**user_data), secret

    async def update_user(self, username: str, **kwargs) -> UserInfo:
        """
        Обновить пользователя (PATCH /v1/users/{username}).
        kwargs: любые поля из PatchUserRequest (secret, max_tcp_conns, etc.)
        """
        endpoint = f"/users/{username}"
        payload = {k: v for k, v in kwargs.items() if v is not None}
        if not payload:
            raise ValueError("Нет полей для обновления")
        data, _ = await self._request("PATCH", endpoint, payload=payload)
        return UserInfo(**data)

    async def delete_user(self, username: str) -> str:
        """
        Удалить пользователя (/v1/users/{username} DELETE).
        Возвращает имя удаленного пользователя.
        """
        endpoint = f"/users/{username}"
        data, _ = await self._request("DELETE", endpoint)
        return data

    def _get_link_from_user(self, user: UserInfo, mode: str) -> str | None:
        """Вспомогательный метод для извлечения ссылки нужного типа."""
        if not user.links:
            return None
        target_list = user.links.get(mode, [])
        if not target_list:
            return None
        return target_list[0]

    async def create_user_with_link(
        self,
        user_req: CreateUserRequest,
        link_mode: str = "tls",
        retries: int = 5,
        delay: float = 0.2,
    ) -> tuple[UserInfo, str, str]:
        """
        Создает пользователя и получает ссылку, обрабатывая задержку синхронизации конфига.
        """

        created_user, secret = await self.create_user(user_req)
        full_user = None

        for attempt in range(retries):
            try:
                if attempt > 0:
                    await asyncio.sleep(delay)

                full_user = await self.get_user(user_req.username)

                link = self._get_link_from_user(full_user, link_mode)
                if link:
                    return full_user, secret, link

                if attempt == retries - 1:
                    raise ValueError(
                        f"Ссылки типа '{link_mode}' не сгенерированы сервером после {retries} попыток."
                    )

            except TelemtAPIError as e:
                if e.status_code == 404 and "User not found" in e.error.message:
                    continue
                raise e

        raise TelemtAPIError(
            error=ApiError(
                code="sync_timeout",
                message=f"Сервер не увидел созданного пользователя '{user_req.username}' после {retries} попыток. Возможно, проблема с записью конфиг-файла или правами доступа.",
            ),
            status_code=408,
        )
