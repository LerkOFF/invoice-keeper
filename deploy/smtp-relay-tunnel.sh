#!/usr/bin/env bash
# Проброс SMTP Яндекса через сервер, где исходящий SMTP открыт.
# Слушает только шлюз docker-сети Invoice Keeper, снаружи порт не виден.
# Ключ на relay-хосте ограничен: restrict,port-forwarding,permitopen="smtp.yandex.ru:465".
set -euo pipefail

relay="${SMTP_RELAY:-root@157.22.231.158}"
key="${SMTP_RELAY_KEY:-/root/.ssh/invoice_keeper_smtp}"

gateway=$(/usr/bin/docker network inspect invoice-keeper_default --format '{{(index .IPAM.Config 0).Gateway}}')
if [[ -z "$gateway" ]]; then
    echo 'Docker gateway for invoice-keeper_default is unavailable' >&2
    exit 1
fi

exec /usr/bin/ssh -N -T \
    -i "$key" \
    -o BatchMode=yes \
    -o ExitOnForwardFailure=yes \
    -o StrictHostKeyChecking=yes \
    -o ConnectTimeout=10 \
    -o ServerAliveInterval=15 \
    -o ServerAliveCountMax=3 \
    -L "${gateway}:465:smtp.yandex.ru:465" \
    "$relay"
