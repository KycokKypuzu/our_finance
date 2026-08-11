# Маленький сервис «Мои финансы»

Простой локальный веб-сервис на Python + FastAPI + Jinja2 + Bootstrap.

## Запуск

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app:app --reload
```

Открыть в браузере: http://127.0.0.1:8000

## Хранение

- пользователи: `data/users.json`
- месячные отчёты: `data/<username>_<month>_<year>.json`
- база данных не используется.

## Важная реализация для больших выписок

На страницах проверки/редактирования данные строк не отправляются как отдельные HTML form fields. JavaScript собирает все строки в один JSON-поле `payload` перед отправкой формы. Поэтому выписки с большим количеством операций не упираются в стандартный лимит Starlette `1000 fields`.
