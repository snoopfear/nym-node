#!/bin/bash

# Убедимся, что скрипт запускается с правами суперпользователя
if [ "$(id -u)" -ne "0" ]; then
  echo "Этот скрипт должен быть запущен от имени суперпользователя (sudo)." 1>&2
  exit 1
fi

# Скачиваем последнюю версию nym-node
echo "Скачиваем последний релиз nym-node..."
wget -q https://github.com/nymtech/nym/releases/download/nym-binaries-v2025.2-hu/nym-node -O /tmp/nym-node

# Даем файлу права на исполнение
echo "Даем права на исполнение скачанному файлу..."
chmod +x /tmp/nym-node

# Останавливаем сервис nym-node
echo "Останавливаем сервис nym-node..."
systemctl stop nym-node

# Копируем новый бинарник в /usr/local/bin
echo "Копируем новый бинарник nym-node в /usr/local/bin..."
cp -f /tmp/nym-node /usr/local/bin/

# Удаляем временный файл
echo "Удаляем временный файл..."
rm /tmp/nym-node

# Перезапускаем сервис nym-node
echo "Перезапускаем сервис nym-node..."
systemctl start nym-node

# Проверяем версию nym-node
echo "Проверяем версию nym-node..."
nym-node --version

echo "Обновление завершено!"
