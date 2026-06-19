"""
Офлайн-тесты MVP2 (mock LLM, без сети/ключей).

Запуск:
    cd /home/oleg/freelance-mvp && .venv/bin/python mvp2_n8n_automation/test_reference.py
Ожидаемый хвост вывода: MVP2 TESTS OK
"""
import sys
sys.path.insert(0, "/home/oleg/freelance-mvp")

import os
os.environ["LLM_PROVIDER"] = "mock"  # детерминированный провайдер для стабильности

import json

from mvp2_n8n_automation.reference import (
    score_lead,
    categorize,
    process_lead,
)

WORKFLOW = "/home/oleg/freelance-mvp/mvp2_n8n_automation/workflow.json"


def test_hot_lead():
    lead = {
        "name": "ООО Большой Бюджет",
        "budget": 150000,
        "phone": "+7 999 000-00-00",
        "email": "boss@big.ru",
        "message": "Нужно срочно, бюджет согласован",
    }
    result = process_lead(lead)
    assert result["category"] == "hot", result
    assert result["routed_to"] == "sales_call", result
    assert result["score"] >= 70, result


def test_cold_lead():
    lead = {
        "name": "Зевака",
        "budget": 0,
        "phone": "",
        "email": "",
        "message": "просто смотрю",
    }
    result = process_lead(lead)
    assert result["category"] == "cold", result
    assert result["routed_to"] == "newsletter", result


def test_warm_lead():
    lead = {
        "name": "Средний клиент",
        "budget": 15000,  # +25
        "phone": "+7 900 000-00-00",  # +10
        "email": "mid@example.com",  # +10  => 45 => warm
        "message": "присматриваюсь к сайту",
    }
    result = process_lead(lead)
    assert result["category"] == "warm", result
    assert result["routed_to"] == "email_nurture", result


def test_note_non_empty_string():
    lead = {"name": "Кто-то", "budget": 5000, "message": "вопрос"}
    note = process_lead(lead)["note"]
    assert isinstance(note, str), type(note)
    assert note.strip(), "note пустая"


def test_scoring_rules():
    # бюджет
    assert score_lead({"budget": 50000}) == 50
    assert score_lead({"budget": 10000}) == 25
    assert score_lead({"budget": 9999}) == 0
    # срочность
    assert score_lead({"message": "нужно ASAP"}) == 30
    # контакты
    assert score_lead({"phone": "123", "email": "a@b.c"}) == 20
    # пороги categorize
    assert categorize(70) == "hot"
    assert categorize(40) == "warm"
    assert categorize(39) == "cold"


def test_workflow_json_valid():
    with open(WORKFLOW, encoding="utf-8") as f:
        wf = json.load(f)
    assert "name" in wf
    assert isinstance(wf.get("nodes"), list)
    assert len(wf["nodes"]) >= 5, f"нод всего {len(wf['nodes'])}"
    assert isinstance(wf.get("connections"), dict)
    assert wf["connections"], "connections пустой"
    # у каждой ноды обязательные поля
    for node in wf["nodes"]:
        for key in ("id", "name", "type", "typeVersion", "position", "parameters"):
            assert key in node, f"нода {node.get('name')} без {key}"


if __name__ == "__main__":
    test_hot_lead()
    test_cold_lead()
    test_warm_lead()
    test_note_non_empty_string()
    test_scoring_rules()
    test_workflow_json_valid()
    print("MVP2 TESTS OK")
