# 🌱 EcoGrid Flow: On-Premise Compute Cost & Carbon Optimizer

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-green.svg)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18+-61DAFB.svg)](https://react.dev/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791.svg)](https://www.postgresql.org/)
[![Docker Compose](https://img.shields.io/badge/Docker-Compose-2496ED.svg)](https://www.docker.com/)

**EcoGrid Flow** — On-Premise B2B-сервис, который подбирает для ресурсоемких вычислений (обучение моделей, Spark/dbt-пайплайны, рендеринг, бэкапы) дата-центр и время запуска, при которых электроэнергия обходится дешевле всего, а задача успевает к дедлайну. Учитываются цены на сутки вперед (ENTSO-E) и затраты на охлаждение по прогнозу погоды (Open-Meteo).

Проект разрабатывается в рамках сквозной проектной работы по дисциплине **«Программная инженерия»** (профиль «Инженерия данных», 3 курс).

---

## 📚 Документация

| Документ | О чем |
| :--- | :--- |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | **С чего начать:** компоненты, поток данных, владельцы, контракты, состояние |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Как работаем: задачи, ветки, PR, ревью, Definition of Done |
| [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) | Требования: FR, NFR, DR, ASR, приоритеты |
| [docs/adr/](docs/adr/) | Архитектурные решения |
| [docs/data/](docs/data/) | Схема БД ([ERD](docs/data/ERD.md)), [источники данных](docs/data/sources.md), [S2T-маппинги](docs/data/s2t/) |
| [docs/contracts/](docs/contracts/) | Контракты расчетного ядра и API |
| [docs/status/](docs/status/) | Еженедельные статусы |
| [docs/archive/](docs/archive/) | Учебные материалы (семинары, ТКУ1) — не источник истины |

---

## 👥 Команда «Шпингалеты»

| Участник | Роль | Зона ответственности |
| :--- | :--- | :--- |
| **Богдан Леонов** | Team Lead / PO / Data Engineer | Бэклог, архитектура данных, схема БД, ETL |
| **Александр Зейферт** | Lead Backend / DevOps | API на FastAPI, Docker Compose, CI |
| **Арина Антонова** | Data Analyst / ML Engineer | Модель PUE, оптимизатор, EDA |
| **Максим Томов** | Frontend Developer | Веб-портал, симулятор задач |
| **Григорий Витрик** | QA Engineer | Тесты, тестовые данные, проверки качества данных |

---

## 🎯 Границы MVP (Release 0.5 — декабрь 2026)

* **Входит:**
  1. Автоматический сбор цен Day-Ahead и прогноза погоды для энергозон `DE-LU`, `FI`, `SE3`.
  2. Проверка качества входящих данных.
  3. Модель динамического PUE: затраты на охлаждение ЦОД в зависимости от уличной температуры.
  4. Поиск самого дешевого окна запуска под дедлайн задачи и выбор ЦОД (гео-арбитраж).
  5. REST API на FastAPI со Swagger-документацией.
  6. Веб-портал с симулятором экономии.
* **Вынесено во 2-й семестр (Release 1.0):**
  * Собственная ML-модель прогноза цен на 3–7 дней вперед.
  * Автоматический запуск и остановка инстансов через Cloud API.
  * Провайдер (Sensor / Operator) для Apache Airflow.

---

## 🚀 Локальный запуск

Сейчас в стеке два сервиса: `postgres` и `etl-worker` (сбор прогноза погоды раз в 3 часа).

1. Скопировать настройки и при необходимости поменять пароль. Без `.env` используются значения по умолчанию из `docker-compose.yml`:
   ```shell
   cp .env.example .env
   ```
2. Поднять стек и проверить состояние:
   ```shell
   docker compose up -d
   docker compose ps
   ```
3. Проверить подключение к БД:
   ```shell
   docker compose exec postgres psql -U ecogrid -d ecogrid -c "SELECT datacenter_id FROM datacenters;"
   ```
4. Загрузить архив погоды (разово, по всем активным ЦОД):
   ```shell
   docker compose run --rm etl-worker python run_historical_weather.py --start-date 2023-10-01 --end-date 2026-10-20
   ```

`infra/db/init.sql` выполняется автоматически только на пустой базе. Чтобы применить изменения схемы к уже созданной базе, скрипт можно прогнать повторно — он идемпотентный:

```shell
docker compose exec -T postgres psql -U ecogrid -d ecogrid < infra/db/init.sql
```

Остановить стек без удаления данных:

```shell
docker compose down
```
