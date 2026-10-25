from copy import deepcopy
from pathlib import Path
from typing import Any

import aiofiles
import orjson
import yaml
from loguru import logger

from . import config, pathes

logger.info(f"Загружен модуль {__name__}!")

groups: list[dict] = []
fields: dict[str, dict] = {}
default: dict[str, Any] = {}


def _resolve_default(meta: dict) -> Any:
    source = meta.get("default_from")
    if not source:
        return meta.get("default")
    target: Any = config
    try:
        for part in str(source).split("."):
            target = getattr(target, part)
    except AttributeError:
        logger.error(f"Не найден источник default: {source}")
        return None
    return target


def _load_schema() -> tuple[list[dict], dict[str, dict], dict[str, Any]]:
    raw = yaml.safe_load(pathes.settings_schema.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("settings.yml должен быть объектом")
    raw_groups = raw.get("groups") or []
    raw_fields = raw.get("fields") or {}
    if not isinstance(raw_groups, list) or not isinstance(raw_fields, dict):
        raise ValueError("settings.yml: groups/fields имеют неверный формат")
    group_ids = {
        str(group.get("id")) for group in raw_groups if isinstance(group, dict)
    }
    resolved_fields: dict[str, dict] = {}
    resolved_defaults: dict[str, Any] = {}
    for key, meta in raw_fields.items():
        if not isinstance(meta, dict):
            raise ValueError(f"settings.yml: поле {key} должно быть объектом")
        item = dict(meta)
        if item.get("group") not in group_ids:
            item["group"] = "advanced"
        resolved_fields[str(key)] = item
        resolved_defaults[str(key)] = _resolve_default(item)
    return raw_groups, resolved_fields, resolved_defaults


def reload_schema() -> None:
    """Перечитывает реестр настроек и пересобирает defaults."""
    new_groups, new_fields, new_defaults = _load_schema()
    groups[:] = new_groups
    fields.clear()
    fields.update(new_fields)
    default.clear()
    default.update(new_defaults)
    logger.info(f"Реестр настроек: {len(fields)} полей, {len(groups)} групп")


def schema_payload() -> dict:
    """Схема для UI с уже разрешёнными defaults."""
    return {
        "groups": deepcopy(groups),
        "fields": {
            key: {**meta, "default": deepcopy(default.get(key))}
            for key, meta in fields.items()
        },
    }


reload_schema()


class UBSettings:
    def __init__(self, number: str, path: Path = pathes.clients) -> None:
        self.filename = path / f"{number}.json"
        self._data: dict = None

    async def _ensure_loaded(self, forced=False) -> None:
        if self._data is not None and not forced:
            return
        if not self.filename.exists():
            self._data = {}
            return
        async with aiofiles.open(self.filename, "rb") as f:
            self._data = orjson.loads(await f.read())

    async def _flush(self) -> None:
        async with aiofiles.open(self.filename, "wb") as f:
            await f.write(orjson.dumps(self._data, option=orjson.OPT_INDENT_2))

    async def reload(self) -> None:
        await self._ensure_loaded(forced=True)

    async def all(self) -> dict:
        await self._ensure_loaded()
        return dict(self._data)

    async def replace(self, data: dict) -> None:
        self._data = dict(data)
        await self._flush()

    async def get(self, name_setting: str, if_none: Any = None) -> Any:
        await self._ensure_loaded()
        if if_none is not None:
            return self._data.get(name_setting, if_none)
        value = self._data.get(name_setting, default.get(name_setting))
        if isinstance(value, (dict, list)):
            return deepcopy(value)
        return value

    async def set(self, key: str, value: Any) -> None:
        await self._ensure_loaded()
        self._data[key] = value
        await self._flush()

    async def remove(self, key: str) -> None:
        await self._ensure_loaded()
        self._data.pop(key, None)
        await self._flush()
