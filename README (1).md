# 📊 Crypto Alert Bot

Telegram-бот для мониторинга криптовалют. Шлёт сигнал когда цена изменилась на заданный %.

## Монеты
BTC, ETH, SOL, BNB, XRP, TON — через Binance API (без ключей)

## Команды
- `/start` — старт
- `/alert` — создать алерт (монета → % → направление → интервал)
- `/list` — активные алерты
- `/clear` — удалить все
- `/prices` — текущие цены

## Запуск

```bash
pip install -r requirements.txt
cp .env.example .env
# вставь BOT_TOKEN в .env
python bot.py
```

## Деплой на Render
1. Создай Web Service → Python
2. Build: `pip install -r requirements.txt`
3. Start: `python bot.py`
4. Env var: `BOT_TOKEN`
