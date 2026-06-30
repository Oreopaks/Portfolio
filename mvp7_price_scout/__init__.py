"""
mvp7_price_scout — парсер цен конкурентов + Telegram-бот сравнения.

Наш сайт-эталон di-park.ru = база цен. Конкуренты (сайты + Яндекс-профили +
Instagram) сопоставляются к каталогу di-park по нормализованному ключу товара.
Цены складываются в SQLite; бот по запросу товара отдаёт компактную таблицу
«наша цена vs конкуренты».

Слои (повторяют идиому mvp4_scout):
  sources/*  — на источник: чистая parse_*(html) + сетевая fetch_*()
  normalize  — title -> model_key (канон для сравнения) + dataclass Product
  match      — привязка товара конкурента к каталогу di-park (rapidfuzz)
  store      — SQLite: upsert цен, чтение каталога/сравнения
  collector  — агрегатор: fetch всех -> normalize -> match -> upsert
  bot/handlers — long-poll бот, рендер таблицы
"""
