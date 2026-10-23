# Выкладка

Прод: сервер zurih (Ubuntu 24.04, Docker), адрес https://invoice-keeper.ru (запасной https://zu.oai.su). Выкладка только через git.

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
PUBLIC_URL=https://invoice-keeper.ru
SMTP_HOST=mail-relay
```

MAX (бот Invoice Keeper, свой, не Lodki): `MAX_BOT_TOKEN` и `MAX_CHAT_ID` в том же `.env`. id чата после добавления бота
в группу администратором и сообщения в ней: `docker compose exec app python -m app.services.max_api`.

## Обновление

```bash
ssh zurih
cd /opt/invoice-keeper && git pull --ff-only && docker compose up -d --build
```

Данные лежат в volume и не теряются. Проверка: `curl -s https://zu.oai.su/api/v1/health`.

## Почта

Письма уходят от `noreply@invoice-keeper.ru` через exim на metrika-rebenka (`157.22.231.158`, PTR `mail.метрика-ребенка.рф`):
у провайдера zurih исходящий SMTP закрыт, а там открыт.

- `deploy/docker-compose.zurih.yml` фиксирует подсеть `172.31.77.0/24`, имя `mail-relay` внутри контейнера указывает на шлюз `172.31.77.1`.
- `deploy/smtp-relay-tunnel.sh` (служба `invoice-keeper-smtp-relay`) пробрасывает `172.31.77.1:25` на `127.0.0.1:25` relay-хоста по SSH.
  Ключ `/root/.ssh/invoice_keeper_smtp` на relay ограничен: `restrict,port-forwarding,permitopen="127.0.0.1:25",command="/bin/false"`.
- ufw на zurih пускает к `172.31.77.1:25` только `172.31.77.0/24`.
- Exim подписывает письмо ключом `/etc/exim4/dkim/invoice-keeper.ru.private` (селектор `mail`, домен берётся из `From`).

`.env` на сервере: `SMTP_HOST=mail-relay`, `SMTP_PORT=25`, `SMTP_SECURITY=none`, без логина,
`SMTP_FROM=Invoice Keeper <noreply@invoice-keeper.ru>`.

DNS `invoice-keeper.ru` (REG.RU): A `@` и `www` → `82.38.135.78`; TXT `@` `v=spf1 ip4:157.22.231.158 ~all`;
TXT `mail._domainkey` с открытым ключом DKIM; TXT `_dmarc` `v=DMARC1; p=none`.
