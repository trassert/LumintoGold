import asyncio
import contextlib
import hmac
import io
import re
import secrets
import time
import traceback
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from typing import Any

import orjson
import yaml
from aiohttp import WSMsgType, web
from loguru import logger
from telethon import TelegramClient, errors
from telethon.tl.custom.qrlogin import QRLogin

from . import config, pathes, settings

DEFAULT_PASSWORD = "luminto"
PHONE_RE = re.compile(r"^\+?\d{5,20}$")
HASH_RE = re.compile(r"^[0-9a-fA-F]{32}$")
LOGIN_ID_RE = re.compile(r"^[a-f0-9]{32}$")
_TG_ERRORS = (
    (errors.ApiIdInvalidError, "Неверный api_id/api_hash", 400),
    (errors.PhoneNumberInvalidError, "Неверный номер телефона", 400),
    (errors.PhoneNumberBannedError, "Номер заблокирован в Telegram", 400),
    (errors.PhoneCodeInvalidError, "Неверный код из Telegram", 400),
    (errors.PhoneCodeExpiredError, "Код истёк — запросите новый", 400),
    (errors.PasswordHashInvalidError, "Неверный пароль 2FA", 400),
    (errors.SessionPasswordNeededError, "Требуется пароль 2FA", 500),
)


class LogBroker:
    """Хранит последние логи и рассылает их в WebSocket-подписчики."""

    def __init__(self, loop: asyncio.AbstractEventLoop, limit: int = 1000):
        self._loop = loop
        self._buffer: deque[dict[str, Any]] = deque(maxlen=limit)
        self._queues: set[asyncio.Queue] = set()
        self._seq = count(1)

    def __call__(self, message) -> None:
        try:
            record = message.record
            entry = {
                "id": next(self._seq),
                "ts": record["time"].strftime("%H:%M:%S"),
                "level": record["level"].name,
                "message": record["message"],
                "source": (f"{record['file'].name}:{record['function']}"),
            }
            if record["exception"]:
                tb = "".join(traceback.format_exception(*record["exception"]))
                entry["traceback"] = tb[-6000:]
            self._buffer.append(entry)
            if not self._queues or self._loop.is_closed():
                return
            for queue in list(self._queues):
                self._loop.call_soon_threadsafe(queue.put_nowait, entry)
        except Exception:
            pass

    def history(self) -> list[dict[str, Any]]:
        return list(self._buffer)

    @contextlib.asynccontextmanager
    async def subscribe(self):
        queue: asyncio.Queue = asyncio.Queue()
        self._queues.add(queue)
        try:
            yield queue
        finally:
            self._queues.discard(queue)


@dataclass
class LoginSession:
    id: str
    phone: str
    api_id: int
    api_hash: str
    method: str
    client: TelegramClient
    temp_session: Path
    state: str = "code_sent"
    error: str | None = None
    phone_code_hash: str | None = None
    qr: QRLogin | None = None
    qr_svg: str | None = None
    result_phone: str | None = None
    expires_at: float = 0.0
    finished_at: float | None = None
    closed: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    qr_task: asyncio.Task | None = None


def normalize_phone(value: Any) -> str:
    phone = str(value or "").strip().replace(" ", "").replace("-", "")
    phone = phone.removeprefix("+")
    if not phone.isdigit() or not (5 <= len(phone) <= 20):
        raise ValueError("Некорректный номер телефона")
    return phone


def validate_credentials(api_id: Any, api_hash: Any) -> tuple[int, str]:
    if isinstance(api_id, str) and api_id.isdigit():
        api_id = int(api_id)
    if isinstance(api_id, bool) or not isinstance(api_id, int) or api_id <= 0:
        raise ValueError("api_id должен быть положительным числом")
    api_hash = str(api_hash or "").strip()
    if not HASH_RE.fullmatch(api_hash):
        raise ValueError("api_hash должен состоять из 32 hex-символов")
    return api_id, api_hash.lower()


def qr_svg(data: str, box_size: int = 10, border: int = 2) -> str:
    import qrcode
    from qrcode.image.svg import SvgPathImage

    qr = qrcode.QRCode(
        image_factory=SvgPathImage,
        box_size=box_size,
        border=border,
    )
    qr.add_data(data)
    qr.make(fit=True)
    image = qr.make_image()
    buffer = io.BytesIO()
    image.save(buffer)
    svg = buffer.getvalue().decode("utf-8")
    return svg[svg.find("<svg") :]


class Panel:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        password: str,
        managers: dict[str, Any],
        statuses: dict[str, dict[str, Any]],
        launch: Callable[[str], Awaitable[bool]],
        stop: Callable[[str], Awaitable[bool]],
        restart: Callable[[str], Awaitable[bool]],
        stop_all: Callable[[], Awaitable[int]],
        make_client: Callable[..., TelegramClient],
        log_broker: LogBroker,
    ) -> None:
        self._host = host
        self._port = port
        self._password = password
        self._managers = managers
        self._statuses = statuses
        self._launch = launch
        self._stop = stop
        self._restart = restart
        self._stop_all = stop_all
        self._make_client = make_client
        self._log_broker = log_broker
        self._web_dir = Path(__file__).resolve().parent.parent / "web"
        self._sessions: dict[str, float] = {}
        self._login_attempts: dict[str, tuple[int, float]] = {}
        self._logins: dict[str, LoginSession] = {}
        self._login_admin_lock = asyncio.Lock()
        self._runner: web.AppRunner | None = None
        self._cleanup_task: asyncio.Task | None = None
        self._closing = False
        self._session_ttl = 0
        self._login_ttl = 0
        self._network_timeout = 0
        self._login_max_attempts = 0
        self._login_block_seconds = 0
        self._qr_box_size = 10
        self._qr_border = 2
        self._max_request_size = 0
        self._cookie_name = "luminto_session"
        self._reload_web_limits()

    def _reload_web_limits(self) -> None:
        web_cfg = config.config.web
        self._session_ttl = max(60, int(web_cfg.session_ttl_hours) * 3600)
        self._login_ttl = max(60, int(web_cfg.login_ttl_minutes) * 60)
        self._network_timeout = max(5, int(web_cfg.network_timeout_seconds))
        self._login_max_attempts = max(1, int(web_cfg.login_max_attempts))
        self._login_block_seconds = max(1, int(web_cfg.login_block_seconds))
        self._qr_box_size = max(1, int(web_cfg.qr_box_size))
        self._qr_border = max(0, int(web_cfg.qr_border))
        self._cookie_name = str(web_cfg.cookie_name)

    async def start(self) -> None:
        if not self._password:
            self._password = secrets.token_urlsafe(12)
            logger.warning(
                "Веб-пароль не задан. Временный пароль на этот запуск: "
                f"{self._password}"
            )
        if self._password == DEFAULT_PASSWORD:
            logger.warning(
                "Веб-панель использует пароль по умолчанию. "
                "Смените web.password в configs/config.yml!"
            )
        self._max_request_size = int(config.config.web.max_request_size)
        app = web.Application(
            middlewares=[self._auth_middleware],
            client_max_size=self._max_request_size,
        )
        self._register_routes(app)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info(f"Веб-панель: http://{self._host}:{self._port}")
        if self._host not in ("127.0.0.1", "localhost", "::1"):
            logger.warning(
                "Панель слушает не только localhost. "
                "HTTP не шифрует пароль — используйте reverse proxy/VPN."
            )

    async def stop(self) -> None:
        self._closing = True
        if self._cleanup_task:
            self._cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._cleanup_task
            self._cleanup_task = None
        for login in list(self._logins.values()):
            await self._cancel_login(login)
        if self._runner:
            await self._runner.cleanup()
            self._runner = None

    def _register_routes(self, app: web.Application) -> None:
        app.router.add_get("/", self._index)
        app.router.add_static("/static", self._web_dir / "static")
        app.router.add_post("/api/login", self._login)
        app.router.add_post("/api/logout", self._logout)
        app.router.add_get("/api/session", self._session_info)
        app.router.add_get("/api/login-options", self._login_options)
        app.router.add_get("/api/settings-schema", self._settings_schema)
        app.router.add_get("/api/global-config", self._global_config)
        app.router.add_put("/api/global-config", self._save_global_config)
        app.router.add_post(
            "/api/global-config/reload", self._reload_global_config
        )
        app.router.add_get("/api/clients", self._list_clients)
        app.router.add_post("/api/clients/import", self._import_clients)
        app.router.add_post("/api/clients/stop-all", self._stop_all_clients)
        app.router.add_get("/api/clients/{phone}", self._get_client)
        app.router.add_put("/api/clients/{phone}", self._save_client)
        app.router.add_patch("/api/clients/{phone}", self._patch_client)
        app.router.add_patch(
            "/api/clients/{phone}/features", self._patch_feature
        )
        app.router.add_post("/api/clients/{phone}/start", self._start_client)
        app.router.add_post("/api/clients/{phone}/stop", self._stop_client)
        app.router.add_post(
            "/api/clients/{phone}/restart", self._restart_client
        )
        app.router.add_post("/api/logins", self._create_login)
        app.router.add_get("/api/logins/{login_id}", self._get_login)
        app.router.add_post("/api/logins/{login_id}/code", self._submit_code)
        app.router.add_post(
            "/api/logins/{login_id}/password", self._submit_password
        )
        app.router.add_post("/api/logins/{login_id}/resend", self._resend_code)
        app.router.add_delete("/api/logins/{login_id}", self._delete_login)
        app.router.add_get("/api/system", self._system)
        app.router.add_get("/ws/logs", self._ws_logs)

    @web.middleware
    async def _auth_middleware(self, request: web.Request, handler):
        try:
            if (
                request.path.startswith("/api/")
                and request.path not in ("/api/login", "/api/session")
                and not self._authorized(request)
            ):
                response = self._error(401, "Требуется вход в панель")
            else:
                response = await handler(request)
        except web.HTTPException as exc:
            response = self._error(exc.status, exc.text)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    @staticmethod
    def _error(status: int, message: str) -> web.Response:
        return web.json_response({"error": message}, status=status)

    @staticmethod
    def _json(data: Any, status: int = 200) -> web.Response:
        return web.json_response(
            data,
            status=status,
            dumps=lambda obj: orjson.dumps(obj).decode(),
        )

    def _phone(self, request: web.Request) -> str | None:
        phone = request.match_info["phone"]
        return phone if PHONE_RE.fullmatch(phone) else None

    async def _client_or_error(self, request: web.Request):
        phone = self._phone(request)
        if not phone:
            return None, None, self._error(400, "Некорректный номер")
        data, error = await self._read_config(phone)
        if error:
            return (
                phone,
                None,
                self._error(400, "Сначала исправьте JSON-конфиг"),
            )
        if data is None:
            return phone, None, self._error(404, "Клиент не найден")
        return phone, data, None

    def _with_detail(self, detail, **extra) -> web.Response:
        if isinstance(detail, web.Response) and detail.status == 200:
            payload = orjson.loads(detail.body)
            payload.update(extra)
            return self._json(payload)
        return detail

    async def _json_body(self, request: web.Request) -> dict:
        if not request.content_type.startswith("application/json"):
            raise web.HTTPUnsupportedMediaType(
                text="Ожидается application/json"
            )
        try:
            data = await request.json(loads=orjson.loads)
        except Exception as exc:
            raise web.HTTPBadRequest(text=f"Некорректный JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise web.HTTPBadRequest(text="Ожидается JSON-объект")
        return data

    def _authorized(self, request: web.Request) -> bool:
        token = request.cookies.get(self._cookie_name)
        if not token:
            return False
        expires = self._sessions.get(token)
        now = time.time()
        if not expires or expires <= now:
            self._sessions.pop(token, None)
            return False
        return True

    def _config_path(self, phone: str) -> Path:
        return pathes.clients / f"{phone}.json"

    def _session_path(self, phone: str) -> Path:
        return pathes.sessions / f"{phone}.session"

    def _has_session(self, phone: str) -> bool:
        return self._session_path(phone).exists()

    def _set_status(
        self, phone: str, status: str, error: str | None = None
    ) -> None:
        self._statuses[phone] = {
            "status": status,
            "error": error,
            "since": time.time(),
        }

    async def _read_raw(self, phone: str) -> str | None:
        path = self._config_path(phone)
        if not path.exists():
            return None
        return await asyncio.to_thread(path.read_text, encoding="utf-8")

    async def _read_config(self, phone: str) -> tuple[dict | None, str | None]:
        try:
            raw = await self._read_raw(phone)
        except OSError as exc:
            return None, f"Не удалось прочитать файл: {exc}"
        if raw is None:
            return None, None
        try:
            data = orjson.loads(raw)
        except Exception as exc:
            return None, f"Некорректный JSON: {exc}"
        if not isinstance(data, dict):
            return None, "Конфиг должен быть JSON-объектом"
        return data, None

    async def _default_credentials(
        self,
    ) -> tuple[tuple[int, str] | None, str | None]:
        try:
            credentials = validate_credentials(
                config.config.telegram.api_id,
                config.config.telegram.api_hash,
            )
        except TypeError, ValueError:
            pass
        else:
            return credentials, "config.yml"
        for path in sorted(pathes.clients.glob("*.json")):
            data, error = await self._read_config(path.stem)
            if error or not data:
                continue
            try:
                credentials = validate_credentials(
                    data.get("api_id"), data.get("api_hash")
                )
            except ValueError:
                continue
            return credentials, f"клиент +{path.stem}"
        return None, None

    async def _write_config(self, phone: str, data: dict) -> None:
        manager = self._managers.get(phone)
        target = manager.settings if manager else settings.UBSettings(phone)
        await target.replace(data)

    def _validate_config(self, data: dict) -> dict:
        if not isinstance(data, dict):
            raise ValueError("Конфиг должен быть JSON-объектом")
        result = dict(data)
        result.pop("phone", None)
        api_id, api_hash = validate_credentials(
            result.get("api_id"), result.get("api_hash")
        )
        result["api_id"] = api_id
        result["api_hash"] = api_hash
        if "disabled" in result and not isinstance(result["disabled"], bool):
            raise ValueError("disabled должен быть true или false")
        encoded = orjson.dumps(result)
        if len(encoded) > 512 * 1024:
            raise ValueError("Конфиг слишком большой")
        return result

    async def _index(self, request: web.Request) -> web.FileResponse:
        response = web.FileResponse(self._web_dir / "index.html")
        response.headers["Cache-Control"] = "no-store"
        return response

    async def _login(self, request: web.Request) -> web.Response:
        remote = request.remote or "unknown"
        attempts, blocked_until = self._login_attempts.get(remote, (0, 0.0))
        now = time.time()
        if blocked_until > now:
            wait = int(blocked_until - now) + 1
            return self._error(
                429, f"Слишком много попыток. Повторите через {wait} с."
            )
        data = await self._json_body(request)
        password = str(data.get("password") or "")
        if not hmac.compare_digest(password.encode(), self._password.encode()):
            attempts += 1
            if attempts >= self._login_max_attempts:
                self._login_attempts[remote] = (
                    0,
                    now + self._login_block_seconds,
                )
            else:
                self._login_attempts[remote] = (attempts, 0.0)
            return self._error(401, "Неверный пароль")
        self._login_attempts.pop(remote, None)
        token = secrets.token_urlsafe(32)
        self._sessions[token] = now + self._session_ttl
        self._prune_sessions()
        response = self._json({"ok": True})
        response.set_cookie(
            self._cookie_name,
            token,
            max_age=self._session_ttl,
            httponly=True,
            samesite="Lax",
            secure=request.secure,
            path="/",
        )
        logger.info(f"Веб-панель: вход с {remote}")
        return response

    async def _logout(self, request: web.Request) -> web.Response:
        token = request.cookies.get(self._cookie_name)
        if token:
            self._sessions.pop(token, None)
        response = self._json({"ok": True})
        response.del_cookie(self._cookie_name, path="/")
        return response

    async def _session_info(self, request: web.Request) -> web.Response:
        return self._json({"authenticated": self._authorized(request)})

    async def _login_options(self, request: web.Request) -> web.Response:
        credentials, source = await self._default_credentials()
        return self._json(
            {
                "has_credentials": credentials is not None,
                "source": source,
            }
        )

    async def _settings_schema(self, request: web.Request) -> web.Response:
        return self._json(settings.schema_payload())

    async def _read_global_text(self, path: Path, defaults: Path) -> str:
        def read() -> str:
            target = path if path.exists() else defaults
            if not target.exists():
                return ""
            return target.read_text(encoding="utf-8")

        return await asyncio.to_thread(read)

    @staticmethod
    def _validate_global_yaml(text: str, label: str) -> None:
        try:
            data = yaml.safe_load(text) if text.strip() else {}
        except yaml.YAMLError as exc:
            raise ValueError(f"{label}: {exc}") from exc
        if data is None:
            return
        if not isinstance(data, dict):
            raise ValueError(f"{label}: ожидается YAML-объект")

    @staticmethod
    async def _write_global_text(path: Path, text: str) -> None:
        def write() -> None:
            path.parent.mkdir(exist_ok=True)
            tmp = path.with_name(f"{path.name}.tmp")
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(path)

        await asyncio.to_thread(write)

    async def _global_config(self, request: web.Request) -> web.Response:
        return self._json(
            {
                "config": await self._read_global_text(
                    pathes.config, pathes.default_config
                ),
                "tokens": await self._read_global_text(
                    pathes.tokens, pathes.default_tokens
                ),
                "restart_required": [
                    "web.host",
                    "web.port",
                    "web.max_request_size",
                    "web.log_buffer_size",
                    "telegram.* для уже запущенных клиентов",
                ],
            }
        )

    async def _save_global_config(self, request: web.Request) -> web.Response:
        body = await self._json_body(request)
        config_text = body.get("config")
        tokens_text = body.get("tokens")
        for name, value in (("config", config_text), ("tokens", tokens_text)):
            if value is not None and not isinstance(value, str):
                return self._error(400, f"{name} должен быть строкой")
        try:
            if config_text is not None:
                self._validate_global_yaml(config_text, "config.yml")
            if tokens_text is not None:
                self._validate_global_yaml(tokens_text, "tokens.yml")
        except ValueError as exc:
            return self._error(400, str(exc))
        if config_text is not None:
            await self._write_global_text(pathes.config, config_text)
        if tokens_text is not None:
            await self._write_global_text(pathes.tokens, tokens_text)
        try:
            await self._reload_globals()
        except Exception as exc:
            logger.exception("Ошибка hot-reload глобальных конфигов")
            return self._error(500, f"Не удалось применить конфиги: {exc}")
        return self._json({"ok": True})

    async def _reload_global_config(self, request: web.Request) -> web.Response:
        try:
            await self._reload_globals()
        except Exception as exc:
            logger.exception("Ошибка hot-reload глобальных конфигов")
            return self._error(500, f"Не удалось перечитать конфиги: {exc}")
        return self._json({"ok": True})

    async def _reload_globals(self) -> None:
        config.reload()
        settings.reload_schema()
        self._reload_web_limits()
        new_password = str(config.config.web.password or "")
        if new_password:
            self._password = new_password
        self._login_attempts.clear()
        for manager in list(self._managers.values()):
            with contextlib.suppress(Exception):
                await manager.apply_features()
        logger.info("Глобальные настройки применены к запущенным клиентам")

    def _prune_sessions(self) -> None:
        now = time.time()
        for token, expires in list(self._sessions.items()):
            if expires <= now:
                self._sessions.pop(token, None)

    async def _summary(self, phone: str) -> dict | None:
        data, error = await self._read_config(phone)
        if data is None and error is None:
            return None
        has_session = self._has_session(phone)
        status_entry = self._statuses.get(phone) or {}
        status = status_entry.get("status")
        status_error = status_entry.get("error")
        disabled = bool((data or {}).get("disabled", False))
        if error:
            status = "invalid"
        elif not status:
            if disabled:
                status = "disabled"
            elif has_session:
                status = "stopped"
            else:
                status = "unauthorized"
        api_hash = str((data or {}).get("api_hash") or "")
        masked_hash = (
            f"{api_hash[:4]}…{api_hash[-4:]}" if len(api_hash) > 8 else api_hash
        )
        return {
            "phone": phone,
            "api_id": (data or {}).get("api_id"),
            "api_hash": masked_hash,
            "has_session": has_session,
            "disabled": disabled,
            "status": status,
            "error": status_error or error,
            "settings_count": len(data or {}),
            "valid": error is None,
        }

    async def _list_clients(self, request: web.Request) -> web.Response:
        clients = []
        for path in sorted(pathes.clients.glob("*.json")):
            phone = path.stem
            if not PHONE_RE.fullmatch(phone):
                continue
            summary = await self._summary(phone)
            if summary:
                clients.append(summary)
        clients.sort(
            key=lambda item: (
                item["status"] not in ("running", "starting", "stopping"),
                item["phone"],
            )
        )
        counts = {
            "total": len(clients),
            "running": sum(
                c["status"] in ("running", "starting", "stopping")
                for c in clients
            ),
            "disabled": sum(c["disabled"] for c in clients),
            "unauthorized": sum(c["status"] == "unauthorized" for c in clients),
            "errors": sum(c["status"] in ("error", "invalid") for c in clients),
        }
        return self._json({"clients": clients, "counts": counts})

    async def _get_client(self, request: web.Request) -> web.Response:
        if not (phone := self._phone(request)):
            return self._error(400, "Некорректный номер")
        raw = await self._read_raw(phone)
        if raw is None:
            return self._error(404, "Клиент не найден")
        data, _ = await self._read_config(phone)
        summary = await self._summary(phone)
        if summary is None:
            return self._error(404, "Клиент не найден")
        summary.update({"config": data, "raw": raw})
        return self._json(summary)

    async def _save_client(self, request: web.Request) -> web.Response:
        if not (phone := self._phone(request)):
            return self._error(400, "Некорректный номер")
        if not self._config_path(phone).exists():
            return self._error(404, "Клиент не найден")
        body = await self._json_body(request)
        if "raw" in body:
            try:
                data = orjson.loads(str(body["raw"]))
            except Exception as exc:
                return self._error(400, f"Некорректный JSON: {exc}")
            if not isinstance(data, dict):
                return self._error(400, "Конфиг должен быть JSON-объектом")
        elif "config" in body:
            data = body["config"]
        else:
            return self._error(400, "Нет поля config или raw")
        try:
            data = self._validate_config(data)
        except ValueError as exc:
            return self._error(400, str(exc))
        old, old_error = await self._read_config(phone)
        if old_error:
            old = None
        manager = self._managers.get(phone)
        restart_needed = bool(
            manager
            and old
            and (
                old.get("api_id") != data.get("api_id")
                or old.get("api_hash") != data.get("api_hash")
            )
        )
        await self._write_config(phone, data)
        if data.get("disabled"):
            await self._stop(phone)
            self._set_status(phone, "disabled")
        elif restart_needed:
            await self._restart(phone)
        elif manager and manager.status == "running":
            await manager.apply_features()
        return self._with_detail(
            await self._get_client(request), restarted=restart_needed
        )

    async def _patch_client(self, request: web.Request) -> web.Response:
        phone, data, error = await self._client_or_error(request)
        if error:
            return error
        body = await self._json_body(request)
        disabled = body.get("disabled")
        if not isinstance(disabled, bool):
            return self._error(400, "disabled должен быть true или false")
        data["disabled"] = disabled
        await self._write_config(phone, data)
        needs_login = False
        if disabled:
            await self._stop(phone)
            self._set_status(phone, "disabled")
        elif not self._has_session(phone):
            needs_login = True
            self._set_status(
                phone,
                "unauthorized",
                "Нет сессии — требуется вход",
            )
        else:
            await self._launch(phone)
        return self._with_detail(
            await self._get_client(request), needs_login=needs_login
        )

    async def _patch_feature(self, request: web.Request) -> web.Response:
        phone, data, error = await self._client_or_error(request)
        if error:
            return error
        body = await self._json_body(request)
        key = str(body.get("key") or "")
        value = body.get("value")
        meta = settings.fields.get(key)
        if not meta or not meta.get("feature"):
            return self._error(400, "Неизвестная функция")
        if not isinstance(value, bool):
            return self._error(400, "value должен быть true или false")
        data[key] = value
        manager = self._managers.get(phone)
        target = manager.settings if manager else settings.UBSettings(phone)
        await target.replace(data)
        applied = bool(manager and manager.status == "running")
        if applied:
            await manager.apply_features()
        return self._with_detail(
            await self._get_client(request),
            feature_applied=applied,
            feature=key,
            value=value,
        )

    async def _start_client(self, request: web.Request) -> web.Response:
        phone, _, error = await self._client_or_error(request)
        if error:
            return error
        if not self._has_session(phone):
            return self._error(400, "Нет сессии — войдите в аккаунт")
        await self._launch(phone)
        return self._json({"ok": True})

    async def _stop_client(self, request: web.Request) -> web.Response:
        if not (phone := self._phone(request)):
            return self._error(400, "Некорректный номер")
        data, error = await self._read_config(phone)
        if data is None and error is None:
            return self._error(404, "Клиент не найден")
        await self._stop(phone)
        if (data or {}).get("disabled"):
            self._set_status(phone, "disabled")
        return self._json({"ok": True})

    async def _restart_client(self, request: web.Request) -> web.Response:
        phone, _, error = await self._client_or_error(request)
        if error:
            return error
        if not self._has_session(phone):
            return self._error(400, "Нет сессии — войдите в аккаунт")
        await self._restart(phone)
        return self._json({"ok": True})

    async def _stop_all_clients(self, request: web.Request) -> web.Response:
        count = await self._stop_all()
        for path in pathes.clients.glob("*.json"):
            data, error = await self._read_config(path.stem)
            if not error and data and data.get("disabled"):
                self._set_status(path.stem, "disabled")
        return self._json({"ok": True, "stopped": count})

    async def _import_clients(self, request: web.Request) -> web.Response:
        body = await self._json_body(request)
        items = body.get("items")
        if not isinstance(items, list) or not items:
            return self._error(400, "Нет конфигов для импорта")
        if len(items) > 50:
            return self._error(400, "За один раз можно импортировать до 50")
        results = []
        for item in items:
            name = str((item or {}).get("filename") or "")
            try:
                if not isinstance(item, dict):
                    raise ValueError("Некорректный элемент импорта")
                item_config = item.get("config")
                if item_config is None:
                    content = item.get("content")
                    if not isinstance(content, str):
                        raise ValueError("Нет содержимого файла")
                    item_config = orjson.loads(content)
                if not isinstance(item_config, dict):
                    raise ValueError("Конфиг должен быть JSON-объектом")
                source = item_config.get("phone") or Path(name).name
                phone = normalize_phone(Path(str(source)).stem)
                item_config.pop("phone", None)
                item_config = self._validate_config(item_config)
                if self._config_path(phone).exists():
                    raise ValueError("Клиент уже существует")
                await self._write_config(phone, item_config)
                results.append(
                    {
                        "ok": True,
                        "phone": phone,
                        "has_session": self._has_session(phone),
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "ok": False,
                        "filename": name,
                        "error": str(exc),
                    }
                )
        return self._json({"results": results})

    async def _create_login(self, request: web.Request) -> web.Response:
        body = await self._json_body(request)
        try:
            method = str(body.get("method") or "code")
            if method not in ("code", "qr"):
                raise ValueError("Неизвестный способ входа")
            raw_phone = body.get("phone")
            phone = normalize_phone(raw_phone) if raw_phone else ""
            if method == "code" and not phone:
                raise ValueError("Введите номер телефона")
            existing = None
            if phone:
                existing, existing_error = await self._read_config(phone)
                if existing_error:
                    raise ValueError(
                        "Конфиг клиента повреждён — сначала исправьте JSON"
                    )
            raw_id = body.get("api_id")
            raw_hash = body.get("api_hash")
            api_id = None
            api_hash = None
            if raw_id or raw_hash:
                api_id, api_hash = validate_credentials(raw_id, raw_hash)
            else:
                if existing:
                    with contextlib.suppress(ValueError):
                        api_id, api_hash = validate_credentials(
                            existing.get("api_id"),
                            existing.get("api_hash"),
                        )
                if api_id is None or api_hash is None:
                    defaults, _ = await self._default_credentials()
                    if not defaults:
                        raise ValueError(
                            "Не заданы api_id/api_hash. Укажите их в форме "
                            "или в telegram.api_id/api_hash "
                            "(configs/config.yml)"
                        )
                    api_id, api_hash = defaults
        except ValueError as exc:
            return self._error(400, str(exc))
        manager = self._managers.get(phone) if phone else None
        if manager and not manager._stopped:
            return self._error(409, "Клиент уже запущен")
        async with self._login_admin_lock:
            for old in list(self._logins.values()):
                if old.phone == phone:
                    await self._cancel_login(old)
            login_id = uuid.uuid4().hex
            temp_session = pathes.sessions / f"login_{login_id}"
            client = None
            login = None
            try:
                client = self._make_client(
                    phone,
                    api_id,
                    api_hash,
                    temp_session,
                    connection_retries=3,
                )
                await asyncio.wait_for(client.connect(), self._network_timeout)
                if await asyncio.wait_for(
                    client.is_user_authorized(), self._network_timeout
                ):
                    with contextlib.suppress(Exception):
                        await asyncio.wait_for(client.disconnect(), 5)
                    await self._remove_temp_session(temp_session)
                    return self._error(409, "Сессия уже авторизована")
                login = LoginSession(
                    id=login_id,
                    phone=phone,
                    api_id=api_id,
                    api_hash=api_hash,
                    method=method,
                    client=client,
                    temp_session=temp_session,
                    expires_at=time.time() + self._login_ttl,
                )
                if method == "code":
                    sent = await asyncio.wait_for(
                        client.send_code_request(phone),
                        self._network_timeout,
                    )
                    login.phone_code_hash = sent.phone_code_hash
                    login.state = "code_sent"
                else:
                    qr = await asyncio.wait_for(
                        client.qr_login(), self._network_timeout
                    )
                    login.qr = qr
                    login.qr_svg = qr_svg(
                        qr.url, self._qr_box_size, self._qr_border
                    )
                    login.state = "qr_waiting"
                self._logins[login_id] = login
                if method == "qr":
                    login.qr_task = asyncio.create_task(self._qr_loop(login_id))
                logger.info(
                    f"Веб-панель: начат вход {phone or 'QR'} ({method})"
                )
                return self._json(self._login_payload(login))
            except Exception as exc:
                if login is not None:
                    await self._cancel_login(login)
                elif client is not None:
                    with contextlib.suppress(Exception):
                        await asyncio.wait_for(client.disconnect(), 5)
                    await self._remove_temp_session(temp_session)
                return self._telegram_error(exc)

    def _login_payload(self, login: LoginSession) -> dict:
        return {
            "id": login.id,
            "phone": login.phone or login.result_phone or "",
            "method": login.method,
            "state": login.state,
            "error": login.error,
            "qr_svg": login.qr_svg,
            "result_phone": login.result_phone,
            "expires_at": login.expires_at,
        }

    async def _find_login(
        self, request: web.Request
    ) -> LoginSession | web.Response:
        login_id = request.match_info["login_id"]
        if not LOGIN_ID_RE.fullmatch(login_id):
            return self._error(400, "Некорректный id входа")
        login = self._logins.get(login_id)
        if not login:
            return self._error(404, "Вход не найден или истёк")
        return login

    async def _get_login(self, request: web.Request) -> web.Response:
        login = await self._find_login(request)
        if isinstance(login, web.Response):
            return login
        async with login.lock:
            if time.time() > login.expires_at and login.state not in (
                "authorized",
                "expired",
                "cancelled",
            ):
                login.state = "expired"
                login.error = "Время входа истекло"
            return self._json(self._login_payload(login))

    async def _submit_code(self, request: web.Request) -> web.Response:
        login = await self._find_login(request)
        if isinstance(login, web.Response):
            return login
        body = await self._json_body(request)
        code = str(body.get("code") or "").strip()
        if not code.isdigit() or not (3 <= len(code) <= 8):
            return self._error(400, "Введите код из Telegram")
        async with login.lock:
            if login.state != "code_sent":
                return self._error(409, "Сейчас код вводить не нужно")
            try:
                await asyncio.wait_for(
                    login.client.sign_in(
                        phone=login.phone,
                        code=code,
                        phone_code_hash=login.phone_code_hash,
                    ),
                    self._network_timeout,
                )
            except errors.SessionPasswordNeededError:
                login.state = "password_required"
                login.error = None
                return self._json(self._login_payload(login))
            except Exception as exc:
                login.error = self._friendly_error(exc)
                status = self._error_status(exc)
                payload = self._login_payload(login)
                payload["error"] = login.error
                return self._json(payload, status)
            await self._finish_login(login)
            return self._json(self._login_payload(login))

    async def _submit_password(self, request: web.Request) -> web.Response:
        login = await self._find_login(request)
        if isinstance(login, web.Response):
            return login
        body = await self._json_body(request)
        password = str(body.get("password") or "")
        if not password:
            return self._error(400, "Введите пароль 2FA")
        async with login.lock:
            if login.state != "password_required":
                return self._error(409, "Пароль сейчас не требуется")
            try:
                await asyncio.wait_for(
                    login.client.sign_in(password=password),
                    self._network_timeout,
                )
            except Exception as exc:
                login.error = self._friendly_error(exc)
                payload = self._login_payload(login)
                payload["error"] = login.error
                return self._json(payload, self._error_status(exc))
            await self._finish_login(login)
            return self._json(self._login_payload(login))

    async def _resend_code(self, request: web.Request) -> web.Response:
        login = await self._find_login(request)
        if isinstance(login, web.Response):
            return login
        async with login.lock:
            if login.state not in ("code_sent", "error"):
                return self._error(409, "Сейчас нельзя запросить код")
            try:
                sent = await asyncio.wait_for(
                    login.client.send_code_request(login.phone),
                    self._network_timeout,
                )
                login.phone_code_hash = sent.phone_code_hash
                login.state = "code_sent"
                login.error = None
                return self._json(self._login_payload(login))
            except Exception as exc:
                login.error = self._friendly_error(exc)
                return self._json(
                    self._login_payload(login),
                    self._error_status(exc),
                )

    async def _delete_login(self, request: web.Request) -> web.Response:
        login = await self._find_login(request)
        if isinstance(login, web.Response):
            return login
        await self._cancel_login(login)
        return self._json({"ok": True})

    async def _finish_login(self, login: LoginSession) -> None:
        if login.state in ("authorized", "finishing"):
            return
        login.state = "finishing"
        actual_phone = login.phone
        try:
            me = await asyncio.wait_for(
                login.client.get_me(), self._network_timeout
            )
            if me and me.phone:
                with contextlib.suppress(ValueError):
                    actual_phone = normalize_phone(me.phone)
            if not actual_phone:
                raise ValueError("Telegram не вернул номер аккаунта")
            if (
                login.phone
                and actual_phone != login.phone
                and self._config_path(login.phone).exists()
            ):
                raise ValueError(
                    "Вход выполнен под другим номером "
                    f"+{actual_phone}, а конфиг +{login.phone} "
                    "уже существует"
                )
            if actual_phone in self._managers:
                raise ValueError(f"Клиент +{actual_phone} уже запущен")
            existing, existing_error = await self._read_config(actual_phone)
            if existing_error:
                raise ValueError(
                    "Конфиг найден, но повреждён. Сначала исправьте JSON."
                )
            with contextlib.suppress(Exception):
                await asyncio.wait_for(login.client.disconnect(), 5)
            temp_session = Path(str(login.temp_session) + ".session")
            if not await asyncio.to_thread(temp_session.exists):
                raise ValueError("Telegram не создал файл сессии")
            target = self._session_path(actual_phone)
            target.parent.mkdir(exist_ok=True)
            await asyncio.to_thread(temp_session.replace, target)
            data = dict(existing or {})
            data["api_id"] = login.api_id
            data["api_hash"] = login.api_hash
            data.pop("phone", None)
            await self._write_config(actual_phone, data)
            login.result_phone = actual_phone
            login.state = "authorized"
            login.error = None
            login.qr_svg = None
            login.finished_at = time.time()
            logger.info(f"Веб-панель: клиент +{actual_phone} авторизован")
            if not data.get("disabled"):
                await self._launch(actual_phone)
            else:
                self._set_status(actual_phone, "disabled")
        except Exception as exc:
            login.state = "error"
            login.error = self._friendly_error(exc)
            login.finished_at = time.time()
            logger.warning(
                f"Веб-панель: ошибка входа {login.phone or 'QR'}: {exc}"
            )
            with contextlib.suppress(Exception):
                await asyncio.wait_for(login.client.disconnect(), 5)
            if login.qr_task and login.qr_task is not asyncio.current_task():
                login.qr_task.cancel()

    async def _qr_loop(self, login_id: str) -> None:
        login = self._logins.get(login_id)
        if not login:
            return
        try:
            while True:
                qr = login.qr
                if qr is None:
                    return
                timeout = max(
                    1.0,
                    (qr.expires - datetime.now(tz=UTC)).total_seconds() + 0.5,
                )
                try:
                    await qr.wait(timeout=timeout)
                except TimeoutError:
                    async with login.lock:
                        if login.state != "qr_waiting":
                            return
                        try:
                            await asyncio.wait_for(
                                qr.recreate(), self._network_timeout
                            )
                        except Exception as exc:
                            login.state = "error"
                            login.error = self._friendly_error(exc)
                            login.finished_at = time.time()
                            return
                        login.qr_svg = qr_svg(
                            qr.url, self._qr_box_size, self._qr_border
                        )
                    continue
                except errors.SessionPasswordNeededError:
                    async with login.lock:
                        if login.state == "qr_waiting":
                            login.state = "password_required"
                            login.error = None
                            login.qr_svg = None
                    return
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    async with login.lock:
                        login.state = "error"
                        login.error = self._friendly_error(exc)
                        login.finished_at = time.time()
                    return
                else:
                    async with login.lock:
                        if login.state in (
                            "qr_waiting",
                            "password_required",
                        ):
                            await self._finish_login(login)
                    return
        except asyncio.CancelledError:
            raise

    def _friendly_error(self, exc: Exception) -> str:
        if isinstance(exc, TimeoutError):
            return (
                "Telegram не отвечает. Проверьте сеть/прокси и попробуйте снова"
            )
        if isinstance(exc, (ConnectionError, OSError)):
            return f"Ошибка сети: {exc}"
        if isinstance(exc, errors.FloodWaitError):
            return f"Telegram просит подождать {exc.seconds} с. из-за лимита попыток"
        return next(
            (text for cls, text, _ in _TG_ERRORS if isinstance(exc, cls)),
            f"{type(exc).__name__}: {exc}",
        )

    def _error_status(self, exc: Exception) -> int:
        if isinstance(exc, TimeoutError):
            return 504
        if isinstance(exc, (ConnectionError, OSError)):
            return 502
        if isinstance(exc, errors.FloodWaitError):
            return 429
        return next(
            (status for cls, _, status in _TG_ERRORS if isinstance(exc, cls)),
            500,
        )

    def _telegram_error(self, exc: Exception) -> web.Response:
        return self._error(self._error_status(exc), self._friendly_error(exc))

    async def _cancel_login(self, login: LoginSession) -> None:
        async with login.lock:
            if login.closed:
                self._logins.pop(login.id, None)
                return
            login.state = "cancelled"
            login.finished_at = time.time()
            login.closed = True
            task = login.qr_task
            if task and task is not asyncio.current_task():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
            with contextlib.suppress(Exception):
                await asyncio.wait_for(login.client.disconnect(), 5)
            await self._remove_temp_session(login.temp_session)
        self._logins.pop(login.id, None)

    async def _remove_temp_session(self, path: Path) -> None:
        for suffix in (".session", ".session-journal"):
            with contextlib.suppress(OSError):
                await asyncio.to_thread(
                    Path(str(path) + suffix).unlink, missing_ok=True
                )

    async def _cleanup_loop(self) -> None:
        try:
            while not self._closing:
                await asyncio.sleep(60)
                now = time.time()
                for login in list(self._logins.values()):
                    if login.closed:
                        self._logins.pop(login.id, None)
                        continue
                    if login.finished_at and now - login.finished_at > 120:
                        await self._cancel_login(login)
                        continue
                    if now > login.expires_at and login.state != "authorized":
                        async with login.lock:
                            if login.state in (
                                "authorized",
                                "cancelled",
                            ):
                                continue
                            login.state = "expired"
                            login.error = "Время входа истекло"
                            login.finished_at = now
                        with contextlib.suppress(Exception):
                            await asyncio.wait_for(login.client.disconnect(), 5)
                        if (
                            login.qr_task
                            and login.qr_task is not asyncio.current_task()
                        ):
                            login.qr_task.cancel()
                        await self._remove_temp_session(login.temp_session)
        except asyncio.CancelledError:
            raise

    async def _system(self, request: web.Request) -> web.Response:
        import platform
        import shutil

        import psutil

        mem = psutil.virtual_memory()
        try:
            disk = shutil.disk_usage(str(Path.cwd()))
            disk_data = {
                "total": disk.total,
                "used": disk.used,
                "free": disk.free,
                "percent": round(disk.used / disk.total * 100, 1),
            }
        except OSError:
            disk_data = {
                "total": 0,
                "used": 0,
                "free": 0,
                "percent": 0,
            }
        try:
            load = list(psutil.getloadavg())
        except AttributeError, OSError:
            load = []
        cpu_freq = None
        net = None
        with contextlib.suppress(Exception):
            cpu_freq = psutil.cpu_freq()
        with contextlib.suppress(Exception):
            net = psutil.net_io_counters()
        return self._json(
            {
                "cpu": {
                    "percent": psutil.cpu_percent(interval=None),
                    "cores": psutil.cpu_count(logical=True),
                    "physical": psutil.cpu_count(logical=False),
                    "freq": round(cpu_freq.current) if cpu_freq else None,
                    "load": [round(x, 2) for x in load],
                },
                "memory": {
                    "total": mem.total,
                    "used": mem.used,
                    "available": mem.available,
                    "percent": mem.percent,
                },
                "disk": disk_data,
                "uptime": int(time.time() - psutil.boot_time()),
                "network": {
                    "sent": getattr(net, "bytes_sent", 0),
                    "recv": getattr(net, "bytes_recv", 0),
                },
                "platform": (f"{platform.system()} {platform.release()}"),
                "python": platform.python_version(),
                "clients": {
                    "total": len(list(pathes.clients.glob("*.json"))),
                    "running": sum(
                        (self._statuses.get(p.stem) or {}).get("status")
                        in ("running", "starting")
                        for p in pathes.clients.glob("*.json")
                    ),
                },
            }
        )

    async def _ws_logs(self, request: web.Request) -> web.StreamResponse:
        if not self._authorized(request):
            return self._error(401, "Требуется вход в панель")
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        async with self._log_broker.subscribe() as queue:
            await ws.send_str(
                orjson.dumps(
                    {
                        "type": "history",
                        "entries": self._log_broker.history(),
                    }
                ).decode()
            )

            async def sender() -> None:
                try:
                    while True:
                        entry = await queue.get()
                        await ws.send_str(
                            orjson.dumps(
                                {"type": "log", "entry": entry}
                            ).decode()
                        )
                except (
                    asyncio.CancelledError,
                    ConnectionResetError,
                    RuntimeError,
                ):
                    return

            send_task = asyncio.create_task(sender())
            try:
                async for message in ws:
                    if message.type == WSMsgType.ERROR:
                        break
            finally:
                send_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await send_task
        return ws
