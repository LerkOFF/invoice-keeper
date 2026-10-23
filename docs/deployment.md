# Выкладка

Прод: сервер zurih (Ubuntu 24.04, Docker), адрес https://zu.oai.su. Выкладка только через git.

## Устройство

| Что | Где |
| --- | --- |
| код | `/opt/invoice-keeper`, git-копия `origin/main` |
| секреты и настройки | `/opt/invoice-keeper/.env` (не в git), права `600` |
| данные (SQLite, чеки) | Docker volume `invoice-keeper_invoice_data` |
| приложение | контейнер `invoice-keeper-app-1`, `127.0.0.1:8090` |
| HTTPS | nginx `zu.oai.su` → `127.0.0.1:8090`, сертификат Let's Encrypt (certbot); `/coin_radar/` остаётся за Coin Radar |
| SMTP | провайдер закрывает исходящий SMTP, поэтому служба `invoice-keeper-smtp-relay` держит SSH-туннель через сервер с открытым SMTP |

В `.env` на сервере, помимо обычных настроек:

```
COMPOSE_FILE=docker-compose.yml:deploy/docker-compose.zurih.yml
APP_BIND=127.0.0.1
APP_PORT=8090
COOKIE_SECURE=true
PUBLIC_URL=https://zu.oai.su
SMTP_HOST=smtp.yandex.ru
```

## Обновление

```bash
ssh zurih
cd /opt/invoice-keeper && git pull --ff-only && docker compose up -d --build
```

Данные лежат в volume и не теряются. Проверка: `curl -s https://zu.oai.su/api/v1/health`.

## SMTP через туннель

- `deploy/docker-compose.zurih.yml` фиксирует подсеть `172.31.77.0/24` и направляет `smtp.yandex.ru` внутри контейнера на шлюз `172.31.77.1`.
- `deploy/smtp-relay-tunnel.sh` пробрасывает `172.31.77.1:465` на `smtp.yandex.ru:465` через relay-хост.
  Ключ `/root/.ssh/invoice_keeper_smtp` на relay ограничен: `restrict,port-forwarding,permitopen="smtp.yandex.ru:465"`.
- ufw разрешает только `172.31.77.0/24 → 172.31.77.1:465`.
- TLS не разрывается: приложение проверяет настоящий сертификат `smtp.yandex.ru`.

Если провайдер откроет SMTP, туннель можно выключить (`systemctl disable --now invoice-keeper-smtp-relay`) и убрать `extra_hosts`.
