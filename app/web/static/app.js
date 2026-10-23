// Invoice Keeper: панель без сборки и внешних зависимостей.
// Все данные в DOM попадают через textContent, поэтому названия платежей не могут внедрить разметку.

const API = "/api/v1";
const CURRENCIES = ["RUB", "USD", "EUR"];
const CURRENCY_NAMES = { RUB: "Российский рубль", USD: "Доллар США", EUR: "Евро" };
const SOON_DAYS = 3;

const state = {
  me: null,
  asOf: null, // «сегодня» по часовому поясу сервера
  tab: "payments",
  filters: { status: "all", currency: "", scope: "all", deleted: false, on: "" },
  cal: null, // { year, month, selected }
  budgetYear: null,
};

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

function toast(message, kind = "ok") {
  const el = h("div", { class: `toast ${kind === "error" ? "error" : ""}` }, message);
  document.getElementById("toasts").append(el);
  setTimeout(() => el.remove(), kind === "error" ? 6500 : 3500);
}

// ---------- форматирование ----------

function money(value, currency) {
  return new Intl.NumberFormat("ru-RU", { style: "currency", currency }).format(Number(value));
}

function fmtDate(iso) {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-");
  return `${d}.${m}.${y}`;
}

function fmtDateTime(iso) {
  return new Date(iso).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" });
}

function diffDays(fromIso, toIso) {
  const parse = (s) => Date.UTC(...s.split("-").map((n, i) => (i === 1 ? Number(n) - 1 : Number(n))));
  return Math.round((parse(toIso) - parse(fromIso)) / 86400000);
}

function plural(n, forms) {
  const mod10 = n % 10;
  const mod100 = n % 100;
  const form = mod10 === 1 && mod100 !== 11 ? 0 : mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20) ? 1 : 2;
  return `${n} ${forms[form]}`;
}

function monthRange(iso) {
  const [y, m] = iso.split("-").map(Number);
  const last = new Date(Date.UTC(y, m, 0)).getUTCDate();
  const mm = String(m).padStart(2, "0");
  return { due_from: `${y}-${mm}-01`, due_to: `${y}-${mm}-${String(last).padStart(2, "0")}` };
}

// ---------- API ----------

class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

const FIELD_NAMES = {
  login: "Логин",
  password: "Пароль",
  name: "Название",
  amount: "Сумма",
  currency: "Валюта",
  first_due_date: "Дата ближайшей оплаты",
  status: "Статус",
  paid_at: "Дата оплаты",
};

const VALIDATION_TEXT = {
  string_too_short: "слишком короткое значение",
  string_too_long: "слишком длинное значение",
  string_pattern_mismatch: "недопустимые символы",
  greater_than: "должно быть больше нуля",
  decimal_max_places: "не больше двух знаков после запятой",
  decimal_parsing: "неверное число",
  decimal_type: "неверное число",
  decimal_max_digits: "слишком большое число",
  extra_forbidden: "поле не поддерживается",
  missing: "обязательное поле",
  date_parsing: "неверная дата",
  date_from_datetime_parsing: "неверная дата",
  enum: "недопустимое значение",
};

function explain(data, status) {
  const detail = data && data.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((e) => {
        const field = e.loc && e.loc[e.loc.length - 1];
        return `${FIELD_NAMES[field] || field}: ${VALIDATION_TEXT[e.type] || e.msg}`;
      })
      .join("; ");
  }
  return `Ошибка сервера (${status})`;
}

async function api(path, { method = "GET", body, params, silent = false } = {}) {
  const url = new URL(API + path, location.origin);
  for (const [key, value] of Object.entries(params || {})) {
    if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, value);
  }

  let response;
  try {
    response = await fetch(url, {
      method,
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
      credentials: "same-origin",
    });
  } catch {
    throw new ApiError(0, "Нет связи с сервером");
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
    throw new ApiError(response.status, explain(data, response.status));
  }
  return data;
}

// ---------- модальные окна ----------

function field({ label, name, type = "text", value = "", hint, required = true, ...rest }) {
  return h(
    "label",
    { class: "field" },
    h("span", {}, label),
    h("input", { name, type, value, required, ...rest }),
    hint ? h("span", { class: "hint" }, hint) : null,
  );
}

function openDialog({ title, description, fields = [], confirmLabel = "Сохранить", danger = false, onSubmit }) {
  const error = h("p", { class: "form-error", role: "alert" });
  const submit = h("button", { type: "submit", class: `btn btn-primary ${danger ? "btn-danger" : ""}` }, confirmLabel);
  const cancel = h("button", { type: "button", class: "btn", onclick: () => dialog.close() }, "Отмена");
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
    submit.disabled = true;
    try {
      await onSubmit(new FormData(form));
      dialog.close();
    } catch (err) {
      error.textContent = err.message;
      submit.disabled = false;
    }
  });
  dialog.addEventListener("close", () => dialog.remove());
  document.body.append(dialog);
  dialog.showModal();
  const first = form.querySelector("input");
  if (first) first.focus();
}

// ---------- валидация на клиенте (сервер проверяет всё то же самое) ----------

function parseAmount(raw) {
  const text = String(raw).trim().replace(",", ".");
  if (!/^\d{1,10}(\.\d{1,2})?$/.test(text) || Number(text) <= 0) {
    throw new Error("Сумма: положительное число, не больше двух знаков после запятой");
  }
  return text;
}

function checkLogin(login) {
  if (!/^[A-Za-z0-9._@-]{3,64}$/.test(login)) {
    throw new Error("Логин: 3–64 символа, латиница, цифры и . _ @ -");
  }
}

function checkPassword(password) {
  if (password.length < 8 || password.length > 128) throw new Error("Пароль: от 8 до 128 символов");
}

// ---------- вход и выход ----------

function sessionExpired() {
  if (!state.me) return;
  state.me = null;
  showLogin("Сессия закончилась, войдите снова");
}

function showLogin(notice = "") {
  const error = h("p", { class: "form-error", role: "alert" }, notice);
  const submit = h("button", { type: "submit", class: "btn btn-primary btn-block" }, "Войти");
  const form = h(
    "form",
    { novalidate: true },
    field({ label: "Логин", name: "login", autocomplete: "username", autocapitalize: "none", spellcheck: "false" }),
    field({ label: "Пароль", name: "password", type: "password", autocomplete: "current-password" }),
    error,
    submit,
  );

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(form);
    const login = String(data.get("login")).trim();
    const password = String(data.get("password"));
    if (!login || !password) {
      error.textContent = "Введите логин и пароль";
      return;
    }
    error.textContent = "";
    submit.disabled = true;
    try {
      const result = await api("/auth/login", { method: "POST", body: { login, password }, silent: true });
      state.me = result.user;
      state.tab = "payments";
      await showApp();
    } catch (err) {
      error.textContent = err.status === 401 ? "Неверный логин или пароль" : err.message;
      submit.disabled = false;
    }
  });

  app().replaceChildren(
    h(
      "div",
      { class: "login-wrap" },
      h(
        "div",
        { class: "login-card" },
        brand(),
        h("h1", {}, "Вход в панель"),
        h("p", { class: "lead" }, "Платежи, сроки и напоминания в одном месте."),
        form,
      ),
    ),
  );
  form.querySelector("input").focus();
}

function brand() {
  return h(
    "div",
    { class: "brand" },
    h("img", { class: "brand-mark", src: "/static/brand/logo-mark.svg", alt: "", width: 38, height: 38 }),
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

// ---------- каркас ----------

function tabsFor(me) {
  const tabs = [
    { id: "payments", label: "Платежи" },
    { id: "calendar", label: "Календарь" },
    { id: "budget", label: "Бюджет" },
  ];
  if (me.role === "admin") {
    tabs.push({ id: "recurring", label: "Регулярные платежи" }, { id: "users", label: "Пользователи" }, { id: "audit", label: "Журнал" });
  }
  return tabs;
}

async function showApp() {
  const summary = await api("/payments/summary");
  state.asOf = summary.as_of;

  const main = h("main", { id: "view" });
  const tabButtons = tabsFor(state.me).map((tab) =>
    h(
      "button",
      {
        class: "tab",
        role: "tab",
        "data-tab": tab.id,
        "aria-selected": String(tab.id === state.tab),
        onclick: () => {
          state.tab = tab.id;
          for (const btn of tabButtons) btn.setAttribute("aria-selected", String(btn.dataset.tab === tab.id));
          loadTab(main);
        },
      },
      tab.label,
    ),
  );

  const header = h(
    "header",
    { class: "topbar" },
    h(
      "div",
      { class: "topbar-inner" },
      brand(),
      h(
        "div",
        { class: "user-box" },
        h(
          "div",
          { class: "who" },
          h("span", {}, state.me.login, " ", h("span", { class: "role-badge" }, state.me.role === "admin" ? "админ" : "пользователь")),
          h("small", {}, `Сегодня ${fmtDate(state.asOf)}`),
        ),
        h("button", { class: "btn btn-sm", onclick: logout }, "Выйти"),
      ),
    ),
    h("nav", { class: "tabs", role: "tablist" }, tabButtons),
  );

  app().replaceChildren(header, main);
  await loadTab(main);
}

async function loadTab(main) {
  main.replaceChildren(h("p", { class: "loading" }, "Загрузка…"));
  try {
    if (state.tab === "calendar") await calendarView(main);
    else if (state.tab === "budget") await budgetView(main);
    else if (state.tab === "recurring" && state.me.role === "admin") await recurringView(main);
    else if (state.tab === "users" && state.me.role === "admin") await usersView(main);
    else if (state.tab === "audit" && state.me.role === "admin") await auditView(main);
    else await paymentsView(main);
  } catch (err) {
    if (err.status !== 401) main.replaceChildren(h("div", { class: "empty" }, h("strong", {}, "Не удалось загрузить данные"), err.message));
  }
}

// ---------- раздел «Платежи» ----------

function statusOf(o) {
  if (o.status === "paid") {
    return o.is_overdue ? { cls: "late", text: "Оплачено позже срока" } : { cls: "paid", text: "Оплачено" };
  }
  if (o.is_overdue) return { cls: "overdue", text: `Просрочено ${o.overdue_days} дн.` };
  if (diffDays(state.asOf, o.due_date) <= SOON_DAYS) return { cls: "soon", text: "Скоро срок" };
  return { cls: "", text: "Не оплачено" };
}

function dueNote(o) {
  if (o.status === "paid") return null;
  const left = diffDays(state.asOf, o.due_date);
  if (left < 0) return { text: `просрочено на ${plural(-left, ["день", "дня", "дней"])}`, bad: true };
  if (left === 0) return { text: "сегодня" };
  if (left === 1) return { text: "завтра" };
  return { text: `через ${plural(left, ["день", "дня", "дней"])}` };
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

function summaryCard(c, onDate = null) {
  const row = (label, value, cls = "") => h("div", { class: "sum-row" }, h("span", {}, label), h("span", { class: `num ${cls}` }, value));
  return h(
    "article",
    { class: `card sum-card ${c.count_overdue > 0 ? "has-overdue" : ""}` },
    h("div", { class: "sum-head" }, h("span", {}, c.currency), h("span", {}, onDate ? `на ${fmtDate(onDate)}` : CURRENCY_NAMES[c.currency])),
    h("div", { class: "sum-main num" }, money(c.unpaid, c.currency)),
    h("div", { class: "sum-sub" }, c.count_unpaid ? `к оплате · ${plural(c.count_unpaid, ["платёж", "платежа", "платежей"])}` : "к оплате · всё закрыто"),
    h(
      "div",
      { class: "sum-rows" },
      row("Просрочено", money(c.overdue, c.currency), c.count_overdue > 0 ? "bad" : ""),
      row("Оплачено", money(c.paid, c.currency), c.count_paid > 0 ? "ok" : ""),
    ),
  );
}

async function paymentsView(main) {
  const summaryBox = h("section", { class: "summary", "aria-label": "Итоги по валютам" });
  const listBox = h("div", { class: "card table-card" });
  const counter = h("span", { class: "muted grow" });

  async function reload() {
    const f = state.filters;
    const range = f.scope === "month" ? monthRange(state.asOf) : {};
    const [items, summary] = await Promise.all([
      api("/payment-occurrences", {
        params: {
          status: f.status === "paid" || f.status === "unpaid" ? f.status : undefined,
          overdue: f.status === "overdue" ? "true" : undefined,
          currency: f.currency,
          include_deleted: f.deleted ? "true" : undefined,
          limit: 1000,
          ...range,
        },
      }),
      api("/payments/summary", {
        params: { include_deleted: f.deleted ? "true" : undefined, on: f.on || undefined, ...(f.on ? {} : range) },
      }),
    ]);
    if (!f.on) state.asOf = summary.as_of;
    summaryBox.replaceChildren(...summary.currencies.map((c) => summaryCard(c, f.on ? summary.as_of : null)));
    counter.textContent = items.length ? `Показано: ${items.length}` : "";
    listBox.replaceChildren(items.length ? occurrencesTable(items, reload) : emptyPayments());
  }

  const currencySelect = h(
    "select",
    { "aria-label": "Валюта", onchange: (e) => { state.filters.currency = e.target.value; reload().catch(report); } },
    h("option", { value: "" }, "Все валюты"),
    CURRENCIES.map((c) => h("option", { value: c, selected: state.filters.currency === c }, c)),
  );

  const toolbar = h(
    "div",
    { class: "toolbar" },
    segmented(
      [
        { value: "all", label: "Все" },
        { value: "unpaid", label: "Не оплачено" },
        { value: "overdue", label: "Просрочено" },
        { value: "paid", label: "Оплачено" },
      ],
      state.filters.status,
      (v) => { state.filters.status = v; reload().catch(report); },
    ),
    segmented(
      [
        { value: "all", label: "Все периоды" },
        { value: "month", label: "Текущий месяц" },
      ],
      state.filters.scope,
      (v) => { state.filters.scope = v; reload().catch(report); },
    ),
    currencySelect,
    h(
      "label",
      { class: "check" },
      h("input", { type: "checkbox", checked: state.filters.deleted, onchange: (e) => { state.filters.deleted = e.target.checked; reload().catch(report); } }),
      "С прекращёнными",
    ),
    h(
      "label",
      { class: "check on-date" },
      "Итоги на дату",
      h("input", { type: "date", value: state.filters.on, "aria-label": "Итоги на дату", onchange: (e) => { state.filters.on = e.target.value; reload().catch(report); } }),
      state.filters.on ? h("button", { type: "button", class: "btn btn-sm btn-ghost", onclick: () => { state.filters.on = ""; loadTab(document.getElementById("view")); } }, "Сбросить") : null,
    ),
    counter,
  );

  main.replaceChildren(
    h("div", { class: "page-head" }, h("div", {}, h("h2", {}, "Платежи"), h("p", {}, "Что и когда оплатить, что уже оплачено и что просрочено"))),
    summaryBox,
    toolbar,
    listBox,
  );
  await reload();
}

function report(err) {
  if (err.status !== 401) toast(err.message, "error");
}

function emptyPayments() {
  const none = state.me.role === "admin" ? "Добавьте первый платёж в разделе «Регулярные платежи»." : "Администратор ещё не добавил платежи.";
  return h("div", { class: "empty" }, h("strong", {}, "Платежей по этим условиям нет"), none);
}

function occurrencesTable(items, reload) {
  return h(
    "table",
    {},
    h("thead", {}, h("tr", {}, h("th", {}, "Платёж"), h("th", { class: "right" }, "Сумма"), h("th", {}, "Срок"), h("th", {}, "Статус"), h("th", {}, "Оплачено"), h("th", {}, ""))),
    h("tbody", {}, items.map((o) => occurrenceRow(o, reload))),
  );
}

function occurrenceRow(o, reload) {
  const status = statusOf(o);
  const note = dueNote(o);
  const rowClass = [o.status === "unpaid" && o.is_overdue ? "row-overdue" : "", o.payment_deleted ? "row-deleted" : ""].join(" ");

  let actions = null;
  if (!o.payment_deleted) {
    actions =
      o.status === "unpaid"
        ? [h("button", { class: "btn btn-sm btn-primary", onclick: () => payDialog(o, reload, false) }, "Отметить оплату")]
        : [
            h("button", { class: "btn btn-sm", onclick: () => payDialog(o, reload, true) }, "Изменить дату"),
            h("button", { class: "btn btn-sm btn-danger", onclick: () => cancelDialog(o, reload) }, "Отменить"),
          ];
  }

  return h(
    "tr",
    { class: rowClass },
    h("td", { class: "title-cell" }, h("div", { class: "cell-title" }, o.name), o.payment_deleted ? h("div", { class: "cell-sub" }, "Платёж прекращён") : null),
    h("td", { class: "right", "data-label": "Сумма" }, h("span", { class: "amount num" }, money(o.amount, o.currency))),
    h("td", { "data-label": "Срок" }, h("div", {}, h("div", { class: "num" }, fmtDate(o.due_date)), note ? h("div", { class: `cell-sub ${note.bad ? "bad" : ""}` }, note.text) : null)),
    h("td", { "data-label": "Статус" }, h("span", { class: `badge ${status.cls}` }, status.text)),
    h("td", { "data-label": "Оплачено", class: "num" }, fmtDate(o.paid_at)),
    h("td", { class: "actions" }, actions),
  );
}

function payDialog(o, reload, editing) {
  openDialog({
    title: editing ? "Изменить дату оплаты" : "Отметить оплату",
    description: `${o.name}, срок ${fmtDate(o.due_date)}, ${money(o.amount, o.currency)}`,
    confirmLabel: editing ? "Сохранить" : "Оплачено",
    fields: [
      field({
        label: "Фактическая дата оплаты",
        name: "paid_at",
        type: "date",
        value: editing ? o.paid_at : state.asOf,
        max: state.asOf,
        hint: "Если оплатили не сегодня, укажите реальную дату: от неё считается просрочка",
      }),
    ],
    onSubmit: async (data) => {
      const paidAt = String(data.get("paid_at"));
      if (!paidAt) throw new Error("Укажите дату оплаты");
      const body = editing ? { paid_at: paidAt } : { status: "paid", paid_at: paidAt };
      await api(`/payment-occurrences/${o.id}`, { method: "PATCH", body });
      toast(editing ? "Дата оплаты обновлена" : "Оплата отмечена");
      await reload();
    },
  });
}

function cancelDialog(o, reload) {
  openDialog({
    title: "Отменить оплату?",
    description: `Период «${o.name}» за ${fmtDate(o.due_date)} снова станет неоплаченным, дата оплаты очистится.`,
    confirmLabel: "Отменить оплату",
    danger: true,
    onSubmit: async () => {
      await api(`/payment-occurrences/${o.id}`, { method: "PATCH", body: { status: "unpaid" } });
      toast("Оплата отменена");
      await reload();
    },
  });
}

// ---------- раздел «Регулярные платежи» (админ) ----------

async function recurringView(main) {
  const listBox = h("div", { class: "card table-card" });

  async function reload() {
    const [payments, unpaid] = await Promise.all([
      api("/recurring-payments"),
      api("/payment-occurrences", { params: { status: "unpaid", limit: 1000 } }),
    ]);
    const nextDue = new Map();
    for (const o of unpaid) if (!nextDue.has(o.recurring_id)) nextDue.set(o.recurring_id, o.due_date);

    listBox.replaceChildren(
      payments.length
        ? h(
            "table",
            {},
            h("thead", {}, h("tr", {}, h("th", {}, "Платёж"), h("th", { class: "right" }, "Сумма"), h("th", {}, "Периодичность"), h("th", {}, "Ближайший неоплаченный срок"), h("th", {}, ""))),
            h(
              "tbody",
              {},
              payments.map((p) => {
                const day = Number(p.first_due_date.split("-")[2]);
                const next = nextDue.get(p.id);
                return h(
                  "tr",
                  {},
                  h("td", { class: "title-cell" }, h("div", { class: "cell-title" }, p.name), h("div", { class: "cell-sub" }, `первый срок ${fmtDate(p.first_due_date)}`)),
                  h("td", { class: "right", "data-label": "Сумма" }, h("span", { class: "amount num" }, money(p.amount, p.currency))),
                  h("td", { "data-label": "Периодичность" }, h("div", {}, "Ежемесячно"), h("div", { class: "cell-sub" }, day > 28 ? `${day}-го числа, в коротких месяцах в последний день` : `${day}-го числа`)),
                  h("td", { "data-label": "Ближайший срок", class: "num" }, next ? fmtDate(next) : "—"),
                  h("td", { class: "actions" }, h("button", { class: "btn btn-sm btn-danger", onclick: () => deletePaymentDialog(p, reload) }, "Прекратить")),
                );
              }),
            ),
          )
        : h("div", { class: "empty" }, h("strong", {}, "Регулярных платежей пока нет"), "Добавьте аренду, подписку или оплату сервера формой выше."),
    );
  }

  const form = h(
    "form",
    { class: "card inline-form", novalidate: true },
    h("h3", {}, "Новый регулярный платёж", h("span", { class: "muted" }, " · повторяется ежемесячно")),
    h(
      "div",
      { class: "form-grid" },
      field({ label: "Название", name: "name", placeholder: "Аренда офиса", maxlength: "200" }),
      field({ label: "Сумма", name: "amount", inputmode: "decimal", placeholder: "45000.00" }),
      h(
        "label",
        { class: "field" },
        h("span", {}, "Валюта"),
        h("select", { name: "currency" }, CURRENCIES.map((c) => h("option", { value: c }, c))),
      ),
      field({ label: "Дата ближайшей оплаты", name: "first_due_date", type: "date", value: state.asOf }),
      h("button", { type: "submit", class: "btn btn-primary" }, "Добавить"),
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
      const name = String(data.get("name")).trim();
      if (!name) throw new Error("Название: укажите название платежа");
      const amount = parseAmount(data.get("amount"));
      const firstDue = String(data.get("first_due_date"));
      if (!firstDue) throw new Error("Дата ближайшей оплаты: укажите дату");
      submit.disabled = true;
      await api("/recurring-payments", { method: "POST", body: { name, amount, currency: data.get("currency"), first_due_date: firstDue } });
      toast(`Платёж «${name}» добавлен`);
      form.querySelector("[name=name]").value = "";
      form.querySelector("[name=amount]").value = "";
      await reload();
    } catch (err) {
      error.textContent = err.message;
    } finally {
      submit.disabled = false;
    }
  });

  main.replaceChildren(
    h("div", { class: "page-head" }, h("div", {}, h("h2", {}, "Регулярные платежи"), h("p", {}, "Добавленный платёж повторяется каждый месяц, напоминание приходит в Telegram за 3 дня до срока"))),
    form,
    listBox,
  );
  await reload();
}

function deletePaymentDialog(p, reload) {
  openDialog({
    title: "Прекратить платёж?",
    description: `«${p.name}» больше не будет создавать периоды и напоминания. История оплат сохранится.`,
    confirmLabel: "Прекратить",
    danger: true,
    onSubmit: async () => {
      await api(`/recurring-payments/${p.id}`, { method: "DELETE" });
      toast(`Платёж «${p.name}» прекращён`);
      await reload();
    },
  });
}

// ---------- раздел «Пользователи» (админ) ----------

async function usersView(main) {
  const listBox = h("div", { class: "card table-card" });

  async function reload() {
    const users = await api("/users");
    listBox.replaceChildren(
      users.length
        ? h(
            "table",
            {},
            h("thead", {}, h("tr", {}, h("th", {}, "Логин"), h("th", {}, "Создан"), h("th", {}, ""))),
            h(
              "tbody",
              {},
              users.map((u) =>
                h(
                  "tr",
                  {},
                  h("td", { class: "title-cell" }, h("div", { class: "cell-title" }, u.login)),
                  h("td", { "data-label": "Создан", class: "num" }, fmtDateTime(u.created_at)),
                  h(
                    "td",
                    { class: "actions" },
                    h("button", { class: "btn btn-sm", onclick: () => editUserDialog(u, reload) }, "Изменить"),
                    h("button", { class: "btn btn-sm btn-danger", onclick: () => deleteUserDialog(u, reload) }, "Удалить"),
                  ),
                ),
              ),
            ),
          )
        : h("div", { class: "empty" }, h("strong", {}, "Обычных пользователей пока нет"), "Создайте учётную запись формой выше, и команда сможет отмечать оплаты."),
    );
  }

  const form = h(
    "form",
    { class: "card inline-form", novalidate: true },
    h("h3", {}, "Новый пользователь"),
    h(
      "div",
      { class: "form-grid" },
      field({ label: "Логин", name: "login", autocomplete: "off", autocapitalize: "none", spellcheck: "false", placeholder: "ivan" }),
      field({ label: "Пароль", name: "password", type: "password", autocomplete: "new-password", placeholder: "не короче 8 символов" }),
      h("button", { type: "submit", class: "btn btn-primary" }, "Создать"),
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
      submit.disabled = true;
      await api("/users", { method: "POST", body: { login, password } });
      toast(`Пользователь «${login}» создан`);
      form.reset();
      await reload();
    } catch (err) {
      error.textContent = err.message;
    } finally {
      submit.disabled = false;
    }
  });

  main.replaceChildren(
    h("div", { class: "page-head" }, h("div", {}, h("h2", {}, "Пользователи"), h("p", {}, "Обычные учётные записи. Администратор задаётся в .env и здесь не показывается"))),
    form,
    listBox,
  );
  await reload();
}

function editUserDialog(u, reload) {
  openDialog({
    title: "Изменить пользователя",
    fields: [
      field({ label: "Логин", name: "login", value: u.login, autocapitalize: "none", spellcheck: "false" }),
      field({ label: "Новый пароль", name: "password", type: "password", required: false, autocomplete: "new-password", hint: "оставьте пустым, чтобы не менять; смена пароля завершит сессии пользователя" }),
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
      if (!Object.keys(body).length) throw new Error("Нечего менять");
      await api(`/users/${u.id}`, { method: "PATCH", body });
      toast("Пользователь обновлён");
      await reload();
    },
  });
}

function deleteUserDialog(u, reload) {
  openDialog({
    title: "Удалить пользователя?",
    description: `«${u.login}» потеряет доступ сразу, его сессии завершатся.`,
    confirmLabel: "Удалить",
    danger: true,
    onSubmit: async () => {
      await api(`/users/${u.id}`, { method: "DELETE" });
      toast(`Пользователь «${u.login}» удалён`);
      await reload();
    },
  });
}

// ---------- разделы «Календарь» и «Бюджет» ----------

const MONTHS = Array.from({ length: 12 }, (_, i) => {
  const name = new Intl.DateTimeFormat("ru-RU", { month: "long" }).format(new Date(Date.UTC(2026, i, 1)));
  return name.charAt(0).toUpperCase() + name.slice(1);
});
const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

function isoDate(y, m, d) {
  return `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}

function totalsRow(totals) {
  const shown = totals.filter((t) => t.count_planned > 0);
  if (!shown.length) return h("p", { class: "muted" }, "В этом месяце платежей нет");
  return h(
    "div",
    { class: "month-totals" },
    shown.map((t) =>
      h(
        "div",
        { class: "card mini-card" },
        h("div", { class: "sum-head" }, h("span", {}, t.currency), h("span", {}, plural(t.count_planned, ["платёж", "платежа", "платежей"]))),
        h("div", { class: "sum-main num" }, money(t.planned, t.currency)),
        h("div", { class: "sum-sub" }, `оплачено ${money(t.paid, t.currency)} · осталось ${money(t.remaining, t.currency)}`),
        h("progress", { max: Math.max(Number(t.planned), 1), value: Number(t.paid), "aria-label": "Доля оплаченного" }),
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
  if (item.status === "planned") return "Запланирован";
  if (item.status === "paid") return item.is_overdue ? `Оплачено позже срока (${item.overdue_days} дн.)` : "Оплачено";
  return item.is_overdue ? `Просрочено ${item.overdue_days} дн.` : "Не оплачено";
}

async function calendarView(main) {
  if (!state.cal) {
    const [y, m] = state.asOf.split("-").map(Number);
    state.cal = { year: y, month: m, selected: state.asOf };
  }
  const grid = h("div", { class: "cal-grid", role: "grid" });
  const totalsBox = h("div", {});
  const dayBox = h("div", { class: "card day-box" });
  const title = h("h3", { class: "cal-title" });

  async function reload() {
    const { year, month } = state.cal;
    const data = await api("/payments/calendar", { params: { year, month } });
    state.asOf = data.today;
    title.textContent = `${MONTHS[month - 1]} ${year}`;
    totalsBox.replaceChildren(totalsRow(data.totals));

    const byDay = new Map(data.days.map((d) => [d.day, d.items]));
    if (!state.cal.selected || !state.cal.selected.startsWith(isoDate(year, month, 1).slice(0, 8))) {
      const todayHere = data.today.startsWith(isoDate(year, month, 1).slice(0, 8)) ? data.today : null;
      state.cal.selected = todayHere || (data.days[0] && data.days[0].day) || isoDate(year, month, 1);
    }

    const first = (new Date(Date.UTC(year, month - 1, 1)).getUTCDay() + 6) % 7;
    const count = new Date(Date.UTC(year, month, 0)).getUTCDate();
    const cells = WEEKDAYS.map((d) => h("div", { class: "cal-wd", role: "columnheader" }, d));
    for (let i = 0; i < first; i++) cells.push(h("div", { class: "cal-cell empty", "aria-hidden": "true" }));
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
            "aria-label": `${d} ${MONTHS[month - 1]}, платежей: ${items.length}`,
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
      h("h3", {}, `${fmtDate(state.cal.selected)}`),
      items.length
        ? h("div", { class: "day-list" }, items.map((it) => dayItem(it, reload)))
        : h("p", { class: "muted" }, "В этот день платежей нет"),
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
    h("div", { class: "page-head" }, h("div", {}, h("h2", {}, "Календарь оплат"), h("p", {}, "Сроки на месяц вперёд и дальше: будущие периоды вычисляются по правилу повторения"))),
    h(
      "div",
      { class: "cal-nav" },
      h("button", { class: "btn btn-sm", type: "button", "aria-label": "Предыдущий месяц", onclick: () => shift(-1) }, "←"),
      title,
      h("button", { class: "btn btn-sm", type: "button", "aria-label": "Следующий месяц", onclick: () => shift(1) }, "→"),
      h("button", { class: "btn btn-sm", type: "button", onclick: () => { state.cal = null; calendarView(main).catch(report); } }, "Сегодня"),
    ),
    totalsBox,
    h("div", { class: "card cal-card" }, grid),
    dayBox,
  );
  await reload();
}

function dayItem(it, reload) {
  const occurrence = { id: it.occurrence_id, name: it.name, due_date: it.due_date, amount: it.amount, currency: it.currency, paid_at: it.paid_at };
  let actions = null;
  if (it.occurrence_id && !it.payment_deleted) {
    actions =
      it.status === "unpaid"
        ? [h("button", { class: "btn btn-sm btn-primary", onclick: () => payDialog(occurrence, reload, false) }, "Отметить оплату")]
        : [
            h("button", { class: "btn btn-sm", onclick: () => payDialog(occurrence, reload, true) }, "Изменить дату"),
            h("button", { class: "btn btn-sm btn-danger", onclick: () => cancelDialog(occurrence, reload) }, "Отменить"),
          ];
  }
  return h(
    "div",
    { class: `day-item ${chipClass(it)}` },
    h("div", {}, h("div", { class: "cell-title" }, it.name), h("div", { class: "cell-sub" }, it.paid_at ? `оплачено ${fmtDate(it.paid_at)}` : it.payment_deleted ? "платёж прекращён" : "")),
    h("div", { class: "amount num" }, money(it.amount, it.currency)),
    h("span", { class: `badge ${chipClass(it) === "unpaid" ? "" : chipClass(it)}` }, chipStatus(it)),
    h("div", { class: "day-actions" }, actions),
  );
}

async function budgetView(main) {
  if (!state.budgetYear) state.budgetYear = Number(state.asOf.slice(0, 4));
  const cards = h("section", { class: "summary", "aria-label": "Бюджет за год" });
  const tableBox = h("div", { class: "card table-card" });
  const title = h("h3", { class: "cal-title" });

  async function reload() {
    const year = state.budgetYear;
    const data = await api("/payments/budget", { params: { year } });
    title.textContent = `${year} год`;
    cards.replaceChildren(
      ...data.currencies.map((c) =>
        h(
          "article",
          { class: "card sum-card" },
          h("div", { class: "sum-head" }, h("span", {}, c.currency), h("span", {}, "план на год")),
          h("div", { class: "sum-main num" }, money(c.planned, c.currency)),
          h("div", { class: "sum-sub" }, c.count_planned ? plural(c.count_planned, ["платёж", "платежа", "платежей"]) : "платежей нет"),
          h("progress", { max: Math.max(Number(c.planned), 1), value: Number(c.paid), "aria-label": "Доля оплаченного" }),
          h("div", { class: "sum-rows" }, h("div", { class: "sum-row" }, h("span", {}, "Оплачено"), h("span", { class: "num ok" }, money(c.paid, c.currency))), h("div", { class: "sum-row" }, h("span", {}, "Осталось"), h("span", { class: "num" }, money(c.remaining, c.currency)))),
        ),
      ),
    );

    const active = CURRENCIES.filter((cur) => data.currencies.find((c) => c.currency === cur).count_planned > 0);
    tableBox.replaceChildren(
      active.length
        ? h(
            "table",
            {},
            h("thead", {}, h("tr", {}, h("th", {}, "Месяц"), active.map((cur) => h("th", { class: "right" }, cur)))),
            h(
              "tbody",
              {},
              data.months.map((m) =>
                h(
                  "tr",
                  { class: "clickable", tabindex: "0", onclick: () => openMonth(year, m.month), onkeydown: (e) => { if (e.key === "Enter") openMonth(year, m.month); } },
                  h("td", { class: "title-cell" }, h("div", { class: "cell-title" }, MONTHS[m.month - 1])),
                  active.map((cur) => {
                    const c = m.currencies.find((x) => x.currency === cur);
                    return h(
                      "td",
                      { class: "right num", "data-label": cur },
                      c.count_planned ? h("div", {}, h("div", { class: "amount" }, money(c.planned, cur)), h("div", { class: "cell-sub" }, c.paid === c.planned ? "оплачено" : `оплачено ${money(c.paid, cur)}`)) : h("span", { class: "muted" }, "—"),
                    );
                  }),
                ),
              ),
            ),
          )
        : h("div", { class: "empty" }, h("strong", {}, "В этом году платежей нет"), "Бюджет появится, как только администратор добавит регулярные платежи."),
    );
  }

  function openMonth(year, month) {
    state.cal = { year, month, selected: null };
    state.tab = "calendar";
    showApp().catch(report);
  }

  const shift = (delta) => { state.budgetYear += delta; reload().catch(report); };

  main.replaceChildren(
    h("div", { class: "page-head" }, h("div", {}, h("h2", {}, "Бюджет"), h("p", {}, "Плановые расходы по каждой валюте отдельно, без конвертации. Нажмите на месяц, чтобы открыть его в календаре"))),
    h(
      "div",
      { class: "cal-nav" },
      h("button", { class: "btn btn-sm", type: "button", "aria-label": "Предыдущий год", onclick: () => shift(-1) }, "←"),
      title,
      h("button", { class: "btn btn-sm", type: "button", "aria-label": "Следующий год", onclick: () => shift(1) }, "→"),
    ),
    cards,
    tableBox,
  );
  await reload();
}

// ---------- раздел «Журнал» (админ) ----------

const AUDIT_LABELS = {
  "auth.login": "Вход",
  "auth.login_failed": "Неудачный вход",
  "auth.logout": "Выход",
  "payment.create": "Платёж добавлен",
  "payment.delete": "Платёж прекращён",
  "occurrence.paid": "Оплата отмечена",
  "occurrence.unpaid": "Оплата отменена",
  "occurrence.paid_at_changed": "Дата оплаты исправлена",
  "user.create": "Пользователь создан",
  "user.update": "Пользователь изменён",
  "user.delete": "Пользователь удалён",
  "receipt.add": "Чек или ссылка добавлены",
  "receipt.delete": "Чек или ссылка удалены",
  "reminder.sent": "Напоминание отправлено",
};

const ACTOR_LABELS = { admin: "админ", user: "пользователь", telegram: "Telegram", system: "система", anonymous: "аноним" };

function auditSummary(e) {
  const d = e.details || {};
  const due = d.due_date ? `срок ${fmtDate(d.due_date)}` : "";
  switch (e.action) {
    case "occurrence.paid":
    case "occurrence.unpaid":
      return [d.name, due, d.paid_at ? `оплата ${fmtDate(d.paid_at)}` : ""].filter(Boolean).join(", ");
    case "occurrence.paid_at_changed":
      return `${d.name}, ${due}: дата оплаты ${fmtDate(d.paid_at_before)} → ${fmtDate(d.paid_at)}`;
    case "payment.create":
      return `${d.name}, ${money(d.amount, d.currency)}, первый срок ${fmtDate(d.first_due_date)}`;
    case "payment.delete":
      return d.name;
    case "user.create":
    case "user.delete":
      return d.login;
    case "user.update":
      return [d.login_before ? `${d.login_before} → ${d.login}` : d.login, d.password_changed ? "пароль изменён" : ""].filter(Boolean).join(", ");
    case "reminder.sent":
      return `${d.name}, ${due}, канал: ${d.channel}`;
    case "receipt.add":
    case "receipt.delete":
      return [d.title || d.filename || d.url, d.name].filter(Boolean).join(" · ");
    case "auth.login_failed":
      return "попытка входа с этим логином";
    default:
      return d && Object.keys(d).length ? JSON.stringify(d) : "";
  }
}

const AUDIT_FILTERS = {
  group: [
    { value: "", label: "Всё" },
    { value: "auth.", label: "Вход" },
    { value: "occurrence.", label: "Оплаты" },
    { value: "payment.", label: "Платежи" },
    { value: "user.", label: "Пользователи" },
    { value: "reminder.", label: "Напоминания" },
  ],
  period: [
    { value: "", label: "Всё время" },
    { value: "1", label: "Сегодня" },
    { value: "7", label: "7 дней" },
    { value: "30", label: "30 дней" },
  ],
};

const auditState = { group: "", period: "" };

async function auditView(main) {
  const PAGE = 100;
  const listBox = h("div", { class: "card table-card" });
  const more = h("button", { class: "btn", type: "button" }, "Показать ещё");
  const moreWrap = h("div", { class: "more-wrap" }, more);
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
            h("thead", {}, h("tr", {}, h("th", {}, "Время"), h("th", {}, "Кто"), h("th", {}, "Действие"), h("th", {}, "Подробности"), h("th", {}, "Адрес"))),
            h(
              "tbody",
              {},
              rows.map((e) =>
                h(
                  "tr",
                  {},
                  h("td", { class: "title-cell num", "data-label": "Время" }, fmtDateTime(e.at)),
                  h("td", { "data-label": "Кто" }, h("span", { class: `actor ${e.actor_type}` }, e.actor), " ", h("span", { class: "cell-sub" }, ACTOR_LABELS[e.actor_type] || e.actor_type)),
                  h("td", { "data-label": "Действие" }, h("span", { class: `act ${e.action === "auth.login_failed" ? "bad" : ""}` }, AUDIT_LABELS[e.action] || e.action)),
                  h("td", { "data-label": "Подробности", class: "details-cell" }, auditSummary(e)),
                  h("td", { "data-label": "Адрес", class: "num muted" }, e.ip || "—"),
                ),
              ),
            ),
          )
        : h("div", { class: "empty" }, h("strong", {}, "Записей нет"), "Здесь появятся входы, оплаты, изменения платежей и пользователей."),
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

  more.addEventListener("click", () => load(false).catch(report));

  const toolbar = h(
    "div",
    { class: "toolbar" },
    segmented(AUDIT_FILTERS.group, auditState.group, (v) => { auditState.group = v; load(true).catch(report); }),
    segmented(AUDIT_FILTERS.period, auditState.period, (v) => { auditState.period = v; load(true).catch(report); }),
  );

  main.replaceChildren(
    h("div", { class: "page-head" }, h("div", {}, h("h2", {}, "Журнал"), h("p", {}, "Кто и что делал: входы, оплаты (в том числе из Telegram), платежи, пользователи. Пароли сюда не попадают"))),
    toolbar,
    listBox,
    moreWrap,
  );
  await load(true);
}

// ---------- старт ----------

async function bootstrap() {
  try {
    state.me = await api("/auth/me", { silent: true });
  } catch {
    state.me = null;
  }
  if (state.me) await showApp();
  else showLogin();
}

bootstrap();
