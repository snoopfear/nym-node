cat > /tmp/install-nym-bot.sh <<'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail

echo "=== Nym Performance Bot installer for screen ==="

REPO_URL="https://github.com/snoopfear/nym-node.git"
APP_DIR="$HOME/nym-node"
SCREEN_NAME="nym-bot"

ask() {
  local var_name="$1"
  local prompt="$2"
  local default_value="${3:-}"
  local value=""

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
  local value=""

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

echo "Python: $("$PYTHON_BIN" --version 2>&1)"
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

"$APP_DIR/venv/bin/python" -m pip install --upgrade pip
"$APP_DIR/venv/bin/python" -m pip install -r "$APP_DIR/requirements.txt"

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

chmod 600 "$APP_DIR/.env"

screen -dmS "$SCREEN_NAME" bash -lc 'cd "$1" && source venv/bin/activate && exec python bot.py' _ "$APP_DIR"

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
