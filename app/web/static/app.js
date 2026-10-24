// Invoice Keeper: панель без сборки и внешних зависимостей, оформление в стиле кабинета my.aeza.ru (светлая и тёмная тема).
// Все данные в DOM попадают через textContent, поэтому названия платежей не могут внедрить разметку.

const API = "/api/v1";
const CURRENCIES = ["RUB", "USD", "EUR"];
const PERIODS = ["monthly", "quarterly", "yearly"];
const SOON_DAYS = 3;

const state = {
  me: null,
  asOf: null, // «сегодня» по часовому поясу сервера
  tab: "payments",
  filters: { status: "all", currency: "", category: "", assignee: "", scope: "all", deleted: false, on: "", q: "" },
  sort: { key: "due", dir: 1 },
  cal: null, // { year, month, selected }
  budgetYear: null,
};

// ---------- язык интерфейса: русский и английский, как переключатель в кабинете aeza ----------

const LANGS = [
  { id: "ru", label: "Русский", locale: "ru-RU" },
  { id: "en", label: "English", locale: "en-GB" },
];
const LANG_KEY = "ik-lang";

const I18N = {
  ru: {
    "app.description": "Напоминания о регулярных платежах: срок, оплата, просрочка",

    "common.cancel": "Отмена",
    "common.save": "Сохранить",
    "common.close": "Закрыть",
    "common.delete": "Удалить",
    "common.edit": "Изменить",
    "common.loading": "Загрузка…",
    "common.reset": "Сбросить",
    "common.today": "Сегодня",
    "common.showMore": "Показать ещё",
    "common.nothingToChange": "Нечего менять",

    "error.network": "Нет связи с сервером",
    "error.server": "Ошибка сервера ({status})",
    "error.load": "Не удалось загрузить данные",

    "field.login": "Логин",
    "field.password": "Пароль",
    "field.name": "Название",
    "field.amount": "Сумма",
    "field.currency": "Валюта",
    "field.period": "Периодичность",
    "field.first_due_date": "Дата ближайшей оплаты",
    "field.status": "Статус",
    "field.paid_at": "Дата оплаты",
    "field.url": "Ссылка",
    "field.file": "Файл",
    "field.title": "Название",
    "field.q": "Поиск",
    "field.otp": "Код из приложения",
    "field.current_password": "Текущий пароль",
    "field.new_password": "Новый пароль",
    "field.scope": "Доступ",
    "field.expires_in_days": "Срок действия",
    "field.pay_url": "Ссылка на оплату",
    "field.category": "Категория",
    "rec.categoryPlaceholder": "аренда, IT, подписки",
    "payments.allCategories": "Все категории",
    "payments.noCategory": "Без категории",
    "field.assignee_id": "Ответственный",
    "rec.noAssignee": "— не назначен —",
    "payments.mine": "Только мои",
    "payments.allAssignees": "Все ответственные",
    "payments.noAssignee": "Без ответственного",
    "budget.byCategory": "по категориям",
    "budget.category": "Категория",
    "field.pay_details": "Реквизиты",
    "rec.payUrlPlaceholder": "https://…",
    "rec.payDetailsPlaceholder": "договор, счёт, ИНН",
    "rec.payLink": "ссылка на оплату ↗",
    "act.pay": "Оплатить",
    "check.payUrl": "Ссылка на оплату: начните с http:// или https://",

    "valid.string_too_short": "слишком короткое значение",
    "valid.string_too_long": "слишком длинное значение",
    "valid.string_pattern_mismatch": "недопустимые символы",
    "valid.greater_than": "должно быть больше нуля",
    "valid.decimal_max_places": "не больше двух знаков после запятой",
    "valid.decimal_parsing": "неверное число",
    "valid.decimal_type": "неверное число",
    "valid.decimal_max_digits": "слишком большое число",
    "valid.extra_forbidden": "поле не поддерживается",
    "valid.missing": "обязательное поле",
    "valid.date_parsing": "неверная дата",
    "valid.date_from_datetime_parsing": "неверная дата",
    "valid.enum": "недопустимое значение",

    "check.amount": "Сумма: положительное число, не больше двух знаков после запятой",
    "check.login": "Логин: 3–64 символа, латиница, цифры и . _ @ -",
    "check.password": "Пароль: от 8 до 128 символов",
    "check.name": "Название: укажите название платежа",
    "check.firstDue": "Дата ближайшей оплаты: укажите дату",
    "check.paidAt": "Укажите дату оплаты",
    "check.newSchedule": "Новый график: укажите дату ближайшей оплаты",
    "check.url": "Ссылка: нужен адрес, начинающийся с http:// или https://",
    "check.file": "Файл: выберите файл",
    "check.credentials": "Введите логин и пароль",

    "pw.show": "Показать пароль",
    "pw.hide": "Скрыть пароль",

    "auth.title": "Вход в панель",
    "auth.lead": "Платежи, сроки и напоминания в одном месте.",
    "auth.submit": "Войти",
    "auth.invalid": "Неверный логин или пароль",
    "auth.expired": "Сессия закончилась, войдите снова",
    "auth.otpNeeded": "Введите шестизначный код из приложения-аутентификатора",
    "auth.otpHint": "Google Authenticator, Яндекс Ключ, Aegis или другое приложение с кодами TOTP",
    "auth.promoTitle": "платежи под контролем",
    "auth.point1": "Напоминание за 3 дня до срока в Telegram, MAX и на почту",
    "auth.point2": "Просрочка считается сама, история оплат не теряется",
    "auth.point3": "RUB, USD и EUR, итоги по каждой валюте отдельно",

    "shell.logout": "Выйти",
    "shell.password": "Сменить пароль",
    "pass.title": "Смена пароля",
    "pass.desc": "После смены остальные ваши сессии завершатся, эта останется открытой.",
    "pass.current": "Текущий пароль",
    "pass.new": "Новый пароль",
    "pass.repeat": "Новый пароль ещё раз",
    "pass.mismatch": "Новые пароли не совпадают",
    "pass.done": "Пароль изменён",
    "shell.today": "сегодня",
    "shell.addPayment": "Добавить платёж",
    "shell.api": "API и Swagger",
    "shell.menu": "Меню",
    "shell.language": "Язык",
    "theme.title": "Цветовая тема",
    "theme.current": "Тема: {mode}",
    "theme.system": "Системная",
    "theme.light": "Светлая",
    "theme.dark": "Тёмная",
    "role.admin": "админ",
    "role.user": "пользователь",

    "tab.payments": "Платежи",
    "tab.calendar": "Календарь",
    "tab.budget": "Бюджет",
    "tab.recurring": "Регулярные платежи",
    "tab.users": "Пользователи",
    "tab.audit": "Журнал",
    "tab.messengers": "Мессенджеры",
    "tab.account": "Аккаунт",

    "currency.RUB": "Российский рубль",
    "currency.USD": "Доллар США",
    "currency.EUR": "Евро",

    "status.paid": "Оплачено",
    "status.late": "Оплачено позже срока",
    "status.lateDays": "Оплачено позже срока ({n} дн.)",
    "status.overdue": "Просрочено {n} дн.",
    "status.soon": "Скоро срок",
    "status.unpaid": "Не оплачено",
    "status.planned": "Запланирован",

    "due.overdueBy": "просрочено на {days}",
    "due.today": "сегодня",
    "due.tomorrow": "завтра",
    "due.in": "через {days}",

    "payments.lead": "Что и когда оплатить, что уже оплачено и что просрочено",
    "payments.summary": "Итоги по валютам",
    "payments.list": "периоды оплаты",
    "payments.all": "Все",
    "payments.unpaid": "Не оплачено",
    "payments.overdue": "Просрочено",
    "payments.paid": "Оплачено",
    "payments.allPeriods": "Все периоды",
    "payments.thisMonth": "Текущий месяц",
    "payments.allCurrencies": "Все валюты",
    "payments.withDeleted": "С прекращёнными",
    "payments.onDate": "Итоги на дату",
    "payments.shown": "Показано: {n}",
    "payments.search": "Поиск по названию",
    "payments.csv": "Скачать CSV",
    "payments.csvHint": "Выгрузка с текущими фильтрами, открывается в Excel",
    "payments.empty": "Платежей по этим условиям нет",
    "payments.emptyAdmin": "Добавьте первый платёж в разделе «Регулярные платежи».",
    "payments.emptyUser": "Администратор ещё не добавил платежи.",
    "payments.stopped": "Платёж прекращён",
    "col.payment": "Платёж",
    "col.amount": "Сумма",
    "col.due": "Срок",
    "col.status": "Статус",
    "col.paidAt": "Оплачено",
    "act.markPaid": "Отметить оплату",
    "act.changeDate": "Изменить дату",
    "act.undo": "Отменить",

    "sum.onDate": "на {date}",
    "sum.toPay": "к оплате · {payments}",
    "sum.allClosed": "к оплате · всё закрыто",
    "sum.overdue": "Просрочено",
    "sum.paid": "Оплачено",
    "sum.due": "Ждёт оплаты",
    "sum.left": "Осталось",
    "sum.sticker": "просрочка!",
    "sum.open": "Показать периоды в {currency}",

    "pay.title": "Отметить оплату",
    "pay.titleEdit": "Изменить дату оплаты",
    "pay.desc": "{name}, срок {date}, {amount}",
    "pay.confirm": "Оплачено",
    "pay.field": "Фактическая дата оплаты",
    "pay.hint": "Если оплатили не сегодня, укажите реальную дату: от неё считается просрочка",
    "pay.done": "Оплата отмечена",
    "pay.doneEdit": "Дата оплаты обновлена",
    "unpay.title": "Отменить оплату?",
    "unpay.desc": "Период «{name}» за {date} снова станет неоплаченным, дата оплаты очистится.",
    "unpay.confirm": "Отменить оплату",
    "unpay.done": "Оплата отменена",

    "rc.button": "Чеки",
    "rc.buttonCount": "Чеки ({n})",
    "rc.title": "Чеки и ссылки",
    "rc.desc": "{name}, срок {date}",
    "rc.kind.file": "файл",
    "rc.kind.link": "ссылка",
    "rc.deleted": "Вложение удалено",
    "rc.empty": "Пока ничего не прикреплено",
    "rc.linkTitle": "Прикрепить ссылку",
    "rc.url": "Адрес",
    "rc.titleOptional": "Название (необязательно)",
    "rc.linkPlaceholder": "Чек из банка",
    "rc.addLink": "Добавить ссылку",
    "rc.linkAdded": "Ссылка прикреплена",
    "rc.fileTitle": "Загрузить чек",
    "rc.fileHint": "PDF, PNG, JPEG или WebP, до 5 МБ",
    "rc.upload": "Загрузить чек",
    "rc.uploaded": "Чек загружен",
    "rc.stopped": "Платёж прекращён: вложения можно смотреть, добавлять нельзя",
    "size.mb": "{n} МБ",
    "size.kb": "{n} КБ",

    "period.monthly": "Ежемесячно",
    "period.quarterly": "Раз в квартал",
    "period.yearly": "Раз в год",
    "hint.yearly": "каждый год {day}",
    "hint.yearlyLeap": "каждый год {day}, в невисокосный год 28 февраля",
    "hint.quarterly": "раз в 3 месяца, ",
    "hint.day": "{d}-го числа",
    "hint.short": ", в коротких месяцах в последний день",

    "rec.lead": "Платёж повторяется каждый месяц, раз в квартал или раз в год, напоминание приходит за 3 дня до срока",
    "rec.list": "все платежи",
    "rec.colPeriod": "Периодичность",
    "rec.colNext": "Ближайший неоплаченный срок",
    "rec.colNextShort": "Ближайший срок",
    "rec.firstDue": "первый срок {date}",
    "rec.stop": "Прекратить",
    "rec.pause": "Пауза",
    "rec.resume": "Возобновить",
    "rec.pauseTitle": "Поставить на паузу?",
    "rec.pauseDesc": "«{name}»: пока пауза, новых периодов и напоминаний не будет. Неоплаченные сроки внутри паузы уберутся, оплаты и прошлые долги останутся.",
    "rec.pauseUntil": "До какого дня",
    "rec.pauseHint": "пусто — до ручного возобновления; сам этот день уже не на паузе",
    "rec.paused": "на паузе",
    "rec.pausedUntil": "на паузе до {date}",
    "rec.pausedDone": "«{name}» на паузе",
    "rec.resumed": "«{name}» снова активен",
    "audit.until": "до {date}",
    "rec.empty": "Регулярных платежей пока нет",
    "rec.emptyText": "Добавьте аренду, подписку или оплату сервера формой выше.",
    "rec.new": "Новый регулярный платёж",
    "rec.namePlaceholder": "Аренда офиса",
    "rec.add": "Добавить",
    "rec.added": "Платёж «{name}» добавлен",
    "rec.editTitle": "Изменить платёж",
    "rec.editDesc": "Новая сумма действует для неоплаченных периодов с сегодняшнего дня, оплаченные и прошлые сохраняют свою. Валюта ({currency}) не меняется.",
    "rec.amountIn": "Сумма, {currency}",
    "rec.newFirstDue": "Дата ближайшей оплаты по новому графику",
    "rec.newFirstDueHint": "только если меняется график: неоплаченные будущие сроки старого графика уберутся, история останется",
    "rec.updated": "Платёж «{name}» обновлён",
    "rec.stopTitle": "Прекратить платёж?",
    "rec.stopDesc": "«{name}» больше не будет создавать периоды и напоминания. История оплат сохранится.",
    "rec.stopped": "Платёж «{name}» прекращён",

    "users.lead": "Обычные учётные записи. Администратор задаётся в .env и здесь не показывается",
    "users.list": "учётные записи",
    "users.colCreated": "Создан",
    "users.colMessengers": "Мессенджеры",
    "users.empty": "Обычных пользователей пока нет",
    "users.emptyText": "Создайте учётную запись формой выше, и команда сможет отмечать оплаты.",
    "users.new": "Новый пользователь",
    "users.passwordPlaceholder": "не короче 8 символов",
    "users.create": "Создать",
    "users.created": "Пользователь «{login}» создан",
    "users.editTitle": "Изменить пользователя",
    "users.newPassword": "Новый пароль",
    "users.newPasswordHint": "оставьте пустым, чтобы не менять; смена пароля завершит сессии пользователя",
    "users.updated": "Пользователь обновлён",
    "users.deleteTitle": "Удалить пользователя?",
    "users.deleteDesc": "«{login}» потеряет доступ сразу, его сессии завершатся.",
    "users.deleted": "Пользователь «{login}» удалён",

    "cal.title": "Календарь оплат",
    "cal.lead": "Сроки на месяц вперёд и дальше: будущие периоды вычисляются по правилу повторения",
    "cal.prev": "Предыдущий месяц",
    "cal.next": "Следующий месяц",
    "cal.none": "В этом месяце платежей нет",
    "cal.noneDay": "В этот день платежей нет",
    "cal.dayLabel": "{date}, платежей: {n}",
    "cal.paidShare": "Доля оплаченного",
    "cal.paidLeft": "оплачено {paid} · осталось {left}",
    "cal.paidOn": "оплачено {date}",
    "cal.stopped": "платёж прекращён",

    "budget.lead": "Плановые расходы по каждой валюте отдельно, без конвертации. Нажмите на месяц, чтобы открыть его в календаре",
    "budget.year": "{year} год",
    "budget.prev": "Предыдущий год",
    "budget.next": "Следующий год",
    "budget.plan": "план на год",
    "budget.none": "платежей нет",
    "budget.month": "Месяц",
    "budget.byMonth": "по месяцам",
    "budget.paidAll": "оплачено",
    "budget.paidPart": "оплачено {amount}",
    "budget.empty": "В этом году платежей нет",
    "budget.emptyText": "Бюджет появится, как только администратор добавит регулярные платежи.",

    "audit.lead": "Кто и что делал: входы, оплаты (в том числе из Telegram и MAX), платежи, пользователи. Пароли сюда не попадают",
    "audit.colTime": "Время",
    "audit.colWho": "Кто",
    "audit.colAction": "Действие",
    "audit.colDetails": "Подробности",
    "audit.colIp": "Адрес",
    "audit.empty": "Записей нет",
    "audit.emptyText": "Здесь появятся входы, оплаты, изменения платежей и пользователей.",
    "audit.due": "срок {date}",
    "audit.paidOn": "оплата {date}",
    "audit.paidChanged": "{name}, {due}: дата оплаты {before} → {after}",
    "audit.created": "{name}, {amount}, {period}первый срок {date}",
    "audit.amountChanged": "сумма {before} → {after}",
    "audit.scheduleChanged": "график: {period}, ближайший срок {date}",
    "audit.passwordChanged": "пароль изменён",
    "audit.channel": "{name}, {due}, канал: {channel}",
    "audit.failed": "попытка входа с этим логином",
    "audit.locked": "вход закрыт на {minutes} мин.",
    "audit.otpFailed": "неверный или повторный код второго фактора",
    "audit.sessionsClosed": "закрыто сессий: {n}",
    "audit.token": "«{name}», {scope}",
    "audit.f.all": "Всё",
    "audit.f.auth": "Вход",
    "audit.f.occurrence": "Оплаты",
    "audit.f.payment": "Платежи",
    "audit.f.user": "Пользователи",
    "audit.f.reminder": "Напоминания",
    "audit.f.messenger": "Мессенджеры",
    "audit.f.token": "API-токены",
    "audit.p.all": "Всё время",
    "audit.p.1": "Сегодня",
    "audit.p.7": "7 дней",
    "audit.p.30": "30 дней",
    "action.auth.login": "Вход",
    "action.auth.login_failed": "Неудачный вход",
    "action.auth.login_locked": "Вход заблокирован",
    "action.auth.logout": "Выход",
    "action.auth.otp_failed": "Неверный код второго фактора",
    "action.auth.password_changed": "Пароль изменён",
    "action.auth.password_failed": "Неверный текущий пароль",
    "action.auth.session_ended": "Сессия завершена",
    "action.auth.sessions_ended": "Остальные сессии завершены",
    "action.token.create": "API-токен создан",
    "action.token.revoke": "API-токен отозван",
    "action.payment.create": "Платёж добавлен",
    "action.payment.update": "Платёж изменён",
    "action.payment.delete": "Платёж прекращён",
    "action.payment.pause": "Платёж на паузе",
    "action.payment.resume": "Пауза снята",
    "action.occurrence.paid": "Оплата отмечена",
    "action.occurrence.unpaid": "Оплата отменена",
    "action.occurrence.paid_at_changed": "Дата оплаты исправлена",
    "action.user.create": "Пользователь создан",
    "action.user.update": "Пользователь изменён",
    "action.user.delete": "Пользователь удалён",
    "action.receipt.add": "Чек или ссылка добавлены",
    "action.receipt.delete": "Чек или ссылка удалены",
    "action.reminder.sent": "Напоминание отправлено",
    "action.reminder.overdue_sent": "Напоминание о просрочке отправлено",
    "action.messenger.link": "Мессенджер привязан",
    "action.messenger.unlink": "Мессенджер отвязан",
    "actor.admin": "админ",
    "actor.user": "пользователь",
    "actor.telegram": "Telegram",
    "actor.max": "MAX",
    "actor.system": "система",
    "actor.anonymous": "аноним",

    "msg.lead": "Привяжите Telegram или MAX, и напоминания об оплате будут приходить вам лично, с кнопкой «Оплачено». Отметка из мессенджера записывается от вашего имени",
    "msg.notConfigured": "Бот этого мессенджера не настроен на сервере",
    "msg.linkedTo": "Привязан: ",
    "msg.since": " · с {date}",
    "msg.notLinkedText": "Не привязан: напоминания приходят только в общий чат",
    "msg.linked": "привязан",
    "msg.notLinked": "не привязан",
    "msg.link": "Привязать",
    "msg.linkOther": "Привязать другой аккаунт",
    "msg.unlink": "Отвязать",
    "msg.unlinkTitle": "Отвязать {title}?",
    "msg.unlinkDesc": "Личные напоминания в {title} перестанут приходить. Общий чат продолжит работать.",
    "msg.unlinked": "{title} отвязан",
    "msg.linkTitle": "Привязать {title}",
    "msg.linkByUrl": "Откройте бота по ссылке и нажмите «Старт». Ссылка одноразовая и действует до {until}.",
    "msg.linkByCommand": "Найдите бота {title} и отправьте ему в личку команду ниже. Она одноразовая и действует до {until}.",
    "msg.open": "Открыть {title}",
    "msg.alt": "Если ссылка не открывается, отправьте боту в личку эту команду:",
    "msg.copy": "Скопировать",
    "msg.copied": "Команда скопирована",
    "msg.copyFailed": "Не удалось скопировать, выделите команду вручную",
    "msg.wait": "Жду подтверждения от бота…",
    "msg.expired": "Ссылка устарела. Закройте окно и получите новую.",
    "msg.done": "{title} привязан: {account}",

    "account.lead": "Пароль, входы с других устройств и API-токены для интеграций",
    "account.password": "смена пароля",
    "account.passwordLead": "После смены остальные сессии закроются, эта останется.",
    "account.repeat": "Новый пароль ещё раз",
    "account.mismatch": "Новые пароли не совпадают",
    "account.samePassword": "Новый пароль совпадает с текущим",
    "account.changePassword": "Сменить пароль",
    "account.passwordChanged": "Пароль изменён",
    "account.passwordChangedEnded": "Пароль изменён, закрыто: {sessions}",
    "account.admin": "вход администратора",
    "account.adminPassword": "Пароль администратора",
    "account.adminPasswordText": "Задаётся в .env на сервере (ADMIN_PASSWORD), в панели его не поменять. После смены пароля в .env все сессии администратора закрываются.",
    "account.twoFactor": "Двухфакторный вход",
    "account.on": "включён",
    "account.off": "выключен",
    "account.twoFactorOnText": "Кроме пароля при входе нужен шестизначный код из приложения-аутентификатора. Каждый код принимается один раз.",
    "account.twoFactorOffText": "Чтобы включить: выполните на сервере команду ниже, добавьте строку ADMIN_TOTP_SECRET в .env, откройте ссылку otpauth:// или введите секрет в приложении-аутентификаторе и перезапустите сервис. Сессии администратора закроются.",
    "account.sessions": "активные сессии",
    "account.sessionsLead": "Где сейчас выполнен вход в эту учётную запись. Незнакомое устройство завершите и смените пароль.",
    "account.colDevice": "Устройство",
    "account.colCreated": "Вход",
    "account.colSeen": "Активность",
    "account.colExpires": "Действует до",
    "account.current": "эта сессия",
    "account.unknownDevice": "Неизвестное устройство",
    "account.end": "Завершить",
    "account.endOthers": "Завершить все остальные",
    "account.endTitle": "Завершить сессию?",
    "account.endDesc": "«{device}» сразу потеряет доступ, там придётся войти снова.",
    "account.endOthersTitle": "Завершить остальные сессии?",
    "account.endOthersDesc": "Закроются все входы, кроме этого. Пригодится, если вы забыли выйти на чужом устройстве.",
    "account.ended": "Сессия завершена",
    "account.endedOthers": "Закрыто: {sessions}",
    "account.tokens": "API-токены",
    "account.tokensLead": "Для скриптов и интеграций вместо пароля, заголовок Authorization: Bearer ik_… Токен действует с вашими правами, «только чтение» ничего не меняет. Пароль, сессии и токены через токен не поменять.",
    "account.colName": "Название",
    "account.colScope": "Доступ",
    "account.colToken": "Токен",
    "account.colIssued": "Создан",
    "account.colUsed": "Использован",
    "account.neverUsed": "ещё нет",
    "account.forever": "бессрочно",
    "account.expired": "истёк",
    "account.scope.read": "только чтение",
    "account.scope.write": "чтение и запись",
    "account.newToken": "Создать токен",
    "account.tokenNamePlaceholder": "Выгрузка в 1С",
    "account.tokenNameHint": "Чтобы потом понять, где он используется",
    "account.ttl.30": "30 дней",
    "account.ttl.90": "90 дней",
    "account.ttl.365": "1 год",
    "account.ttl.never": "Бессрочно",
    "account.create": "Создать",
    "account.tokenTitle": "Токен «{name}» создан",
    "account.tokenOnce": "Скопируйте токен сейчас: он показывается один раз, на сервере хранится только его хэш.",
    "account.tokenExample": "Пример запроса:",
    "account.tokenCopied": "Скопировано",
    "account.revoke": "Отозвать",
    "account.revokeTitle": "Отозвать токен?",
    "account.revokeDesc": "Всё, что работает с токеном «{name}», сразу потеряет доступ.",
    "account.revoked": "Токен «{name}» отозван",
    "account.tokensEmpty": "Токенов пока нет",
    "account.tokensEmptyText": "Создайте токен, если к API нужен доступ из скрипта или другой системы.",
    "check.tokenName": "Название: укажите, для чего токен",

    "tab.help": "Помощь",
    "help.lead": "Как устроена панель, ответы на частые вопросы и куда писать, если что-то не так",
    "help.overview": "разделы панели",
    "help.open": "Открыть",
    "help.adminOnly": "только администратор",
    "help.about.payments": "Итоги по каждой валюте и все периоды: отметить оплату, исправить дату, приложить чек, выгрузить CSV.",
    "help.about.calendar": "Сроки по дням на любой месяц. Будущие месяцы считаются по правилу повторения.",
    "help.about.budget": "Плановые расходы на год и по месяцам, отдельно по валютам: сколько оплачено и сколько осталось.",
    "help.about.recurring": "Добавить, изменить или прекратить регулярный платёж.",
    "help.about.users": "Создать, переименовать или удалить обычных пользователей и сменить им пароль.",
    "help.about.audit": "Кто входил и что менял: оплаты, платежи, пользователи, отправленные напоминания.",
    "help.about.messengers": "Привяжите Telegram или MAX, и напоминания будут приходить вам лично.",
    "help.about.account": "Сменить пароль, завершить входы на других устройствах, выпустить API-токен для интеграций.",
    "help.about.account.admin": "Двухфакторный вход, входы на других устройствах и API-токены для интеграций.",
    "help.rules": "как считаются сроки",
    "help.rule.reminder": "Напоминание приходит за {days} до срока, по одному разу на каждый период.",
    "help.rule.overdueNotice": "Если оплату так и не отметили, на следующий день после срока придёт одно повторное напоминание.",
    "help.rule.overdue": "Просрочка начинается со следующего дня после срока. Оплата в день срока считается вовремя.",
    "help.rule.periods": "Сроки считаются от первой даты платежа. Если такого числа в месяце нет, срок падает на последний день месяца.",
    "help.rule.currency": "RUB, USD и EUR считаются отдельно, без пересчёта по курсу.",
    "help.rule.timezone": "«Сегодня» считается по часовому поясу {tz}.",
    "help.rule.channels": "Напоминания уходят: {list}.",
    "help.rule.noChannels": "Каналы напоминаний на сервере пока не настроены.",
    "help.channel.telegram": "в Telegram",
    "help.channel.max": "в MAX",
    "help.channel.email": "на почту",
    "help.channel.webhook": "на webhook",
    "help.faq": "частые вопросы",
    "help.q.pay": "Как отметить оплату?",
    "help.a.pay": "Во вкладке «Платежи» нажмите «Отметить оплату» у нужного периода. По умолчанию ставится сегодняшняя дата, её можно поменять. Ещё быстрее — кнопка «✅ Оплачено» прямо в напоминании в Telegram или MAX.",
    "help.q.wrongOverdue": "Оплатили вовремя, а платёж показан просроченным",
    "help.a.wrongOverdue": "Значит, дата оплаты указана позже срока. Нажмите «Изменить дату» и поставьте настоящую: просрочка пересчитается, а срок останется прежним.",
    "help.q.undo": "Отметили оплату по ошибке",
    "help.a.undo": "Нажмите «Отменить» у этого периода: он снова станет неоплаченным, дата оплаты очистится. Другие периоды не изменятся.",
    "help.q.noReminder": "Не пришло напоминание",
    "help.a.noReminder": "Напоминание приходит за {days} до срока и один раз на период. Оплаченные и прекращённые платежи не напоминают. Если всё равно тишина, проверьте, что бот добавлен в чат, и напишите администратору.",
    "help.q.personal": "Как получать напоминания себе в личку?",
    "help.a.personal": "Во вкладке «Мессенджеры» нажмите «Привязать» и откройте ссылку на бота. После этого напоминания будут приходить и вам лично, с той же кнопкой «Оплачено».",
    "help.q.commands": "Какие команды понимает бот?",
    "help.a.commands": "/todo — что оплатить в ближайшие 7 дней и что уже просрочено, /overdue — только просрочка, /help — справка. Списки видны в чате напоминаний и тем, кто привязал мессенджер.",
    "help.q.currency": "Почему суммы в разных валютах не складываются?",
    "help.a.currency": "Так задумано: рубли, доллары и евро считаются отдельно, без пересчёта по курсу, чтобы итоги не зависели от курса на сегодня.",
    "help.q.edit": "Как добавить или изменить платёж?",
    "help.a.edit.admin": "Во вкладке «Регулярные платежи»: форма сверху добавляет платёж, кнопка «Изменить» меняет название, сумму и график. Новая сумма действует для неоплаченных периодов с сегодняшнего дня, прошлые остаются как были.",
    "help.a.edit.user": "Платежи добавляет и меняет администратор. Если сумма или срок изменились, напишите ему.",
    "help.q.stop": "Что будет, если прекратить платёж?",
    "help.a.stop": "Новых периодов и напоминаний не будет, а история оплат сохранится: её видно с флажком «С прекращёнными».",
    "help.q.csv": "Как выгрузить платежи в Excel?",
    "help.a.csv": "Во вкладке «Платежи» нажмите «Скачать CSV». В файл попадут периоды с текущими фильтрами и поиском, Excel откроет его без настройки.",
    "help.q.password": "Забыли пароль",
    "help.a.password.admin": "Пароль администратора задаётся в файле .env на сервере (ADMIN_PASSWORD), через панель его не поменять.",
    "help.a.password.user": "Если помните текущий пароль, смените его во вкладке «Аккаунт». Если забыли, напишите администратору: он задаст новый во вкладке «Пользователи».",
    "help.q.api": "Можно ли работать через API?",
    "help.a.api": "Да, всё, что умеет панель, доступно через REST API. Документация открывается по ссылке «API и Swagger» в боковой панели.",
    "help.contacts": "связаться",
    "help.admin.title": "Администратор",
    "help.admin.text.user": "Вопросы по платежам, суммам и доступу — администратору вашей команды.",
    "help.admin.text.admin": "Вы администратор: платежи, пользователи и доступ в ваших руках.",
    "help.support.title": "Поддержка Invoice Keeper",
    "help.support.text": "Ошибки и пожелания по сервису.",
    "help.support.none": "Контакты поддержки не заданы. Добавьте SUPPORT_TELEGRAM, SUPPORT_EMAIL или SUPPORT_URL в .env.",
    "help.bots.title": "Бот напоминаний",
    "help.bots.text": "Напишите боту /help, чтобы увидеть команды.",
    "help.api.title": "API",
    "help.api.text": "REST API и документация Swagger.",
    "help.api.link": "Открыть документацию",
    "help.security": "безопасность",
    "help.sec.access": "Без входа панель и данные недоступны: каждый запрос к API проверяет сессию на сервере.",
    "help.sec.roles": "Права проверяются на сервере: обычный пользователь не выполнит действия администратора, даже напрямую через API.",
    "help.sec.admin": "Администратор задаётся только в .env на сервере. Через панель или API его не создать, не изменить и не удалить.",
    "help.sec.passwords": "Пароли хранятся только в виде хэша argon2 и никогда не попадают в журнал.",
    "help.sec.sessions": "«Выйти» завершает сессию на сервере. Во вкладке «Аккаунт» видны все входы, любой можно завершить. После смены пароля остальные сессии закрываются.",
    "help.sec.twofactor": "Вход администратора защищается вторым фактором: кодом из приложения-аутентификатора (TOTP). Каждый код принимается один раз.",
    "help.sec.tokens": "API-токены для интеграций хранятся только в виде хэша, бывают только для чтения и отзываются в один клик. Пароль, сессии и токены через них не поменять.",
    "help.sec.bruteforce": "После нескольких неудачных попыток вход с этого адреса временно блокируется.",
    "help.sec.audit.admin": "Входы, неудачные попытки и все изменения записываются во вкладку «Журнал».",
    "help.sec.audit.user": "Входы и изменения записываются в журнал, который видит администратор.",
    "help.sec.receipts": "Чеки принимаются только в PDF, PNG, JPEG и WebP: тип проверяется по содержимому файла, а не по имени.",
    "help.sec.bots": "Кнопку «Оплачено» в Telegram и MAX принимают только от участников чата напоминаний и от пользователей, привязавших мессенджер. Код привязки одноразовый и действует 10 минут.",
    "help.sec.secrets": "Пароль администратора и токены ботов хранятся только в .env на сервере и в панели не показываются.",
    "help.sec.tip": "Не передавайте свой пароль другим и нажимайте «Выйти» на чужом устройстве.",
  },

  en: {
    "app.description": "Reminders for recurring payments: due dates, payments, overdue",

    "common.cancel": "Cancel",
    "common.save": "Save",
    "common.close": "Close",
    "common.delete": "Delete",
    "common.edit": "Edit",
    "common.loading": "Loading…",
    "common.reset": "Reset",
    "common.today": "Today",
    "common.showMore": "Show more",
    "common.nothingToChange": "Nothing to change",

    "error.network": "No connection to the server",
    "error.server": "Server error ({status})",
    "error.load": "Could not load the data",

    "field.login": "Login",
    "field.password": "Password",
    "field.name": "Name",
    "field.amount": "Amount",
    "field.currency": "Currency",
    "field.period": "Frequency",
    "field.first_due_date": "Next due date",
    "field.status": "Status",
    "field.paid_at": "Payment date",
    "field.url": "Link",
    "field.file": "File",
    "field.title": "Title",
    "field.q": "Search",
    "field.otp": "Authenticator code",
    "field.current_password": "Current password",
    "field.new_password": "New password",
    "field.scope": "Access",
    "field.expires_in_days": "Lifetime",
    "field.pay_url": "Payment link",
    "field.category": "Category",
    "rec.categoryPlaceholder": "rent, IT, subscriptions",
    "payments.allCategories": "All categories",
    "payments.noCategory": "No category",
    "field.assignee_id": "Responsible",
    "rec.noAssignee": "— not assigned —",
    "payments.mine": "Only mine",
    "payments.allAssignees": "Anyone responsible",
    "payments.noAssignee": "No one responsible",
    "budget.byCategory": "by category",
    "budget.category": "Category",
    "field.pay_details": "Payment details",
    "rec.payUrlPlaceholder": "https://…",
    "rec.payDetailsPlaceholder": "contract, invoice, tax ID",
    "rec.payLink": "payment link ↗",
    "act.pay": "Pay",
    "check.payUrl": "Payment link: start with http:// or https://",

    "valid.string_too_short": "too short",
    "valid.string_too_long": "too long",
    "valid.string_pattern_mismatch": "invalid characters",
    "valid.greater_than": "must be greater than zero",
    "valid.decimal_max_places": "at most two decimal places",
    "valid.decimal_parsing": "not a valid number",
    "valid.decimal_type": "not a valid number",
    "valid.decimal_max_digits": "the number is too large",
    "valid.extra_forbidden": "field is not supported",
    "valid.missing": "required field",
    "valid.date_parsing": "not a valid date",
    "valid.date_from_datetime_parsing": "not a valid date",
    "valid.enum": "value is not allowed",

    "check.amount": "Amount: a positive number with at most two decimal places",
    "check.login": "Login: 3–64 characters, Latin letters, digits and . _ @ -",
    "check.password": "Password: 8 to 128 characters",
    "check.name": "Name: enter the payment name",
    "check.firstDue": "Next due date: pick a date",
    "check.paidAt": "Pick the payment date",
    "check.newSchedule": "New schedule: pick the next due date",
    "check.url": "Link: the address must start with http:// or https://",
    "check.file": "File: choose a file",
    "check.credentials": "Enter your login and password",

    "pw.show": "Show password",
    "pw.hide": "Hide password",

    "auth.title": "Sign in",
    "auth.lead": "Payments, due dates and reminders in one place.",
    "auth.submit": "Sign in",
    "auth.invalid": "Wrong login or password",
    "auth.expired": "Your session has ended, please sign in again",
    "auth.otpNeeded": "Enter the six-digit code from your authenticator app",
    "auth.otpHint": "Google Authenticator, Aegis or any other TOTP app",
    "auth.promoTitle": "payments under control",
    "auth.point1": "A reminder 3 days before the due date in Telegram, MAX and by email",
    "auth.point2": "Overdue is calculated automatically, payment history is never lost",
    "auth.point3": "RUB, USD and EUR with separate totals for each currency",

    "shell.logout": "Sign out",
    "shell.password": "Change password",
    "pass.title": "Change password",
    "pass.desc": "Your other sessions will be signed out, this one stays open.",
    "pass.current": "Current password",
    "pass.new": "New password",
    "pass.repeat": "Repeat the new password",
    "pass.mismatch": "The new passwords do not match",
    "pass.done": "Password changed",
    "shell.today": "today",
    "shell.addPayment": "Add payment",
    "shell.api": "API & Swagger",
    "shell.menu": "Menu",
    "shell.language": "Language",
    "theme.title": "Color theme",
    "theme.current": "Theme: {mode}",
    "theme.system": "System",
    "theme.light": "Light",
    "theme.dark": "Dark",
    "role.admin": "admin",
    "role.user": "user",

    "tab.payments": "Payments",
    "tab.calendar": "Calendar",
    "tab.budget": "Budget",
    "tab.recurring": "Recurring payments",
    "tab.users": "Users",
    "tab.audit": "Activity log",
    "tab.messengers": "Messengers",
    "tab.account": "Account",

    "currency.RUB": "Russian ruble",
    "currency.USD": "US dollar",
    "currency.EUR": "Euro",

    "status.paid": "Paid",
    "status.late": "Paid late",
    "status.lateDays": "Paid late ({days})",
    "status.overdue": "Overdue {days}",
    "status.soon": "Due soon",
    "status.unpaid": "Unpaid",
    "status.planned": "Planned",

    "due.overdueBy": "overdue by {days}",
    "due.today": "today",
    "due.tomorrow": "tomorrow",
    "due.in": "in {days}",

    "payments.lead": "What to pay and when, what is already paid and what is overdue",
    "payments.summary": "Totals by currency",
    "payments.list": "payment periods",
    "payments.all": "All",
    "payments.unpaid": "Unpaid",
    "payments.overdue": "Overdue",
    "payments.paid": "Paid",
    "payments.allPeriods": "All periods",
    "payments.thisMonth": "This month",
    "payments.allCurrencies": "All currencies",
    "payments.withDeleted": "Include stopped",
    "payments.onDate": "Totals as of",
    "payments.shown": "Shown: {n}",
    "payments.search": "Search by name",
    "payments.csv": "Download CSV",
    "payments.csvHint": "Export with the current filters, opens in Excel",
    "payments.empty": "No payments match these filters",
    "payments.emptyAdmin": "Add your first payment in “Recurring payments”.",
    "payments.emptyUser": "The administrator has not added any payments yet.",
    "payments.stopped": "Payment stopped",
    "col.payment": "Payment",
    "col.amount": "Amount",
    "col.due": "Due",
    "col.status": "Status",
    "col.paidAt": "Paid on",
    "act.markPaid": "Mark as paid",
    "act.changeDate": "Change date",
    "act.undo": "Undo",

    "sum.onDate": "as of {date}",
    "sum.toPay": "to pay · {payments}",
    "sum.allClosed": "to pay · all settled",
    "sum.overdue": "Overdue",
    "sum.paid": "Paid",
    "sum.due": "Awaiting",
    "sum.left": "Left",
    "sum.sticker": "overdue!",
    "sum.open": "Show {currency} periods",

    "pay.title": "Mark as paid",
    "pay.titleEdit": "Change payment date",
    "pay.desc": "{name}, due {date}, {amount}",
    "pay.confirm": "Paid",
    "pay.field": "Actual payment date",
    "pay.hint": "If you paid on another day, enter the real date: overdue is counted from it",
    "pay.done": "Payment marked",
    "pay.doneEdit": "Payment date updated",
    "unpay.title": "Undo the payment?",
    "unpay.desc": "The “{name}” period due {date} becomes unpaid again and its payment date is cleared.",
    "unpay.confirm": "Undo payment",
    "unpay.done": "Payment undone",

    "rc.button": "Receipts",
    "rc.buttonCount": "Receipts ({n})",
    "rc.title": "Receipts and links",
    "rc.desc": "{name}, due {date}",
    "rc.kind.file": "file",
    "rc.kind.link": "link",
    "rc.deleted": "Attachment deleted",
    "rc.empty": "Nothing attached yet",
    "rc.linkTitle": "Attach a link",
    "rc.url": "URL",
    "rc.titleOptional": "Title (optional)",
    "rc.linkPlaceholder": "Bank receipt",
    "rc.addLink": "Add link",
    "rc.linkAdded": "Link attached",
    "rc.fileTitle": "Upload a receipt",
    "rc.fileHint": "PDF, PNG, JPEG or WebP, up to 5 MB",
    "rc.upload": "Upload receipt",
    "rc.uploaded": "Receipt uploaded",
    "rc.stopped": "The payment is stopped: attachments can be viewed but not added",
    "size.mb": "{n} MB",
    "size.kb": "{n} KB",

    "period.monthly": "Monthly",
    "period.quarterly": "Quarterly",
    "period.yearly": "Yearly",
    "hint.yearly": "every year on {day}",
    "hint.yearlyLeap": "every year on {day}, on 28 February in non-leap years",
    "hint.quarterly": "every 3 months, ",
    "hint.day": "on day {d}",
    "hint.short": ", on the last day in shorter months",

    "rec.lead": "A payment repeats monthly, quarterly or yearly; a reminder arrives 3 days before the due date",
    "rec.list": "all payments",
    "rec.colPeriod": "Frequency",
    "rec.colNext": "Next unpaid due date",
    "rec.colNextShort": "Next due",
    "rec.firstDue": "first due {date}",
    "rec.stop": "Stop",
    "rec.pause": "Pause",
    "rec.resume": "Resume",
    "rec.pauseTitle": "Pause the payment?",
    "rec.pauseDesc": "“{name}”: no new periods or reminders while paused. Unpaid due dates within the pause are removed; payments and past debts stay.",
    "rec.pauseUntil": "Until",
    "rec.pauseHint": "empty — until you resume; that day itself is no longer paused",
    "rec.paused": "paused",
    "rec.pausedUntil": "paused until {date}",
    "rec.pausedDone": "“{name}” is paused",
    "rec.resumed": "“{name}” is active again",
    "audit.until": "until {date}",
    "rec.empty": "No recurring payments yet",
    "rec.emptyText": "Add rent, a subscription or a server bill with the form above.",
    "rec.new": "New recurring payment",
    "rec.namePlaceholder": "Office rent",
    "rec.add": "Add",
    "rec.added": "Payment “{name}” added",
    "rec.editTitle": "Edit payment",
    "rec.editDesc": "The new amount applies to unpaid periods from today; paid and past periods keep theirs. The currency ({currency}) does not change.",
    "rec.amountIn": "Amount, {currency}",
    "rec.newFirstDue": "Next due date on the new schedule",
    "rec.newFirstDueHint": "only if the schedule changes: unpaid future dates of the old schedule are removed, the history stays",
    "rec.updated": "Payment “{name}” updated",
    "rec.stopTitle": "Stop the payment?",
    "rec.stopDesc": "“{name}” will no longer create periods or reminders. The payment history is kept.",
    "rec.stopped": "Payment “{name}” stopped",

    "users.lead": "Regular accounts. The administrator is set in .env and is not listed here",
    "users.list": "accounts",
    "users.colCreated": "Created",
    "users.colMessengers": "Messengers",
    "users.empty": "No regular users yet",
    "users.emptyText": "Create an account with the form above so your team can mark payments.",
    "users.new": "New user",
    "users.passwordPlaceholder": "at least 8 characters",
    "users.create": "Create",
    "users.created": "User “{login}” created",
    "users.editTitle": "Edit user",
    "users.newPassword": "New password",
    "users.newPasswordHint": "leave empty to keep it; changing the password ends the user's sessions",
    "users.updated": "User updated",
    "users.deleteTitle": "Delete the user?",
    "users.deleteDesc": "“{login}” loses access immediately and their sessions end.",
    "users.deleted": "User “{login}” deleted",

    "cal.title": "Payment calendar",
    "cal.lead": "Due dates for this month and beyond: future periods are calculated from the repeat rule",
    "cal.prev": "Previous month",
    "cal.next": "Next month",
    "cal.none": "No payments this month",
    "cal.noneDay": "No payments on this day",
    "cal.dayLabel": "{date}, payments: {n}",
    "cal.paidShare": "Share paid",
    "cal.paidLeft": "paid {paid} · left {left}",
    "cal.paidOn": "paid {date}",
    "cal.stopped": "payment stopped",

    "budget.lead": "Planned spending for each currency separately, without conversion. Click a month to open it in the calendar",
    "budget.year": "{year}",
    "budget.prev": "Previous year",
    "budget.next": "Next year",
    "budget.plan": "plan for the year",
    "budget.none": "no payments",
    "budget.month": "Month",
    "budget.byMonth": "by month",
    "budget.paidAll": "paid",
    "budget.paidPart": "paid {amount}",
    "budget.empty": "No payments this year",
    "budget.emptyText": "The budget appears once the administrator adds recurring payments.",

    "audit.lead": "Who did what: sign-ins, payments (including from Telegram and MAX), recurring payments, users. Passwords never get here",
    "audit.colTime": "Time",
    "audit.colWho": "Who",
    "audit.colAction": "Action",
    "audit.colDetails": "Details",
    "audit.colIp": "IP address",
    "audit.empty": "No entries",
    "audit.emptyText": "Sign-ins, payments and changes to payments and users will appear here.",
    "audit.due": "due {date}",
    "audit.paidOn": "paid {date}",
    "audit.paidChanged": "{name}, {due}: payment date {before} → {after}",
    "audit.created": "{name}, {amount}, {period}first due {date}",
    "audit.amountChanged": "amount {before} → {after}",
    "audit.scheduleChanged": "schedule: {period}, next due {date}",
    "audit.passwordChanged": "password changed",
    "audit.channel": "{name}, {due}, channel: {channel}",
    "audit.failed": "sign-in attempt with this login",
    "audit.locked": "sign-in locked for {minutes} min",
    "audit.otpFailed": "wrong or reused second-factor code",
    "audit.sessionsClosed": "sessions closed: {n}",
    "audit.token": "“{name}”, {scope}",
    "audit.f.all": "All",
    "audit.f.auth": "Sign-ins",
    "audit.f.occurrence": "Payments made",
    "audit.f.payment": "Recurring",
    "audit.f.user": "Users",
    "audit.f.reminder": "Reminders",
    "audit.f.messenger": "Messengers",
    "audit.f.token": "API tokens",
    "audit.p.all": "All time",
    "audit.p.1": "Today",
    "audit.p.7": "7 days",
    "audit.p.30": "30 days",
    "action.auth.login": "Signed in",
    "action.auth.login_failed": "Failed sign-in",
    "action.auth.login_locked": "Sign-in locked",
    "action.auth.logout": "Signed out",
    "action.auth.otp_failed": "Wrong second-factor code",
    "action.auth.password_changed": "Password changed",
    "action.auth.password_failed": "Wrong current password",
    "action.auth.session_ended": "Session ended",
    "action.auth.sessions_ended": "Other sessions ended",
    "action.token.create": "API token created",
    "action.token.revoke": "API token revoked",
    "action.payment.create": "Payment added",
    "action.payment.update": "Payment edited",
    "action.payment.delete": "Payment stopped",
    "action.payment.pause": "Payment paused",
    "action.payment.resume": "Payment resumed",
    "action.occurrence.paid": "Payment marked",
    "action.occurrence.unpaid": "Payment undone",
    "action.occurrence.paid_at_changed": "Payment date corrected",
    "action.user.create": "User created",
    "action.user.update": "User edited",
    "action.user.delete": "User deleted",
    "action.receipt.add": "Receipt or link added",
    "action.receipt.delete": "Receipt or link deleted",
    "action.reminder.sent": "Reminder sent",
    "action.reminder.overdue_sent": "Overdue reminder sent",
    "action.messenger.link": "Messenger linked",
    "action.messenger.unlink": "Messenger unlinked",
    "actor.admin": "admin",
    "actor.user": "user",
    "actor.telegram": "Telegram",
    "actor.max": "MAX",
    "actor.system": "system",
    "actor.anonymous": "anonymous",

    "msg.lead": "Link Telegram or MAX to get payment reminders personally, with a “Paid” button. A payment marked in the messenger is recorded under your name",
    "msg.notConfigured": "This messenger's bot is not configured on the server",
    "msg.linkedTo": "Linked: ",
    "msg.since": " · since {date}",
    "msg.notLinkedText": "Not linked: reminders go to the shared chat only",
    "msg.linked": "linked",
    "msg.notLinked": "not linked",
    "msg.link": "Link",
    "msg.linkOther": "Link another account",
    "msg.unlink": "Unlink",
    "msg.unlinkTitle": "Unlink {title}?",
    "msg.unlinkDesc": "Personal reminders in {title} will stop. The shared chat keeps working.",
    "msg.unlinked": "{title} unlinked",
    "msg.linkTitle": "Link {title}",
    "msg.linkByUrl": "Open the bot via the link and press “Start”. The link is single-use and valid until {until}.",
    "msg.linkByCommand": "Find the {title} bot and send it the command below in a private chat. It is single-use and valid until {until}.",
    "msg.open": "Open {title}",
    "msg.alt": "If the link does not open, send this command to the bot in a private chat:",
    "msg.copy": "Copy",
    "msg.copied": "Command copied",
    "msg.copyFailed": "Could not copy, select the command manually",
    "msg.wait": "Waiting for the bot to confirm…",
    "msg.expired": "The link has expired. Close this window and get a new one.",
    "msg.done": "{title} linked: {account}",

    "account.lead": "Your password, sign-ins on other devices and API tokens for integrations",
    "account.password": "change password",
    "account.passwordLead": "Other sessions are closed after the change, this one stays.",
    "account.repeat": "New password again",
    "account.mismatch": "The new passwords do not match",
    "account.samePassword": "The new password is the same as the current one",
    "account.changePassword": "Change password",
    "account.passwordChanged": "Password changed",
    "account.passwordChangedEnded": "Password changed, closed: {sessions}",
    "account.admin": "administrator sign-in",
    "account.adminPassword": "Administrator password",
    "account.adminPasswordText": "Set in .env on the server (ADMIN_PASSWORD) and cannot be changed in the panel. Changing it in .env closes every administrator session.",
    "account.twoFactor": "Two-factor sign-in",
    "account.on": "on",
    "account.off": "off",
    "account.twoFactorOnText": "Signing in needs a six-digit code from an authenticator app besides the password. Each code is accepted once.",
    "account.twoFactorOffText": "To turn it on: run the command below on the server, add the ADMIN_TOTP_SECRET line to .env, open the otpauth:// link or type the secret into your authenticator app and restart the service. Administrator sessions will be closed.",
    "account.sessions": "active sessions",
    "account.sessionsLead": "Where this account is signed in right now. End any device you do not recognise and change the password.",
    "account.colDevice": "Device",
    "account.colCreated": "Signed in",
    "account.colSeen": "Last active",
    "account.colExpires": "Valid until",
    "account.current": "this session",
    "account.unknownDevice": "Unknown device",
    "account.end": "End",
    "account.endOthers": "End all other sessions",
    "account.endTitle": "End the session?",
    "account.endDesc": "“{device}” loses access right away and will have to sign in again.",
    "account.endOthersTitle": "End the other sessions?",
    "account.endOthersDesc": "Every sign-in except this one is closed. Handy if you forgot to sign out on someone else's device.",
    "account.ended": "Session ended",
    "account.endedOthers": "Closed: {sessions}",
    "account.tokens": "API tokens",
    "account.tokensLead": "For scripts and integrations instead of a password, header Authorization: Bearer ik_… A token acts with your rights, a read-only one changes nothing. A token cannot change the password, sessions or tokens.",
    "account.colName": "Name",
    "account.colScope": "Access",
    "account.colToken": "Token",
    "account.colIssued": "Created",
    "account.colUsed": "Last used",
    "account.neverUsed": "not yet",
    "account.forever": "no expiry",
    "account.expired": "expired",
    "account.scope.read": "read only",
    "account.scope.write": "read and write",
    "account.newToken": "Create token",
    "account.tokenNamePlaceholder": "Accounting export",
    "account.tokenNameHint": "So you know later where it is used",
    "account.ttl.30": "30 days",
    "account.ttl.90": "90 days",
    "account.ttl.365": "1 year",
    "account.ttl.never": "No expiry",
    "account.create": "Create",
    "account.tokenTitle": "Token “{name}” created",
    "account.tokenOnce": "Copy the token now: it is shown only once, the server keeps just its hash.",
    "account.tokenExample": "Example request:",
    "account.tokenCopied": "Copied",
    "account.revoke": "Revoke",
    "account.revokeTitle": "Revoke the token?",
    "account.revokeDesc": "Everything that uses the token “{name}” loses access right away.",
    "account.revoked": "Token “{name}” revoked",
    "account.tokensEmpty": "No tokens yet",
    "account.tokensEmptyText": "Create a token when a script or another system needs access to the API.",
    "check.tokenName": "Name: say what the token is for",

    "tab.help": "Help",
    "help.lead": "How the panel works, answers to common questions and whom to contact if something is wrong",
    "help.overview": "panel sections",
    "help.open": "Open",
    "help.adminOnly": "admin only",
    "help.about.payments": "Totals per currency and every period: mark as paid, fix the date, attach a receipt, download CSV.",
    "help.about.calendar": "Due dates by day for any month. Future months follow the repeat rule.",
    "help.about.budget": "Planned spending for the year and by month, per currency: how much is paid and how much is left.",
    "help.about.recurring": "Add, edit or stop a recurring payment.",
    "help.about.users": "Create, rename or delete regular users and change their passwords.",
    "help.about.audit": "Who signed in and what changed: payments, users, sent reminders.",
    "help.about.messengers": "Link Telegram or MAX to get reminders personally.",
    "help.about.account": "Change your password, end sign-ins on other devices, issue an API token for integrations.",
    "help.about.account.admin": "Two-factor sign-in, sign-ins on other devices and API tokens for integrations.",
    "help.rules": "how due dates work",
    "help.rule.reminder": "A reminder comes {days} before the due date, once per period.",
    "help.rule.overdueNotice": "If the payment is still not marked, one more reminder comes the day after the due date.",
    "help.rule.overdue": "A payment is overdue from the day after the due date. Paying on the due date is on time.",
    "help.rule.periods": "Due dates follow the first payment date. If a month has no such day, the last day of the month is used.",
    "help.rule.currency": "RUB, USD and EUR are counted separately, without exchange rates.",
    "help.rule.timezone": "“Today” follows the {tz} time zone.",
    "help.rule.channels": "Reminders go {list}.",
    "help.rule.noChannels": "No reminder channels are configured on the server yet.",
    "help.channel.telegram": "to Telegram",
    "help.channel.max": "to MAX",
    "help.channel.email": "by email",
    "help.channel.webhook": "to a webhook",
    "help.faq": "faq",
    "help.q.pay": "How do I mark a payment as paid?",
    "help.a.pay": "On the Payments tab, click “Mark as paid” next to the period. Today's date is used by default and you can change it. Even faster: the “✅ Paid” button right in the Telegram or MAX reminder.",
    "help.q.wrongOverdue": "We paid on time, but the payment shows as overdue",
    "help.a.wrongOverdue": "The payment date is later than the due date. Click “Change date” and set the real one: the overdue status is recalculated, the due date stays the same.",
    "help.q.undo": "I marked a payment by mistake",
    "help.a.undo": "Click “Undo” on that period: it becomes unpaid again and the payment date is cleared. Other periods are not affected.",
    "help.q.noReminder": "A reminder did not arrive",
    "help.a.noReminder": "A reminder comes {days} before the due date, once per period. Paid and stopped payments get no reminders. If it is still silent, check that the bot is in the chat and contact the administrator.",
    "help.q.personal": "How do I get reminders in a private chat?",
    "help.a.personal": "On the Messengers tab, click “Link” and open the bot link. From then on reminders also come to you personally, with the same “Paid” button.",
    "help.q.commands": "Which commands does the bot understand?",
    "help.a.commands": "/todo — what to pay in the next 7 days and what is overdue, /overdue — overdue only, /help — help. Lists are shown in the reminder chat and to those who linked a messenger.",
    "help.q.currency": "Why are amounts in different currencies not added up?",
    "help.a.currency": "By design: rubles, dollars and euros are counted separately, without exchange rates, so totals do not depend on today's rate.",
    "help.q.edit": "How do I add or change a payment?",
    "help.a.edit.admin": "On the Recurring payments tab: the form at the top adds a payment, “Edit” changes the name, amount and schedule. A new amount applies to unpaid periods from today on, past ones stay as they were.",
    "help.a.edit.user": "Payments are added and changed by the administrator. If an amount or a date changed, let them know.",
    "help.q.stop": "What happens when a payment is stopped?",
    "help.a.stop": "No new periods or reminders, but the payment history stays: turn on “Include stopped” to see it.",
    "help.q.csv": "How do I export payments to Excel?",
    "help.a.csv": "On the Payments tab, click “Download CSV”. The file contains the periods matching the current filters and search, and Excel opens it as is.",
    "help.q.password": "I forgot my password",
    "help.a.password.admin": "The administrator password is set in the .env file on the server (ADMIN_PASSWORD); it cannot be changed in the panel.",
    "help.a.password.user": "If you remember the current password, change it on the Account tab. If you forgot it, ask the administrator to set a new one on the Users tab.",
    "help.q.api": "Is there an API?",
    "help.a.api": "Yes, everything the panel does is available via the REST API. The docs open from “API & Swagger” in the sidebar.",
    "help.contacts": "contacts",
    "help.admin.title": "Administrator",
    "help.admin.text.user": "Questions about payments, amounts and access go to your team's administrator.",
    "help.admin.text.admin": "You are the administrator: payments, users and access are up to you.",
    "help.support.title": "Invoice Keeper support",
    "help.support.text": "Bugs and wishes about the service.",
    "help.support.none": "No support contacts are set. Add SUPPORT_TELEGRAM, SUPPORT_EMAIL or SUPPORT_URL to .env.",
    "help.bots.title": "Reminder bot",
    "help.bots.text": "Send /help to the bot to see its commands.",
    "help.api.title": "API",
    "help.api.text": "REST API and Swagger docs.",
    "help.api.link": "Open the docs",
    "help.security": "security",
    "help.sec.access": "Without signing in, the panel and data are unavailable: every API request checks the session on the server.",
    "help.sec.roles": "Permissions are checked on the server: a regular user cannot perform admin actions, even directly through the API.",
    "help.sec.admin": "The administrator is defined only in .env on the server. It cannot be created, changed or deleted through the panel or the API.",
    "help.sec.passwords": "Passwords are stored only as argon2 hashes and never get into the log.",
    "help.sec.sessions": "“Sign out” ends the session on the server. The Account tab lists every sign-in, and any of them can be ended. Changing the password closes the other sessions.",
    "help.sec.twofactor": "The administrator sign-in is protected by a second factor: a code from an authenticator app (TOTP). Each code is accepted once.",
    "help.sec.tokens": "API tokens for integrations are stored only as a hash, can be read-only and are revoked in one click. They cannot change the password, sessions or tokens.",
    "help.sec.bruteforce": "After several failed attempts, signing in from that address is blocked for a while.",
    "help.sec.audit.admin": "Sign-ins, failed attempts and every change are recorded on the Activity log tab.",
    "help.sec.audit.user": "Sign-ins and changes are recorded in a log that the administrator can see.",
    "help.sec.receipts": "Receipts are accepted only as PDF, PNG, JPEG and WebP: the type is checked by the file contents, not its name.",
    "help.sec.bots": "The “Paid” button in Telegram and MAX is accepted only from members of the reminder chat and from users who linked the messenger. A link code works once and expires in 10 minutes.",
    "help.sec.secrets": "The administrator password and bot tokens live only in .env on the server and are never shown in the panel.",
    "help.sec.tip": "Do not share your password and sign out on devices that are not yours.",
  },
};

// Склонения: формы подбираются по Intl.PluralRules выбранного языка
const PLURALS = {
  ru: {
    day: { one: "день", few: "дня", many: "дней", other: "дня" },
    payment: { one: "платёж", few: "платежа", many: "платежей", other: "платежа" },
    session: { one: "сессия", few: "сессии", many: "сессий", other: "сессии" },
  },
  en: {
    day: { one: "day", other: "days" },
    payment: { one: "payment", other: "payments" },
    session: { one: "session", other: "sessions" },
  },
};

// Сервер отвечает по-русски; в английском интерфейсе переводим известные ответы, остальное показываем как есть
const SERVER_EN = {
  "Аккаунт не привязан": "The account is not linked",
  "Текущий пароль неверный": "The current password is incorrect",
  "Новый пароль совпадает с текущим": "The new password is the same as the current one",
  "Пароль администратора задаётся в .env, через панель его не поменять": "The administrator password is set in .env and cannot be changed here",
  "Бот этого мессенджера не настроен на сервере": "This messenger's bot is not configured on the server",
  "Не найдено": "Not found",
  "Неверный логин или пароль": "Wrong login or password",
  "Нужно передать login или password": "Pass login or password",
  "Нужно передать хотя бы одно поле": "Pass at least one field",
  "Платёж не найден": "Payment not found",
  "Пользователь не найден": "User not found",
  "Регулярный платёж не найден": "Recurring payment not found",
  "Регулярный платёж прекращён, период изменить нельзя": "The recurring payment is stopped, the period cannot be changed",
  "Только для администратора": "Administrators only",
  "Требуется авторизация": "Sign-in required",
  "Удалить может администратор или автор вложения": "Only an administrator or the author of the attachment can delete it",
  "Ссылка: нужен адрес, начинающийся с http:// или https://": "Link: the address must start with http:// or https://",
  "Ссылка слишком длинная (до 2000 символов)": "The link is too long (up to 2000 characters)",
  "Файл пустой": "The file is empty",
  "Допустимы только PDF, PNG, JPEG и WebP": "Only PDF, PNG, JPEG and WebP are allowed",
  "Новый график: укажите дату ближайшей оплаты": "New schedule: pick the next due date",
  "Дата ближайшей оплаты по новому графику не может быть в прошлом": "The next due date on the new schedule cannot be in the past",
  "Этот логин зарезервирован": "This login is reserved",
  "Пользователь с таким логином уже есть": "A user with this login already exists",
  "Учётная запись администратора не управляется через панель": "The administrator account is not managed in the panel",
  "Нужно передать status или paid_at": "Pass status or paid_at",
  "Фактическая дата оплаты не может быть в будущем": "The actual payment date cannot be in the future",
  "Период не оплачен: сначала отметьте оплату (status=paid)": "The period is unpaid: mark it as paid first (status=paid)",
  "Для неоплаченного периода дата оплаты не указывается": "An unpaid period has no payment date",
  "Нельзя очистить дату оплаты у оплаченного периода: отмените оплату": "The payment date of a paid period cannot be cleared: undo the payment",
  "Введите код из приложения-аутентификатора": "Enter the code from your authenticator app",
  "Неверный или уже использованный код": "The code is wrong or has already been used",
  "Неверный текущий пароль": "The current password is wrong",
  "Новый пароль совпадает с текущим": "The new password is the same as the current one",
  "Пароль администратора задаётся в .env (ADMIN_PASSWORD)": "The administrator password is set in .env (ADMIN_PASSWORD)",
  "Это текущая сессия: чтобы её завершить, выйдите из панели": "This is the current session: sign out to end it",
  "Сессия не найдена": "Session not found",
  "Токен не найден": "Token not found",
  "API-токен только для чтения": "The API token is read-only",
  "Нужен вход по паролю, API-токен здесь не подходит": "Sign in with a password: an API token does not work here",
};

const SERVER_EN_PATTERNS = [
  [/^Не больше (\d+) токенов: отзовите ненужные$/, "At most $1 tokens: revoke the ones you do not need"],
  [/^Слишком много неудачных попыток входа\. Попробуйте через (\d+) мин\.$/, "Too many failed sign-in attempts. Try again in $1 min."],
  [/^Файл больше (\d+) МБ$/, "The file is larger than $1 MB"],
  [/^К одному периоду можно прикрепить не больше (\d+) чеков и ссылок$/, "A period can have at most $1 receipts and links"],
];

function savedLang() {
  try {
    return localStorage.getItem(LANG_KEY);
  } catch {
    return null;
  }
}

function initialLang() {
  const saved = savedLang();
  if (saved && I18N[saved]) return saved;
  return String(navigator.language || "").toLowerCase().startsWith("en") ? "en" : "ru";
}

let lang = initialLang();

const locale = () => (LANGS.find((l) => l.id === lang) || LANGS[0]).locale;

function t(key, vars = {}) {
  const text = I18N[lang][key] ?? I18N.ru[key];
  if (text === undefined) return key;
  return text.replace(/\{(\w+)\}/g, (match, name) => (name in vars ? String(vars[name]) : match));
}

function has(key) {
  return key in I18N[lang] || key in I18N.ru;
}

function plural(n, key) {
  const forms = PLURALS[lang][key];
  return `${n} ${forms[new Intl.PluralRules(locale()).select(n)] || forms.other}`;
}

function serverText(text) {
  if (lang === "ru" || typeof text !== "string") return text;
  if (SERVER_EN[text]) return SERVER_EN[text];
  for (const [pattern, out] of SERVER_EN_PATTERNS) {
    const match = text.match(pattern);
    if (match) return out.replace(/\$(\d)/g, (_, i) => match[Number(i)]);
  }
  return text;
}

// ---------- DOM ----------

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.className = value;
    else if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2), value);
    else if (value === true) el.setAttribute(key, "");
    else el.setAttribute(key, value);
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

const app = () => document.getElementById("app");

const SVG_NS = "http://www.w3.org/2000/svg";

function svg(tag, attrs = {}, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, value);
  el.append(...children);
  return el;
}

// Линейные иконки 24×24 в духе иконок кабинета; строка — path, объект — circle или rect
const ICONS = {
  payments: ["M5 3h14v18l-3-2-2 2-2-2-2 2-2-2-3 2Z", "M9 8h6", "M9 12h6", "M9 16h3"],
  calendar: [{ rect: [3, 4, 18, 18, 2] }, "M16 2v4", "M8 2v4", "M3 10h18"],
  budget: ["M21.2 15.9A10 10 0 1 1 8 2.8", "M22 12A10 10 0 0 0 12 2v10Z"],
  recurring: ["m17 2 4 4-4 4", "M3 11v-1a4 4 0 0 1 4-4h14", "m7 22-4-4 4-4", "M21 13v1a4 4 0 0 1-4 4H3"],
  users: ["M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2", { circle: [9, 7, 4] }, "M22 21v-2a4 4 0 0 0-3-3.87", "M16 3.13a4 4 0 0 1 0 7.75"],
  audit: ["M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z", "M14 2v5h5", "M16 13H8", "M16 17H8", "M10 9H8"],
  messengers: ["M7.9 20A9 9 0 1 0 4 16.1L2 22Z"],
  logout: ["M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4", "m16 17 5-5-5-5", "M21 12H9"],
  plus: ["M5 12h14", "M12 5v14"],
  chevronRight: ["m9 18 6-6-6-6"],
  chevronLeft: ["m15 18-6-6 6-6"],
  menu: ["M4 6h16", "M4 12h16", "M4 18h16"],
  globe: [{ circle: [12, 12, 10] }, "M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20", "M2 12h20"],
  book: ["m19 21-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2Z"],
  check: ["M20 6 9 17l-5-5"],
  download: ["M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4", "m7 10 5 5 5-5", "M12 15V3"],
  sun: [{ circle: [12, 12, 4] }, "M12 2v2", "M12 20v2", "m4.93 4.93 1.41 1.41", "m17.66 17.66 1.41 1.41", "M2 12h2", "M20 12h2", "m6.34 17.66-1.41 1.41", "m19.07 4.93-1.41 1.41"],
  moon: ["M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"],
  monitor: [{ rect: [2, 3, 20, 14, 2] }, "M8 21h8", "M12 17v4"],
  key: [{ circle: [7.5, 15.5, 5.5] }, "m21 2-9.6 9.6", "m15.5 7.5 3 3L22 7l-3-3"],
  help: [{ circle: [12, 12, 10] }, "M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3", "M12 17h.01"],
  account: ["M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z", "m9 12 2 2 4-4"],
};

function icon(name, extra = "") {
  const parts = (ICONS[name] || []).map((part) => {
    if (typeof part === "string") return svg("path", { d: part });
    if (part.circle) {
      const [cx, cy, r] = part.circle;
      return svg("circle", { cx, cy, r });
    }
    const [x, y, width, height, rx] = part.rect;
    return svg("rect", { x, y, width, height, rx });
  });
  return svg("svg", { class: extra ? `ic ${extra}` : "ic", viewBox: "0 0 24 24", "aria-hidden": "true", focusable: "false" }, ...parts);
}

// Флаги в кружке, как у выбора языка в кабинете: свои SVG, эмодзи-флаги Windows не рисует
function flag(id) {
  if (id === "ru") {
    return svg(
      "svg",
      { class: "flag", viewBox: "0 0 9 6", preserveAspectRatio: "xMidYMid slice", "aria-hidden": "true" },
      svg("rect", { width: 9, height: 2, fill: "#ffffff" }),
      svg("rect", { y: 2, width: 9, height: 2, fill: "#0039a6" }),
      svg("rect", { y: 4, width: 9, height: 2, fill: "#d52b1e" }),
    );
  }
  return svg(
    "svg",
    { class: "flag", viewBox: "0 0 60 30", preserveAspectRatio: "xMidYMid slice", "aria-hidden": "true" },
    svg("rect", { width: 60, height: 30, fill: "#012169" }),
    svg("path", { d: "M0 0 60 30M60 0 0 30", stroke: "#ffffff", "stroke-width": 6 }),
    svg("path", { d: "M0 0 60 30M60 0 0 30", stroke: "#c8102e", "stroke-width": 2 }),
    svg("path", { d: "M30 0v30M0 15h60", stroke: "#ffffff", "stroke-width": 10 }),
    svg("path", { d: "M30 0v30M0 15h60", stroke: "#c8102e", "stroke-width": 6 }),
  );
}

function toast(message, kind = "ok") {
  const isError = kind === "error";
  const el = h("div", { class: "toast" }, h("span", { class: `toast-icon ${isError ? "error" : "ok"}`, "aria-hidden": "true" }), h("span", {}, message));
  document.getElementById("toasts").append(el);
  setTimeout(() => {
    el.classList.add("leaving");
    el.addEventListener("animationend", () => el.remove(), { once: true });
    setTimeout(() => el.remove(), 600); // без анимаций (prefers-reduced-motion) событие не придёт
  }, isError ? 6500 : 3500);
}

function setBusy(button, busy) {
  button.disabled = busy;
  button.classList.toggle("is-busy", busy);
}

// ---------- форматирование ----------

function money(value, currency) {
  return new Intl.NumberFormat(locale(), { style: "currency", currency, currencyDisplay: "narrowSymbol" }).format(Number(value));
}

function utcDate(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

function fmtDate(iso) {
  if (!iso) return "—";
  if (lang === "ru") {
    const [y, m, d] = iso.split("-");
    return `${d}.${m}.${y}`;
  }
  return new Intl.DateTimeFormat(locale(), { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).format(utcDate(iso));
}

function fmtShort(iso) {
  return new Intl.DateTimeFormat(locale(), { day: "numeric", month: "short", timeZone: "UTC" }).format(utcDate(iso));
}

function fmtDayMonth(iso) {
  return new Intl.DateTimeFormat(locale(), { day: "numeric", month: "long", timeZone: "UTC" }).format(utcDate(iso));
}

function fmtDateTime(iso) {
  return new Date(iso).toLocaleString(locale(), { dateStyle: "short", timeStyle: "short" });
}

function monthName(month) {
  const name = new Intl.DateTimeFormat(locale(), { month: "long", timeZone: "UTC" }).format(new Date(Date.UTC(2026, month - 1, 1)));
  return name.charAt(0).toUpperCase() + name.slice(1);
}

function weekdays() {
  // 5 января 2026 года — понедельник
  return Array.from({ length: 7 }, (_, i) =>
    new Intl.DateTimeFormat(locale(), { weekday: "short", timeZone: "UTC" }).format(new Date(Date.UTC(2026, 0, 5 + i))),
  );
}

function diffDays(fromIso, toIso) {
  return Math.round((utcDate(toIso) - utcDate(fromIso)) / 86400000);
}

function monthRange(iso) {
  const [y, m] = iso.split("-").map(Number);
  const last = new Date(Date.UTC(y, m, 0)).getUTCDate();
  const mm = String(m).padStart(2, "0");
  return { due_from: `${y}-${mm}-01`, due_to: `${y}-${mm}-${String(last).padStart(2, "0")}` };
}

// ---------- API ----------

class ApiError extends Error {
  constructor(status, message, otpRequired = false) {
    super(message);
    this.status = status;
    this.otpRequired = otpRequired; // сервер ждёт код двухфакторного входа
  }
}

function explain(data, status) {
  const detail = data && data.detail;
  if (typeof detail === "string") return serverText(detail);
  if (Array.isArray(detail)) {
    return detail
      .map((e) => {
        const field = e.loc && e.loc[e.loc.length - 1];
        const name = has(`field.${field}`) ? t(`field.${field}`) : field;
        const reason = has(`valid.${e.type}`) ? t(`valid.${e.type}`) : e.msg;
        return `${name}: ${reason}`;
      })
      .join("; ");
  }
  return t("error.server", { status });
}

async function api(path, { method = "GET", body, params, silent = false } = {}) {
  const url = new URL(API + path, location.origin);
  for (const [key, value] of Object.entries(params || {})) {
    if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, value);
  }

  let response;
  try {
    const isForm = body instanceof FormData;
    response = await fetch(url, {
      method,
      headers: body && !isForm ? { "Content-Type": "application/json" } : {},
      body: body ? (isForm ? body : JSON.stringify(body)) : undefined,
      credentials: "same-origin",
    });
  } catch {
    throw new ApiError(0, t("error.network"));
  }

  if (response.status === 204) return null;
  let data = null;
  try {
    data = await response.json();
  } catch {
    /* тело не JSON */
  }

  if (!response.ok) {
    if (response.status === 401 && !silent) sessionExpired();
    throw new ApiError(response.status, explain(data, response.status), response.headers.get("X-OTP-Required") === "true");
  }
  return data;
}

// ---------- модальные окна ----------

function eyeIcon(open) {
  const shapes = [svg("path", { d: "M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z" }), svg("circle", { cx: "12", cy: "12", r: "3" })];
  if (!open) shapes.push(svg("path", { d: "M3 3l18 18" }));
  return svg("svg", { viewBox: "0 0 24 24", "aria-hidden": "true" }, ...shapes);
}

// Поле пароля с кнопкой «глаз»: показывает и снова скрывает введённое
function passwordInput(attrs) {
  const input = h("input", { ...attrs, type: "password" });
  const toggle = h("button", {
    type: "button",
    class: "pw-toggle",
    "aria-label": t("pw.show"),
    "aria-pressed": "false",
    title: t("pw.show"),
  });
  toggle.append(eyeIcon(true));
  toggle.addEventListener("click", () => {
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    const label = show ? t("pw.hide") : t("pw.show");
    toggle.setAttribute("aria-label", label);
    toggle.setAttribute("title", label);
    toggle.setAttribute("aria-pressed", String(show));
    toggle.replaceChildren(eyeIcon(!show));
    input.focus();
  });
  return h("div", { class: "pw-wrap" }, input, toggle);
}

function field({ label, name, type = "text", value = "", hint, required = true, ...rest }) {
  const control =
    type === "password" ? passwordInput({ name, value, required, ...rest }) : h("input", { name, type, value, required, ...rest });
  return h("label", { class: "field" }, h("span", {}, label), control, hint ? h("span", { class: "hint" }, hint) : null);
}

function selectField(label, name, options) {
  return h("label", { class: "field" }, h("span", {}, label), h("select", { name }, options));
}

// Окно появляется масштабом 0.9 → 1 (CSS), закрывается так же: удаляем из DOM после анимации
function presentDialog(dialog, onClose) {
  let pressedOutside = false;
  dialog.addEventListener("mousedown", (event) => { pressedOutside = event.target === dialog; });
  dialog.addEventListener("click", (event) => { if (pressedOutside && event.target === dialog) dialog.close(); });
  dialog.addEventListener("close", () => {
    if (onClose) onClose();
    setTimeout(() => dialog.remove(), 320);
  });
  document.body.append(dialog);
  dialog.showModal();
}

function openDialog({ title, description, fields = [], confirmLabel = t("common.save"), danger = false, onSubmit }) {
  const error = h("p", { class: "form-error", role: "alert" });
  const submit = h("button", { type: "submit", class: `btn btn-primary ${danger ? "btn-danger" : ""}` }, confirmLabel);
  const cancel = h("button", { type: "button", class: "btn", onclick: () => dialog.close() }, t("common.cancel"));
  const form = h(
    "form",
    { method: "dialog", novalidate: true },
    h("h2", {}, title),
    description ? h("p", { class: "desc" }, description) : null,
    ...fields,
    error,
    h("div", { class: "dialog-actions" }, cancel, submit),
  );
  const dialog = h("dialog", {}, form);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    error.textContent = "";
    setBusy(submit, true);
    try {
      await onSubmit(new FormData(form));
      dialog.close();
    } catch (err) {
      error.textContent = err.message;
      setBusy(submit, false);
    }
  });
  presentDialog(dialog);
  const first = form.querySelector("input");
  if (first) first.focus();
}

// ---------- валидация на клиенте (сервер проверяет всё то же самое) ----------

function parseAmount(raw) {
  const text = String(raw).trim().replace(",", ".");
  if (!/^\d{1,10}(\.\d{1,2})?$/.test(text) || Number(text) <= 0) throw new Error(t("check.amount"));
  return text;
}

function checkLogin(login) {
  if (!/^[A-Za-z0-9._@-]{3,64}$/.test(login)) throw new Error(t("check.login"));
}

// Категории для подсказок и фильтра: из списка регулярных платежей
function categoriesOf(payments) {
  return [...new Set(payments.map((p) => p.category).filter(Boolean))].sort((a, b) => a.localeCompare(b, locale()));
}

function assigneeField(users, value = null) {
  return selectField(
    t("field.assignee_id"),
    "assignee_id",
    [h("option", { value: "" }, t("rec.noAssignee")), ...users.map((u) => h("option", { value: String(u.id), selected: u.id === value }, `@${u.login}`))],
  );
}

function assigneeValue(data) {
  const raw = String(data.get("assignee_id") || "");
  return raw ? Number(raw) : null;
}

// Подпись под названием: категория и ответственный
function paymentMeta(p) {
  return [p.category, p.assignee_login ? `@${p.assignee_login}` : null].filter(Boolean).join(" · ");
}

function categoryField(value = "") {
  return field({ label: t("field.category"), name: "category", required: false, maxlength: "60", value, list: "category-options", placeholder: t("rec.categoryPlaceholder") });
}

function payLinkFields(data) {
  const url = String(data.get("pay_url") || "").trim();
  if (url && !/^https?:\/\/\S+$/i.test(url)) throw new Error(t("check.payUrl"));
  return { pay_url: url || null, pay_details: String(data.get("pay_details") || "").trim() || null };
}

function checkPassword(password) {
  if (password.length < 8 || password.length > 128) throw new Error(t("check.password"));
}

// ---------- язык ----------

function setTitle() {
  document.documentElement.lang = lang;
  document.title = state.me ? `${t(`tab.${state.tab}`)} · Invoice Keeper` : "Invoice Keeper";
  const meta = document.querySelector('meta[name="description"]');
  if (meta) meta.setAttribute("content", t("app.description"));
}

function setLang(id) {
  if (!I18N[id] || id === lang) return;
  lang = id;
  try {
    localStorage.setItem(LANG_KEY, id);
  } catch {
    /* приватный режим: язык просто не запомнится */
  }
  if (state.me) showApp().catch(report);
  else showLogin();
}

// ---------- тема: системная, светлая или тёмная, как настройка «Цветовая тема» в кабинете aeza ----------

const THEMES = ["system", "light", "dark"];
const THEME_KEY = "ik-theme";
const THEME_COLORS = { light: "#f4f4f4", dark: "#000000" };
const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");

function savedTheme() {
  try {
    const value = localStorage.getItem(THEME_KEY);
    return THEMES.includes(value) ? value : "system";
  } catch {
    return "system";
  }
}

let theme = savedTheme();

// Цвета переключает CSS (color-scheme и light-dark), здесь только атрибут на <html> и цвет строки браузера
function applyTheme() {
  const root = document.documentElement;
  if (theme === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", theme);
  const resolved = theme === "system" ? (darkQuery.matches ? "dark" : "light") : theme;
  for (const meta of document.querySelectorAll('meta[name="theme-color"]')) {
    const own = (meta.getAttribute("media") || "").includes("dark") ? "dark" : "light";
    meta.setAttribute("content", THEME_COLORS[theme === "system" ? own : resolved]);
  }
}

function setTheme(id) {
  if (!THEMES.includes(id) || id === theme) return;
  theme = id;
  try {
    localStorage.setItem(THEME_KEY, id);
  } catch {
    /* приватный режим: тема просто не запомнится */
  }
  const root = document.documentElement;
  root.classList.add("theme-fade");
  applyTheme();
  setTimeout(() => root.classList.remove("theme-fade"), 350);
  for (const el of document.querySelectorAll('.picker[data-picker="theme"]')) {
    el.replaceWith(themeSelect(el.classList.contains("down") ? "down" : "up"));
  }
}

applyTheme();
darkQuery.addEventListener("change", applyTheme);

// ---------- всплывающий список в сайдбаре: язык и тема ----------

function closePickers(except = null) {
  for (const el of document.querySelectorAll(".picker.open")) {
    if (el === except) continue;
    el.classList.remove("open");
    el.querySelector(".picker-toggle").setAttribute("aria-expanded", "false");
  }
}

// Пункт сайдбара со списком: всплывает масштабом 0.95 → 1 за 0.2 с, как выпадающие списки кабинета
function picker({ kind, direction, title, current, trailing, options, selected, onPick }) {
  const wrap = h("div", { class: `picker ${direction === "down" ? "down" : ""}`, "data-picker": kind });
  const toggle = h(
    "button",
    { type: "button", class: "nav-item picker-toggle", "aria-haspopup": "menu", "aria-expanded": "false", title },
    h("span", { class: "picker-current" }, current),
    icon(trailing),
  );
  const menu = h(
    "div",
    { class: "picker-menu", role: "menu", "aria-label": title },
    options.map((o) =>
      h(
        "button",
        {
          type: "button",
          class: "picker-option",
          role: "menuitemradio",
          lang: o.lang,
          "aria-checked": String(o.id === selected),
          onclick: () => { closePickers(); onPick(o.id); },
        },
        o.lead,
        o.label,
        o.id === selected ? icon("check", "tick") : null,
      ),
    ),
  );
  toggle.addEventListener("click", () => {
    const open = !wrap.classList.contains("open");
    closePickers(wrap);
    wrap.classList.toggle("open", open);
    toggle.setAttribute("aria-expanded", String(open));
  });
  wrap.append(toggle, menu);
  return wrap;
}

function langSelect(direction = "up") {
  const current = LANGS.find((l) => l.id === lang);
  return picker({
    kind: "lang",
    direction,
    title: t("shell.language"),
    current: [flag(current.id), current.label],
    trailing: "globe",
    options: LANGS.map((l) => ({ id: l.id, label: l.label, lead: flag(l.id), lang: l.id })),
    selected: lang,
    onPick: setLang,
  });
}

const THEME_ICONS = { system: "monitor", light: "sun", dark: "moon" };

function themeSelect(direction = "up") {
  return picker({
    kind: "theme",
    direction,
    title: t("theme.title"),
    current: t("theme.current", { mode: t(`theme.${theme}`).toLowerCase() }),
    trailing: THEME_ICONS[theme],
    options: THEMES.map((id) => ({ id, label: t(`theme.${id}`), lead: icon(THEME_ICONS[id]) })),
    selected: theme,
    onPick: setTheme,
  });
}

// ---------- вход и выход ----------

function sessionExpired() {
  if (!state.me) return;
  state.me = null;
  showLogin(t("auth.expired"));
}

function authShape() {
  return svg(
    "svg",
    { class: "auth-shape", viewBox: "0 0 274 301", "aria-hidden": "true" },
    svg("path", { d: "M264 134c13 7 13 26 0 33L28 298c-13 7-28-2-28-17V19C0 5 16-5 28 3Z" }),
  );
}

function showLogin(notice = "") {
  ui = null;
  setTitle();
  const error = h("p", { class: "form-error", role: "alert" }, notice);
  const submit = h("button", { type: "submit", class: "btn btn-block" }, t("auth.submit"));
  // Поле кода появляется, только когда сервер ответил, что для этого входа нужен второй фактор
  const otpField = field({
    label: t("field.otp"),
    name: "otp",
    inputmode: "numeric",
    autocomplete: "one-time-code",
    maxlength: "8",
    hint: t("auth.otpHint"),
    required: false,
  });
  otpField.hidden = true;
  const form = h(
    "form",
    { novalidate: true },
    field({ label: t("field.login"), name: "login", autocomplete: "username", autocapitalize: "none", spellcheck: "false" }),
    field({ label: t("field.password"), name: "password", type: "password", autocomplete: "current-password" }),
    otpField,
    error,
    submit,
  );

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(form);
    const login = String(data.get("login")).trim();
    const password = String(data.get("password"));
    const otp = String(data.get("otp") || "").replace(/\s/g, "");
    if (!login || !password) {
      error.textContent = t("check.credentials");
      return;
    }
    if (!otpField.hidden && !otp) {
      error.textContent = t("auth.otpNeeded");
      otpField.querySelector("input").focus();
      return;
    }
    error.textContent = "";
    setBusy(submit, true);
    try {
      const body = otpField.hidden ? { login, password } : { login, password, otp };
      const result = await api("/auth/login", { method: "POST", body, silent: true });
      state.me = result.user;
      state.tab = "payments";
      await showApp();
    } catch (err) {
      setBusy(submit, false);
      if (err.otpRequired) {
        const input = otpField.querySelector("input");
        error.textContent = otpField.hidden ? t("auth.otpNeeded") : err.message;
        otpField.hidden = false;
        input.value = "";
        input.focus();
        return;
      }
      error.textContent = err.status === 401 ? t("auth.invalid") : err.message;
    }
  });

  const points = ["auth.point1", "auth.point2", "auth.point3"].map((key) => h("li", {}, icon("check"), h("span", {}, t(key))));

  app().replaceChildren(
    h(
      "div",
      { class: "auth" },
      h("div", { class: "auth-tools" }, langSelect("down"), themeSelect("down")),
      h(
        "div",
        { class: "auth-card" },
        h(
          "section",
          { class: "auth-panel auth-promo", "aria-hidden": "true" },
          authShape(),
          brand(),
          h("div", { class: "auth-promo-text" }, h("h2", {}, t("auth.promoTitle")), h("ul", { class: "auth-points" }, points)),
        ),
        h(
          "section",
          { class: "auth-panel auth-form" },
          h("div", {}, h("h1", {}, t("auth.title")), h("p", { class: "lead" }, t("auth.lead"))),
          form,
        ),
      ),
    ),
  );
  form.querySelector("input").focus();
}

function brand() {
  return h(
    "div",
    { class: "brand" },
    h("img", { class: "brand-mark", src: "/static/brand/logo-mark.svg", alt: "", width: 32, height: 32 }),
    h("span", { class: "brand-name" }, "Invoice Keeper"),
  );
}

async function logout() {
  try {
    await api("/auth/logout", { method: "POST", silent: true });
  } catch {
    /* сессия могла уже закончиться */
  }
  state.me = null;
  showLogin();
}

// ---------- каркас: сайдбар как в кабинете aeza ----------

let ui = null; // { shell, page, navItems, menuButton }

function tabsFor(me) {
  const tabs = [
    { id: "payments", icon: "payments" },
    { id: "calendar", icon: "calendar" },
    { id: "budget", icon: "budget" },
  ];
  if (me.role === "admin") {
    tabs.push({ id: "recurring", icon: "recurring" }, { id: "users", icon: "users" }, { id: "audit", icon: "audit" });
  }
  tabs.push({ id: "messengers", icon: "messengers" }, { id: "account", icon: "account" }, { id: "help", icon: "help" });
  return tabs;
}

function setNavOpen(open) {
  if (!ui) return;
  ui.shell.classList.toggle("nav-open", open);
  ui.menuButton.setAttribute("aria-expanded", String(open));
}

function navigate(tab) {
  state.tab = tab;
  if (!ui) return Promise.resolve();
  for (const item of ui.navItems) {
    if (item.dataset.tab === tab) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  }
  setNavOpen(false);
  setTitle();
  window.scrollTo({ top: 0 });
  return loadTab(ui.page);
}

async function addPayment() {
  await navigate("recurring");
  const input = document.querySelector(".inline-form [name=name]");
  if (input) input.focus();
}

function userPanel() {
  return h(
    "div",
    { class: "user-panel" },
    h(
      "div",
      { class: "user-row" },
      h("span", { class: "user-login", title: state.me.login }, `@${state.me.login}`),
      h(
        "div",
        { class: "user-actions" },
        // пароль администратора живёт в .env, сменить его может только пользователь
        state.me.role === "admin"
          ? null
          : h("button", { type: "button", class: "icon-btn", "aria-label": t("shell.password"), title: t("shell.password"), onclick: passwordDialog }, icon("key")),
        h("button", { type: "button", class: "icon-btn", "aria-label": t("shell.logout"), title: t("shell.logout"), onclick: logout }, icon("logout")),
      ),
    ),
    h(
      "div",
      { class: "user-row" },
      h("div", { class: "user-today" }, h("small", {}, t("shell.today")), h("b", { class: "num" }, fmtShort(state.asOf))),
      h("span", { class: "skew-badge" }, t(state.me.role === "admin" ? "role.admin" : "role.user")),
    ),
  );
}

function passwordDialog() {
  openDialog({
    title: t("pass.title"),
    description: t("pass.desc"),
    confirmLabel: t("common.save"),
    fields: [
      field({ label: t("pass.current"), name: "current", type: "password", autocomplete: "current-password" }),
      field({ label: t("pass.new"), name: "next", type: "password", autocomplete: "new-password", placeholder: t("users.passwordPlaceholder") }),
      field({ label: t("pass.repeat"), name: "repeat", type: "password", autocomplete: "new-password" }),
    ],
    onSubmit: async (data) => {
      const current = String(data.get("current"));
      const next = String(data.get("next"));
      checkPassword(next);
      if (next !== String(data.get("repeat"))) throw new Error(t("pass.mismatch"));
      await api("/auth/password", { method: "POST", body: { current_password: current, new_password: next } });
      toast(t("pass.done"));
    },
  });
}

async function showApp() {
  const summary = await api("/payments/summary");
  state.asOf = summary.as_of;
  setTitle();

  const page = h("main", { id: "view", class: "page" });
  const navItems = tabsFor(state.me).map((tab) =>
    h(
      "button",
      {
        type: "button",
        class: "nav-item",
        "data-tab": tab.id,
        "aria-current": tab.id === state.tab ? "page" : null,
        onclick: () => navigate(tab.id),
      },
      h("span", {}, t(`tab.${tab.id}`)),
      icon(tab.icon),
    ),
  );

  const sidebar = h(
    "aside",
    { class: "sidebar", id: "sidebar" },
    userPanel(),
    h("nav", { class: "nav", "aria-label": t("shell.menu") }, navItems),
    h(
      "div",
      { class: "side-bottom" },
      state.me.role === "admin"
        ? h("div", { class: "add-block" }, h("button", { type: "button", onclick: () => addPayment().catch(report) }, h("span", {}, t("shell.addPayment")), icon("plus")))
        : null,
      h(
        "div",
        { class: "side-links" },
        h("a", { class: "nav-item", href: `${API}/docs`, target: "_blank", rel: "noopener" }, h("span", {}, t("shell.api")), icon("book")),
        langSelect("up"),
        themeSelect("up"),
      ),
      h("div", { class: "side-logo" }, h("img", { src: "/static/brand/logo-mark.svg", alt: "", width: 32, height: 32 }), "Invoice Keeper"),
    ),
  );

  const menuButton = h(
    "button",
    { type: "button", class: "icon-btn", "aria-label": t("shell.menu"), "aria-controls": "sidebar", "aria-expanded": "false", onclick: () => setNavOpen(!ui.shell.classList.contains("nav-open")) },
    icon("menu"),
  );
  const shell = h(
    "div",
    { class: "shell" },
    sidebar,
    h("div", { class: "scrim", "aria-hidden": "true", onclick: () => setNavOpen(false) }),
    h("div", { class: "main" }, h("div", { class: "mobile-bar" }, menuButton, brand()), page),
  );

  ui = { shell, page, navItems, menuButton };
  app().replaceChildren(shell);
  await loadTab(page);
}

function pageHead(title, lead) {
  return h("header", { class: "page-head" }, h("h1", { class: "page-title" }, title), lead ? h("p", { class: "page-lead" }, lead) : null);
}

function section(title, ...children) {
  return h("section", { class: "section" }, title ? h("h2", { class: "section-title" }, title) : null, ...children);
}

// Скелетон, пока грузятся данные: те же серые плашки с бегущим бликом, что в кабинете
function skeletonPage() {
  return h(
    "div",
    { class: "sk-page", "aria-busy": "true", "aria-label": t("common.loading") },
    h("span", { class: "skeleton sk-title" }),
    skeletonTiles(),
    skeletonRows(4),
  );
}

function skeletonTileList(count = 3) {
  return Array.from({ length: count }, () => h("span", { class: "skeleton sk-tile", "aria-hidden": "true" }));
}

function skeletonTiles(count = 3) {
  return h("div", { class: "sk-tiles", "aria-hidden": "true" }, skeletonTileList(count));
}

function skeletonRows(count = 5) {
  return h("div", { class: "sk-page", "aria-hidden": "true" }, Array.from({ length: count }, () => h("span", { class: "skeleton sk-line" })));
}

async function loadTab(main) {
  main.replaceChildren(skeletonPage());
  try {
    if (state.tab === "calendar") await calendarView(main);
    else if (state.tab === "budget") await budgetView(main);
    else if (state.tab === "recurring" && state.me.role === "admin") await recurringView(main);
    else if (state.tab === "users" && state.me.role === "admin") await usersView(main);
    else if (state.tab === "audit" && state.me.role === "admin") await auditView(main);
    else if (state.tab === "messengers") await messengersView(main);
    else if (state.tab === "account") await accountView(main);
    else if (state.tab === "help") await helpView(main);
    else await paymentsView(main);
  } catch (err) {
    if (err.status !== 401) {
      main.replaceChildren(pageHead(t(`tab.${state.tab}`)), h("div", { class: "empty" }, h("strong", {}, t("error.load")), err.message));
    }
  }
}

function report(err) {
  if (err.status !== 401) toast(err.message, "error");
}

// ---------- раздел «Платежи» ----------

function statusOf(o) {
  if (o.status === "paid") {
    return o.is_overdue ? { cls: "late", text: t("status.late") } : { cls: "paid", text: t("status.paid") };
  }
  if (o.is_overdue) return { cls: "overdue", text: t("status.overdue", { n: o.overdue_days, days: plural(o.overdue_days, "day") }) };
  if (diffDays(state.asOf, o.due_date) <= SOON_DAYS) return { cls: "soon", text: t("status.soon") };
  return { cls: "", text: t("status.unpaid") };
}

function dueNote(o) {
  if (o.status === "paid") return null;
  const left = diffDays(state.asOf, o.due_date);
  if (left < 0) return { text: t("due.overdueBy", { days: plural(-left, "day") }), bad: true };
  if (left === 0) return { text: t("due.today") };
  if (left === 1) return { text: t("due.tomorrow") };
  return { text: t("due.in", { days: plural(left, "day") }) };
}

function segmented(options, value, onChange) {
  const buttons = options.map((opt) =>
    h(
      "button",
      {
        type: "button",
        "aria-pressed": String(opt.value === value),
        onclick: () => {
          for (const b of buttons) b.setAttribute("aria-pressed", "false");
          buttons[options.indexOf(opt)].setAttribute("aria-pressed", "true");
          onChange(opt.value);
        },
      },
      opt.label,
    ),
  );
  return h("div", { class: "seg", role: "group" }, buttons);
}

const toMinor = (value) => Math.round(Number(value) * 100);

// Шкала из отрезков по суммам валюты, как ряды на плитке VPS в кабинете aeza, только с данными.
// Ширина отрезка задана атрибутом rect, а не style, поэтому CSP панели не мешает.
function shareBar(parts, currency) {
  const items = parts.map((p) => ({ ...p, minor: Math.max(toMinor(p.amount), 0) }));
  const total = items.reduce((sum, p) => sum + p.minor, 0);
  const shown = items.filter((p) => p.minor > 0);
  const GAP = 1; // доля ширины между отрезками, из 100
  const rects = [];
  if (!total) {
    rects.push(svg("rect", { class: "seg-empty", width: 100, height: 10 }));
  } else {
    const free = 100 - GAP * (shown.length - 1);
    let x = 0;
    shown.forEach((p, i) => {
      const width = i === shown.length - 1 ? 100 - x : (free * p.minor) / total;
      rects.push(svg("rect", { class: `seg-${p.kind}`, x: x.toFixed(3), width: width.toFixed(3), height: 10 }));
      x += width + GAP;
    });
  }
  const percent = (minor) => {
    if (!total || !minor) return "0%";
    const share = (minor / total) * 100;
    return share < 1 ? "<1%" : `${Math.round(share)}%`;
  };
  return h(
    "div",
    { class: "share" },
    svg(
      "svg",
      { class: "share-bar", viewBox: "0 0 100 10", preserveAspectRatio: "none", role: "img", "aria-label": items.map((p) => `${p.label} ${percent(p.minor)}`).join(", ") },
      ...rects,
    ),
    h(
      "div",
      { class: "share-legend" },
      items.map((p) =>
        h(
          "div",
          { class: `share-row ${p.kind} ${p.minor ? "has" : ""}` },
          h("span", { class: "share-name" }, p.label),
          h("span", { class: "num share-sum" }, money(p.minor / 100, currency)),
          h("span", { class: "num share-pct" }, percent(p.minor)),
        ),
      ),
    ),
  );
}

// Стрелка на плитке валюты: кнопка, открывает периоды оплаты в этой валюте
function tileArrow(currency, onOpen) {
  const label = t("sum.open", { currency });
  return h("button", { class: "tile-arrow", type: "button", "aria-label": label, title: label, onclick: () => onOpen(currency) }, icon("chevronRight"));
}

function summaryCard(c, onDate = null, onOpen = null) {
  const due = (toMinor(c.unpaid) - toMinor(c.overdue)) / 100;
  return h(
    "article",
    { class: `tile ${c.count_overdue > 0 ? "has-overdue" : ""}` },
    c.count_overdue > 0 ? h("span", { class: "sticker" }, t("sum.sticker")) : null,
    h(
      "div",
      { class: "tile-head" },
      h("span", {}, `${c.currency} · `, h("span", { class: "muted" }, onDate ? t("sum.onDate", { date: fmtDate(onDate) }) : t(`currency.${c.currency}`))),
      onOpen ? tileArrow(c.currency, onOpen) : null,
    ),
    h(
      "div",
      {},
      h("div", { class: "tile-amount num" }, money(c.unpaid, c.currency)),
      h("div", { class: "tile-sub" }, c.count_unpaid ? t("sum.toPay", { payments: plural(c.count_unpaid, "payment") }) : t("sum.allClosed")),
    ),
    shareBar(
      [
        { kind: "paid", label: t("sum.paid"), amount: c.paid },
        { kind: "due", label: t("sum.due"), amount: due },
        { kind: "overdue", label: t("sum.overdue"), amount: c.overdue },
      ],
      c.currency,
    ),
  );
}

async function paymentsView(main) {
  const summaryBox = h("section", { class: "summary", "aria-label": t("payments.summary") }, skeletonTileList());
  const listBox = h("div", { class: "table-card" }, skeletonRows());
  const counter = h("span", { class: "muted grow" });
  const csvLink = h("a", { class: "btn btn-sm", download: "", title: t("payments.csvHint") }, icon("download"), t("payments.csv"));

  async function reload() {
    const f = state.filters;
    const range = f.scope === "month" ? monthRange(state.asOf) : {};
    const filters = {
      status: f.status === "paid" || f.status === "unpaid" ? f.status : undefined,
      overdue: f.status === "overdue" ? "true" : undefined,
      currency: f.currency,
      category: f.category || undefined,
      assignee: f.assignee || undefined,
      include_deleted: f.deleted ? "true" : undefined,
      q: f.q.trim() || undefined,
      ...range,
    };
    const csvUrl = new URL(`${API}/payment-occurrences/export`, location.origin);
    for (const [key, value] of Object.entries(filters)) if (value) csvUrl.searchParams.set(key, value);
    csvLink.href = csvUrl.pathname + csvUrl.search;
    const [items, summary] = await Promise.all([
      api("/payment-occurrences", { params: { ...filters, limit: 1000 } }),
      api("/payments/summary", {
        params: { include_deleted: f.deleted ? "true" : undefined, on: f.on || undefined, ...(f.on ? {} : range) },
      }),
    ]);
    if (!f.on) state.asOf = summary.as_of;
    summaryBox.replaceChildren(...summary.currencies.map((c) => summaryCard(c, f.on ? summary.as_of : null, openCurrency)));
    counter.textContent = items.length ? t("payments.shown", { n: items.length }) : "";
    lastItems = items;
    renderList();
  }

  let lastItems = [];
  const renderList = () => listBox.replaceChildren(lastItems.length ? occurrencesTable(lastItems, reload, renderList) : emptyPayments());

  let searchTimer;
  const search = h("input", {
    type: "search",
    class: "search",
    placeholder: t("payments.search"),
    "aria-label": t("payments.search"),
    value: state.filters.q,
    oninput: (e) => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => { state.filters.q = e.target.value; reload().catch(report); }, 250);
    },
  });

  const currencySelect = h(
    "select",
    { "aria-label": t("field.currency"), onchange: (e) => { state.filters.currency = e.target.value; reload().catch(report); } },
    h("option", { value: "" }, t("payments.allCurrencies")),
    CURRENCIES.map((c) => h("option", { value: c, selected: state.filters.currency === c }, c)),
  );

  const categories = categoriesOf(await api("/recurring-payments", { params: { include_deleted: "true" } }));
  if (state.filters.category && state.filters.category !== "-" && !categories.includes(state.filters.category)) state.filters.category = "";
  const categorySelect = categories.length
    ? h(
        "select",
        { "aria-label": t("field.category"), onchange: (e) => { state.filters.category = e.target.value; reload().catch(report); } },
        h("option", { value: "" }, t("payments.allCategories")),
        categories.map((c) => h("option", { value: c, selected: state.filters.category === c }, c)),
        h("option", { value: "-", selected: state.filters.category === "-" }, t("payments.noCategory")),
      )
    : null;

  // ответственный: у пользователя переключатель «Только мои», у админа выбор пользователя
  let assigneeControl;
  if (state.me.role === "admin") {
    const users = await api("/users");
    if (state.filters.assignee && !["-", ...users.map((u) => String(u.id))].includes(state.filters.assignee)) state.filters.assignee = "";
    assigneeControl = users.length
      ? h(
          "select",
          { "aria-label": t("field.assignee_id"), onchange: (e) => { state.filters.assignee = e.target.value; reload().catch(report); } },
          h("option", { value: "" }, t("payments.allAssignees")),
          users.map((u) => h("option", { value: String(u.id), selected: state.filters.assignee === String(u.id) }, `@${u.login}`)),
          h("option", { value: "-", selected: state.filters.assignee === "-" }, t("payments.noAssignee")),
        )
      : null;
  } else {
    if (state.filters.assignee !== "me") state.filters.assignee = "";
    assigneeControl = h(
      "label",
      { class: "check" },
      h("input", { type: "checkbox", checked: state.filters.assignee === "me", onchange: (e) => { state.filters.assignee = e.target.checked ? "me" : ""; reload().catch(report); } }),
      t("payments.mine"),
    );
  }

  const toolbar = h(
    "div",
    { class: "toolbar" },
    search,
    segmented(
      [
        { value: "all", label: t("payments.all") },
        { value: "unpaid", label: t("payments.unpaid") },
        { value: "overdue", label: t("payments.overdue") },
        { value: "paid", label: t("payments.paid") },
      ],
      state.filters.status,
      (v) => { state.filters.status = v; reload().catch(report); },
    ),
    segmented(
      [
        { value: "all", label: t("payments.allPeriods") },
        { value: "month", label: t("payments.thisMonth") },
      ],
      state.filters.scope,
      (v) => { state.filters.scope = v; reload().catch(report); },
    ),
    currencySelect,
    categorySelect,
    assigneeControl,
    h(
      "label",
      { class: "check" },
      h("input", { type: "checkbox", checked: state.filters.deleted, onchange: (e) => { state.filters.deleted = e.target.checked; reload().catch(report); } }),
      t("payments.withDeleted"),
    ),
    h(
      "label",
      { class: "check on-date" },
      t("payments.onDate"),
      h("input", { type: "date", value: state.filters.on, "aria-label": t("payments.onDate"), onchange: (e) => { state.filters.on = e.target.value; reload().catch(report); } }),
      state.filters.on ? h("button", { type: "button", class: "btn btn-sm btn-ghost", onclick: () => { state.filters.on = ""; loadTab(document.getElementById("view")); } }, t("common.reset")) : null,
    ),
    counter,
    csvLink,
  );

  const listSection = section(t("payments.list"), toolbar, listBox);

  // Стрелка на плитке: таблица ниже только по этой валюте
  async function openCurrency(currency) {
    state.filters.currency = currency;
    currencySelect.value = currency;
    await reload().catch(report);
    listSection.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  main.replaceChildren(pageHead(t("tab.payments"), t("payments.lead")), summaryBox, listSection);
  await reload();
}

function emptyPayments() {
  const none = state.me.role === "admin" ? t("payments.emptyAdmin") : t("payments.emptyUser");
  return h("div", { class: "empty" }, h("strong", {}, t("payments.empty")), none);
}

// Сортировка таблицы на клиенте: ключ столбца и направление, при равенстве по сроку
const SORT_KEYS = {
  name: (o) => o.name.toLocaleLowerCase(locale()),
  amount: (o) => Number(o.amount),
  due: (o) => o.due_date,
  status: (o) => ({ overdue: 0, soon: 1, "": 2, late: 3, paid: 4 })[statusOf(o).cls] ?? 2,
  paid: (o) => o.paid_at || "",
};

function sortedItems(items) {
  const { key, dir } = state.sort;
  const value = SORT_KEYS[key] || SORT_KEYS.due;
  const cmp = (x, y) => (x < y ? -1 : x > y ? 1 : 0);
  return [...items].sort((a, b) => dir * (cmp(value(a), value(b)) || cmp(a.due_date, b.due_date) || a.id - b.id));
}

function sortHeader(label, key, rerender, cls = "") {
  const active = state.sort.key === key;
  const toggle = () => {
    state.sort = { key, dir: active ? -state.sort.dir : 1 };
    rerender();
  };
  return h(
    "th",
    { class: cls, "aria-sort": active ? (state.sort.dir > 0 ? "ascending" : "descending") : "none" },
    h(
      "button",
      { type: "button", class: `th-sort ${active ? "active" : ""}`, onclick: toggle },
      label,
      active ? h("span", { class: "arrow", "aria-hidden": "true" }, state.sort.dir > 0 ? "↑" : "↓") : null,
    ),
  );
}

function occurrencesTable(items, reload, rerender) {
  return h(
    "table",
    {},
    h(
      "thead",
      {},
      h(
        "tr",
        {},
        sortHeader(t("col.payment"), "name", rerender),
        sortHeader(t("col.amount"), "amount", rerender, "right"),
        sortHeader(t("col.due"), "due", rerender),
        sortHeader(t("col.status"), "status", rerender),
        sortHeader(t("col.paidAt"), "paid", rerender),
        h("th", {}, ""),
      ),
    ),
    h("tbody", {}, sortedItems(items).map((o) => occurrenceRow(o, reload))),
  );
}

function occurrenceActions(o, reload) {
  const actions = [receiptsButton(o, reload)];
  if (o.payment_deleted) return actions;
  if (o.status === "unpaid") {
    if (o.pay_url) {
      actions.push(h("a", { class: "btn btn-sm", href: o.pay_url, target: "_blank", rel: "noopener noreferrer", title: o.pay_details || o.pay_url }, t("act.pay")));
    }
    actions.push(h("button", { class: "btn btn-sm btn-accent", onclick: () => payDialog(o, reload, false) }, t("act.markPaid")));
  } else {
    actions.push(
      h("button", { class: "btn btn-sm", onclick: () => payDialog(o, reload, true) }, t("act.changeDate")),
      h("button", { class: "btn btn-sm btn-danger", onclick: () => cancelDialog(o, reload) }, t("act.undo")),
    );
  }
  return actions;
}

function occurrenceRow(o, reload) {
  const status = statusOf(o);
  const note = dueNote(o);
  const rowClass = [
    o.status === "unpaid" && o.is_overdue ? "row-overdue" : "",
    status.cls === "soon" ? "row-soon" : "",
    status.cls === "late" ? "row-late" : "",
    o.payment_deleted ? "row-deleted" : "",
  ].join(" ");

  return h(
    "tr",
    { class: rowClass },
    h(
      "td",
      { class: "title-cell" },
      h("div", { class: "cell-title" }, o.name),
      paymentMeta(o) ? h("div", { class: "cell-sub" }, paymentMeta(o)) : null,
      o.payment_deleted ? h("div", { class: "cell-sub" }, t("payments.stopped")) : null,
    ),
    h("td", { class: "right", "data-label": t("col.amount") }, h("span", { class: "amount num" }, money(o.amount, o.currency))),
    h("td", { "data-label": t("col.due") }, h("div", {}, h("div", { class: "num" }, fmtDate(o.due_date)), note ? h("div", { class: `cell-sub ${note.bad ? "bad" : ""}` }, note.text) : null)),
    h("td", { "data-label": t("col.status") }, h("span", { class: `badge ${status.cls}` }, status.text)),
    h("td", { "data-label": t("col.paidAt"), class: "num" }, fmtDate(o.paid_at)),
    h("td", { class: "actions" }, occurrenceActions(o, reload)),
  );
}

function payDialog(o, reload, editing) {
  openDialog({
    title: editing ? t("pay.titleEdit") : t("pay.title"),
    description: t("pay.desc", { name: o.name, date: fmtDate(o.due_date), amount: money(o.amount, o.currency) }) + (o.pay_details ? ` ${t("field.pay_details")}: ${o.pay_details}` : ""),
    confirmLabel: editing ? t("common.save") : t("pay.confirm"),
    fields: [
      field({
        label: t("pay.field"),
        name: "paid_at",
        type: "date",
        value: editing ? o.paid_at : state.asOf,
        max: state.asOf,
        hint: t("pay.hint"),
      }),
    ],
    onSubmit: async (data) => {
      const paidAt = String(data.get("paid_at"));
      if (!paidAt) throw new Error(t("check.paidAt"));
      const body = editing ? { paid_at: paidAt } : { status: "paid", paid_at: paidAt };
      await api(`/payment-occurrences/${o.id}`, { method: "PATCH", body });
      toast(editing ? t("pay.doneEdit") : t("pay.done"));
      await reload();
    },
  });
}

function cancelDialog(o, reload) {
  openDialog({
    title: t("unpay.title"),
    description: t("unpay.desc", { name: o.name, date: fmtDate(o.due_date) }),
    confirmLabel: t("unpay.confirm"),
    danger: true,
    onSubmit: async () => {
      await api(`/payment-occurrences/${o.id}`, { method: "PATCH", body: { status: "unpaid" } });
      toast(t("unpay.done"));
      await reload();
    },
  });
}

// ---------- чеки и ссылки ----------

function receiptsButton(o, reload) {
  const count = o.receipts_count || 0;
  return h("button", { class: "btn btn-sm", type: "button", onclick: () => receiptsDialog(o, reload) }, count ? t("rc.buttonCount", { n: count }) : t("rc.button"));
}

function fmtSize(bytes) {
  const number = (n, digits) => new Intl.NumberFormat(locale(), { maximumFractionDigits: digits, minimumFractionDigits: digits }).format(n);
  if (bytes >= 1048576) return t("size.mb", { n: number(bytes / 1048576, 1) });
  return t("size.kb", { n: Math.max(1, Math.round(bytes / 1024)) });
}

function safeHref(url) {
  return /^https?:\/\//i.test(url) ? url : "#";
}

function receiptsDialog(o, reload) {
  const listBox = h("div", { class: "rc-list" });
  const error = h("p", { class: "form-error", role: "alert" });
  const dialog = h("dialog", {});

  async function refresh() {
    const items = await api(`/payment-occurrences/${o.id}/receipts`);
    o.receipts_count = items.length;
    listBox.replaceChildren(
      ...(items.length
        ? items.map((r) => {
            const mine = r.can_delete; // сервер решает сам: администратор или автор по id
            const label = r.title || r.filename || r.url;
            const open = r.kind === "file" ? r.download_url : safeHref(r.url);
            return h(
              "div",
              { class: "rc-item" },
              h("span", { class: `rc-kind ${r.kind}` }, t(r.kind === "file" ? "rc.kind.file" : "rc.kind.link")),
              h(
                "div",
                { class: "rc-main" },
                h("a", { href: open, target: "_blank", rel: "noopener noreferrer", class: "rc-name" }, label),
                h("div", { class: "cell-sub" }, [r.kind === "file" ? fmtSize(r.size_bytes) : new URL(safeHref(r.url), location.origin).hostname, r.created_by, fmtDateTime(r.created_at)].filter(Boolean).join(" · ")),
              ),
              mine
                ? h(
                    "button",
                    {
                      class: "btn btn-sm btn-danger",
                      type: "button",
                      onclick: async () => {
                        try {
                          await api(`/receipts/${r.id}`, { method: "DELETE" });
                          toast(t("rc.deleted"));
                          await refresh();
                          await reload();
                        } catch (err) {
                          error.textContent = err.message;
                        }
                      },
                    },
                    t("common.delete"),
                  )
                : null,
            );
          })
        : [h("p", { class: "muted" }, t("rc.empty"))]),
    );
  }

  async function submit(button, task, okMessage) {
    error.textContent = "";
    setBusy(button, true);
    try {
      await task();
      toast(okMessage);
      await refresh();
      await reload();
    } catch (err) {
      error.textContent = err.message;
    } finally {
      setBusy(button, false);
    }
  }

  const linkForm = h("form", { class: "rc-form", novalidate: true });
  const linkBtn = h("button", { type: "submit", class: "btn btn-primary btn-sm" }, t("rc.addLink"));
  linkForm.append(
    h("h3", {}, t("rc.linkTitle")),
    field({ label: t("rc.url"), name: "url", type: "url", placeholder: "https://…", autocomplete: "off" }),
    field({ label: t("rc.titleOptional"), name: "title", required: false, maxlength: "200", placeholder: t("rc.linkPlaceholder") }),
    linkBtn,
  );
  linkForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const data = new FormData(linkForm);
    const url = String(data.get("url")).trim();
    if (!/^https?:\/\/\S+$/i.test(url)) {
      error.textContent = t("check.url");
      return;
    }
    submit(linkBtn, async () => {
      await api(`/payment-occurrences/${o.id}/receipts/link`, { method: "POST", body: { url, title: String(data.get("title")).trim() || null } });
      linkForm.reset();
    }, t("rc.linkAdded"));
  });

  const fileForm = h("form", { class: "rc-form", novalidate: true });
  const fileBtn = h("button", { type: "submit", class: "btn btn-primary btn-sm" }, t("rc.upload"));
  fileForm.append(
    h("h3", {}, t("rc.fileTitle")),
    field({ label: t("field.file"), name: "file", type: "file", accept: ".pdf,.png,.jpg,.jpeg,.webp,application/pdf,image/png,image/jpeg,image/webp", hint: t("rc.fileHint") }),
    field({ label: t("rc.titleOptional"), name: "title", required: false, maxlength: "200" }),
    fileBtn,
  );
  fileForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const input = fileForm.querySelector("input[type=file]");
    if (!input.files.length) {
      error.textContent = t("check.file");
      return;
    }
    const body = new FormData();
    body.append("file", input.files[0]);
    const title = fileForm.querySelector("[name=title]").value.trim();
    if (title) body.append("title", title);
    submit(fileBtn, async () => {
      await api(`/payment-occurrences/${o.id}/receipts/file`, { method: "POST", body });
      fileForm.reset();
    }, t("rc.uploaded"));
  });

  const close = h("button", { type: "button", class: "btn", onclick: () => dialog.close() }, t("common.close"));
  dialog.append(
    h(
      "div",
      { class: "rc-dialog" },
      h("h2", {}, t("rc.title")),
      h("p", { class: "desc" }, t("rc.desc", { name: o.name, date: fmtDate(o.due_date) })),
      listBox,
      o.payment_deleted ? h("p", { class: "muted" }, t("rc.stopped")) : h("div", { class: "rc-forms" }, linkForm, fileForm),
      error,
      h("div", { class: "dialog-actions" }, close),
    ),
  );
  presentDialog(dialog);
  refresh().catch((err) => { error.textContent = err.message; });
}

// ---------- раздел «Регулярные платежи» (админ) ----------

function periodLabel(period) {
  return t(`period.${PERIODS.includes(period) ? period : "monthly"}`);
}

function periodOptions(selected) {
  return PERIODS.map((p) => h("option", { value: p, selected: p === selected }, periodLabel(p)));
}

// Когда платёж повторяется: сроки считаются от первой даты, в коротких месяцах это последний день
function periodHint(p) {
  const [, m, d] = p.first_due_date.split("-").map(Number);
  if (p.period === "yearly") {
    const day = fmtDayMonth(`2028-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`);
    return t(m === 2 && d === 29 ? "hint.yearlyLeap" : "hint.yearly", { day });
  }
  const every = p.period === "quarterly" ? t("hint.quarterly") : "";
  return `${every}${t("hint.day", { d })}${d > 28 ? t("hint.short") : ""}`;
}

async function recurringView(main) {
  const listBox = h("div", { class: "table-card" }, skeletonRows(3));
  const categoryOptions = h("datalist", { id: "category-options" });
  const assigneeSlot = h("div", { class: "field-slot" }, assigneeField([]));

  async function reload() {
    const [payments, unpaid, users] = await Promise.all([
      api("/recurring-payments"),
      api("/payment-occurrences", { params: { status: "unpaid", limit: 1000 } }),
      api("/users"),
    ]);
    state.recurringUsers = users;
    assigneeSlot.replaceChildren(assigneeField(users, Number(assigneeSlot.querySelector("select")?.value) || null));
    const nextDue = new Map();
    for (const o of unpaid) if (!nextDue.has(o.recurring_id)) nextDue.set(o.recurring_id, o.due_date);
    categoryOptions.replaceChildren(...categoriesOf(payments).map((c) => h("option", { value: c })));

    listBox.replaceChildren(
      payments.length
        ? h(
            "table",
            {},
            h("thead", {}, h("tr", {}, h("th", {}, t("col.payment")), h("th", { class: "right" }, t("col.amount")), h("th", {}, t("rec.colPeriod")), h("th", {}, t("rec.colNext")), h("th", {}, ""))),
            h(
              "tbody",
              {},
              payments.map((p) => {
                const next = nextDue.get(p.id);
                return h(
                  "tr",
                  {},
                  h(
                    "td",
                    { class: "title-cell" },
                    h("div", { class: "cell-title" }, p.name),
                    h("div", { class: "cell-sub" }, paymentMeta(p) ? `${paymentMeta(p)} · ` : "", t("rec.firstDue", { date: fmtDate(p.first_due_date) })),
                    p.pay_url ? h("a", { class: "cell-link", href: p.pay_url, target: "_blank", rel: "noopener noreferrer", title: p.pay_details || p.pay_url }, t("rec.payLink")) : null,
                  ),
                  h("td", { class: "right", "data-label": t("col.amount") }, h("span", { class: "amount num" }, money(p.amount, p.currency))),
                  h(
                    "td",
                    { "data-label": t("rec.colPeriod") },
                    h("div", {}, periodLabel(p.period)),
                    h("div", { class: "cell-sub" }, periodHint(p)),
                    p.is_paused || p.paused_from ? h("span", { class: "badge late" }, p.paused_until ? t("rec.pausedUntil", { date: fmtDate(p.paused_until) }) : t("rec.paused")) : null,
                  ),
                  h("td", { "data-label": t("rec.colNextShort"), class: "num" }, next ? fmtDate(next) : "—"),
                  h(
                    "td",
                    { class: "actions" },
                    h("button", { class: "btn btn-sm", onclick: () => editPaymentDialog(p, reload) }, t("common.edit")),
                    p.is_paused || p.paused_from
                      ? h("button", { class: "btn btn-sm btn-accent", onclick: () => resumePayment(p, reload).catch(report) }, t("rec.resume"))
                      : h("button", { class: "btn btn-sm", onclick: () => pauseDialog(p, reload) }, t("rec.pause")),
                    h("button", { class: "btn btn-sm btn-danger", onclick: () => deletePaymentDialog(p, reload) }, t("rec.stop")),
                  ),
                );
              }),
            ),
          )
        : h("div", { class: "empty" }, h("strong", {}, t("rec.empty")), t("rec.emptyText")),
    );
  }

  const form = h(
    "form",
    { class: "inline-form", novalidate: true },
    h("h3", {}, t("rec.new")),
    h(
      "div",
      { class: "form-grid" },
      field({ label: t("field.name"), name: "name", placeholder: t("rec.namePlaceholder"), maxlength: "200" }),
      field({ label: t("field.amount"), name: "amount", inputmode: "decimal", placeholder: "45000.00" }),
      selectField(t("field.currency"), "currency", CURRENCIES.map((c) => h("option", { value: c }, c))),
      selectField(t("field.period"), "period", periodOptions("monthly")),
      field({ label: t("field.first_due_date"), name: "first_due_date", type: "date", value: state.asOf }),
      field({ label: t("field.pay_url"), name: "pay_url", type: "url", required: false, maxlength: "500", placeholder: t("rec.payUrlPlaceholder") }),
      field({ label: t("field.pay_details"), name: "pay_details", required: false, maxlength: "1000", placeholder: t("rec.payDetailsPlaceholder") }),
      categoryField(),
      assigneeSlot,
      h("button", { type: "submit", class: "btn btn-primary" }, t("rec.add")),
    ),
    categoryOptions,
    h("p", { class: "form-error", role: "alert" }),
  );

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const error = form.querySelector(".form-error");
    const submit = form.querySelector("button[type=submit]");
    const data = new FormData(form);
    error.textContent = "";
    try {
      const name = String(data.get("name")).trim();
      if (!name) throw new Error(t("check.name"));
      const amount = parseAmount(data.get("amount"));
      const firstDue = String(data.get("first_due_date"));
      if (!firstDue) throw new Error(t("check.firstDue"));
      setBusy(submit, true);
      const link = payLinkFields(data);
      const category = String(data.get("category") || "").trim() || null;
      const body = { name, amount, currency: data.get("currency"), period: data.get("period"), first_due_date: firstDue, category, assignee_id: assigneeValue(data), ...link };
      await api("/recurring-payments", { method: "POST", body });
      toast(t("rec.added", { name }));
      for (const key of ["name", "amount", "pay_url", "pay_details", "category"]) form.querySelector(`[name=${key}]`).value = "";
      await reload();
    } catch (err) {
      error.textContent = err.message;
    } finally {
      setBusy(submit, false);
    }
  });

  main.replaceChildren(pageHead(t("tab.recurring"), t("rec.lead")), form, section(t("rec.list"), listBox));
  await reload();
}

function editPaymentDialog(p, reload) {
  openDialog({
    title: t("rec.editTitle"),
    description: t("rec.editDesc", { currency: p.currency }),
    fields: [
      field({ label: t("field.name"), name: "name", value: p.name, maxlength: "200" }),
      field({ label: t("rec.amountIn", { currency: p.currency }), name: "amount", value: p.amount, inputmode: "decimal" }),
      selectField(t("field.period"), "period", periodOptions(p.period)),
      field({
        label: t("rec.newFirstDue"),
        name: "first_due_date",
        type: "date",
        required: false,
        min: state.asOf,
        hint: t("rec.newFirstDueHint"),
      }),
      field({ label: t("field.pay_url"), name: "pay_url", type: "url", required: false, maxlength: "500", value: p.pay_url || "", placeholder: t("rec.payUrlPlaceholder") }),
      field({ label: t("field.pay_details"), name: "pay_details", required: false, maxlength: "1000", value: p.pay_details || "", placeholder: t("rec.payDetailsPlaceholder") }),
      categoryField(p.category || ""),
      assigneeField(state.recurringUsers || [], p.assignee_id),
    ],
    onSubmit: async (data) => {
      const body = {};
      const assignee = assigneeValue(data);
      if (assignee !== (p.assignee_id ?? null)) body.assignee_id = assignee;
      const category = String(data.get("category") || "").trim().replace(/\s+/g, " ") || null;
      if (category !== (p.category || null)) body.category = category;
      const link = payLinkFields(data);
      if (link.pay_url !== (p.pay_url || null)) body.pay_url = link.pay_url;
      if (link.pay_details !== (p.pay_details || null)) body.pay_details = link.pay_details;
      const name = String(data.get("name")).trim();
      if (!name) throw new Error(t("check.name"));
      if (name !== p.name) body.name = name;
      const amount = parseAmount(data.get("amount"));
      if (Number(amount) !== Number(p.amount)) body.amount = amount;
      const period = String(data.get("period"));
      const firstDue = String(data.get("first_due_date") || "");
      if (period !== p.period) body.period = period;
      if (firstDue) body.first_due_date = firstDue;
      if (body.period && !firstDue) throw new Error(t("check.newSchedule"));
      if (!Object.keys(body).length) throw new Error(t("common.nothingToChange"));
      await api(`/recurring-payments/${p.id}`, { method: "PATCH", body });
      toast(t("rec.updated", { name }));
      await reload();
    },
  });
}

function pauseDialog(p, reload) {
  const tomorrow = new Date(Date.parse(`${state.asOf}T00:00:00Z`) + 86400000).toISOString().slice(0, 10);
  openDialog({
    title: t("rec.pauseTitle"),
    description: t("rec.pauseDesc", { name: p.name }),
    confirmLabel: t("rec.pause"),
    fields: [field({ label: t("rec.pauseUntil"), name: "until", type: "date", required: false, min: tomorrow, hint: t("rec.pauseHint") })],
    onSubmit: async (data) => {
      const until = String(data.get("until") || "") || null;
      await api(`/recurring-payments/${p.id}/pause`, { method: "POST", body: { until } });
      toast(t("rec.pausedDone", { name: p.name }));
      await reload();
    },
  });
}

async function resumePayment(p, reload) {
  await api(`/recurring-payments/${p.id}/resume`, { method: "POST" });
  toast(t("rec.resumed", { name: p.name }));
  await reload();
}

function deletePaymentDialog(p, reload) {
  openDialog({
    title: t("rec.stopTitle"),
    description: t("rec.stopDesc", { name: p.name }),
    confirmLabel: t("rec.stop"),
    danger: true,
    onSubmit: async () => {
      await api(`/recurring-payments/${p.id}`, { method: "DELETE" });
      toast(t("rec.stopped", { name: p.name }));
      await reload();
    },
  });
}

// ---------- раздел «Пользователи» (админ) ----------

async function usersView(main) {
  const listBox = h("div", { class: "table-card" }, skeletonRows(3));

  async function reload() {
    const users = await api("/users");
    listBox.replaceChildren(
      users.length
        ? h(
            "table",
            {},
            h("thead", {}, h("tr", {}, h("th", {}, t("field.login")), h("th", {}, t("users.colCreated")), h("th", {}, t("users.colMessengers")), h("th", {}, ""))),
            h(
              "tbody",
              {},
              users.map((u) =>
                h(
                  "tr",
                  {},
                  h("td", { class: "title-cell" }, h("div", { class: "cell-title" }, u.login)),
                  h("td", { "data-label": t("users.colCreated"), class: "num" }, fmtDateTime(u.created_at)),
                  h(
                    "td",
                    { "data-label": t("users.colMessengers") },
                    (u.messengers || []).length
                      ? u.messengers.map((m) => h("span", { class: "badge paid msg-badge" }, MESSENGER_TITLES[m] || m))
                      : h("span", { class: "muted" }, "—"),
                  ),
                  h(
                    "td",
                    { class: "actions" },
                    h("button", { class: "btn btn-sm", onclick: () => editUserDialog(u, reload) }, t("common.edit")),
                    h("button", { class: "btn btn-sm btn-danger", onclick: () => deleteUserDialog(u, reload) }, t("common.delete")),
                  ),
                ),
              ),
            ),
          )
        : h("div", { class: "empty" }, h("strong", {}, t("users.empty")), t("users.emptyText")),
    );
  }

  const form = h(
    "form",
    { class: "inline-form", novalidate: true },
    h("h3", {}, t("users.new")),
    h(
      "div",
      { class: "form-grid" },
      field({ label: t("field.login"), name: "login", autocomplete: "off", autocapitalize: "none", spellcheck: "false", placeholder: "ivan" }),
      field({ label: t("field.password"), name: "password", type: "password", autocomplete: "new-password", placeholder: t("users.passwordPlaceholder") }),
      h("button", { type: "submit", class: "btn btn-primary" }, t("users.create")),
    ),
    h("p", { class: "form-error", role: "alert" }),
  );

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const error = form.querySelector(".form-error");
    const submit = form.querySelector("button[type=submit]");
    const data = new FormData(form);
    error.textContent = "";
    try {
      const login = String(data.get("login")).trim();
      const password = String(data.get("password"));
      checkLogin(login);
      checkPassword(password);
      setBusy(submit, true);
      await api("/users", { method: "POST", body: { login, password } });
      toast(t("users.created", { login }));
      form.reset();
      await reload();
    } catch (err) {
      error.textContent = err.message;
    } finally {
      setBusy(submit, false);
    }
  });

  main.replaceChildren(pageHead(t("tab.users"), t("users.lead")), form, section(t("users.list"), listBox));
  await reload();
}

function editUserDialog(u, reload) {
  openDialog({
    title: t("users.editTitle"),
    fields: [
      field({ label: t("field.login"), name: "login", value: u.login, autocapitalize: "none", spellcheck: "false" }),
      field({ label: t("users.newPassword"), name: "password", type: "password", required: false, autocomplete: "new-password", hint: t("users.newPasswordHint") }),
    ],
    onSubmit: async (data) => {
      const login = String(data.get("login")).trim();
      const password = String(data.get("password"));
      const body = {};
      if (login !== u.login) {
        checkLogin(login);
        body.login = login;
      }
      if (password) {
        checkPassword(password);
        body.password = password;
      }
      if (!Object.keys(body).length) throw new Error(t("common.nothingToChange"));
      await api(`/users/${u.id}`, { method: "PATCH", body });
      toast(t("users.updated"));
      await reload();
    },
  });
}

function deleteUserDialog(u, reload) {
  openDialog({
    title: t("users.deleteTitle"),
    description: t("users.deleteDesc", { login: u.login }),
    confirmLabel: t("common.delete"),
    danger: true,
    onSubmit: async () => {
      await api(`/users/${u.id}`, { method: "DELETE" });
      toast(t("users.deleted", { login: u.login }));
      await reload();
    },
  });
}

// ---------- разделы «Календарь» и «Бюджет» ----------

function isoDate(y, m, d) {
  return `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

function totalsRow(totals) {
  const shown = totals.filter((x) => x.count_planned > 0);
  if (!shown.length) return h("p", { class: "muted" }, t("cal.none"));
  return h(
    "div",
    { class: "month-totals" },
    shown.map((x) =>
      h(
        "div",
        { class: "tile mini-card" },
        h("div", { class: "tile-head" }, h("span", {}, x.currency), h("span", { class: "muted" }, plural(x.count_planned, "payment"))),
        h("div", { class: "tile-amount num" }, money(x.planned, x.currency)),
        h("div", { class: "tile-sub" }, t("cal.paidLeft", { paid: money(x.paid, x.currency), left: money(x.remaining, x.currency) })),
        h("progress", { max: Math.max(Number(x.planned), 1), value: Number(x.paid), "aria-label": t("cal.paidShare") }),
      ),
    ),
  );
}

function chipClass(item) {
  if (item.status === "planned") return "planned";
  if (item.status === "paid") return item.is_overdue ? "late" : "paid";
  return item.is_overdue ? "overdue" : "unpaid";
}

function chipStatus(item) {
  if (item.status === "planned") return t("status.planned");
  if (item.status === "paid") {
    return item.is_overdue ? t("status.lateDays", { n: item.overdue_days, days: plural(item.overdue_days, "day") }) : t("status.paid");
  }
  return item.is_overdue ? t("status.overdue", { n: item.overdue_days, days: plural(item.overdue_days, "day") }) : t("status.unpaid");
}

async function calendarView(main) {
  if (!state.cal) {
    const [y, m] = state.asOf.split("-").map(Number);
    state.cal = { year: y, month: m, selected: state.asOf };
  }
  const grid = h("div", { class: "cal-grid", role: "grid" });
  const totalsBox = h("div", {});
  const dayBox = h("div", { class: "day-box" });
  const title = h("h3", { class: "cal-title" });

  async function reload() {
    const { year, month } = state.cal;
    const data = await api("/payments/calendar", { params: { year, month } });
    state.asOf = data.today;
    title.textContent = `${monthName(month)} ${year}`;
    totalsBox.replaceChildren(totalsRow(data.totals));

    const byDay = new Map(data.days.map((d) => [d.day, d.items]));
    if (!state.cal.selected || !state.cal.selected.startsWith(isoDate(year, month, 1).slice(0, 8))) {
      const todayHere = data.today.startsWith(isoDate(year, month, 1).slice(0, 8)) ? data.today : null;
      state.cal.selected = todayHere || (data.days[0] && data.days[0].day) || isoDate(year, month, 1);
    }

    const first = (new Date(Date.UTC(year, month - 1, 1)).getUTCDay() + 6) % 7;
    const count = new Date(Date.UTC(year, month, 0)).getUTCDate();
    const cells = weekdays().map((d) => h("div", { class: "cal-wd", role: "columnheader" }, d));
    for (let i = 0; i < first; i++) cells.push(h("div", { class: "cal-cell blank", "aria-hidden": "true" }));
    for (let d = 1; d <= count; d++) {
      const iso = isoDate(year, month, d);
      const items = byDay.get(iso) || [];
      const classes = ["cal-cell", iso === data.today ? "today" : "", iso === state.cal.selected ? "selected" : "", items.length ? "has-items" : ""];
      cells.push(
        h(
          "button",
          {
            type: "button",
            class: classes.join(" "),
            role: "gridcell",
            "aria-label": t("cal.dayLabel", { date: fmtDayMonth(iso), n: items.length }),
            "aria-pressed": String(iso === state.cal.selected),
            onclick: () => { state.cal.selected = iso; reload().catch(report); },
          },
          h("span", { class: "cal-day" }, String(d)),
          h(
            "span",
            { class: "cal-chips" },
            items.slice(0, 3).map((it) => h("span", { class: `chip ${chipClass(it)}`, title: `${it.name}, ${money(it.amount, it.currency)}` }, it.name)),
            items.length > 3 ? h("span", { class: "chip more" }, `+${items.length - 3}`) : null,
          ),
          items.length ? h("span", { class: "cal-dots", "aria-hidden": "true" }, items.slice(0, 4).map((it) => h("i", { class: `dot ${chipClass(it)}` }))) : null,
        ),
      );
    }
    grid.replaceChildren(...cells);

    const items = byDay.get(state.cal.selected) || [];
    dayBox.replaceChildren(
      h("h3", {}, fmtDate(state.cal.selected)),
      items.length ? h("div", { class: "day-list" }, items.map((it) => dayItem(it, reload))) : h("p", { class: "muted" }, t("cal.noneDay")),
    );
  }

  const shift = (delta) => {
    let { year, month } = state.cal;
    month += delta;
    if (month < 1) { month = 12; year -= 1; }
    if (month > 12) { month = 1; year += 1; }
    state.cal = { year, month, selected: null };
    reload().catch(report);
  };

  main.replaceChildren(
    pageHead(t("cal.title"), t("cal.lead")),
    h(
      "div",
      { class: "cal-nav" },
      h("button", { class: "btn btn-sm", type: "button", "aria-label": t("cal.prev"), title: t("cal.prev"), onclick: () => shift(-1) }, icon("chevronLeft")),
      title,
      h("button", { class: "btn btn-sm", type: "button", "aria-label": t("cal.next"), title: t("cal.next"), onclick: () => shift(1) }, icon("chevronRight")),
      h("button", { class: "btn btn-sm", type: "button", onclick: () => { state.cal = null; calendarView(main).catch(report); } }, t("common.today")),
    ),
    totalsBox,
    h("div", { class: "cal-card" }, grid),
    dayBox,
  );
  await reload();
}

function dayItem(it, reload) {
  const occurrence = {
    id: it.occurrence_id,
    name: it.name,
    due_date: it.due_date,
    amount: it.amount,
    currency: it.currency,
    status: it.status,
    paid_at: it.paid_at,
    payment_deleted: it.payment_deleted,
    receipts_count: it.receipts_count,
  };
  const actions = it.occurrence_id ? occurrenceActions(occurrence, reload) : null;
  const sub = it.paid_at ? t("cal.paidOn", { date: fmtDate(it.paid_at) }) : it.payment_deleted ? t("cal.stopped") : "";
  return h(
    "div",
    { class: `day-item ${chipClass(it)}` },
    h("div", {}, h("div", { class: "cell-title" }, it.name), h("div", { class: "cell-sub" }, sub)),
    h("div", { class: "amount num" }, money(it.amount, it.currency)),
    h("span", { class: `badge ${chipClass(it) === "unpaid" ? "" : chipClass(it)}` }, chipStatus(it)),
    h("div", { class: "day-actions" }, actions),
  );
}

async function budgetView(main) {
  if (!state.budgetYear) state.budgetYear = Number(state.asOf.slice(0, 4));
  const cards = h("section", { class: "summary", "aria-label": t("tab.budget") }, skeletonTileList());
  const tableBox = h("div", { class: "table-card" }, skeletonRows());
  const categoryBox = h("div", { class: "table-card" });
  const categorySection = section(t("budget.byCategory"), categoryBox);
  const title = h("h3", { class: "cal-title" });

  // Стрелка на плитке: вкладка «Платежи» с периодами этой валюты
  const openPayments = (currency) => {
    state.filters.currency = currency;
    navigate("payments").catch(report);
  };

  async function reload() {
    const year = state.budgetYear;
    const data = await api("/payments/budget", { params: { year } });
    title.textContent = t("budget.year", { year });
    cards.replaceChildren(
      ...data.currencies.map((c) =>
        h(
          "article",
          { class: "tile" },
          h(
            "div",
            { class: "tile-head" },
            h("span", {}, `${c.currency} · `, h("span", { class: "muted" }, t("budget.plan"))),
            tileArrow(c.currency, openPayments),
          ),
          h(
            "div",
            {},
            h("div", { class: "tile-amount num" }, money(c.planned, c.currency)),
            h("div", { class: "tile-sub" }, c.count_planned ? plural(c.count_planned, "payment") : t("budget.none")),
          ),
          shareBar(
            [
              { kind: "paid", label: t("sum.paid"), amount: c.paid },
              { kind: "left", label: t("sum.left"), amount: c.remaining },
            ],
            c.currency,
          ),
        ),
      ),
    );

    const active = CURRENCIES.filter((cur) => data.currencies.find((c) => c.currency === cur).count_planned > 0);
    tableBox.replaceChildren(
      active.length
        ? h(
            "table",
            {},
            h("thead", {}, h("tr", {}, h("th", {}, t("budget.month")), active.map((cur) => h("th", { class: "right" }, cur)))),
            h(
              "tbody",
              {},
              data.months.map((m) =>
                h(
                  "tr",
                  { class: "clickable", tabindex: "0", onclick: () => openMonth(year, m.month), onkeydown: (e) => { if (e.key === "Enter") openMonth(year, m.month); } },
                  h("td", { class: "title-cell" }, h("div", { class: "cell-title" }, monthName(m.month))),
                  active.map((cur) => {
                    const c = m.currencies.find((x) => x.currency === cur);
                    return h(
                      "td",
                      { class: "right num", "data-label": cur },
                      c.count_planned
                        ? h("div", {}, h("div", { class: "amount" }, money(c.planned, cur)), h("div", { class: "cell-sub" }, c.paid === c.planned ? t("budget.paidAll") : t("budget.paidPart", { amount: money(c.paid, cur) })))
                        : h("span", { class: "muted" }, "—"),
                    );
                  }),
                ),
              ),
            ),
          )
        : h("div", { class: "empty" }, h("strong", {}, t("budget.empty")), t("budget.emptyText")),
    );

    // по категориям: только если хоть у одного платежа категория задана
    const named = (data.categories || []).some((c) => c.category);
    categorySection.hidden = !named || !active.length;
    if (named && active.length) {
      categoryBox.replaceChildren(
        h(
          "table",
          {},
          h("thead", {}, h("tr", {}, h("th", {}, t("budget.category")), active.map((cur) => h("th", { class: "right" }, cur)))),
          h(
            "tbody",
            {},
            data.categories.map((row) =>
              h(
                "tr",
                {},
                h("td", { class: "title-cell" }, h("div", { class: "cell-title" }, row.category || t("payments.noCategory"))),
                active.map((cur) => {
                  const c = row.currencies.find((x) => x.currency === cur);
                  return h(
                    "td",
                    { class: "right num", "data-label": cur },
                    c.count_planned
                      ? h("div", {}, h("div", { class: "amount" }, money(c.planned, cur)), h("div", { class: "cell-sub" }, c.paid === c.planned ? t("budget.paidAll") : t("budget.paidPart", { amount: money(c.paid, cur) })))
                      : h("span", { class: "muted" }, "—"),
                  );
                }),
              ),
            ),
          ),
        ),
      );
    }
  }

  function openMonth(year, month) {
    state.cal = { year, month, selected: null };
    navigate("calendar").catch(report);
  }

  const shift = (delta) => { state.budgetYear += delta; reload().catch(report); };

  main.replaceChildren(
    pageHead(t("tab.budget"), t("budget.lead")),
    h(
      "div",
      { class: "cal-nav" },
      h("button", { class: "btn btn-sm", type: "button", "aria-label": t("budget.prev"), title: t("budget.prev"), onclick: () => shift(-1) }, icon("chevronLeft")),
      title,
      h("button", { class: "btn btn-sm", type: "button", "aria-label": t("budget.next"), title: t("budget.next"), onclick: () => shift(1) }, icon("chevronRight")),
    ),
    cards,
    categorySection,
    section(t("budget.byMonth"), tableBox),
  );
  await reload();
}

// ---------- раздел «Журнал» (админ) ----------

function auditSummary(e) {
  const d = e.details || {};
  const due = d.due_date ? t("audit.due", { date: fmtDate(d.due_date) }) : "";
  switch (e.action) {
    case "occurrence.paid":
    case "occurrence.unpaid":
      return [d.name, due, d.paid_at ? t("audit.paidOn", { date: fmtDate(d.paid_at) }) : ""].filter(Boolean).join(", ");
    case "occurrence.paid_at_changed":
      return t("audit.paidChanged", { name: d.name, due, before: fmtDate(d.paid_at_before), after: fmtDate(d.paid_at) });
    case "payment.create":
      return t("audit.created", {
        name: d.name,
        amount: money(d.amount, d.currency),
        period: d.period ? `${periodLabel(d.period).toLowerCase()}, ` : "",
        date: fmtDate(d.first_due_date),
      });
    case "payment.update":
      return [
        d.name_before ? `${d.name_before} → ${d.name}` : d.name,
        d.amount_before ? t("audit.amountChanged", { before: money(d.amount_before, d.currency), after: money(d.amount, d.currency) }) : "",
        d.first_due_date_before ? t("audit.scheduleChanged", { period: periodLabel(d.period).toLowerCase(), date: fmtDate(d.first_due_date) }) : "",
      ].filter(Boolean).join(", ");
    case "payment.pause":
      return [d.name, d.until ? t("audit.until", { date: fmtDate(d.until) }) : ""].filter(Boolean).join(", ");
    case "payment.resume":
    case "payment.delete":
      return d.name;
    case "user.create":
    case "user.delete":
      return d.login;
    case "user.update":
      return [d.login_before ? `${d.login_before} → ${d.login}` : d.login, d.password_changed ? t("audit.passwordChanged") : ""].filter(Boolean).join(", ");
    case "messenger.link":
    case "messenger.unlink":
      return `${MESSENGER_TITLES[d.messenger] || d.messenger}: ${d.account || ""}`;
    case "reminder.sent":
    case "reminder.overdue_sent":
      return t("audit.channel", { name: d.name, due, channel: d.channel });
    case "receipt.add":
    case "receipt.delete":
      return [d.title || d.filename || d.url, d.name].filter(Boolean).join(" · ");
    case "auth.login_failed":
      return t("audit.failed");
    case "auth.login_locked":
      return d.minutes ? t("audit.locked", { minutes: d.minutes }) : "";
    case "auth.otp_failed":
      return t("audit.otpFailed");
    case "auth.password_changed":
      return t("audit.sessionsClosed", { n: d.ended_sessions ?? 0 });
    case "auth.sessions_ended":
      return t("audit.sessionsClosed", { n: d.count ?? 0 });
    case "auth.session_ended":
    case "auth.password_failed":
      return "";
    case "token.create":
      return t("audit.token", { name: d.name, scope: t(`account.scope.${d.scope}`) });
    case "token.revoke":
      return d.name || "";
    default:
      return d && Object.keys(d).length ? JSON.stringify(d) : "";
  }
}

const AUDIT_GROUPS = ["", "auth.", "occurrence.", "payment.", "user.", "reminder.", "messenger.", "token."];
const AUDIT_BAD = new Set(["auth.login_failed", "auth.login_locked", "auth.otp_failed", "auth.password_failed"]);
const AUDIT_PERIODS = ["", "1", "7", "30"];

const auditState = { group: "", period: "" };

async function auditView(main) {
  const PAGE = 100;
  const listBox = h("div", { class: "table-card" }, skeletonRows());
  const more = h("button", { class: "btn", type: "button" }, t("common.showMore"));
  const moreWrap = h("div", { class: "more-wrap", hidden: true }, more);
  let offset = 0;
  let rows = [];

  function params() {
    const since = auditState.period
      ? new Date(Date.now() - (Number(auditState.period) - 1) * 86400000).toISOString().slice(0, 10)
      : undefined;
    return { action: auditState.group || undefined, since, limit: PAGE, offset };
  }

  function draw(hasMore) {
    listBox.replaceChildren(
      rows.length
        ? h(
            "table",
            {},
            h("thead", {}, h("tr", {}, h("th", {}, t("audit.colTime")), h("th", {}, t("audit.colWho")), h("th", {}, t("audit.colAction")), h("th", {}, t("audit.colDetails")), h("th", {}, t("audit.colIp")))),
            h(
              "tbody",
              {},
              rows.map((e) =>
                h(
                  "tr",
                  {},
                  h("td", { class: "title-cell num", "data-label": t("audit.colTime") }, fmtDateTime(e.at)),
                  h("td", { "data-label": t("audit.colWho") }, h("span", { class: `actor ${e.actor_type}` }, e.actor), " ", h("span", { class: "cell-sub" }, has(`actor.${e.actor_type}`) ? t(`actor.${e.actor_type}`) : e.actor_type)),
                  h("td", { "data-label": t("audit.colAction") }, h("span", { class: `act ${AUDIT_BAD.has(e.action) ? "bad" : ""}` }, has(`action.${e.action}`) ? t(`action.${e.action}`) : e.action)),
                  h("td", { "data-label": t("audit.colDetails"), class: "details-cell" }, auditSummary(e)),
                  h("td", { "data-label": t("audit.colIp"), class: "num muted" }, e.ip || "—"),
                ),
              ),
            ),
          )
        : h("div", { class: "empty" }, h("strong", {}, t("audit.empty")), t("audit.emptyText")),
    );
    moreWrap.hidden = !hasMore;
  }

  async function load(reset) {
    if (reset) {
      offset = 0;
      rows = [];
    }
    const page = await api("/audit-log", { params: params() });
    rows = rows.concat(page);
    offset = rows.length;
    draw(page.length === PAGE);
  }

  more.addEventListener("click", async () => {
    setBusy(more, true);
    try {
      await load(false);
    } catch (err) {
      report(err);
    } finally {
      setBusy(more, false);
    }
  });

  const groupKey = (g) => (g ? `audit.f.${g.slice(0, -1)}` : "audit.f.all");
  const toolbar = h(
    "div",
    { class: "toolbar" },
    segmented(AUDIT_GROUPS.map((g) => ({ value: g, label: t(groupKey(g)) })), auditState.group, (v) => { auditState.group = v; load(true).catch(report); }),
    segmented(AUDIT_PERIODS.map((p) => ({ value: p, label: t(p ? `audit.p.${p}` : "audit.p.all") })), auditState.period, (v) => { auditState.period = v; load(true).catch(report); }),
  );

  main.replaceChildren(pageHead(t("tab.audit"), t("audit.lead")), toolbar, listBox, moreWrap);
  await load(true);
}

// ---------- раздел «Аккаунт» ----------

const TOKEN_TTLS = ["30", "90", "365", ""];

// Короткое имя устройства из User-Agent: браузер и система без версий
function deviceLabel(ua) {
  if (!ua) return t("account.unknownDevice");
  const pick = (marks) => (marks.find(([mark]) => ua.includes(mark)) || [])[1];
  const browser = pick([["Edg/", "Edge"], ["OPR/", "Opera"], ["YaBrowser/", "Yandex Browser"], ["Firefox/", "Firefox"], ["Chrome/", "Chrome"], ["Safari/", "Safari"], ["curl/", "curl"]]);
  const os = pick([["Windows", "Windows"], ["Android", "Android"], ["iPhone", "iOS"], ["iPad", "iPadOS"], ["Mac OS X", "macOS"], ["Linux", "Linux"]]);
  const parts = [browser, os].filter(Boolean);
  return parts.length ? parts.join(", ") : ua.slice(0, 60);
}

function copyButton(text, done) {
  return h(
    "button",
    {
      class: "btn btn-sm",
      type: "button",
      onclick: async () => {
        try {
          await navigator.clipboard.writeText(text);
          toast(done);
        } catch {
          toast(t("msg.copyFailed"), "error");
        }
      },
    },
    t("msg.copy"),
  );
}

async function accountView(main) {
  const isAdmin = state.me.role === "admin";
  const sessionsBox = h("div", { class: "table-card" }, skeletonRows(2));
  const sessionsTools = h("div", { class: "toolbar" });
  const tokensBox = h("div", { class: "table-card" }, skeletonRows(2));

  async function reloadSessions() {
    const sessions = await api("/auth/sessions");
    sessionsTools.replaceChildren(
      ...(sessions.length > 1
        ? [h("button", { type: "button", class: "btn btn-danger", onclick: () => endOthersDialog(reloadSessions) }, t("account.endOthers"))]
        : []),
    );
    const cols = ["colCreated", "colSeen", "colExpires"].map((key) => t(`account.${key}`));
    sessionsBox.replaceChildren(
      h(
        "table",
        {},
        h("thead", {}, h("tr", {}, h("th", {}, t("account.colDevice")), cols.map((c) => h("th", {}, c)), h("th", {}, ""))),
        h(
          "tbody",
          {},
          sessions.map((s) =>
            h(
              "tr",
              {},
              h(
                "td",
                { class: "title-cell" },
                h("div", { class: "cell-title" }, deviceLabel(s.user_agent)),
                h("div", { class: "cell-sub" }, s.ip || "—"),
                s.current ? h("span", { class: "badge paid" }, t("account.current")) : null,
              ),
              h("td", { "data-label": cols[0], class: "num" }, fmtDateTime(s.created_at)),
              h("td", { "data-label": cols[1], class: "num" }, s.last_seen_at ? fmtDateTime(s.last_seen_at) : "—"),
              h("td", { "data-label": cols[2], class: "num" }, fmtDateTime(s.expires_at)),
              h(
                "td",
                { class: "actions" },
                s.current ? null : h("button", { class: "btn btn-sm btn-danger", onclick: () => endSessionDialog(s, reloadSessions) }, t("account.end")),
              ),
            ),
          ),
        ),
      ),
    );
  }

  async function reloadTokens() {
    const tokens = await api("/me/tokens");
    const cols = ["colScope", "colToken", "colIssued", "colUsed", "colExpires"].map((key) => t(`account.${key}`));
    const expires = (tk) => {
      if (!tk.expires_at) return h("span", { class: "muted" }, t("account.forever"));
      if (new Date(tk.expires_at) <= new Date()) return h("span", { class: "badge overdue" }, t("account.expired"));
      return fmtDateTime(tk.expires_at);
    };
    tokensBox.replaceChildren(
      tokens.length
        ? h(
            "table",
            {},
            h("thead", {}, h("tr", {}, h("th", {}, t("account.colName")), cols.map((c) => h("th", {}, c)), h("th", {}, ""))),
            h(
              "tbody",
              {},
              tokens.map((tk) =>
                h(
                  "tr",
                  {},
                  h("td", { class: "title-cell" }, h("div", { class: "cell-title" }, tk.name)),
                  h("td", { "data-label": cols[0] }, h("span", { class: `badge ${tk.scope === "write" ? "soon" : ""}` }, t(`account.scope.${tk.scope}`))),
                  h("td", { "data-label": cols[1], class: "num" }, h("code", {}, `${tk.prefix}…`)),
                  h("td", { "data-label": cols[2], class: "num" }, fmtDateTime(tk.created_at)),
                  h("td", { "data-label": cols[3], class: "num" }, tk.last_used_at ? fmtDateTime(tk.last_used_at) : h("span", { class: "muted" }, t("account.neverUsed"))),
                  h("td", { "data-label": cols[4], class: "num" }, expires(tk)),
                  h("td", { class: "actions" }, h("button", { class: "btn btn-sm btn-danger", onclick: () => revokeTokenDialog(tk, reloadTokens) }, t("account.revoke"))),
                ),
              ),
            ),
          )
        : h("div", { class: "empty" }, h("strong", {}, t("account.tokensEmpty")), t("account.tokensEmptyText")),
    );
  }

  const newToken = h("button", { type: "button", class: "btn btn-primary", onclick: () => createTokenDialog(reloadTokens) }, icon("plus"), t("account.newToken"));

  main.replaceChildren(
    pageHead(t("tab.account"), t("account.lead")),
    isAdmin ? section(t("account.admin"), adminSignInCards()) : passwordForm(reloadSessions),
    section(t("account.sessions"), h("p", { class: "section-lead" }, t("account.sessionsLead")), sessionsBox, sessionsTools),
    section(t("account.tokens"), h("p", { class: "section-lead" }, t("account.tokensLead")), h("div", { class: "toolbar" }, newToken), tokensBox),
  );
  await Promise.all([reloadSessions(), reloadTokens()]);
}

function passwordForm(reloadSessions) {
  const form = h(
    "form",
    { class: "inline-form", novalidate: true },
    h("h3", {}, t("account.password")),
    h("p", { class: "section-lead" }, t("account.passwordLead")),
    h(
      "div",
      { class: "form-grid" },
      field({ label: t("field.current_password"), name: "current_password", type: "password", autocomplete: "current-password" }),
      field({ label: t("field.new_password"), name: "new_password", type: "password", autocomplete: "new-password", placeholder: t("users.passwordPlaceholder") }),
      field({ label: t("account.repeat"), name: "repeat", type: "password", autocomplete: "new-password" }),
      h("button", { type: "submit", class: "btn btn-primary" }, t("account.changePassword")),
    ),
    h("p", { class: "form-error", role: "alert" }),
  );

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const error = form.querySelector(".form-error");
    const submit = form.querySelector("button[type=submit]");
    const data = new FormData(form);
    const current = String(data.get("current_password"));
    const next = String(data.get("new_password"));
    error.textContent = "";
    try {
      if (!current) throw new Error(t("check.credentials"));
      checkPassword(next);
      if (next !== String(data.get("repeat"))) throw new Error(t("account.mismatch"));
      if (next === current) throw new Error(t("account.samePassword"));
      setBusy(submit, true);
      const result = await api("/auth/password", { method: "POST", body: { current_password: current, new_password: next } });
      toast(result.ended_sessions ? t("account.passwordChangedEnded", { sessions: plural(result.ended_sessions, "session") }) : t("account.passwordChanged"));
      form.reset();
      await reloadSessions();
    } catch (err) {
      error.textContent = err.message;
    } finally {
      setBusy(submit, false);
    }
  });
  return form;
}

function adminSignInCards() {
  const on = Boolean(state.me.two_factor);
  const command = "docker compose exec app python -m app.services.totp";
  return h(
    "div",
    { class: "msg-grid" },
    h("article", { class: "tile msg-card" }, h("div", { class: "tile-head" }, h("h3", {}, t("account.adminPassword"))), h("p", {}, t("account.adminPasswordText"))),
    h(
      "article",
      { class: `tile msg-card ${on ? "is-linked" : ""}` },
      h("div", { class: "tile-head" }, h("h3", {}, t("account.twoFactor")), h("span", { class: `badge ${on ? "paid" : ""}` }, t(on ? "account.on" : "account.off"))),
      h("p", {}, t(on ? "account.twoFactorOnText" : "account.twoFactorOffText")),
      on ? null : h("div", { class: "msg-command" }, h("code", {}, command), copyButton(command, t("account.tokenCopied"))),
    ),
  );
}

function endSessionDialog(s, reload) {
  openDialog({
    title: t("account.endTitle"),
    description: t("account.endDesc", { device: deviceLabel(s.user_agent) }),
    confirmLabel: t("account.end"),
    danger: true,
    onSubmit: async () => {
      await api(`/auth/sessions/${s.id}`, { method: "DELETE" });
      toast(t("account.ended"));
      await reload();
    },
  });
}

function endOthersDialog(reload) {
  openDialog({
    title: t("account.endOthersTitle"),
    description: t("account.endOthersDesc"),
    confirmLabel: t("account.endOthers"),
    danger: true,
    onSubmit: async () => {
      const result = await api("/auth/sessions/end-others", { method: "POST" });
      toast(t("account.endedOthers", { sessions: plural(result.ended, "session") }));
      await reload();
    },
  });
}

function createTokenDialog(reload) {
  const option = (value, label, selected = false) => h("option", { value, selected }, label);
  openDialog({
    title: t("account.newToken"),
    confirmLabel: t("account.create"),
    fields: [
      field({ label: t("account.colName"), name: "name", maxlength: "64", placeholder: t("account.tokenNamePlaceholder"), hint: t("account.tokenNameHint") }),
      selectField(t("field.scope"), "scope", [option("read", t("account.scope.read"), true), option("write", t("account.scope.write"))]),
      selectField(
        t("field.expires_in_days"),
        "expires_in_days",
        TOKEN_TTLS.map((days) => option(days, t(`account.ttl.${days || "never"}`), days === "90")),
      ),
    ],
    onSubmit: async (data) => {
      const name = String(data.get("name")).trim();
      if (!name) throw new Error(t("check.tokenName"));
      const days = String(data.get("expires_in_days"));
      const created = await api("/me/tokens", {
        method: "POST",
        body: { name, scope: String(data.get("scope")), expires_in_days: days ? Number(days) : null },
      });
      await reload();
      showTokenDialog(created);
    },
  });
}

// Сам токен виден только здесь: сервер хранит лишь хэш и повторно его не отдаёт
function showTokenDialog(created) {
  const example = `curl -H "Authorization: Bearer ${created.token}" ${location.origin}${API}/payments/summary`;
  const dialog = h(
    "dialog",
    {},
    h(
      "div",
      { class: "rc-dialog" },
      h("h2", {}, t("account.tokenTitle", { name: created.name })),
      h("p", { class: "desc" }, t("account.tokenOnce")),
      h("div", { class: "msg-command" }, h("code", {}, created.token), copyButton(created.token, t("account.tokenCopied"))),
      h("p", { class: "msg-alt" }, t("account.tokenExample")),
      h("div", { class: "msg-command" }, h("code", {}, example), copyButton(example, t("account.tokenCopied"))),
      h("div", { class: "dialog-actions" }, h("button", { class: "btn", type: "button", onclick: () => dialog.close() }, t("common.close"))),
    ),
  );
  presentDialog(dialog);
}

function revokeTokenDialog(tk, reload) {
  openDialog({
    title: t("account.revokeTitle"),
    description: t("account.revokeDesc", { name: tk.name }),
    confirmLabel: t("account.revoke"),
    danger: true,
    onSubmit: async () => {
      await api(`/me/tokens/${tk.id}`, { method: "DELETE" });
      toast(t("account.revoked", { name: tk.name }));
      await reload();
    },
  });
}

// ---------- раздел «Помощь» ----------

const ADMIN_TABS = new Set(["recurring", "users", "audit"]);
const HELP_FAQ = ["pay", "wrongOverdue", "undo", "noReminder", "personal", "commands", "currency", "edit", "stop", "csv", "password", "api"];

async function helpView(main) {
  const info = await api("/help");
  const isAdmin = state.me.role === "admin";
  const days = plural(info.reminder_days, "day");
  const roleKey = (key) => (has(`${key}.${state.me.role}`) ? `${key}.${state.me.role}` : key);

  const overview = h(
    "div",
    { class: "help-grid" },
    tabsFor(state.me)
      .filter((tab) => tab.id !== "help")
      .map((tab) =>
        h(
          "article",
          { class: "tile help-card" },
          h("h3", {}, icon(tab.icon), t(`tab.${tab.id}`)),
          h("p", {}, t(roleKey(`help.about.${tab.id}`)), ADMIN_TABS.has(tab.id) ? h("span", { class: "help-note" }, ` · ${t("help.adminOnly")}`) : null),
          h("button", { type: "button", class: "btn btn-sm", onclick: () => navigate(tab.id).catch(report) }, t("help.open")),
        ),
      ),
  );

  const channels = info.channels.map((c) => t(`help.channel.${c}`));
  const rules = h(
    "ul",
    { class: "help-rules" },
    h("li", {}, t("help.rule.reminder", { days })),
    info.overdue_reminders ? h("li", {}, t("help.rule.overdueNotice")) : null,
    h("li", {}, t("help.rule.overdue")),
    h("li", {}, t("help.rule.periods")),
    h("li", {}, t("help.rule.currency")),
    h("li", {}, t("help.rule.timezone", { tz: info.timezone })),
    h("li", {}, channels.length ? t("help.rule.channels", { list: channels.join(", ") }) : t("help.rule.noChannels")),
  );

  const faq = h(
    "div",
    { class: "faq" },
    HELP_FAQ.map((key) =>
      h(
        "details",
        { class: "faq-item" },
        h("summary", {}, h("span", {}, t(`help.q.${key}`)), icon("chevronRight")),
        h("div", { class: "faq-answer" }, t(roleKey(`help.a.${key}`), { days })),
      ),
    ),
  );

  const securityKeys = ["access", "roles", "admin", "passwords", "sessions", "twofactor", "tokens", "bruteforce", "audit", "receipts", "bots"];
  if (isAdmin) securityKeys.push("secrets");
  securityKeys.push("tip");
  const security = h(
    "ul",
    { class: "help-rules" },
    securityKeys.map((key) => h("li", {}, t(roleKey(`help.sec.${key}`)))),
  );

  const link = (c) => h("a", { href: c.url, target: "_blank", rel: "noopener" }, c.label);
  const supportLinks = [info.contacts.telegram, info.contacts.email, info.contacts.url].filter(Boolean);
  const card = (title, text, ...links) =>
    h("article", { class: "tile help-card" }, h("h3", {}, title), h("p", {}, text), links.length ? h("div", { class: "help-links" }, links) : null);
  const contacts = h(
    "div",
    { class: "help-grid" },
    card(t("help.admin.title"), t(isAdmin ? "help.admin.text.admin" : "help.admin.text.user")),
    supportLinks.length
      ? card(t("help.support.title"), t("help.support.text"), ...supportLinks.map(link))
      : isAdmin
        ? card(t("help.support.title"), t("help.support.none"))
        : null,
    Object.keys(info.bots).length ? card(t("help.bots.title"), t("help.bots.text"), ...Object.values(info.bots).map(link)) : null,
    card(t("help.api.title"), t("help.api.text"), link({ url: `${API}/docs`, label: t("help.api.link") })),
  );

  main.replaceChildren(
    pageHead(t("tab.help"), t("help.lead")),
    section(t("help.overview"), overview),
    section(t("help.rules"), rules),
    section(t("help.faq"), faq),
    section(t("help.security"), security),
    section(t("help.contacts"), contacts),
  );
}

// ---------- раздел «Мессенджеры» ----------

const MESSENGER_TITLES = { telegram: "Telegram", max: "MAX" };

async function messengersView(main) {
  const cards = h("div", { class: "msg-grid" }, skeletonTileList(2));

  async function reload() {
    const items = await api("/me/messengers");
    cards.replaceChildren(...items.map((m) => messengerCard(m, reload)));
    return items;
  }

  main.replaceChildren(pageHead(t("tab.messengers"), t("msg.lead")), cards);
  await reload();
}

function messengerCard(m, reload) {
  let status;
  if (!m.available) status = h("p", { class: "muted" }, t("msg.notConfigured"));
  else if (m.linked) status = h("p", {}, t("msg.linkedTo"), h("b", {}, m.account), h("span", { class: "muted" }, t("msg.since", { date: fmtDateTime(m.linked_at) })));
  else status = h("p", { class: "muted" }, t("msg.notLinkedText"));

  const actions = [];
  if (m.available) {
    actions.push(h("button", { class: `btn ${m.linked ? "" : "btn-accent"}`, type: "button", onclick: () => linkDialog(m, reload) }, m.linked ? t("msg.linkOther") : t("msg.link")));
  }
  if (m.linked) {
    actions.push(
      h(
        "button",
        {
          class: "btn btn-danger",
          type: "button",
          onclick: () =>
            openDialog({
              title: t("msg.unlinkTitle", { title: m.title }),
              description: t("msg.unlinkDesc", { title: m.title }),
              confirmLabel: t("msg.unlink"),
              danger: true,
              onSubmit: async () => {
                await api(`/me/messengers/${m.messenger}`, { method: "DELETE" });
                toast(t("msg.unlinked", { title: m.title }));
                await reload();
              },
            }),
        },
        t("msg.unlink"),
      ),
    );
  }
  return h(
    "article",
    { class: `tile msg-card ${m.linked ? "is-linked" : ""}` },
    h("div", { class: "tile-head" }, h("h3", {}, m.title), h("span", { class: `badge ${m.linked ? "paid" : ""}` }, m.linked ? t("msg.linked") : t("msg.notLinked"))),
    status,
    h("div", { class: "msg-actions" }, actions),
  );
}

async function linkDialog(m, reload) {
  let link;
  try {
    link = await api(`/me/messengers/${m.messenger}/link`, { method: "POST" });
  } catch (err) {
    report(err);
    return;
  }
  const until = new Date(link.expires_at).toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit" });
  const wait = h("p", { class: "muted msg-wait" }, t("msg.wait"));
  const copy = h(
    "button",
    {
      class: "btn btn-sm",
      type: "button",
      onclick: async () => {
        try {
          await navigator.clipboard.writeText(link.command);
          toast(t("msg.copied"));
        } catch {
          toast(t("msg.copyFailed"), "error");
        }
      },
    },
    t("msg.copy"),
  );
  const dialog = h(
    "dialog",
    {},
    h(
      "div",
      { class: "rc-dialog" },
      h("h2", {}, t("msg.linkTitle", { title: m.title })),
      h("p", { class: "desc" }, link.url ? t("msg.linkByUrl", { until }) : t("msg.linkByCommand", { title: m.title, until })),
      link.url ? h("a", { class: "btn btn-accent btn-block", href: link.url, target: "_blank", rel: "noopener noreferrer" }, t("msg.open", { title: m.title })) : null,
      link.url ? h("p", { class: "msg-alt" }, t("msg.alt")) : null,
      h("div", { class: "msg-command" }, h("code", {}, link.command), copy),
      wait,
      h("div", { class: "dialog-actions" }, h("button", { class: "btn", type: "button", onclick: () => dialog.close() }, t("common.close"))),
    ),
  );
  // ждём, пока бот примет код: раз в 3 секунды, пока окно открыто и ссылка жива
  const timer = setInterval(async () => {
    if (Date.now() > new Date(link.expires_at).getTime()) {
      wait.textContent = t("msg.expired");
      wait.classList.add("done");
      clearInterval(timer);
      return;
    }
    try {
      const items = await api("/me/messengers");
      const now = items.find((x) => x.messenger === m.messenger);
      if (now && now.linked && now.account !== m.account) {
        clearInterval(timer);
        toast(t("msg.done", { title: m.title, account: now.account }));
        dialog.close();
        await reload();
      }
    } catch {
      /* попробуем на следующем шаге */
    }
  }, 3000);
  presentDialog(dialog, () => clearInterval(timer));
}

// ---------- старт ----------

document.addEventListener("click", (event) => {
  for (const el of document.querySelectorAll(".picker.open")) if (!el.contains(event.target)) closePickers();
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  closePickers();
  setNavOpen(false);
});

async function bootstrap() {
  setTitle();
  try {
    state.me = await api("/auth/me", { silent: true });
  } catch {
    state.me = null;
  }
  if (state.me) await showApp();
  else showLogin();
}

bootstrap();
