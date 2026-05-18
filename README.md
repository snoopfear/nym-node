# Nym Performance Telegram Bot

Бот проверяет `https://validator.nymtech.net/api/v1/nym-nodes/performance-history/{node_id}` и отправляет Telegram-уведомление, если текущий performance ниже порога. Также отправляет обязательные отчёты в заданное время, по умолчанию в `10:00` и `22:00` по Москве. При неудачном API-запросе бот делает несколько ретраев; если после всех попыток performance получить не удалось, он принудительно отправляет Telegram-уведомление об ошибке.

## Быстрый запуск

```bash
sudo apt update && sudo apt install -y python3 python3-venv python3-pip
sudo mkdir -p /opt/nym-performance-bot
sudo cp bot.py requirements.txt .env.example /opt/nym-performance-bot/
cd /opt/nym-performance-bot
sudo cp .env.example .env
sudo nano .env
sudo python3 -m venv venv
sudo ./venv/bin/pip install -r requirements.txt
sudo ./venv/bin/python bot.py
```

## systemd

```bash
sudo cp nym-performance-bot.service /etc/systemd/system/nym-performance-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now nym-performance-bot
sudo journalctl -u nym-performance-bot -f
```

## Настройки `.env`

- `TELEGRAM_BOT_TOKEN` — токен Telegram-бота.
- `TELEGRAM_CHAT_ID` — chat id получателя/группы.
- `NYM_NODE_ID` — node id.
- `CHECK_INTERVAL_MINUTES` — период проверки, по умолчанию `30`.
- `PERFORMANCE_THRESHOLD` — порог, по умолчанию `0.9`.
- `TIMEZONE` — по умолчанию `Europe/Moscow`.
- `DAILY_REPORT_TIMES` — обязательные отчёты, по умолчанию `10:00,22:00`.
- `HTTP_TIMEOUT_SECONDS` — timeout одного HTTP-запроса к API и Telegram, по умолчанию `15`.
- `API_RETRY_ATTEMPTS` — общее количество попыток получить performance, включая первую попытку, по умолчанию `3`.
- `API_RETRY_DELAY_SECONDS` — пауза перед первым ретраем, по умолчанию `10`.
- `API_RETRY_BACKOFF` — множитель паузы между ретраями, по умолчанию `1.5`; при `10` и `1.5` паузы будут `10s`, затем `15s`.
- `ALERT_COOLDOWN_MINUTES` — защита от спама по low-performance alert; при `30` бот шлёт не чаще одного тревожного сообщения за 30 минут. На уведомления о провале API после всех ретраев этот cooldown не влияет.

## Поведение при ошибках API

Если `performance-history` временно недоступен, бот не считает проверку сразу проваленной. Он делает `API_RETRY_ATTEMPTS` попыток с задержкой `API_RETRY_DELAY_SECONDS` и backoff-множителем `API_RETRY_BACKOFF`.

Если все попытки исчерпаны:

- для обычной проверки бот отправляет `⚠️ Nym regular check failed after retries`;
- для обязательного отчёта в 10:00/22:00 бот отправляет `⚠️ Nym scheduled report failed after retries`;
- уведомление содержит `Node ID`, `API URL`, количество попыток, время проверки и текст последней ошибки.
