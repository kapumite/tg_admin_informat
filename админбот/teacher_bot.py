# =============================================================================
#  teacher_bot.py — Бот управления компьютерным классом (Преподаватель)
#
#  Запуск:  python teacher_bot.py
#
#  Зависимости: pyTelegramBotAPI, requests
# =============================================================================

import os
import time
import logging
import threading
from datetime import datetime
from typing import Optional

import telebot
from telebot import types

# --- Импорт конфигурации ---
try:
    from config import API_TOKEN, ADMIN_ID
except ImportError:
    print("[ОШИБКА] Файл config.py не найден. Скопируйте config.py в эту же папку.")
    raise SystemExit(1)

# =============================================================================
#  Настройка логирования
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("teacher_bot.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("УчительБот")

# =============================================================================
#  Инициализация бота
# =============================================================================

bot = telebot.TeleBot(API_TOKEN, parse_mode="HTML")

# =============================================================================
#  Реестр подключённых агентов (студенческих ПК)
#  Формат: { hostname: { "chat_id": int, "last_seen": datetime, "ip": str } }
# =============================================================================

agents: dict[str, dict] = {}
agents_lock = threading.Lock()

# =============================================================================
#  Состояние диалога — ожидание ввода от преподавателя
#  Ключи: "awaiting_process", "awaiting_file_target"
# =============================================================================

admin_state: dict[str, object] = {}

# =============================================================================
#  Вспомогательные функции
# =============================================================================

def _ts() -> str:
    """Текущее время в формате ЧЧ:ММ:СС."""
    return datetime.now().strftime("%H:%M:%S")


def _is_admin(message: types.Message) -> bool:
    """Проверка: сообщение от преподавателя."""
    return message.from_user.id == ADMIN_ID


def _admin_only(func):
    """Декоратор: разрешить выполнение только преподавателю."""
    def wrapper(message, *args, **kwargs):
        if not _is_admin(message):
            bot.reply_to(message, "⛔ Доступ запрещён. Только преподаватель может использовать этот бот.")
            log.warning("[БЕЗОПАСНОСТЬ] Попытка доступа от user_id=%s", message.from_user.id)
            return
        return func(message, *args, **kwargs)
    return wrapper


def _agents_list_text() -> str:
    """Сформировать текстовый список активных агентов."""
    with agents_lock:
        if not agents:
            return "ℹ️ Нет подключённых рабочих станций."
        lines = ["<b>🖥 Подключённые рабочие станции:</b>\n"]
        for hostname, info in agents.items():
            last_seen = info.get("last_seen")
            if last_seen:
                delta = (datetime.now() - last_seen).seconds
                status = "🟢 онлайн" if delta < 30 else "🟡 нет ответа"
            else:
                status = "🔴 неизвестно"
            lines.append(f"  • <code>{hostname}</code>  —  {status}")
        return "\n".join(lines)


def _build_agents_keyboard() -> types.InlineKeyboardMarkup:
    """
    Клавиатура с кнопками для каждого подключённого агента.
    Используется при выборе цели команды.
    """
    kb = types.InlineKeyboardMarkup(row_width=2)
    with agents_lock:
        for hostname in agents:
            kb.add(types.InlineKeyboardButton(
                text=f"🖥 {hostname}",
                callback_data=f"select_agent|{hostname}",
            ))
    kb.add(types.InlineKeyboardButton("📢 Всем сразу", callback_data="select_agent|__ALL__"))
    kb.add(types.InlineKeyboardButton("◀️ Назад", callback_data="menu_back"))
    return kb


# =============================================================================
#  Главное меню
# =============================================================================

MAIN_MENU_TEXT = (
    "👨‍🏫 <b>Система управления компьютерным классом</b>\n\n"
    "Выберите действие из меню ниже:"
)


def main_menu_keyboard() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("📸 Скриншот экрана",     callback_data="cmd_screenshot"),
        types.InlineKeyboardButton("🖥️ Инфо о системе",      callback_data="cmd_sysinfo"),
    )
    kb.add(
        types.InlineKeyboardButton("📂 Раздать файл",        callback_data="cmd_sendfile"),
        types.InlineKeyboardButton("📥 Собрать работы",      callback_data="cmd_collect"),
    )
    kb.add(
        types.InlineKeyboardButton("❌ Завершить процесс",   callback_data="cmd_kill"),
        types.InlineKeyboardButton("📋 Список станций",      callback_data="cmd_list"),
    )
    kb.add(
        types.InlineKeyboardButton("🔄 Обновить статус",     callback_data="cmd_refresh"),
    )
    return kb


# =============================================================================
#  Обработчики сообщений от бота
# =============================================================================

@bot.message_handler(commands=["start", "menu"])
@_admin_only
def handle_start(message: types.Message):
    """Главное меню по команде /start или /menu."""
    log.info("[КОМАНДА] /start от преподавателя (id=%s)", message.from_user.id)
    bot.send_message(
        message.chat.id,
        MAIN_MENU_TEXT,
        reply_markup=main_menu_keyboard(),
    )


@bot.message_handler(commands=["help"])
@_admin_only
def handle_help(message: types.Message):
    """Справка по командам."""
    text = (
        "📖 <b>Доступные команды:</b>\n\n"
        "/start — Главное меню\n"
        "/list  — Список подключённых ПК\n"
        "/help  — Эта справка\n\n"
        "<i>Используйте кнопки меню для управления рабочими станциями.</i>"
    )
    bot.send_message(message.chat.id, text)


@bot.message_handler(commands=["list"])
@_admin_only
def handle_list(message: types.Message):
    """Список подключённых агентов."""
    bot.send_message(message.chat.id, _agents_list_text())


# =============================================================================
#  Входящие данные от агентов (студенческих ПК)
# =============================================================================

@bot.message_handler(content_types=["text"])
def handle_text(message: types.Message):
    """
    Обработка текстовых сообщений.
    Агенты присылают регистрационное сообщение в формате:
        REGISTER|<hostname>|<ip_address>
    """
    text = message.text or ""

    # --- Регистрация агента ---
    if text.startswith("REGISTER|"):
        parts = text.split("|")
        if len(parts) >= 3:
            hostname = parts[1].strip()
            ip_addr  = parts[2].strip()
            with agents_lock:
                is_new = hostname not in agents
                agents[hostname] = {
                    "chat_id":   message.chat.id,
                    "last_seen": datetime.now(),
                    "ip":        ip_addr,
                }
            if is_new:
                log.info("[АГЕНТ] Новая рабочая станция: %s (IP: %s)", hostname, ip_addr)
                bot.send_message(
                    ADMIN_ID,
                    f"✅ <b>Рабочая станция подключилась</b>\n"
                    f"  Имя: <code>{hostname}</code>\n"
                    f"  IP:  <code>{ip_addr}</code>\n"
                    f"  Время: {_ts()}",
                )
            else:
                # Обновление heartbeat
                log.debug("[АГЕНТ] Heartbeat от %s", hostname)
        return

    # --- Heartbeat (пульс соединения) ---
    if text.startswith("HEARTBEAT|"):
        parts = text.split("|")
        if len(parts) >= 2:
            hostname = parts[1].strip()
            with agents_lock:
                if hostname in agents:
                    agents[hostname]["last_seen"] = datetime.now()
        return

    # --- Сообщение об ошибке от агента ---
    if text.startswith("ERROR|"):
        parts = text.split("|", 2)
        hostname = parts[1] if len(parts) > 1 else "неизвестно"
        error_msg = parts[2] if len(parts) > 2 else "неизвестная ошибка"
        log.warning("[АГЕНТ] Ошибка от %s: %s", hostname, error_msg)
        bot.send_message(
            ADMIN_ID,
            f"⚠️ <b>Ошибка на рабочей станции</b> <code>{hostname}</code>\n"
            f"<i>{error_msg}</i>",
        )
        return

    # --- Информация о системе ---
    if text.startswith("SYSINFO|"):
        parts = text.split("|", 2)
        hostname = parts[1] if len(parts) > 1 else "неизвестно"
        info_text = parts[2] if len(parts) > 2 else ""
        bot.send_message(
            ADMIN_ID,
            f"🖥️ <b>Информация о системе: {hostname}</b>\n\n{info_text}",
        )
        return

    # --- Ответ о завершении процесса ---
    if text.startswith("KILL_RESULT|"):
        parts = text.split("|", 2)
        hostname = parts[1] if len(parts) > 1 else "неизвестно"
        result   = parts[2] if len(parts) > 2 else ""
        bot.send_message(
            ADMIN_ID,
            f"❌ <b>Завершение процесса: {hostname}</b>\n{result}",
        )
        return

    # --- Ответ о получении файла ---
    if text.startswith("FILE_RECEIVED|"):
        parts = text.split("|", 2)
        hostname = parts[1] if len(parts) > 1 else "неизвестно"
        msg      = parts[2] if len(parts) > 2 else "файл получен"
        bot.send_message(
            ADMIN_ID,
            f"📂 <b>{hostname}</b>: {msg}",
        )
        return

    # --- Обычное сообщение (не от агента) ---
    if _is_admin(message):
        # Преподаватель ввёл название процесса
        if admin_state.get("awaiting_process"):
            process_name = text.strip()
            target = admin_state.pop("awaiting_process")
            admin_state.clear()
            _send_kill_command(message.chat.id, target, process_name)
            return
        # Другие текстовые сообщения — показать меню
        bot.send_message(message.chat.id, MAIN_MENU_TEXT, reply_markup=main_menu_keyboard())


@bot.message_handler(content_types=["photo"])
def handle_photo(message: types.Message):
    """Скриншот от агента."""
    caption = message.caption or ""
    hostname = "неизвестно"
    if caption.startswith("SCREENSHOT|"):
        hostname = caption.split("|", 1)[1].strip()
        log.info("[АГЕНТ] Скриншот получен от %s", hostname)

    # Пересылаем преподавателю с подписью
    bot.send_photo(
        ADMIN_ID,
        message.photo[-1].file_id,
        caption=(
            f"📸 <b>Скриншот рабочей станции</b>\n"
            f"  Компьютер: <code>{hostname}</code>\n"
            f"  Время: {_ts()}"
        ),
    )


@bot.message_handler(content_types=["document"])
def handle_document(message: types.Message):
    """
    Документ от агента (архив собранных работ)
    ИЛИ файл от преподавателя для рассылки.
    """
    caption = message.caption or ""

    # --- Архив от агента ---
    if caption.startswith("WORKS|"):
        parts    = caption.split("|", 1)
        hostname = parts[1].strip() if len(parts) > 1 else "неизвестно"
        log.info("[АГЕНТ] Архив работ получен от %s", hostname)
        bot.send_document(
            ADMIN_ID,
            message.document.file_id,
            caption=(
                f"📥 <b>Работы получены</b>\n"
                f"  Компьютер: <code>{hostname}</code>\n"
                f"  Файл: <code>{message.document.file_name}</code>\n"
                f"  Время: {_ts()}"
            ),
        )
        return

    # --- Файл от преподавателя для рассылки ---
    if _is_admin(message) and admin_state.get("awaiting_file"):
        target = admin_state.pop("awaiting_file")
        file_id   = message.document.file_id
        file_name = message.document.file_name or "материал"
        log.info("[БОТ] Рассылка файла '%s' → %s", file_name, target)

        targets = _resolve_targets(target)
        sent_count = 0
        for hostname in targets:
            chat_id = agents.get(hostname, {}).get("chat_id")
            if chat_id:
                try:
                    bot.send_document(
                        chat_id,
                        file_id,
                        caption=f"RECEIVE_FILE|{file_name}",
                    )
                    sent_count += 1
                except Exception as exc:
                    log.error("[БОТ] Ошибка отправки файла на %s: %s", hostname, exc)

        bot.send_message(
            ADMIN_ID,
            f"📂 Файл <b>{file_name}</b> разослан на {sent_count} станц.",
        )
        return

    if _is_admin(message):
        bot.send_message(
            ADMIN_ID,
            "❓ Для рассылки файла нажмите кнопку <b>«📂 Раздать файл»</b> в меню.",
        )


# =============================================================================
#  Callback-обработчики кнопок главного меню
# =============================================================================

@bot.callback_query_handler(func=lambda c: True)
def handle_callback(call: types.CallbackQuery):
    """Единый обработчик всех inline-кнопок."""
    if call.from_user.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "⛔ Доступ запрещён.")
        return

    data = call.data

    # ── Главное меню ────────────────────────────────────────────────────────
    if data == "menu_back":
        bot.edit_message_text(
            MAIN_MENU_TEXT,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=main_menu_keyboard(),
        )
        bot.answer_callback_query(call.id)
        return

    # ── Список станций ───────────────────────────────────────────────────────
    if data == "cmd_list":
        bot.edit_message_text(
            _agents_list_text(),
            call.message.chat.id,
            call.message.message_id,
            reply_markup=_back_keyboard(),
        )
        bot.answer_callback_query(call.id)
        return

    # ── Обновить статус ──────────────────────────────────────────────────────
    if data == "cmd_refresh":
        bot.edit_message_text(
            MAIN_MENU_TEXT + f"\n\n<i>Обновлено: {_ts()}</i>",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=main_menu_keyboard(),
        )
        bot.answer_callback_query(call.id, "✅ Статус обновлён.")
        return

    # ── Скриншот — выбор цели ────────────────────────────────────────────────
    if data == "cmd_screenshot":
        _show_agent_selector(call, "screenshot")
        return

    # ── Инфо о системе — выбор цели ─────────────────────────────────────────
    if data == "cmd_sysinfo":
        _show_agent_selector(call, "sysinfo")
        return

    # ── Собрать работы — выбор цели ──────────────────────────────────────────
    if data == "cmd_collect":
        _show_agent_selector(call, "collect")
        return

    # ── Раздать файл — выбор цели ────────────────────────────────────────────
    if data == "cmd_sendfile":
        _show_agent_selector(call, "sendfile")
        return

    # ── Завершить процесс — выбор цели ───────────────────────────────────────
    if data == "cmd_kill":
        _show_agent_selector(call, "kill")
        return

    # ── Выбор конкретного агента ─────────────────────────────────────────────
    if data.startswith("select_agent|"):
        parts   = data.split("|", 2)
        target  = parts[1]          # hostname или '__ALL__'
        command = parts[2] if len(parts) > 2 else ""
        _execute_command_on_target(call, target, command)
        return

    bot.answer_callback_query(call.id, "⚠️ Неизвестная команда.")


# =============================================================================
#  Вспомогательные функции для callback-логики
# =============================================================================

def _back_keyboard() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("◀️ Главное меню", callback_data="menu_back"))
    return kb


def _show_agent_selector(call: types.CallbackQuery, command: str):
    """Показать список агентов для выбора цели команды."""
    with agents_lock:
        if not agents:
            bot.answer_callback_query(call.id, "⚠️ Нет подключённых станций.")
            bot.edit_message_text(
                "❌ Нет подключённых рабочих станций.\n"
                "Запустите агент на студенческих ПК.",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=_back_keyboard(),
            )
            return

    # Строим клавиатуру с именами агентов
    kb = types.InlineKeyboardMarkup(row_width=2)
    with agents_lock:
        for hostname in agents:
            kb.add(types.InlineKeyboardButton(
                text=f"🖥 {hostname}",
                callback_data=f"select_agent|{hostname}|{command}",
            ))
    kb.add(types.InlineKeyboardButton(
        "📢 Всем сразу",
        callback_data=f"select_agent|__ALL__|{command}",
    ))
    kb.add(types.InlineKeyboardButton("◀️ Назад", callback_data="menu_back"))

    cmd_labels = {
        "screenshot": "📸 Скриншот экрана",
        "sysinfo":    "🖥️ Информация о системе",
        "collect":    "📥 Собрать работы",
        "sendfile":   "📂 Раздать файл",
        "kill":       "❌ Завершить процесс",
    }
    label = cmd_labels.get(command, command)
    bot.edit_message_text(
        f"<b>{label}</b>\n\nВыберите рабочую станцию:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=kb,
    )
    bot.answer_callback_query(call.id)


def _resolve_targets(target: str) -> list[str]:
    """Вернуть список hostname-ов для команды."""
    with agents_lock:
        if target == "__ALL__":
            return list(agents.keys())
        return [target] if target in agents else []


def _execute_command_on_target(call: types.CallbackQuery, target: str, command: str):
    """Отправить команду на выбранную(ые) станцию(и)."""
    bot.answer_callback_query(call.id, "⏳ Выполняется...")

    targets = _resolve_targets(target)
    if not targets:
        bot.edit_message_text(
            "⚠️ Рабочая станция не найдена или не подключена.",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=_back_keyboard(),
        )
        return

    target_label = "всем" if target == "__ALL__" else f"<code>{target}</code>"

    # --- Скриншот ---
    if command == "screenshot":
        _broadcast_command(targets, "CMD_SCREENSHOT")
        bot.edit_message_text(
            f"📸 Запрос скриншота отправлен {target_label}.\n"
            "Скриншот появится в этом чате через несколько секунд.",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=_back_keyboard(),
        )
        log.info("[БОТ] Команда SCREENSHOT → %s", target)
        return

    # --- Инфо о системе ---
    if command == "sysinfo":
        _broadcast_command(targets, "CMD_SYSINFO")
        bot.edit_message_text(
            f"🖥️ Запрос информации о системе отправлен {target_label}.",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=_back_keyboard(),
        )
        log.info("[БОТ] Команда SYSINFO → %s", target)
        return

    # --- Собрать работы ---
    if command == "collect":
        _broadcast_command(targets, "CMD_COLLECT")
        bot.edit_message_text(
            f"📥 Команда сбора работ отправлена {target_label}.\n"
            "Архивы появятся в этом чате через несколько секунд.",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=_back_keyboard(),
        )
        log.info("[БОТ] Команда COLLECT → %s", target)
        return

    # --- Раздать файл ---
    if command == "sendfile":
        admin_state["awaiting_file"] = target
        bot.edit_message_text(
            f"📂 Отправьте файл для рассылки {target_label}.\n"
            "<i>Просто прикрепите файл к следующему сообщению.</i>",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=_back_keyboard(),
        )
        log.info("[БОТ] Ожидание файла для рассылки → %s", target)
        return

    # --- Завершить процесс ---
    if command == "kill":
        admin_state["awaiting_process"] = target
        bot.edit_message_text(
            f"❌ Введите имя процесса для завершения на {target_label}.\n"
            "Пример: <code>chrome.exe</code>, <code>vlc.exe</code>, <code>notepad.exe</code>",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=_back_keyboard(),
        )
        log.info("[БОТ] Ожидание имени процесса для завершения → %s", target)
        return

    bot.edit_message_text(
        "⚠️ Неизвестная команда.",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=_back_keyboard(),
    )


def _send_kill_command(chat_id: int, target: str, process_name: str):
    """Отправить команду завершения процесса агентам."""
    targets = _resolve_targets(target)
    if not targets:
        bot.send_message(chat_id, "⚠️ Рабочая станция не найдена.")
        return

    target_label = "всем" if target == "__ALL__" else f"<code>{target}</code>"
    _broadcast_command(targets, f"CMD_KILL|{process_name.strip()}")
    bot.send_message(
        chat_id,
        f"❌ Команда завершения процесса <code>{process_name}</code> "
        f"отправлена {target_label}.",
        reply_markup=main_menu_keyboard(),
    )
    log.info("[БОТ] Команда KILL '%s' → %s", process_name, target)


def _broadcast_command(targets: list[str], command: str):
    """Отправить текстовую команду всем указанным агентам."""
    with agents_lock:
        for hostname in targets:
            info = agents.get(hostname, {})
            chat_id = info.get("chat_id")
            if not chat_id:
                continue
            try:
                bot.send_message(chat_id, command)
                log.debug("[БОТ] Команда '%s' → %s (chat_id=%s)",
                          command, hostname, chat_id)
            except Exception as exc:
                log.error("[БОТ] Ошибка отправки команды на %s: %s", hostname, exc)


# =============================================================================
#  Мониторинг соединений (фоновый поток)
# =============================================================================

def _monitor_connections():
    """
    Периодически проверяет, какие агенты перестали отвечать,
    и уведомляет преподавателя об отключениях.
    """
    notified_offline: set[str] = set()
    TIMEOUT_SEC = 60  # считать агент отключённым через N секунд

    while True:
        time.sleep(15)
        now = datetime.now()
        with agents_lock:
            for hostname, info in list(agents.items()):
                last = info.get("last_seen")
                if last is None:
                    continue
                delta = (now - last).seconds
                if delta > TIMEOUT_SEC and hostname not in notified_offline:
                    notified_offline.add(hostname)
                    log.warning("[МОНИТОР] Станция '%s' не отвечает (%ds)", hostname, delta)
                    try:
                        bot.send_message(
                            ADMIN_ID,
                            f"⚠️ <b>Рабочая станция не отвечает</b>\n"
                            f"  Компьютер: <code>{hostname}</code>\n"
                            f"  Последний сигнал: {delta} сек. назад",
                        )
                    except Exception:
                        pass
                elif delta <= TIMEOUT_SEC and hostname in notified_offline:
                    notified_offline.discard(hostname)


# =============================================================================
#  Точка входа
# =============================================================================

def main():
    log.info("=" * 60)
    log.info("[ЗАПУСК] Бот управления классом запущен.")
    log.info("[ИНФО]   ADMIN_ID = %s", ADMIN_ID)
    log.info("=" * 60)

    # Уведомить преподавателя о запуске
    try:
        bot.send_message(
            ADMIN_ID,
            f"🟢 <b>Система управления классом запущена</b>\n"
            f"Время: {_ts()}\n\n"
            "Используйте /start для открытия меню.",
        )
    except Exception as exc:
        log.error("[ОШИБКА] Не удалось уведомить преподавателя: %s", exc)
        log.error("Проверьте API_TOKEN и ADMIN_ID в config.py")
        raise SystemExit(1)

    # Запустить поток мониторинга
    monitor_thread = threading.Thread(
        target=_monitor_connections,
        daemon=True,
        name="МониторСоединений",
    )
    monitor_thread.start()

    log.info("[ИНФО] Бот готов. Ожидание команд от преподавателя...")

    # Запустить polling
    bot.infinity_polling(timeout=30, long_polling_timeout=20)


if __name__ == "__main__":
    main()
