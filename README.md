# 🌱 EcoGrid Flow: On-Premise Compute Cost & Carbon Optimizer

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-green.svg)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18+-61DAFB.svg)](https://react.dev/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791.svg)](https://www.postgresql.org/)
[![Docker Compose](https://img.shields.io/badge/Docker-Compose-2496ED.svg)](https://www.docker.com/)

**EcoGrid Flow** — On-Premise аналитический B2B-сервис и рекомендательная система для оптимизации расписания и пространственной маршрутизации (*Geo-Arbitrage*) ресурсоемких серверных вычислений (обучение нейросетей, регулярные dbt/Spark пайплайны, рендеринг, бэкапы).

Проект разрабатывается в рамках сквозной проектной работы по дисциплине **«Программная инженерия»** (профиль «Инженерия данных», 3 курс, 5-й семестр).

---

## 👥 Команда «Шпингалеты» (*Shpingalets*)

| Участник | Роль в проекте | Основная зона ответственности |
| :--- | :--- | :--- |
| **Богдан Леонов** | **Team Lead / PO / Data Engineer** | Управление бэклогом, архитектура данных, ETL-пайплайны, алгоритмы Geo-Arbitrage |
| **Александр Зейферт** | **Lead Backend / DevOps** | Ядро FastAPI, архитектура PostgreSQL, Docker Compose, CI/CD |
| **Максим Томов** | **Frontend Developer** | Корпоративный веб-портал на React / TypeScript, ECharts дашборды, карта цен |
| **Арина Антонова** | **Data Analyst / ML Engineer** | Исследование исторических рядов (EDA), физическая модель PUE, ML-прогнозирование |
| **Григорий Витрик** | **QA Engineer** | Валидация Data Quality, нагрузочные тесты, автотесты `pytest`, мокирование API |

---

## 🏛️ Ключевая концепция и архитектура

Сервис поставляется как изолированная Docker-композиция и развертывается **строго внутри закрытого корпоративного периметра (On-Premise VPC)** клиента. Данные о топологии ЦОД, серверах и задачах компании никогда не покидают защищенный контур.

```
Внешний интернет:
[ENTSO-E (Day-Ahead / Gen)] + [Open-Meteo (Погода)]
                     │ (XML / JSON)
                     ▼
Закрытый On-Premise контур клиента:
[ETL Ingestion Workers] ──► [Data Quality Validation]
                                    │
                                    ▼
                        [PostgreSQL (Timeseries)]
                                    │
[Airflow / DataOps] ──► [FastAPI Gateway] ──► [Optimization & ML Engine (PUE + Geo)]
                                    │
                                    ▼
                         [React Web UI Portal]
```

---

## 📁 Структура репозитория и документация

* **[docs/seminar_1/README.md](docs/seminar_1/README.md)** — Семинар 1: паспорт проекта, роли, границы MVP.
* **[docs/seminar_2/README.md](docs/seminar_2/README.md)** — Семинар 2: Kanban-процесс, бэклог, Definition of Done.
* **[docs/seminar_3/README.md](docs/seminar_3/README.md)** — Семинар 3: стейкхолдеры, глоссарий, AS-IS / TO-BE, контекстная диаграмма.
* **[docs/seminar_4/readme.md](docs/seminar_4/readme.md)** — Семинар 4: требования v1.1.0 (FR / NFR / DR), критерии приемки, ASR.
* **[docs/seminar_5/README.md](docs/seminar_5/README.md)** — Семинар 5: устав проекта, WBS, дорожная карта, RACI.
* **[docs/seminar_6/README.md](docs/seminar_6/README.md)** — Семинар 6: реестр рисков, матрица, план реагирования, задачи по снижению рисков.
* **[docs/seminar_7/README.md](docs/seminar_7/README.md)** — Семинар 7: масштабирование на 4 команды, общие контракты, карта межкомандных зависимостей, правила интеграции.
* **[docs/tku1/README.md](docs/tku1/README.md)** — промежуточная защита (ТКУ1): инструкция, презентация, текст выступления, где что показать по запросу.
* **[docs/data ingestion/](docs/data%20ingestion/)** — каталог источников данных и описание полей таблиц.
* **[docs/database/](docs/database/)** — [ER-диаграмма](docs/database/ERD.md) схемы `infra/db/init.sql` и S2T-маппинги источников на таблицы.
* **[docs/status/](docs/status/)** — еженедельные статус-отчеты проекта.

---

## 🎯 Границы MVP (Release 50% — Декабрь 2026)

* **Реализуется в первом семестре:**
  1. Автоматический сбор Day-Ahead тарифов биржи и прогнозов погоды по целевым энергозонам (`DE-LU`, `FI`, `SE3`).
  2. Data Quality валидация входящих временных рядов.
  3. Физико-математическая модель расчета динамического PUE охлаждения дата-центров по уличной температуре.
  4. Движок оптимизации скользящего окна запуска под SLA-дедлайн задачи.
  5. Пространственный арбитраж (Geo-Arbitrage) между несколькими ЦОД.
  6. Защищенный REST API (FastAPI) с интерактивной Swagger-документацией.
  7. Веб-портал (React SPA) с картой тарифов и симулятором экономии.
* **Вынесено во 2-й семестр (Release 100%):**
  * Обучение собственной ML-модели на 5-летнем архиве для прогнозирования тарифов на 3–7 дней вперед.
  * Прямая интеграция с Cloud API для автоматического запуска/остановки инстансов.
  * Нативный провайдер (Sensor/Operator) под Apache Airflow.

### Local PostgreSQL

Optionally copy `.env.example` to `.env` and change the development credentials.
The defaults from `.env.example` are also used when `.env` is absent.

```shell
docker compose up -d
docker compose ps
```

Test the connection from inside the container:

```shell
docker compose exec postgres psql -U ecogrid -d ecogrid -c "SELECT 1;"
```

Stop the container without deleting its persistent data:

```shell
docker compose down
```
