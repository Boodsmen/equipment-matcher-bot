# Журнал багов

Здесь фиксируются баги, обнаруженные во время разработки и тестирования.

---

## Баг #1: Конфликт зависимостей pydantic
- **Дата**: 2026-02-08
- **Статус**: Исправлен
- **Описание**: `aiogram 3.13.1` требует `pydantic<2.10`, но в `requirements.txt` было указано `pydantic>=2.10.0`. Docker build падал с ошибкой разрешения зависимостей.
- **Решение**: Изменено на `pydantic>=2.4.1,<2.10` и `pydantic-settings>=2.6.0,<3.0`.

## Баг #2: Несовместимость версии PostgreSQL
- **Дата**: 2026-02-08
- **Статус**: Исправлен
- **Описание**: Docker volume `postgres_data` был инициализирован с PostgreSQL 16, но в `docker-compose.yml` была указана версия `postgres:15`. Контейнер БД не запускался: "database files are incompatible with server".
- **Решение**: Изменено `image: postgres:15` на `image: postgres:16` в docker-compose.yml.

## Баг #3: Ошибка аутентификации PostgreSQL
- **Дата**: 2026-02-08
- **Статус**: Исправлен
- **Описание**: После исправления версии PostgreSQL, старый volume содержал credentials от другого проекта. `asyncpg.exceptions.InvalidPasswordError: password authentication failed for user "tender"`.
- **Решение**: Пересоздание volume: `docker compose down` → `docker volume rm equipment-matcher-bot_postgres_data` → `docker compose up -d`.
