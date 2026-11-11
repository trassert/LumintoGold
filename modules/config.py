from pathlib import Path

import aiofiles
import orjson
import yaml
from loguru import logger
from sycm import ConfigManager, ConfigSection

from . import pathes

logger.info(f"Загружен модуль {__name__}!")


config = ConfigManager(pathes.config, defaults=pathes.default_config)
tokens = ConfigManager(pathes.tokens, defaults=pathes.default_tokens)


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _load_section(path: Path, defaults: Path) -> ConfigSection:
    default_data = _read_yaml(defaults)
    data = _read_yaml(path)
    if not isinstance(data, dict) or not isinstance(default_data, dict):
        raise ValueError(f"{path}: ожидается YAML-объект")
    return ConfigSection(data, default_data)


def reload() -> None:
    """Перечитывает config.yml и tokens.yml, сохраняя ссылки на объекты."""
    new_config = _load_section(pathes.config, pathes.default_config)
    new_tokens = _load_section(pathes.tokens, pathes.default_tokens)
    config._data = new_config
    tokens._data = new_tokens
    logger.info("Глобальные config.yml и tokens.yml перечитаны")


async def load_client(clients_dir: Path, client_file: str):
    try:
        async with aiofiles.open(clients_dir / client_file, "rb") as f:
            data = orjson.loads(await f.read())
        phone = Path(client_file).stem
        return phone, data["api_id"], data["api_hash"]
    except orjson.JSONDecodeError:
        logger.error(
            f"{client_file} пуст или неправильно размечен! Отключаем клиента.."
        )
        return None


async def set_ai_model(model: str) -> None:
    """Точечно обновляет ai.model в config.yml, сохраняя комментарии."""
    path = pathes.config
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    ai_index = next(
        (i for i, ln in enumerate(lines) if ln.rstrip() == "ai:" or ln.rstrip().startswith("ai: ")),
        None,
    )
    if ai_index is None:
        # ai-блока нет — добавляем в конец файла.
        lines.append(f"\nai:\n  model: {model}\n")
    else:
        indent = "  "
        model_line = next(
            (
                i
                for i in range(ai_index + 1, len(lines))
                if lines[i].strip() and not lines[i].startswith(" ")
            ),
            len(lines),
        )
        replaced = False
        for i in range(ai_index + 1, model_line):
            if lines[i].lstrip().startswith("model:"):
                lines[i] = f"{indent}model: {model}\n"
                replaced = True
                break
        if not replaced:
            lines.insert(ai_index + 1, f"{indent}model: {model}\n")

    path.write_text("".join(lines), encoding="utf-8")
    reload()
    logger.info(f"AI режим изменён на {model}")
