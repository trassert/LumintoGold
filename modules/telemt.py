from dataclasses import asdict, dataclass, field
from typing import Any

import aiohttp
import orjson
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

    def __init__(self, **kwargs):
        self.username = kwargs.get("username")
        self.current_connections = kwargs.get("current_connections", 0)
        self.total_octets = kwargs.get("total_octets", 0)
        self.user_ad_tag = kwargs.get("user_ad_tag")
        self.max_tcp_conns = kwargs.get("max_tcp_conns")
        self.expiration_rfc3339 = kwargs.get("expiration_rfc3339")
        self.data_quota_bytes = kwargs.get("data_quota_bytes")
        self.max_unique_ips = kwargs.get("max_unique_ips")
        self.active_unique_ips = kwargs.get("active_unique_ips", 0)
        self.recent_unique_ips = kwargs.get("recent_unique_ips", 0)
        self.active_unique_ips_list = kwargs.get("active_unique_ips_list") or []
        self.recent_unique_ips_list = kwargs.get("recent_unique_ips_list") or []
        self.links = kwargs.get("links")

    @staticmethod
    def from_dict(data: dict) -> "UserInfo":
        """Безопасное создание объекта из словаря API"""
        return UserInfo(**data)


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
                    data = orjson.loads(text)
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
        data, _ = await self._request("GET", "/health")
        return data

    async def get_system_info(self) -> dict:
        data, _ = await self._request("GET", "/system/info")
        return data

    async def list_users(self) -> list[UserInfo]:
        data, _ = await self._request("GET", "/users")
        users = []
        for user_dict in data:
            users.append(UserInfo.from_dict(user_dict))
        return users

    async def get_user(self, username: str) -> UserInfo:
        endpoint = f"/users/{username}"
        data, _ = await self._request("GET", endpoint)
        return UserInfo.from_dict(data)

    async def create_user(self, user_req: CreateUserRequest) -> tuple[UserInfo, str]:
        payload = {k: v for k, v in asdict(user_req).items() if v is not None}
        data, revision = await self._request("POST", "/users", payload=payload)
        user_data = data.get("user")
        secret = data.get("secret")
        return UserInfo.from_dict(user_data), secret

    async def update_user(self, username: str, **kwargs) -> UserInfo:
        endpoint = f"/users/{username}"
        payload = {k: v for k, v in kwargs.items() if v is not None}
        if not payload:
            raise ValueError("Нет полей для обновления")
        data, _ = await self._request("PATCH", endpoint, payload=payload)
        return UserInfo.from_dict(data)

    async def delete_user(self, username: str) -> str:
        endpoint = f"/users/{username}"
        data, _ = await self._request("DELETE", endpoint)
        return data

    def get_links_from_user(self, user: UserInfo) -> dict[str, str]:
        if not user.links:
            return {}
        result = {}
        if user.links.get("secure"):
            result["secure"] = user.links["secure"][0]
        if user.links.get("tls"):
            result["tls"] = user.links["tls"][0]
        if user.links.get("classic"):
            result["classic"] = user.links["classic"][0]
        return result

    async def create_user_with_links(
        self, user_req: CreateUserRequest
    ) -> tuple[UserInfo, str, dict[str, str]]:
        created_user, secret = await self.create_user(user_req)
        links = self.get_links_from_user(created_user)
        if not links:
            full_user = await self.get_user(user_req.username)
            links = self.get_links_from_user(full_user)
            return full_user, secret, links
        return created_user, secret, links
