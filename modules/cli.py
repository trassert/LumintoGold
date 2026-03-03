import asyncio
import readline
import sys
import threading

_PROMPT = "> "
_HELP = """\
clients       - Список активных клиентов
ping          - Проверка CLI
addclient     - Добавить клиента (интерактивно)
stop <phone>  - Остановить клиента по номеру телефона
stopall       - Остановить всех клиентов
exit / quit   - Выход
help / ?      - Показать эту справку"""

_write_lock = threading.Lock()


def loguru_sink(message: str) -> None:
    """logger.add(loguru_sink, enqueue=False) вместо stderr."""
    with _write_lock:
        buf = readline.get_line_buffer()
        sys.stdout.write(f"\r\033[K{message.rstrip(chr(10))}\n")
        if buf:
            sys.stdout.write(f"{_PROMPT}{buf}")
        sys.stdout.flush()


class CLI:
    def __init__(self, managers, manager_tasks, launch_manager_func, save_config_func):
        self._managers = managers
        self._tasks = manager_tasks
        self._launch = launch_manager_func
        self._save_config = save_config_func
        self._shutting_down = False

    def _print(self, text: str) -> None:
        with _write_lock:
            sys.stdout.write(text + "\n")
            sys.stdout.flush()

    async def _readline(self) -> str:
        return await asyncio.get_running_loop().run_in_executor(None, input, _PROMPT)

    async def _ask(self, prompt: str) -> str:
        return await asyncio.get_running_loop().run_in_executor(None, input, prompt)

    async def _cmd_clients(self):
        if not self._managers:
            self._print("No active clients.")
            return
        self._print("Active clients:\n" + "\n".join(f"  {p}" for p in self._managers))

    async def _cmd_ping(self):
        self._print("pong")

    async def _cmd_addclient(self):
        phone = (await self._ask("Phone: ")).strip()
        api_id_raw = (await self._ask("API ID: ")).strip()
        api_hash = (await self._ask("API Hash: ")).strip()
        try:
            api_id = int(api_id_raw)
        except ValueError:
            self._print("Invalid API ID.")
            return
        if phone in self._managers:
            self._print(f"Client {phone} is already running.")
            return
        await self._save_config(phone, api_id, api_hash)
        launched = await self._launch(phone, api_id, api_hash)
        self._print(f"Client {phone} started." if launched else f"Failed to start {phone}.")

    async def _cmd_stop(self, phone: str):
        if not phone:
            self._print("Usage: stop <phone>")
            return
        manager = self._managers.get(phone)
        if not manager:
            self._print(f"No such client: {phone}")
            return
        await manager.stop()
        self._managers.pop(phone, None)
        task = self._tasks.pop(phone, None)
        if task and not task.done():
            task.cancel()
        self._print(f"Client {phone} stopped.")

    async def _cmd_stopall(self):
        phones = list(self._managers.keys())
        if not phones:
            self._print("No active clients.")
            return
        for phone in phones:
            manager = self._managers.pop(phone, None)
            if manager:
                await manager.stop()
            task = self._tasks.pop(phone, None)
            if task and not task.done():
                task.cancel()
        self._print(f"Stopped {len(phones)} client(s).")

    async def _dispatch(self, line: str) -> bool:
        parts = line.strip().split(maxsplit=1)
        if not parts:
            return True
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""
        match cmd:
            case "clients":
                await self._cmd_clients()
            case "ping":
                await self._cmd_ping()
            case "addclient":
                await self._cmd_addclient()
            case "stop":
                await self._cmd_stop(arg)
            case "stopall":
                await self._cmd_stopall()
            case "exit" | "quit":
                await self._cmd_stopall()
                self._print("Пока.")
                return False
            case "help" | "?":
                self._print(_HELP)
            case _:
                self._print(f"Unknown command: {cmd!r}. Type 'help'.")
        return True

    async def run(self) -> None:
        import signal

        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGINT, lambda: loop.create_task(self._shutdown()))
        while True:
            try:
                line = await self._readline()
            except EOFError:
                break
            if self._shutting_down:
                break
            if not line.strip():
                continue
            if not await self._dispatch(line):
                break

    async def _shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        await self._cmd_stopall()
        self._print("Bye.")
        for task in asyncio.all_tasks():
            if task is not asyncio.current_task():
                task.cancel()
        import os
        import signal

        os.kill(os.getpid(), signal.SIGTERM)
