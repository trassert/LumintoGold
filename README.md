# LumintoGold

<p align="center">
  <a href=https://t.me/lumintoch><img src=https://img.shields.io/badge/Sponsored%20by-Luminto-purple?style=for-the-badge&logo=githubsponsors&logoColor=white></a>
  <a href=https://t.me/lumintomc><img src="https://img.shields.io/badge/Telegram-blue?style=for-the-badge&logo=telegram&logoColor=white" alt="Badge"></a>
  <img src="https://img.shields.io/badge/Python-blue?style=for-the-badge&logo=python&logoColor=white" alt="Badge">
  <img src="https://img.shields.io/badge/Ruff-FFC131?style=for-the-badge&logo=ruff&logoColor=black" alt="Badge">
  <img src="https://img.shields.io/badge/uv-FFC131?style=for-the-badge&logo=astral&logoColor=black&logoSize=auto" alt="Badge">
</p>

Развивающийся юзербот, улучшающий Telegram!

> Это не production-ready репо!  
> Для его установки нужно базовое знание Python, Telegram, Linux или Windows.  
> Весь риск и ответственность при установке лежит на вас!  
> При использовании бота старайтесь не нарушать правила!  
> Иначе вы рискуете попасть в ТГ-бан.  
> P.S. - код полностью открыт и редактируем. Вирусов/стиллеров нет. (и не будет)  

### Информация
- [**Команды**](https://github.com/trassert/LumintoGold/wiki)
- [**Юзер-конфиг**](https://t.me/lumintogold/192)

### Веб-панель

Настройки панели лежат в `configs/config.yml` (файл создаётся из `defaults/config.yml` при первом запуске):

```yaml
web:
  host: "127.0.0.1" # 0.0.0.0 — доступ по сети
  port: 8080
  password: "luminto" # смените перед публикацией

# Необязательно: api_id/api_hash приложения для QR и новых клиентов.
# Если не заданы, берутся из первого клиента в clients/.
telegram:
  api_id: 0
  api_hash: ""
```

Пароль хранится в конфиге открытым текстом. Панель отдаёт обычный HTTP: если открываете её наружу, поставьте перед ней HTTPS reverse proxy (например, Caddy) или используйте VPN. Привязка к `127.0.0.1` по умолчанию безопаснее.

Что умеет панель:
- запуск, остановка и перезапуск клиентов, «остановить всех»;
- отдельный флаг автостарта/отключения клиента (не запускается при старте панели);
- добавление клиента по коду Telegram с 2FA, по QR или импортом JSON (по одному и пачкой);
- QR-вход не спрашивает api_id/api_hash: панель берёт их из `telegram` в конфиге или из первого клиента. Это техническое требование Telegram — без app credentials QR сгенерировать нельзя. Для самой первой установки без клиентов укажите их один раз в `telegram` или добавьте клиента по коду;
- редактор конфига: структурированные настройки и сырой JSON, включая исправление битых файлов;
- живые логи и системные метрики;
- конфиги — `clients/<phone>.json`, сессии — `sessions/<phone>.session`.

#### Caddy (опционально)

```caddyfile
panel.example.com {
    reverse_proxy 127.0.0.1:8080
}
```

### Termux
- `termux-change-repo` | Необязательно, просто ускорит установку
- `pkg install -y curl`
- `curl -sL https://gist.githubusercontent.com/trassert/3ebd8c153c0d34ee6a42d451dc169513/raw/ | bash`

Перезагрузите Termux и введите команду `lumintogold` для запуска.  
Обновление: `git pull`

### Debian, Fedora (Linux)
- `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Перезапустите консоль
- `git clone https://github.com/trassert/LumintoGold.git`
- `cd LumintoGold`
- `uv sync`

Запуск: `uv run main.py`  
Обновление: `git pull`

### Windows
- `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
- Перезапустите консоль
- `winget install --id Git.Git -e --source winget`
- `git clone https://github.com/trassert/LumintoGold.git`
- `cd LumintoGold`
- `uv sync`

Запуск: `uv run main.py`  
Обновление: `git pull`

Если вам понравился бот, вы можете:
- Поставить 🌟 проекту
- Материальные пожертвования: [telegram](https://t.me/trassert)
- Предложить идею: [issues](github.com/trassert/LumintoGold/issues) | [telegram](https://t.me/lumintogold)
- Внести свой вклад через Pull Request

Спасибо за использование **LumintoGold**!

Автор проекта: @trassert. При копировании соблюдайте лицензию.
