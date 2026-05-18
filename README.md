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

однострочник

cat > /tmp/install-nym-bot.sh <<'SCRIPT'
#!/usr/bin/env bash
set -e

echo "=== Nym Performance Bot installer for screen ==="

REPO_URL="https://github.com/snoopfear/nym-node.git"
APP_DIR="$HOME/nym-node"
SCREEN_NAME="nym-bot"

ask() {
  local var_name="$1"
  local prompt="$2"
  local default_value="$3"
  local value

  if [ -n "$default_value" ]; then
    read -rp "$prompt [$default_value]: " value < /dev/tty
    value="${value:-$default_value}"
  else
    read -rp "$prompt: " value < /dev/tty
  fi

  printf -v "$var_name" '%s' "$value"
}

ask_secret() {
  local var_name="$1"
  local prompt="$2"
  local value

  read -rsp "$prompt: " value < /dev/tty
  echo
  printf -v "$var_name" '%s' "$value"
}

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "ERROR: команда '$1' не найдена."
    echo "Установи её вручную и запусти скрипт снова."
    exit 1
  fi
}

echo
echo "=== Checking dependencies ==="

need_cmd git
need_cmd screen

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "ERROR: python/python3 не найден."
  exit 1
fi

echo "Python: $($PYTHON_BIN --version)"
echo "Git: $(git --version)"
echo "Screen: $(screen --version | head -n 1)"

echo
echo "=== Configuration ==="

ask_secret TELEGRAM_BOT_TOKEN "Telegram bot token"
ask TELEGRAM_CHAT_ID "Telegram chat ID" ""
ask NYM_NODE_ID "Nym node ID" ""

ask NYM_API_BASE_URL "Nym API base URL" "https://validator.nymtech.net/api/v1"

ask CHECK_INTERVAL_MINUTES "Check interval in minutes" "30"
ask PERFORMANCE_THRESHOLD "Performance threshold" "0.9"

ask TIMEZONE "Timezone" "Europe/Moscow"
ask DAILY_REPORT_TIMES "Daily report times, comma-separated" "10:00,22:00"

ask ALERT_COOLDOWN_MINUTES "Alert cooldown in minutes" "60"

ask API_RETRY_ATTEMPTS "API retry attempts" "3"
ask API_RETRY_DELAY_SECONDS "API retry delay seconds" "10"
ask API_RETRY_BACKOFF "API retry backoff multiplier" "1.5"

ask SCREEN_NAME "Screen session name" "$SCREEN_NAME"
ask APP_DIR "Install directory" "$APP_DIR"

if [[ "$APP_DIR" != /* ]]; then
  APP_DIR="$PWD/$APP_DIR"
fi

if [ -z "$TELEGRAM_BOT_TOKEN" ] || [ -z "$TELEGRAM_CHAT_ID" ] || [ -z "$NYM_NODE_ID" ]; then
  echo "ERROR: Telegram bot token, Telegram chat ID и Nym node ID обязательны."
  exit 1
fi

echo
echo "=== Installing bot ==="

screen -S "$SCREEN_NAME" -X quit 2>/dev/null || true

rm -rf "$APP_DIR"
git clone "$REPO_URL" "$APP_DIR"

if ! "$PYTHON_BIN" -m venv "$APP_DIR/venv"; then
  echo
  echo "ERROR: не удалось создать venv."
  echo "Скорее всего, на сервере нет модуля python venv."
  echo "На Ubuntu/Debian обычно нужно:"
  echo "sudo apt install -y python3-venv"
  exit 1
fi

"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

cat > "$APP_DIR/.env" <<ENVEOF
TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID=$TELEGRAM_CHAT_ID

NYM_NODE_ID=$NYM_NODE_ID
NYM_API_BASE_URL=$NYM_API_BASE_URL

CHECK_INTERVAL_MINUTES=$CHECK_INTERVAL_MINUTES
PERFORMANCE_THRESHOLD=$PERFORMANCE_THRESHOLD

TIMEZONE=$TIMEZONE
DAILY_REPORT_TIMES=$DAILY_REPORT_TIMES

ALERT_COOLDOWN_MINUTES=$ALERT_COOLDOWN_MINUTES

API_RETRY_ATTEMPTS=$API_RETRY_ATTEMPTS
API_RETRY_DELAY_SECONDS=$API_RETRY_DELAY_SECONDS
API_RETRY_BACKOFF=$API_RETRY_BACKOFF
ENVEOF

screen -dmS "$SCREEN_NAME" bash -c "cd '$APP_DIR' && source venv/bin/activate && python bot.py"

echo
echo "=== Готово ==="
echo "Бот установлен в: $APP_DIR"
echo "Screen-сессия: $SCREEN_NAME"
echo
echo "Проверить:"
echo "screen -ls"
echo "screen -r $SCREEN_NAME"
echo
echo "Выйти из screen без остановки:"
echo "Ctrl+A, потом D"
echo
echo "Остановить бота:"
echo "screen -S $SCREEN_NAME -X quit"
echo
echo "Посмотреть конфиг:"
echo "cat $APP_DIR/.env"
SCRIPT

bash /tmp/install-nym-bot.sh
