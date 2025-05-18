#!/bin/bash

# UFW настройки
ufw allow 22/tcp    # SSH
ufw allow 80/tcp    # HTTP
ufw allow 443/tcp   # HTTPS
ufw allow 1789/tcp  # Nym specific
ufw allow 1790/tcp  # Nym specific
ufw allow 8080/tcp  # Nym specific - nym-node-api
ufw allow 9000/tcp  # Nym Specific - clients port
ufw allow 9001/tcp  # Nym specific - wss port
ufw allow 51822/udp # WireGuard

# Проверка на sudo/root
if [ "$(id -u)" -ne "0" ]; then
  echo "❌ Этот скрипт нужно запускать с правами root (через sudo)."
  exit 1
fi

# Запрос имени узла (node ID)
read -rp "Введите имя вашей ноды (ID): " NODE_ID
if [ -z "$NODE_ID" ]; then
  echo "❌ Имя ноды не может быть пустым."
  exit 1
fi

# Получение последней версии из GitHub
echo "🔍 Получаем последнюю версию nym-node..."
LATEST_VERSION=$(curl -s https://api.github.com/repos/nymtech/nym/releases/latest | grep -oP '"tag_name": "\K(.*?)(?=")')

if [ -z "$LATEST_VERSION" ]; then
  echo "❌ Не удалось получить последнюю версию nym-node."
  exit 1
fi

# Скачивание бинарника
DOWNLOAD_URL="https://github.com/nymtech/nym/releases/download/$LATEST_VERSION/nym-node"
echo "⬇️ Скачиваем nym-node $LATEST_VERSION..."
wget -q "$DOWNLOAD_URL" -O /tmp/nym-node

if [ ! -f /tmp/nym-node ]; then
  echo "❌ Скачивание не удалось."
  exit 1
fi

# Установка бинарника
chmod +x /tmp/nym-node
cp -f /tmp/nym-node /usr/local/bin/
rm /tmp/nym-node
echo "✅ nym-node установлен в /usr/local/bin/"

# Инициализация ноды
echo "⚙️ Инициализация ноды..."
PUBLIC_IP=$(curl -s -4 https://ifconfig.me)
nym-node run \
  --id "$NODE_ID" \
  --init-only \
  --mode mixnode \
  --verloc-bind-address 0.0.0.0:1790 \
  --public-ips "$PUBLIC_IP" \
  --accept-operator-terms-and-conditions

# Создание systemd-сервиса
echo "📝 Создаем systemd unit для nym-node..."
cat > /etc/systemd/system/nym-node.service <<EOF
[Unit]
Description=Nym Node $LATEST_VERSION
StartLimitInterval=350
StartLimitBurst=10

[Service]
User=root
LimitNOFILE=65536
ExecStart=/usr/local/bin/nym-node run --id $NODE_ID --deny-init --mode mixnode --accept-operator-terms-and-conditions
KillSignal=SIGINT
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF

# Активация сервиса
echo "🔄 Перезапускаем systemd и активируем сервис..."
systemctl daemon-reexec
systemctl daemon-reload
systemctl enable nym-node

# Финальное сообщение
echo -e "\n✅ Установка завершена!"
echo "⚠️  Замените конфигурационные файлы с вашими данными, включая IP, если необходимо, а также IP в кошельке NYM."
echo "Проверь настройки в /etc/systemd/journald.conf: Storage=persistent sudo systemctl restart systemd-journald"
echo "▶️  Для запуска ноды выполните: systemctl start nym-node"
echo "логи journalctl -u nym-node -f"
