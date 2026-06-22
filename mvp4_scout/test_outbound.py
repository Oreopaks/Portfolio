"""Офлайн-тесты исхода: парсер Trudvsem + фильтр релевантности (без сети)."""
import sys
sys.path.insert(0, "/home/oleg/freelance-mvp")

from mvp4_scout.trudvsem_source import parse_vacancies
from mvp4_scout.outbound import _relevant, build_package, _fmt_salary

_SAMPLE = {"results": {"vacancies": [
    {"vacancy": {
        "id": "v1", "job-name": "Оператор по обработке заявок",
        "company": {"name": "ООО Ромашка", "inn": "7701234567", "email": "hr@romashka.ru", "url": "romashka.ru"},
        "contact_list": [{"contact_type": "Телефон", "contact_value": "+7(900)000-00-00"}],
        "salary_min": 34000, "salary_max": 40000,
        "region": {"name": "Москва"}, "duty": "принимать входящие заявки от клиентов, заносить в систему",
        "vac_url": "https://trudvsem.ru/vacancy/card/v1",
    }},
    {"vacancy": {  # нерелевантная: грузчик, без контакта
        "id": "v2", "job-name": "Грузчик на склад",
        "company": {"name": "Склад", "inn": "", "email": "", "url": ""},
        "salary_min": 50000, "salary_max": 50000, "region": {"name": "Тверь"},
        "duty": "погрузка-разгрузка", "vac_url": "https://trudvsem.ru/vacancy/card/v2",
    }},
]}}


def test_parse():
    t = parse_vacancies(_SAMPLE)
    assert len(t) == 2
    a = t[0]
    assert a["company"] == "ООО Ромашка" and a["email"] == "hr@romashka.ru"
    assert a["phone"] == "+7(900)000-00-00" and a["salary_min"] == 34000
    assert a["region"] == "Москва" and a["id"] == "v1"
    print("OK parse: компания/контакт/зп/регион распознаны")


def test_relevance():
    a, b = parse_vacancies(_SAMPLE)
    assert _relevant(a), "оператор заявок с контактом — релевантен"
    assert not _relevant(b), "грузчик без контакта — отсеян"
    print("OK relevance: цель прошла, мусор отсеян")


def test_package():
    a = parse_vacancies(_SAMPLE)[0]
    pkg = build_package(a, "Тестовый питч.")
    assert "ООО Ромашка" in pkg and "hr@romashka.ru" in pkg and "34000-40000 ₽" in pkg
    assert _fmt_salary({"salary_min": 0, "salary_max": 0}) == "не указана"
    print("OK package: пакет собран с контактом и зп")


if __name__ == "__main__":
    test_parse()
    test_relevance()
    test_package()
    print("OUTBOUND TESTS OK")
