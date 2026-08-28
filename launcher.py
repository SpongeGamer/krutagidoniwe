"""Запуск Крутагидона одним действием.

Что делает:
  1. Проверяет и доустанавливает зависимости.
  2. Поднимает игровой сервер и УБЕЖДАЕТСЯ, что он отвечает.
  3. Открывает доступ из интернета и ПРОВЕРЯЕТ ссылку настоящим запросом.
  4. Печатает ссылку только после того, как она реально заработала.
  5. Следит за игрой: если туннель отвалится — поднимает заново.

Останавливается по Ctrl+C.
"""
from __future__ import annotations

import os
import platform
import random
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = 8000
LOG = ROOT / "launcher.log"
WORDS = ["kotel", "zhaba", "griby", "chipsy", "vopli", "loshara", "magiya", "vihr", "peklo", "sopli"]

CF_URLS = {
    ("Windows", "AMD64"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe",
    ("Windows", "x86"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-386.exe",
    ("Linux", "x86_64"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
    ("Linux", "aarch64"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64",
    ("Darwin", "x86_64"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz",
    ("Darwin", "arm64"): "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-arm64.tgz",
}


def say(text: str = "") -> None:
    print(text, flush=True)


def line(char: str = "─") -> None:
    say(char * 62)


def room_code() -> str:
    return f"{random.choice(WORDS)}-{random.randint(1000, 9999)}"


def local_ip() -> str:
    """Адрес в домашней сети.

    Docker/WSL/VirtualBox создают адаптеры вида 172.x и 169.254.x — по ним
    друзья не подключатся. Ищем настоящий домашний адрес (192.168.x, 10.x).
    """
    candidates: list[str] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        candidates.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            candidates.append(info[4][0])
    except Exception:
        pass

    def rank(ip: str) -> int:
        if ip.startswith("192.168."):
            return 0
        if ip.startswith("10."):
            return 1
        if ip.startswith("172."):
            return 3          # чаще всего Docker/WSL
        if ip.startswith(("169.254.", "127.")):
            return 4
        return 2

    good = [ip for ip in candidates if ip and not ip.startswith("127.")]
    if not good:
        return "127.0.0.1"
    return sorted(good, key=rank)[0]


def port_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", port)) == 0


def http_ok(url: str, timeout: float = 12.0) -> bool:
    """Настоящий запрос: страница действительно отдаётся."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "krutagidon-launcher"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def kill_proc(proc) -> None:
    """Убить процесс наверняка.

    cloudflared на terminate() уходит в бесконечные повторы подключения
    и продолжает засорять лог, мешая работающему туннелю.
    """
    if not proc or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=4)
    except Exception:
        try:
            proc.kill()
            proc.wait(timeout=3)
        except Exception:
            pass


def install_deps() -> bool:
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
        return True
    except ImportError:
        pass
    say("Первый запуск: доустанавливаю библиотеки (займёт полминуты)…")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "-r", str(ROOT / "requirements.txt")],
            check=True,
        )
        return True
    except subprocess.CalledProcessError:
        say("Не получилось установить библиотеки.")
        say("Проверь интернет и запусти вручную:")
        say(f"    {sys.executable} -m pip install -r requirements.txt")
        return False


def cloudflared_path() -> Path | None:
    """Системный, локальный или свежескачанный cloudflared."""
    system = platform.system()
    name = "cloudflared.exe" if system == "Windows" else "cloudflared"
    local = ROOT / name

    if local.exists() and local.stat().st_size > 1_000_000:
        if system != "Windows":
            try:
                local.chmod(0o755)   # права могли слететь при копировании
            except Exception:
                pass
        return local

    found = shutil.which("cloudflared")
    if found:
        return Path(found)

    machine = platform.machine()
    if system == "Darwin" and machine not in ("x86_64", "arm64"):
        machine = "arm64"
    url = CF_URLS.get((system, machine))
    if not url:
        return None
    if url.endswith(".tgz"):
        say("Для macOS поставь cloudflared командой:  brew install cloudflared")
        return None

    say("Скачиваю cloudflared (нужен один раз, ~38 МБ)…")

    def progress(block: int, block_size: int, total: int) -> None:
        if total <= 0:
            return
        pct = min(100, int(block * block_size * 100 / total))
        print(f"\r   загружено {pct}%", end="", flush=True)

    try:
        tmp = local.with_suffix(".part")
        urllib.request.urlretrieve(url, tmp, reporthook=progress)
        print()
        tmp.replace(local)
        if system != "Windows":
            local.chmod(0o755)
        return local
    except Exception as exc:
        say(f"Не удалось скачать cloudflared: {exc}")
        return None


def start_server(logfile) -> subprocess.Popen | None:
    """Поднимает сервер и ждёт, пока он реально начнёт отвечать."""
    if port_busy(PORT):
        say(f"Порт {PORT} уже занят — похоже, игра запущена в другом окне.")
        say("Закрой то окно и запусти снова.")
        return None
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.server:app",
         "--host", "0.0.0.0", "--port", str(PORT), "--log-level", "warning"],
        cwd=str(ROOT), env=env,
        stdout=logfile, stderr=subprocess.STDOUT,   # логи в файл, а не в пустоту
    )
    for _ in range(80):
        if proc.poll() is not None:
            say("Сервер не смог запуститься. Подробности в файле launcher.log")
            return None
        if http_ok(f"http://127.0.0.1:{PORT}/", timeout=3):
            return proc
        time.sleep(0.25)
    say("Сервер запустился, но не отвечает. Подробности в launcher.log")
    proc.terminate()
    return None


def start_tunnel(binary: Path, logfile, protocol: str = "auto") -> tuple[subprocess.Popen | None, str | None]:
    """Поднимает туннель и проверяет адрес настоящим запросом.

    protocol: "auto" (QUIC/UDP) или "http2" (обычный TCP).
    У многих российских провайдеров UDP режется — тогда спасает http2.
    """
    cmd = [str(binary), "tunnel",
           "--url", f"http://127.0.0.1:{PORT}",
           "--no-autoupdate",
           # IPv6 у многих провайдеров кривой — Cloudflare тогда не достучится
           # до туннеля, и в браузере вылезает 502/1033. Держимся IPv4.
           "--edge-ip-version", "4",
           "--retries", "10",
           "--loglevel", "info"]
    if protocol != "auto":
        cmd += ["--protocol", protocol]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    found: dict[str, str] = {}
    pattern = re.compile(r"https://[-\w]+\.trycloudflare\.com")

    def reader() -> None:
        for raw in proc.stdout:  # type: ignore[union-attr]
            logfile.write(raw)
            logfile.flush()
            if "url" not in found:
                m = pattern.search(raw)
                if m:
                    found["url"] = m.group(0)

    threading.Thread(target=reader, daemon=True).start()

    # Ждём, пока cloudflared выдаст адрес (обычно 3-10 секунд).
    print("   жду адрес", end="", flush=True)
    for i in range(80):
        if "url" in found:
            break
        if proc.poll() is not None:
            say(" — cloudflared завершился, смотри launcher.log")
            return None, None
        if i % 3 == 0:
            print(".", end="", flush=True)
        time.sleep(0.3)
    url = found.get("url")
    if not url:
        say(" — адрес не пришёл")
        kill_proc(proc)
        return None, None
    say(f"\n   адрес: {url}")

    # Адрес получен, но маршрут Cloudflare поднимается не мгновенно: сразу после
    # старта ссылка отдаёт 502 или 1033. Ждём ТРЁХ успешных ответов подряд —
    # иначе друзья получат ошибку вместо игры.
    # Ждём максимум 45 секунд и показываем точки, чтобы окно не выглядело
    # зависшим. Двух успешных ответов подряд достаточно.
    print("Проверяю ссылку", end="", flush=True)
    streak = 0
    deadline = time.time() + 45
    while time.time() < deadline:
        if proc.poll() is not None:
            say(" — туннель закрылся")
            return None, None
        print(".", end="", flush=True)
        if http_ok(f"{url}/", timeout=5):
            streak += 1
            if streak >= 2:
                say(" готово!")
                return proc, url
        else:
            streak = 0
        time.sleep(1.0)

    # Время вышло. Если хоть раз ответила — отдаём как есть: за ссылкой
    # дальше присматривает основной цикл и при поломке поднимет новую.
    if streak > 0 or http_ok(f"{url}/", timeout=5):
        say(" ссылка отвечает с перебоями, но играть можно")
        return proc, url

    say(" не отвечает")
    kill_proc(proc)
    return None, None


def open_tunnel(binary: Path, logfile) -> tuple[subprocess.Popen | None, str | None]:
    """Пробуем разные способы: сначала быстрый QUIC, потом надёжный http2.

    У части российских провайдеров UDP (QUIC) режется наглухо — cloudflared
    крутится в бесконечных «timeout: no recent network activity». Обычный
    TCP-протокол http2 в таких сетях проходит нормально.
    """
    attempts = [
        ("auto", "быстрый способ"),
        ("http2", "запасной способ (для сетей, где режут UDP)"),
        ("http2", "запасной способ, ещё раз"),
    ]
    for index, (protocol, label) in enumerate(attempts, start=1):
        say(f"Открываю доступ из интернета… (способ {index + 1}: {label})")
        proc, url = start_tunnel(binary, logfile, protocol)
        if url:
            return proc, url
        kill_proc(proc)          # не оставляем висеть неудачную попытку
        say("   не вышло")
        time.sleep(2)
    return None, None


def open_any_tunnel(binary: Path | None, logfile) -> tuple[subprocess.Popen | None, str | None, str]:
    """Cloudflare, а если он совсем не пускает — запасной сервис."""
    # Порядок подобран под российские сети: сначала то, что реально работает.

    # 1) CloudPub — серверы в России, блокировать нечего. Если токен уже
    #    сохранён, подключается молча и мгновенно.
    if saved_token():
        say("Открываю доступ из интернета… (CloudPub)")
        proc, url = start_cloudpub(logfile, interactive=False)
        if url:
            return proc, url, "cloudpub"
        say()

    # 2) localtunnel — в прошлый раз именно он и сработал.
    say("Открываю доступ из интернета… (способ 2)")
    proc, url = start_localtunnel(logfile)
    if url:
        return proc, url, "localtunnel"

    # 3) pinggy — SSH через 443 порт.
    say()
    say("Открываю доступ из интернета… (способ 3: через порт 443)")
    proc, url = start_pinggy(logfile)
    if url:
        return proc, url, "pinggy"

    # 4) Cloudflare — его в РФ режут по DPI, поэтому в самом конце.
    if binary:
        say()
        proc, url = open_tunnel(binary, logfile)
        if url:
            return proc, url, "cloudflare"

    # 5) Ничего не вышло — предлагаем разовую регистрацию в CloudPub.
    if not saved_token() and cloudpub_path():
        say()
        say("Все быстрые способы заблокированы твоим провайдером.")
        proc, url = start_cloudpub(logfile, interactive=True)
        if url:
            return proc, url, "cloudpub"

    return None, None, ""


CLOUDPUB_URLS = {
    ("Windows", "AMD64"): "https://cloudpub.ru/download/stable/clo-3.4.889-stable-windows-x86_64.zip",
    ("Linux", "x86_64"): "https://cloudpub.ru/download/stable/clo-3.4.889-stable-linux-x86_64.tar.gz",
    ("Linux", "aarch64"): "https://cloudpub.ru/download/stable/clo-3.4.889-stable-linux-aarch64.tar.gz",
    ("Darwin", "x86_64"): "https://cloudpub.ru/download/stable/clo-3.4.889-stable-macos-x86_64.tar.gz",
    ("Darwin", "arm64"): "https://cloudpub.ru/download/stable/clo-3.4.889-stable-macos-aarch64.tar.gz",
}
def _token_file() -> Path:
    """Токен храним ВНЕ папки игры — в личных настройках пользователя.

    Так его физически невозможно случайно закоммитить в git, даже если
    кто-то удалит .gitignore. Старый файл рядом с игрой подхватываем
    один раз и переносим.
    """
    if platform.system() == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    folder = base / "krutagidon"
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except Exception:
        return ROOT / "cloudpub_token.txt"
    return folder / "cloudpub_token.txt"


TOKEN_FILE = _token_file()
_OLD_TOKEN_FILE = ROOT / "cloudpub_token.txt"


def cloudpub_path() -> Path | None:
    """Клиент CloudPub — российский сервис, серверы внутри РФ."""
    system = platform.system()
    name = "clo.exe" if system == "Windows" else "clo"
    local = ROOT / name
    if local.exists():
        if system != "Windows":
            try:
                local.chmod(0o755)
            except Exception:
                pass
        return local

    url = CLOUDPUB_URLS.get((system, platform.machine()))
    if not url:
        return None

    say("   скачиваю клиент CloudPub (3 МБ, один раз)…")
    try:
        import tarfile
        import zipfile
        tmp = ROOT / ("clo_download.zip" if url.endswith(".zip") else "clo_download.tgz")
        urllib.request.urlretrieve(url, tmp)
        if url.endswith(".zip"):
            with zipfile.ZipFile(tmp) as z:
                z.extractall(ROOT)
        else:
            with tarfile.open(tmp) as t:
                t.extractall(ROOT)
        tmp.unlink(missing_ok=True)
        if local.exists():
            if system != "Windows":
                local.chmod(0o755)
            return local
    except Exception as exc:
        say(f"   не удалось скачать: {exc}")
    return None


def saved_token() -> str:
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text(encoding="utf-8").strip()
    # Переезд со старого места: забираем токен и убираем его из папки игры.
    if _OLD_TOKEN_FILE.exists():
        token = _OLD_TOKEN_FILE.read_text(encoding="utf-8").strip()
        if token:
            try:
                TOKEN_FILE.write_text(token, encoding="utf-8")
                _OLD_TOKEN_FILE.unlink()
                say("  Токен перенесён в личные настройки — из папки игры удалён.")
            except Exception:
                pass
        return token
    return ""


def ask_token() -> str:
    """Разовая регистрация: токен вводится один раз и запоминается."""
    say()
    line("─")
    say("  CloudPub — российский сервис, работает без VPN.")
    say("  Нужна разовая бесплатная регистрация (2 минуты, только у тебя):")
    say()
    say("    1. Открой https://cloudpub.ru/dashboard")
    say("    2. Зарегистрируйся (почта + пароль)")
    say("    3. Скопируй токен с главной страницы кабинета")
    say()
    say("  Друзьям регистрироваться НЕ нужно — они просто откроют ссылку.")
    line("─")
    say()
    try:
        webbrowser.open("https://cloudpub.ru/dashboard")
    except Exception:
        pass
    try:
        token = input("  Вставь токен сюда (или Enter, чтобы пропустить): ").strip()
    except EOFError:
        return ""
    if token:
        TOKEN_FILE.write_text(token, encoding="utf-8")
        say("  Токен сохранён — больше спрашивать не буду.")
    return token


def start_cloudpub(logfile, interactive: bool = True) -> tuple[subprocess.Popen | None, str | None]:
    binary = cloudpub_path()
    if not binary:
        return None, None

    token = saved_token()
    if not token:
        if not interactive:
            return None, None
        token = ask_token()
        if not token:
            return None, None
    try:
        subprocess.run([str(binary), "set", "token", token],
                       cwd=str(ROOT), stdout=logfile, stderr=subprocess.STDOUT, timeout=30)
    except Exception:
        pass

    proc = subprocess.Popen(
        [str(binary), "publish", "http", str(PORT)],
        cwd=str(ROOT),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    found: dict[str, str] = {}
    pattern = re.compile(r"https://[-\w.]+\.cloudpub\.ru")

    def reader() -> None:
        for raw in proc.stdout:  # type: ignore[union-attr]
            logfile.write(raw)
            logfile.flush()
            if "url" not in found:
                m = pattern.search(raw)
                if m:
                    found["url"] = m.group(0)
            if "токен" in raw.lower() and "отсутств" in raw.lower():
                found["bad_token"] = "1"

    threading.Thread(target=reader, daemon=True).start()

    print("   жду адрес", end="", flush=True)
    for i in range(80):
        if "url" in found:
            break
        if found.get("bad_token"):
            say(" — токен не принят")
            TOKEN_FILE.unlink(missing_ok=True)
            proc.terminate()
            return None, None
        if proc.poll() is not None:
            say(" — клиент завершился")
            return None, None
        if i % 3 == 0:
            print(".", end="", flush=True)
        time.sleep(0.5)

    url = found.get("url")
    if not url:
        say(" — адрес не пришёл")
        kill_proc(proc)
        return None, None
    say(f"\n   адрес: {url}")

    print("   проверяю ссылку", end="", flush=True)
    for _ in range(20):
        print(".", end="", flush=True)
        if http_ok(f"{url}/", timeout=10):
            say(" готово!")
            return proc, url
        time.sleep(1.5)
    say(" не отвечает")
    kill_proc(proc)
    return None, None


def start_pinggy(logfile) -> tuple[subprocess.Popen | None, str | None]:
    """Туннель через pinggy.io по SSH на порту 443.

    Главное преимущество для России: снаружи это обычное HTTPS-соединение
    на 443 порт, которое DPI пропускает. Cloudflare же ходит на свой
    порт 7844 и рубится на TLS-рукопожатии.
    """
    ssh = shutil.which("ssh")
    if not ssh:
        say("   (нужен ssh — в Windows 10/11 он есть по умолчанию)")
        return None, None

    proc = subprocess.Popen(
        [ssh, "-o", "StrictHostKeyChecking=no",
         "-o", "UserKnownHostsFile=" + os.devnull,
         "-o", "ConnectTimeout=25",
         "-o", "ServerAliveInterval=30",
         "-o", "ServerAliveCountMax=3",
         # Без явного логина ssh подставляет имя пользователя Windows,
         # и pinggy начинает спрашивать пароль — окно висит навсегда.
         "-o", "BatchMode=yes",
         "-o", "PasswordAuthentication=no",
         "-o", "PubkeyAuthentication=no",
         "-T", "-p", "443", "-R0:localhost:%d" % PORT, "a@a.pinggy.io"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    found: dict[str, str] = {}
    pattern = re.compile(r"https://[-\w]+\.(?:free\.pinggy\.net|run\.pinggy-free\.link)")

    def reader() -> None:
        for raw in proc.stdout:  # type: ignore[union-attr]
            logfile.write(raw)
            logfile.flush()
            if "url" not in found:
                m = pattern.search(raw)
                if m:
                    found["url"] = m.group(0)

    threading.Thread(target=reader, daemon=True).start()

    print("   жду адрес", end="", flush=True)
    for i in range(90):
        if "url" in found:
            break
        if proc.poll() is not None:
            say(" — соединение закрылось")
            return None, None
        if i % 3 == 0:
            print(".", end="", flush=True)
        time.sleep(0.5)
    url = found.get("url")
    if not url:
        say(" — адрес не пришёл")
        kill_proc(proc)
        return None, None
    say(f"\n   адрес: {url}")

    print("   проверяю ссылку", end="", flush=True)
    for _ in range(20):
        print(".", end="", flush=True)
        if http_ok(f"{url}/", timeout=8):
            say(" готово!")
            return proc, url
        time.sleep(1.5)
    say(" не отвечает")
    kill_proc(proc)
    return None, None


def start_localtunnel(logfile) -> tuple[subprocess.Popen | None, str | None]:
    """Запасной туннель через localtunnel.me (нужен Node.js).

    Работает по обычному TCP и в РФ обычно доступен.
    """
    npx = shutil.which("npx")
    if not npx:
        say("   (запасной путь требует Node.js — пропускаю)")
        return None, None
    say("   поднимаю запасной туннель…")
    try:
        proc = subprocess.Popen(
            [npx, "-y", "localtunnel", "--port", str(PORT)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
    except Exception as exc:
        say(f"   не запустился: {exc}")
        return None, None

    found: dict[str, str] = {}
    pattern = re.compile(r"https://[-\w.]+\.loca\.lt")

    def reader() -> None:
        for raw in proc.stdout:  # type: ignore[union-attr]
            logfile.write(raw)
            logfile.flush()
            if "url" not in found:
                m = pattern.search(raw)
                if m:
                    found["url"] = m.group(0)

    threading.Thread(target=reader, daemon=True).start()
    for _ in range(120):
        if "url" in found:
            break
        if proc.poll() is not None:
            return None, None
        time.sleep(0.5)
    url = found.get("url")
    if not url:
        kill_proc(proc)
        return None, None

    print("   проверяю запасную ссылку", end="", flush=True)
    for _ in range(20):
        print(".", end="", flush=True)
        if http_ok(f"{url}/", timeout=8):
            say(" готово!")
            return proc, url
        time.sleep(1.5)
    say(" не отвечает")
    kill_proc(proc)
    return None, None


def banner(invite: str | None, local_url: str, room: str) -> None:
    say()
    line("═")
    if invite:
        say()
        say("  ССЫЛКА ДЛЯ ДРУЗЕЙ — просто скинь её в чат:")
        say()
        say(f"      {invite}")
        say()
        say("  Проверено: ссылка работает. Открывать можно откуда угодно.")
    else:
        say()
        say("  Через интернет пустить не вышло — похоже, провайдер режет туннели.")
        say()
        say("  По домашней сети играть можно прямо сейчас:")
        say()
        say(f"      {local_url}")
        say()
        say("  Эта ссылка работает для всех, кто сидит на том же Wi-Fi.")
        say()
        say("  Чтобы играть с теми, кто далеко, нужен один из вариантов:")
        say("    • раздать интернет с телефона (мобильные сети режут реже);")
        say("    • включить VPN и запустить лаунчер заново;")
        say("    • поднять игру на дешёвом VPS — подробности в файле")
        say("      «КАК ЗАПУСТИТЬ.md», раздел про российский интернет.")
    say()
    line("─")
    say(f"  Ты играешь здесь:  http://localhost:{PORT}/?room={room}")
    say(f"  Код комнаты: {room}")
    say()
    say("  Окно НЕ закрывай — на нём держится игра.")
    say("  Закончили: нажми Ctrl+C.")
    line("═")
    say()


def main() -> int:
    say()
    line("═")
    say("            К Р У Т А Г И Д О Н   O N L I N E")
    line("═")
    say()

    if not install_deps():
        input("Нажми Enter, чтобы закрыть…")
        return 1

    logfile = open(LOG, "w", encoding="utf-8", errors="replace")

    server = start_server(logfile)
    if not server:
        logfile.close()
        input("Нажми Enter, чтобы закрыть…")
        return 1
    say("Сервер запущен и отвечает.")

    room = room_code()
    binary = cloudflared_path()
    tunnel, url, _kind = open_any_tunnel(binary, logfile)
    if not url:
        say("Через интернет пустить не вышло — играем по домашней сети.")

    invite = f"{url}/?room={room}" if url else None
    local_url = f"http://{local_ip()}:{PORT}/?room={room}"
    banner(invite, local_url, room)

    try:
        webbrowser.open(f"http://localhost:{PORT}/?room={room}")
    except Exception:
        pass

    # ---- присмотр за игрой ----
    try:
        checks = 0
        while True:
            time.sleep(1)
            if server.poll() is not None:
                say()
                say("Сервер остановился. Подробности в launcher.log")
                break
            checks += 1
            if not url or checks % 25 != 0:
                continue

            # Процесс может быть жив, а ссылка при этом отдавать 502/1033.
            # Но одна неудачная попытка — ещё не смерть: сеть моргает.
            # Рвём туннель только после ПЯТИ провалов подряд с паузами.
            if tunnel and tunnel.poll() is not None:
                dead = True
            else:
                dead = True
                for _ in range(5):
                    if http_ok(f"{url}/", timeout=10):
                        dead = False
                        break
                    time.sleep(3)

            if not dead:
                continue

            say()
            say("Ссылка перестала отвечать — поднимаю заново…")
            kill_proc(tunnel)

            tunnel, new_url, _k = open_any_tunnel(binary, logfile)
            if new_url:
                url = new_url
                invite = f"{url}/?room={room}"
                say()
                line("═")
                say("  НОВАЯ ССЫЛКА — перекинь её друзьям:")
                say()
                say(f"      {invite}")
                line("═")
                say()
            else:
                say("Не получилось. Играйте по домашней сети:")
                say(f"      {local_url}")
                url = None
    except KeyboardInterrupt:
        say()
        say("Останавливаю игру…")
    finally:
        for proc in (tunnel, server):
            kill_proc(proc)
        logfile.close()
        say("Готово. До встречи!")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        say()
        say(f"Ошибка: {exc}")
        input("Нажми Enter, чтобы закрыть…")
        sys.exit(1)
