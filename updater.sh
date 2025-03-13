#!/bin/bash

# Убедимся, что скрипт запускается с правами суперпользователя
if [ "$(id -u)" -ne "0" ]; then
  echo "Этот скрипт должен быть запущен от имени суперпользователя (sudo)." 1>&2
  exit 1
fi

# Получаем последнюю версию через API GitHub
echo "Получаем информацию о последнем релизе nym-node..."
LATEST_VERSION=$(curl -s https://api.github.com/repos/nymtech/nym/releases/latest | grep -oP '"tag_name": "\K(.*?)(?=")')

# Проверяем, что версия получена
if [ -z "$LATEST_VERSION" ]; then
  echo "Ошибка: не удалось получить последнюю версию nym-node."
  exit 1
fi

# Формируем URL для скачивания
DOWNLOAD_URL="https://github.com/nymtech/nym/releases/download/$LATEST_VERSION/nym-node"

# Скачиваем последнюю версию nym-node
echo "Скачиваем последнюю версию nym-node ($LATEST_VERSION)..."
wget -q "$DOWNLOAD_URL" -O /tmp/nym-node

# Проверяем успешность скачивания
if [ ! -f /tmp/nym-node ]; then
  echo "Ошибка: не удалось скачать nym-node."
  exit 1
fi

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
