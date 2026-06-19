"""
Офлайн-тесты MVP1 (без сети и без токена; LLM = mock по умолчанию).

Запуск:
    python mvp1_gpt_bot/test_bot.py
"""
import sys
import os

sys.path.insert(0, "/home/oleg/freelance-mvp")

# Брони пишем во временный CSV, чтобы не трогать рабочий bookings.csv.
import tempfile

_TMP_CSV = os.path.join(tempfile.gettempdir(), "mvp1_test_bookings.csv")
if os.path.exists(_TMP_CSV):
    os.remove(_TMP_CSV)
os.environ["BOOKINGS_CSV"] = _TMP_CSV

# Путь к самому пакету бота — чтобы импортировать handlers как модуль.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
import handlers
from handlers import handle_message, save_booking

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge.json"), encoding="utf-8") as f:
    KB = json.load(f)

SHOP = KB["name"]


def test_start_greeting():
    reply, state = handle_message("/start", {}, KB)
    assert isinstance(reply, str) and reply.strip(), "greeting must be non-empty"
    assert SHOP in reply, f"greeting must mention shop name '{SHOP}'"
    assert state == {}, "greeting should not leave an active flow"
    print("OK: /start greeting mentions shop name")


def test_faq_answer():
    reply, state = handle_message("Во сколько вы открываетесь?", {}, KB)
    assert isinstance(reply, str) and reply.strip(), "FAQ answer must be non-empty"
    print("OK: FAQ question returns a non-empty answer")


def test_booking_flow():
    # Шаг 1: пользователь просит бронь -> бот спрашивает имя
    reply1, state1 = handle_message("Хочу записаться на столик", {}, KB)
    assert state1.get("flow") == "booking", "should enter booking flow"
    assert state1.get("step") == "name"
    assert reply1.strip()

    # Шаг 2: имя -> бот спрашивает дату/время
    reply2, state2 = handle_message("Олег", state1, KB)
    assert state2.get("step") == "datetime"
    assert "Олег" in reply2

    # Шаг 3: дата/время -> подтверждение + запись в CSV
    reply3, state3 = handle_message("завтра в 19:00", state2, KB)
    assert state3 == {}, "flow should reset after confirmation"
    assert "Олег" in reply3 and "19:00" in reply3, "confirmation must echo name and time"
    assert any(w in reply3 for w in ("Готово", "заброн", "✅")), "must confirm booking"

    # Проверяем, что строка реально записана в CSV
    assert os.path.exists(_TMP_CSV), "bookings.csv must be created"
    with open(_TMP_CSV, encoding="utf-8") as f:
        content = f.read()
    assert "Олег" in content and "19:00" in content, "CSV must contain the booking row"
    print("OK: full booking flow confirms and writes a CSV row")


def test_save_booking_direct():
    path = save_booking("Тест Тестов", "25 июня 14:30")
    assert os.path.exists(path)
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert "Тест Тестов" in content and "25 июня 14:30" in content
    print("OK: save_booking writes a row directly")


if __name__ == "__main__":
    test_start_greeting()
    test_faq_answer()
    test_booking_flow()
    test_save_booking_direct()
    print("MVP1 TESTS OK")
