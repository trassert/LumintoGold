import asyncio
import sys
import threading


_PROMPT = ">>> "
_HELP = """\
clients       - list active clients
ping          - check CLI is alive
addclient     - add a new client without restart
stop <phone>  - stop client by phone number
stopall       - stop all clients
exit / quit   - shutdown
help / ?      - this help"""

_lock = threading.Lock()
_current_input = ""


def _write(text: str) -> None:
    """Стираем промпт, пишем текст, возвращаем промпт с буфером."""
    with _lock:
        sys.stdout.write(f"\r\033[K{text}\n{_PROMPT}{_current_input}")
        sys.stdout.flush()


def loguru_sink(message: str) -> None:
    """logger.add(loguru_sink, enqueue=False) вместо stderr."""
    _write(message.rstrip("\n"))


class CLI:
    def __init__(self, managers, manager_tasks, launch_manager_func, save_config_func):
        self._managers = managers
        self._tasks = manager_tasks
        self._launch = launch_manager_func
        self._save_config = save_config_func
        self._line_queue: asyncio.Queue[str] = asyncio.Queue()
        self._loop: asyncio.AbstractEventLoop | None = None

    def _input_thread(self) -> None:
        """Читает посимвольно чтобы обновлять _current_input в реальном времени."""
        global _current_input
        import tty, termios, os
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            buf = []
            while True:
                ch = os.read(fd, 1)
                if not ch:
                    break
                c = ch.decode("utf-8", errors="replace")
                if c in ("\r", "\n"):
                    line = "".join(buf)
                    buf.clear()
                    with _lock:
                        _current_input = ""
                        sys.stdout.write(f"\r\033[K")
                        sys.stdout.flush()
                    self._loop.call_soon_threadsafe(self._line_queue.put_nowait, line)
                elif c in ("\x7f", "\x08"):  # backspace
                    if buf:
                        buf.pop()
                        with _lock:
                            _current_input = "".join(buf)
                            sys.stdout.write(f"\r\033[K{_PROMPT}{_current_input}")
                            sys.stdout.flush()
                elif c == "\x03":  # Ctrl+C
                    self._loop.call_soon_threadsafe(self._line_queue.put_nowait, None)
                    break
                elif c >= " ":
                    buf.append(c)
                    with _lock:
                        _current_input = "".join(buf)
                        sys.stdout.write(c)
                        sys.stdout.flush()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

    async def _readline(self) -> str | None:
        return await self._line_queue.get()

    async def _ask(self, prompt: str) -> str:
        _write(prompt)
        result = await self._readline()
        return result or ""

    def _print(self, text: str) -> None:
        _write(text)

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
            case "clients":    await self._cmd_clients()
            case "ping":       await self._cmd_ping()
            case "addclient":  await self._cmd_addclient()
            case "stop":       await self._cmd_stop(arg)
            case "stopall":    await self._cmd_stopall()
            case "exit"|"quit":
                await self._cmd_stopall()
                self._print("Bye.")
                return False
            case "help"|"?":   self._print(_HELP)
            case _:            self._print(f"Unknown command: {cmd!r}. Type 'help'.")
        return True

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        t = threading.Thread(target=self._input_thread, daemon=True)
        t.start()
        with _lock:
            sys.stdout.write(_PROMPT)
            sys.stdout.flush()
        while True:
            line = await self._readline()
            if line is None:
                break
            if not await self._dispatch(line):
                break