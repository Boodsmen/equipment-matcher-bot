# Чек-лист разработки

## Этап 1: Инфраструктура и база данных

- [x] **1.1** `database/models.py` — SQLAlchemy модели (User, Model, SearchHistory)
- [x] **1.2** `database/db.py` — Async engine, фабрика сессий, настройка Alembic
- [x] **1.3** `database/crud.py` — CRUD операции (get_user, get_all_models, search_models_by_specs, bulk_create_models и др.)
- [x] **1.4** `scripts/scan_headers.py` — Анализатор заголовков CSV, выгрузка в `data/headers_report.json`
- [x] **1.5** `data/normalization_map.json` — Словарь нормализации на основе headers_report.json
- [x] **1.6** `scripts/import_csv.py` — Импорт CSV в БД с нормализацией (clean_spec_value, normalize_column_name)
- [x] **1.7** `config.py` — Настройки через pydantic-settings (.env)
- [x] **1.8** `middleware/auth.py` — Middleware для проверки whitelist (5 шагов)
- [x] **1.9** `handlers/start.py` — Обработка /start
- [x] **1.10** Dockerfile, docker-compose.yml, requirements.txt, .env.example, .gitignore
- [x] **1.11** `utils/logger.py` — Логирование (RotatingFileHandler)
- [x] **1.12** `alembic/env.py` — Настройка Alembic для async
- [x] **1.13** `bot.py` — Точка входа с регистрацией роутеров и middleware
- [x] **1.14** `handlers/document.py` — Заглушка обработки документов
- [x] **1.15** Миграции Alembic — initial_schema (таблицы models, users, search_history)
- [x] **1.16** Импорт CSV данных — 759 моделей из 46 файлов

## Этап 2: Интеграция с OpenAI и парсинг документов

- [x] **2.1** `services/docx_parser.py` — Чтение DOCX (extract_text_from_docx)
- [ ] **2.2** `services/pdf_parser.py` — Заглушка для PDF (будущее улучшение)
- [x] **2.3** `services/openai_service.py` — Двухэтапная обработка:
  - [x] Этап А: Router (gpt-4o-mini) — extract_tech_section
  - [x] Этап Б: Parser (gpt-4o) — parse_requirements с каноническими ключами
  - [x] Функция-обертка process_document
- [x] **2.4** `handlers/document.py` — Полная обработка загрузки документов (DOCX)

## Этап 3: Логика сопоставления моделей

- [x] **3.1** `services/matcher.py` — find_matching_models, calculate_match_percentage, categorize_matches
- [x] **3.2** compare_spec_values (строгое/нестрогое сравнение)
- [x] **3.3** Fallback стратегия поиска (по model_name -> category -> вся БД)
- [x] **3.4** Интеграция в handlers/document.py — вызов matcher после OpenAI

## Этап 4: Генерация Excel отчета

- [x] **4.1** `services/excel_generator.py` — generate_report
- [x] **4.2** Лист "Сводка" (модель, источник, % совпадения, статус, примечания)
- [x] **4.3** Листы "Детальное сравнение" (характеристика, требуется, в модели, статус)
- [x] **4.4** Форматирование (цвета, жирный шрифт, автоподбор ширины, фильтры)
- [x] **4.5** Интеграция в handlers/document.py — отправка файла пользователю

## Этап 5: Обработка дублей и оптимизация

- [x] **5.1** Обработка дублей моделей (deduplicate_models, _parse_version_priority, фильтрация пустых specs)
- [x] **5.2** Настройка MATCH_THRESHOLD (из .env) — работает с Этапа 3
- [x] **5.3** Настройка ALLOW_LOWER_VALUES (допуск значений) — работает с Этапа 3
- [x] **5.4** Юнит-тесты (61 тест: compare_spec_values, calculate_match_percentage, deduplicate_models, categorize_matches)
- [x] **5.5** Подключение save_search_history в handlers/document.py
- [ ] **5.6** Финальное e2e тестирование (отправка DOCX, проверка Excel, проверка search_history)
