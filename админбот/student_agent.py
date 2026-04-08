# =============================================================================
#  student_agent.py — Агент управления (запускается на ПК студента)
#
#  Запуск: python student_agent.py
#
#  Зависимости: pyTelegramBotAPI, requests, psutil, Pillow
#  Стандартные библиотеки: os, time, sys, logging, platform,
#                           zipfile, socket, subprocess, threading, tkinter
#
#  Правила антивирусной совместимости:
#   - Только subprocess.run / Popen, никакого os.system
#   - Нет PyInstaller / скрытых запусков
#   - Консоль всегда открыта с русскими логами
#   - Используются только стандартные и учебные библиотеки
# =============================================================================

import os
import sys
import time
import socket
import logging
import platform
import zipfile
import subprocess
import threading
from datetime import datetime
from pathlib import Path

# --- Сторонние библиотеки ---
try:
    import requests
    import psutil
    from PIL import ImageGrab
    import telebot
except ImportError as e:
    print(f"[ОШИБКА] Отсутствует зависимость: {e}")
    print("Запустите: pip install pyTelegramBotAPI requests psutil Pillow")
    input("Нажмите Enter для выхода...")
    sys.exit(1)

# --- tkinter (уведомления) ---
try:
    import tkinter as tk
    TKINTER_OK = True
except ImportError:
    TKINTER_OK = False
    print("[ПРЕДУПРЕЖДЕНИЕ] tkinter недоступен — уведомления на экране отключены.")

# --- Импорт конфигурации ---
try:
    from config import API_TOKEN, ADMIN_ID, MATERIALS_FOLDER, PROJECT_FOLDER, AGENT_POLL_INTERVAL
except ImportError:
    print("[ОШИБКА] Файл config.py не найден рядом со скриптом.")
    input("Нажмите Enter для выхода...")
    sys.exit(1)

# =============================================================================
#  Настройка логирования
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("agent.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("Агент")

# =============================================================================
#  Константы и пути
# =============================================================================

HOSTNAME    = socket.gethostname()
LOCAL_IP    = socket.gethostbyname(HOSTNAME)
OS_INFO     = f"{platform.system()} {platform.release()} ({platform.version()[:40]})"

# Рабочий стол (Windows / Linux / macOS)
if platform.system() == "Windows":
    DESKTOP_PATH = Path(os.environ.get("USERPROFILE", Path.home())) / "Desktop"
    DOCUMENTS_PATH = Path(os.environ.get("USERPROFILE", Path.home())) / "Documents"
else:
    DESKTOP_PATH   = Path.home() / "Рабочий стол"
    DOCUMENTS_PATH = Path.home() / "Документы"
    if not DESKTOP_PATH.exists():
        DESKTOP_PATH = Path.home() / "Desktop"
    if not DOCUMENTS_PATH.exists():
        DOCUMENTS_PATH = Path.home() / "Documents"

MATERIALS_PATH = DESKTOP_PATH / MATERIALS_FOLDER
PROJECT_PATH   = DOCUMENTS_PATH / PROJECT_FOLDER

# =============================================================================
#  Инициализация бота
# =============================================================================

bot = telebot.TeleBot(API_TOKEN)

# =============================================================================
#  Вспомогательные утилиты
# =============================================================================

def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _ensure_dir(path: Path) -> bool:
    """Создать папку, если не существует. Вернуть True при успехе."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        return True
    except PermissionError:
        log.error("[ОШИБКА] Нет прав для создания папки: %s", path)
        return False


def _send_text(text: str):
    """Отправить текстовое сообщение преподавателю."""
    try:
        bot.send_message(ADMIN_ID, text)
    except Exception as exc:
        log.error("[ОШИБКА] Не удалось отправить сообщение: %s", exc)


def _send_error(error_text: str):
    """Отправить отчёт об ошибке преподавателю."""
    _send_text(f"ERROR|{HOSTNAME}|{error_text}")


# =============================================================================
#  Уведомление на экране студента (tkinter)
# =============================================================================

def _show_notification(message: str, duration_ms: int = 3000):
    """
    Показать всплывающее уведомление студенту на N миллисекунд.
    Запускается в отдельном потоке, чтобы не блокировать агент.
    """
    if not TKINTER_OK:
        return

    def _run():
        try:
            root = tk.Tk()
            root.title("Уведомление")
            root.attributes("-topmost", True)     # поверх всех окон
            root.resizable(False, False)
            root.overrideredirect(False)           # оставляем заголовок (не hidden)

            # Цветовое оформление
            BG   = "#1a1a2e"
            FG   = "#e0e0e0"
            ACCENT = "#4a90d9"

            root.configure(bg=BG)

            # Иконка + текст
            frame = tk.Frame(root, bg=BG, padx=20, pady=15)
            frame.pack(fill="both", expand=True)

            tk.Label(
                frame,
                text="📡  Система управления классом",
                bg=BG, fg=ACCENT,
                font=("Segoe UI", 10, "bold"),
            ).pack(anchor="w")

            tk.Label(
                frame,
                text=message,
                bg=BG, fg=FG,
                font=("Segoe UI", 11),
                wraplength=360,
                justify="left",
            ).pack(anchor="w", pady=(8, 0))

            # Разместить в правом нижнем углу экрана
            screen_w = root.winfo_screenwidth()
            screen_h = root.winfo_screenheight()
            root.update_idletasks()
            w = root.winfo_width()
            h = root.winfo_height()
            x = screen_w - w - 20
            y = screen_h - h - 60
            root.geometry(f"+{x}+{y}")

            root.after(duration_ms, root.destroy)
            root.mainloop()
        except Exception as exc:
            log.debug("[УВЕДОМЛЕНИЕ] Ошибка tkinter: %s", exc)

    threading.Thread(target=_run, daemon=True, name="Уведомление").start()


# =============================================================================
#  Основные команды агента
# =============================================================================

def cmd_screenshot():
    """
    Снять скриншот экрана и отправить преподавателю.
    Показать уведомление студенту.
    """
    log.info("[%s] [КОМАНДА] Скриншот экрана", _ts())
    _show_notification("📸  Трансляция экрана активна", duration_ms=3500)

    screenshot_path = Path("screenshot_tmp.png")
    try:
        img = ImageGrab.grab()
        img.save(str(screenshot_path), format="PNG", optimize=True)
        log.info("[%s] [ИНФО] Скриншот сохранён: %s", _ts(), screenshot_path)
    except Exception as exc:
        log.error("[%s] [ОШИБКА] Не удалось снять скриншот: %s", _ts(), exc)
        _send_error(f"Не удалось снять скриншот: {exc}")
        return

    try:
        with open(screenshot_path, "rb") as f:
            bot.send_photo(
                ADMIN_ID,
                f,
                caption=f"SCREENSHOT|{HOSTNAME}",
            )
        log.info("[%s] [ИНФО] Скриншот отправлен преподавателю.", _ts())
    except Exception as exc:
        log.error("[%s] [ОШИБКА] Не удалось отправить скриншот: %s", _ts(), exc)
        _send_error(f"Не удалось отправить скриншот: {exc}")
    finally:
        try:
            screenshot_path.unlink(missing_ok=True)
        except Exception:
            pass


def cmd_sysinfo():
    """Собрать и отправить информацию о системе."""
    log.info("[%s] [КОМАНДА] Информация о системе", _ts())
    try:
        cpu_pct   = psutil.cpu_percent(interval=1)
        mem       = psutil.virtual_memory()
        disk      = psutil.disk_usage(str(Path.home().anchor))

        mem_total = mem.total  / (1024 ** 3)
        mem_used  = mem.used   / (1024 ** 3)
        mem_pct   = mem.percent

        disk_total = disk.total / (1024 ** 3)
        disk_used  = disk.used  / (1024 ** 3)
        disk_pct   = disk.percent

        # Процессы с наибольшей нагрузкой на CPU
        top_procs = []
        for proc in sorted(
            psutil.process_iter(["pid", "name", "cpu_percent"]),
            key=lambda p: p.info["cpu_percent"] or 0,
            reverse=True,
        )[:5]:
            top_procs.append(
                f"  • {proc.info['name'][:20]:<20} CPU: {proc.info['cpu_percent']:.1f}%"
            )
        top_text = "\n".join(top_procs) if top_procs else "  (нет данных)"

        info = (
            f"💻 ОС:      {OS_INFO}\n"
            f"🔵 CPU:     {cpu_pct:.1f}%\n"
            f"🟡 ОЗУ:     {mem_used:.1f} / {mem_total:.1f} ГБ  ({mem_pct:.1f}%)\n"
            f"🟠 Диск:    {disk_used:.1f} / {disk_total:.1f} ГБ  ({disk_pct:.1f}%)\n"
            f"🌐 IP:      {LOCAL_IP}\n\n"
            f"📋 Топ процессы:\n{top_text}"
        )
        _send_text(f"SYSINFO|{HOSTNAME}|{info}")
        log.info("[%s] [ИНФО] Информация о системе отправлена.", _ts())
    except Exception as exc:
        log.error("[%s] [ОШИБКА] Не удалось собрать инфо о системе: %s", _ts(), exc)
        _send_error(f"Не удалось собрать информацию о системе: {exc}")


def cmd_collect_works():
    """
    Заархивировать папку Documents/Project и отправить преподавателю.
    """
    log.info("[%s] [КОМАНДА] Сбор работ", _ts())

    if not PROJECT_PATH.exists():
        msg = f"Папка проекта не найдена: {PROJECT_PATH}"
        log.warning("[%s] [ПРЕДУПРЕЖДЕНИЕ] %s", _ts(), msg)
        _send_error(msg)
        return

    archive_name = f"works_{HOSTNAME}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    archive_path = Path(archive_name)

    try:
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in PROJECT_PATH.rglob("*"):
                if file_path.is_file():
                    zf.write(file_path, file_path.relative_to(PROJECT_PATH))
        log.info("[%s] [ИНФО] Архив создан: %s", _ts(), archive_path)
    except Exception as exc:
        log.error("[%s] [ОШИБКА] Не удалось создать архив: %s", _ts(), exc)
        _send_error(f"Не удалось создать архив: {exc}")
        return

    try:
        with open(archive_path, "rb") as f:
            bot.send_document(
                ADMIN_ID,
                f,
                caption=f"WORKS|{HOSTNAME}",
                visible_file_name=archive_name,
            )
        log.info("[%s] [ИНФО] Архив работ отправлен преподавателю.", _ts())
    except Exception as exc:
        log.error("[%s] [ОШИБКА] Не удалось отправить архив: %s", _ts(), exc)
        _send_error(f"Не удалось отправить архив: {exc}")
    finally:
        try:
            archive_path.unlink(missing_ok=True)
        except Exception:
            pass


def cmd_receive_file(file_id: str, file_name: str):
    """
    Скачать файл с серверов Telegram, сохранить на Рабочем столе
    в папку Учебные_материалы и открыть его.
    """
    log.info("[%s] [КОМАНДА] Получение файла: %s", _ts(), file_name)
    _show_notification(f"📂  Получен новый материал:\n{file_name}", duration_ms=4000)

    if not _ensure_dir(MATERIALS_PATH):
        _send_error(f"Не удалось создать папку: {MATERIALS_PATH}")
        return

    save_path = MATERIALS_PATH / file_name

    try:
        file_info = bot.get_file(file_id)
        file_url  = f"https://api.telegram.org/file/bot{API_TOKEN}/{file_info.file_path}"

        response = requests.get(file_url, timeout=60, stream=True)
        response.raise_for_status()

        with open(save_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        log.info("[%s] [ИНФО] Файл сохранён: %s", _ts(), save_path)
    except Exception as exc:
        log.error("[%s] [ОШИБКА] Не удалось скачать файл: %s", _ts(), exc)
        _send_error(f"Не удалось скачать файл '{file_name}': {exc}")
        return

    # Открыть файл стандартным приложением
    try:
        if platform.system() == "Windows":
            subprocess.run(["start", "", str(save_path)], shell=True, check=False)
        elif platform.system() == "Darwin":
            subprocess.run(["open", str(save_path)], check=False)
        else:
            subprocess.run(["xdg-open", str(save_path)], check=False)
        log.info("[%s] [ИНФО] Файл открыт.", _ts())
    except Exception as exc:
        log.warning("[%s] [ПРЕДУПРЕЖДЕНИЕ] Не удалось открыть файл автоматически: %s", _ts(), exc)

    _send_text(f"FILE_RECEIVED|{HOSTNAME}|Файл '{file_name}' сохранён в {MATERIALS_PATH}")


def cmd_kill_process(process_name: str):
    """
    Завершить процесс по имени исполняемого файла.
    Использует только subprocess.run (не os.system).
    """
    log.info("[%s] [КОМАНДА] Завершение процесса: %s", _ts(), process_name)

    if not process_name.strip():
        _send_text(f"KILL_RESULT|{HOSTNAME}|Имя процесса не указано.")
        return

    # Нормализация имени
    proc = process_name.strip()
    if not proc.lower().endswith(".exe") and platform.system() == "Windows":
        proc = proc + ".exe"

    try:
        if platform.system() == "Windows":
            result = subprocess.run(
                ["taskkill", "/F", "/IM", proc],
                capture_output=True,
                text=True,
                encoding="cp866",    # Windows консольная кодировка
                errors="replace",
            )
        else:
            result = subprocess.run(
                ["pkill", "-f", proc],
                capture_output=True,
                text=True,
            )

        if result.returncode == 0:
            msg = f"✅ Процесс '{proc}' успешно завершён."
            log.info("[%s] [ИНФО] %s", _ts(), msg)
        else:
            stderr_clean = (result.stderr or "").strip()
            msg = f"⚠️ Процесс '{proc}' не найден или уже завершён. ({stderr_clean})"
            log.warning("[%s] [ПРЕДУПРЕЖДЕНИЕ] %s", _ts(), msg)

    except FileNotFoundError:
        msg = f"❌ Команда завершения процессов недоступна в данной системе."
        log.error("[%s] [ОШИБКА] %s", _ts(), msg)
    except Exception as exc:
        msg = f"❌ Ошибка при завершении процесса: {exc}"
        log.error("[%s] [ОШИБКА] %s", _ts(), msg)

    _send_text(f"KILL_RESULT|{HOSTNAME}|{msg}")


# =============================================================================
#  Обработчики входящих сообщений (команды от бота)
# =============================================================================

@bot.message_handler(content_types=["text"])
def handle_text_command(message: telebot.types.Message):
    """Принять текстовую команду от бота (от ADMIN_ID)."""
    if message.chat.id != ADMIN_ID:
        return  # игнорировать посторонние сообщения

    text = message.text or ""
    log.debug("[%s] [ВХОДЯЩЕЕ] %s", _ts(), text[:60])

    if text == "CMD_SCREENSHOT":
        threading.Thread(target=cmd_screenshot, daemon=True).start()
        return

    if text == "CMD_SYSINFO":
        threading.Thread(target=cmd_sysinfo, daemon=True).start()
        return

    if text == "CMD_COLLECT":
        threading.Thread(target=cmd_collect_works, daemon=True).start()
        return

    if text.startswith("CMD_KILL|"):
        proc_name = text.split("|", 1)[1] if "|" in text else ""
        threading.Thread(
            target=cmd_kill_process,
            args=(proc_name,),
            daemon=True,
        ).start()
        return


@bot.message_handler(content_types=["document"])
def handle_document(message: telebot.types.Message):
    """Принять файл от бота для сохранения на Рабочем столе."""
    if message.chat.id != ADMIN_ID:
        return

    caption = message.caption or ""
    if not caption.startswith("RECEIVE_FILE|"):
        return

    file_name = caption.split("|", 1)[1] if "|" in caption else "материал"
    file_id   = message.document.file_id

    threading.Thread(
        target=cmd_receive_file,
        args=(file_id, file_name),
        daemon=True,
    ).start()


# =============================================================================
#  Регистрация и поддержание соединения (heartbeat)
# =============================================================================

def _register():
    """Зарегистрировать агент у бота преподавателя."""
    log.info("[%s] [ИНФО] Регистрация рабочей станции '%s'...", _ts(), HOSTNAME)
    try:
        bot.send_message(ADMIN_ID, f"REGISTER|{HOSTNAME}|{LOCAL_IP}")
        log.info("[%s] [ИНФО] Регистрация выполнена успешно.", _ts())
    except Exception as exc:
        log.error("[%s] [ОШИБКА] Не удалось зарегистрироваться: %s", _ts(), exc)
        raise


def _heartbeat_loop():
    """
    Периодически отправлять сигнал жизни боту,
    чтобы преподаватель видел статус станции.
    """
    while True:
        time.sleep(AGENT_POLL_INTERVAL)
        try:
            bot.send_message(ADMIN_ID, f"HEARTBEAT|{HOSTNAME}")
        except Exception as exc:
            log.warning("[%s] [ПРЕДУПРЕЖДЕНИЕ] Heartbeat не отправлен: %s", _ts(), exc)


# =============================================================================
#  Точка входа
# =============================================================================

def main():
    print("=" * 60)
    print("  Агент управления компьютерным классом")
    print(f"  Рабочая станция: {HOSTNAME}")
    print(f"  IP-адрес:        {LOCAL_IP}")
    print(f"  ОС:              {OS_INFO}")
    print("=" * 60)
    print()

    log.info("[ЗАПУСК] Агент запущен на станции '%s' (IP: %s)", HOSTNAME, LOCAL_IP)
    log.info("[ИНФО]   Папка материалов: %s", MATERIALS_PATH)
    log.info("[ИНФО]   Папка проектов:   %s", PROJECT_PATH)

    # Создать рабочие папки при необходимости
    _ensure_dir(MATERIALS_PATH)
    _ensure_dir(PROJECT_PATH)

    # Регистрация у преподавателя
    try:
        _register()
    except Exception:
        log.error("[ОШИБКА] Не удалось подключиться. Проверьте API_TOKEN и ADMIN_ID в config.py")
        input("Нажмите Enter для выхода...")
        sys.exit(1)

    log.info("[ИНФО] Соединение установлено. Ожидание команд от преподавателя...")

    # Запустить heartbeat в фоне
    hb_thread = threading.Thread(
        target=_heartbeat_loop,
        daemon=True,
        name="Heartbeat",
    )
    hb_thread.start()

    # Запустить polling (приём команд)
    try:
        log.info("[ИНФО] Режим прослушивания команд активен.")
        bot.infinity_polling(timeout=30, long_polling_timeout=20)
    except KeyboardInterrupt:
        log.info("[ИНФО] Агент остановлен пользователем.")
    except Exception as exc:
        log.error("[ОШИБКА] Критическая ошибка polling: %s", exc)
        input("Нажмите Enter для выхода...")
        sys.exit(1)


if __name__ == "__main__":
    main()
