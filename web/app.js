const PAGE_SIZE = 20;

const state = {
  categories: [],
  subcategories: [],
  transactions: [],
  transactionPage: 0,
  currentTransaction: null,
};

const $ = (selector, parent = document) => parent.querySelector(selector);
const $$ = (selector, parent = document) => [...parent.querySelectorAll(selector)];

function escapeHTML(value = "") {
  return String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[character]);
}

function localDateString(date = new Date()) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function localMonthString(date = new Date()) {
  return localDateString(date).slice(0, 7);
}

function showNotice(message, isError = false) {
  const notice = $("#notice");
  notice.textContent = message;
  notice.classList.toggle("error", isError);
  notice.hidden = false;
  window.clearTimeout(showNotice.timeout);
  showNotice.timeout = window.setTimeout(() => { notice.hidden = true; }, 4500);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
  });
  if (response.status === 204) return null;
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || `Request failed (${response.status})`);
  return body;
}

function jsonOptions(method, body) {
  return { method, body: JSON.stringify(body) };
}

function formatAmount(value) {
  const raw = String(value ?? "0");
  const [wholePart = "0", fraction = ""] = raw.split(".");
  const negative = wholePart.startsWith("-");
  const absoluteWhole = negative ? wholePart.slice(1) : wholePart;
  const grouped = new Intl.NumberFormat().format(BigInt(absoluteWhole || "0"));
  return `${negative ? "−" : ""}${grouped}${fraction ? `.${fraction}` : ""}`;
}

function sumAmounts(values) {
  const normalized = values.map((value) => String(value));
  const scale = Math.max(0, ...normalized.map((value) => (value.split(".")[1] || "").length));
  const multiplier = 10n ** BigInt(scale);
  const total = normalized.reduce((sum, value) => {
    const [whole = "0", fraction = ""] = value.split(".");
    const negative = whole.startsWith("-");
    const magnitude = BigInt(`${negative ? whole.slice(1) : whole}${fraction.padEnd(scale, "0")}` || "0");
    return sum + (negative ? -magnitude : magnitude);
  }, 0n);
  const negative = total < 0n;
  const absolute = negative ? -total : total;
  const whole = (absolute / multiplier).toString();
  const fraction = scale ? (absolute % multiplier).toString().padStart(scale, "0") : "";
  return `${negative ? "-" : ""}${whole}${fraction ? `.${fraction}` : ""}`;
}

function displayDate(isoDate) {
  if (!isoDate) return "—";
  return new Date(`${isoDate}T00:00:00`).toLocaleDateString(undefined, {
    year: "numeric", month: "short", day: "numeric",
  });
}

function categoryName(categoryId) {
  if (!categoryId) return "Uncategorized";
  return state.categories.find((category) => category.id === categoryId)?.name || "Unknown category";
}

function subcategoryName(subcategoryId) {
  if (!subcategoryId) return "—";
  return state.subcategories.find((subcategory) => subcategory.id === subcategoryId)?.name || "Unknown subcategory";
}

function setPage() {
  const page = window.location.hash.slice(1) || "transactions";
  const knownPages = ["transactions", "categories", "dashboard"];
  const activePage = knownPages.includes(page) ? page : "transactions";
  $$(".page").forEach((section) => {
    section.hidden = section.id !== `${activePage}-page`;
  });
  $$("[data-page-link]").forEach((link) => {
    if (link.dataset.pageLink === activePage) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  if (activePage === "categories") renderCategoryManagement();
  if (activePage === "dashboard") updateDashboard();
}

function populateCategorySelect(select, { includeUncategorized = true } = {}) {
  const value = select.value;
  const defaultLabel = includeUncategorized ? "Uncategorized" : "Choose a category";
  select.innerHTML = `<option value="">${defaultLabel}</option>${state.categories
    .map((category) => `<option value="${escapeHTML(category.id)}">${escapeHTML(category.name)}</option>`)
    .join("")}`;
  if (state.categories.some((category) => category.id === value)) select.value = value;
}

function populateSubcategorySelect(select, categoryId, selectedId = "") {
  const subcategories = state.subcategories.filter((item) => item.category_id === categoryId);
  select.innerHTML = `<option value="">No subcategory</option>${subcategories
    .map((item) => `<option value="${escapeHTML(item.id)}">${escapeHTML(item.name)}</option>`)
    .join("")}`;
  select.disabled = !categoryId || subcategories.length === 0;
  if (subcategories.some((item) => item.id === selectedId)) select.value = selectedId;
}

function refreshTransactionCategoryInputs() {
  const categorySelect = $("#transaction-category");
  const subcategorySelect = $("#transaction-subcategory");
  populateCategorySelect(categorySelect);
  populateSubcategorySelect(subcategorySelect, categorySelect.value, subcategorySelect.value);
}

async function loadReferenceData() {
  [state.categories, state.subcategories] = await Promise.all([
    api("/categories"), api("/subcategories"),
  ]);
  refreshTransactionCategoryInputs();
  populateCategorySelect($("#edit-form [name=category_id]"));
}

function filteredTransactions() {
  return [...state.transactions].sort((left, right) =>
    right.date.localeCompare(left.date) || right.id.localeCompare(left.id));
}

async function loadTransactions() {
  const form = $("#transaction-filter");
  const startDate = form.elements.start_date.value;
  const endDate = form.elements.end_date.value;
  if (Boolean(startDate) !== Boolean(endDate)) {
    showNotice("Choose both the start and end dates for a date range.", true);
    return;
  }
  const params = new URLSearchParams();
  if (startDate && endDate) {
    params.set("start_date", startDate);
    params.set("end_date", endDate);
  }
  try {
    const suffix = params.size ? `?${params}` : "";
    state.transactions = await api(`/transactions${suffix}`);
    state.transactionPage = 0;
    renderTransactions();
  } catch (error) {
    showNotice(error.message, true);
  }
}

function renderTransactions() {
  const transactions = filteredTransactions();
  const pageCount = Math.ceil(transactions.length / PAGE_SIZE);
  state.transactionPage = Math.min(state.transactionPage, Math.max(pageCount - 1, 0));
  const visible = transactions.slice(state.transactionPage * PAGE_SIZE, (state.transactionPage + 1) * PAGE_SIZE);
  $("#transactions-body").innerHTML = visible.map((transaction) => `
    <tr tabindex="0" role="button" data-transaction-id="${escapeHTML(transaction.id)}" aria-label="Edit expense ${escapeHTML(displayDate(transaction.date))}, ${escapeHTML(formatAmount(transaction.amount))}">
      <td class="transaction-date">${escapeHTML(displayDate(transaction.date))}</td>
      <td><span class="category-pill">${escapeHTML(categoryName(transaction.category_id))}</span></td>
      <td>${escapeHTML(subcategoryName(transaction.subcategory_id))}</td>
      <td>${escapeHTML(transaction.note || "—")}</td>
      <td class="amount-cell transaction-amount">${escapeHTML(formatAmount(transaction.amount))}</td>
    </tr>`).join("");
  $("#transactions-empty").hidden = transactions.length > 0;
  $("#transaction-count").textContent = `${transactions.length} ${transactions.length === 1 ? "expense" : "expenses"}`;
  $("#page-indicator").textContent = pageCount ? `Page ${state.transactionPage + 1} of ${pageCount}` : "Page 0 of 0";
  $("#previous-page").disabled = state.transactionPage === 0;
  $("#next-page").disabled = !pageCount || state.transactionPage >= pageCount - 1;
}

function openEditDialog(transaction) {
  state.currentTransaction = transaction;
  const dialog = $("#edit-dialog");
  const form = $("#edit-form");
  form.elements.date.value = transaction.date;
  form.elements.amount.value = transaction.amount;
  populateCategorySelect(form.elements.category_id);
  form.elements.category_id.value = transaction.category_id || "";
  populateSubcategorySelect(form.elements.subcategory_id, transaction.category_id, transaction.subcategory_id || "");
  form.elements.note.value = transaction.note || "";
  dialog.showModal();
}

async function submitTransaction(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const data = new FormData(form);
  const amount = Number(data.get("amount"));
  if (!Number.isFinite(amount) || amount <= 0) {
    showNotice("Amount must be greater than zero.", true);
    return;
  }
  const transaction = {
    date: data.get("date"),
    amount: String(data.get("amount")),
    category_id: data.get("category_id") || null,
    subcategory_id: data.get("subcategory_id") || null,
    note: data.get("note") || null,
  };
  try {
    await api("/transactions", jsonOptions("POST", transaction));
    form.reset();
    $("#transaction-date").value = localDateString();
    refreshTransactionCategoryInputs();
    await loadTransactions();
    showNotice("Expense added.");
  } catch (error) {
    showNotice(error.message, true);
  }
}

async function saveTransactionEdit(event) {
  event.preventDefault();
  if (!state.currentTransaction) return;
  const form = event.currentTarget;
  const data = new FormData(form);
  if (Number(data.get("amount")) <= 0) {
    showNotice("Amount must be greater than zero.", true);
    return;
  }
  const transaction = {
    date: data.get("date"),
    amount: String(data.get("amount")),
    category_id: data.get("category_id") || null,
    subcategory_id: data.get("subcategory_id") || null,
    note: data.get("note") || null,
  };
  try {
    await api(`/transactions/${encodeURIComponent(state.currentTransaction.id)}`, jsonOptions("PATCH", transaction));
    $("#edit-dialog").close();
    await loadTransactions();
    showNotice("Expense updated.");
  } catch (error) {
    showNotice(error.message, true);
  }
}

async function deleteCurrentTransaction() {
  if (!state.currentTransaction) return;
  if (!window.confirm("Delete this expense? This cannot be undone.")) return;
  try {
    await api(`/transactions/${encodeURIComponent(state.currentTransaction.id)}`, { method: "DELETE" });
    $("#edit-dialog").close();
    await loadTransactions();
    showNotice("Expense deleted.");
  } catch (error) {
    showNotice(error.message, true);
  }
}

function renderCategoryManagement() {
  const categorySelect = $("#subcategory-form [name=category_id]");
  const selectedId = categorySelect.value;
  categorySelect.innerHTML = `<option value="">Choose a category</option>${state.categories
    .map((category) => `<option value="${escapeHTML(category.id)}">${escapeHTML(category.name)}</option>`)
    .join("")}`;
  if (state.categories.some((category) => category.id === selectedId)) categorySelect.value = selectedId;

  $("#category-list").innerHTML = state.categories.map((category) => {
    const children = state.subcategories.filter((item) => item.category_id === category.id);
    return `<article class="category-card" data-category-card="${escapeHTML(category.id)}">
      <form class="category-edit-row" data-category-form="${escapeHTML(category.id)}">
        <label>Category name<input name="name" value="${escapeHTML(category.name)}" maxlength="100" required /></label>
        <button class="button button-secondary" type="submit">Save name</button>
        <button class="button button-danger" type="button" data-delete-category="${escapeHTML(category.id)}">Delete</button>
      </form>
      <div class="subcategory-list">${children.map((subcategory) => `
        <div class="subcategory-row" data-subcategory-row="${escapeHTML(subcategory.id)}">
          <span class="subcategory-name">${escapeHTML(subcategory.name)}</span>
          <span class="row-actions">
            <button class="text-button" type="button" data-edit-subcategory="${escapeHTML(subcategory.id)}">Rename</button>
            <button class="text-button danger" type="button" data-delete-subcategory="${escapeHTML(subcategory.id)}">Delete</button>
          </span>
        </div>`).join("") || '<p class="helper-text">No subcategories yet.</p>'}
      </div>
    </article>`;
  }).join("");
  $("#categories-empty").hidden = state.categories.length > 0;
}

async function refreshAfterCategoryChange(message) {
  await loadReferenceData();
  await loadTransactions();
  renderCategoryManagement();
  if (!$("#dashboard-page").hidden) await updateDashboard();
  showNotice(message);
}

function bindCategoryActions() {
  $("#category-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    try {
      await api("/categories", jsonOptions("POST", { name: data.get("name") }));
      event.currentTarget.reset();
      await refreshAfterCategoryChange("Category added.");
    } catch (error) { showNotice(error.message, true); }
  });

  $("#subcategory-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    try {
      await api("/subcategories", jsonOptions("POST", {
        name: data.get("name"), category_id: data.get("category_id"),
      }));
      event.currentTarget.elements.name.value = "";
      await refreshAfterCategoryChange("Subcategory added.");
    } catch (error) { showNotice(error.message, true); }
  });

  $("#category-list").addEventListener("submit", async (event) => {
    const form = event.target.closest("[data-category-form]");
    if (!form) return;
    event.preventDefault();
    try {
      await api(`/categories/${encodeURIComponent(form.dataset.categoryForm)}`, jsonOptions("PATCH", { name: form.elements.name.value }));
      await refreshAfterCategoryChange("Category renamed.");
    } catch (error) { showNotice(error.message, true); }
  });

  $("#category-list").addEventListener("click", async (event) => {
    const deleteCategory = event.target.closest("[data-delete-category]");
    const editSubcategory = event.target.closest("[data-edit-subcategory]");
    const deleteSubcategory = event.target.closest("[data-delete-subcategory]");
    try {
      if (deleteCategory) {
        const category = state.categories.find((item) => item.id === deleteCategory.dataset.deleteCategory);
        if (!window.confirm(`Delete “${category?.name || "this category"}”? Its subcategories will also be deleted, and matching transactions will become uncategorized.`)) return;
        await api(`/categories/${encodeURIComponent(deleteCategory.dataset.deleteCategory)}`, { method: "DELETE" });
        await refreshAfterCategoryChange("Category deleted.");
      } else if (editSubcategory) {
        const subcategory = state.subcategories.find((item) => item.id === editSubcategory.dataset.editSubcategory);
        const name = window.prompt("New subcategory name:", subcategory?.name || "");
        if (name === null) return;
        await api(`/subcategories/${encodeURIComponent(editSubcategory.dataset.editSubcategory)}`, jsonOptions("PATCH", { name }));
        await refreshAfterCategoryChange("Subcategory renamed.");
      } else if (deleteSubcategory) {
        const subcategory = state.subcategories.find((item) => item.id === deleteSubcategory.dataset.deleteSubcategory);
        if (!window.confirm(`Delete “${subcategory?.name || "this subcategory"}”? Transactions will keep their category.`)) return;
        await api(`/subcategories/${encodeURIComponent(deleteSubcategory.dataset.deleteSubcategory)}`, { method: "DELETE" });
        await refreshAfterCategoryChange("Subcategory deleted.");
      }
    } catch (error) { showNotice(error.message, true); }
  });
}

function dashboardPeriod() {
  const form = $("#dashboard-filter");
  const period = form.elements.period.value;
  if (period === "month") {
    const month = form.elements.month.value;
    if (!month) throw new Error("Choose a month to view.");
    const [year, monthNumber] = month.split("-").map(Number);
    const finalDay = new Date(year, monthNumber, 0).getDate();
    return {
      startDate: `${month}-01`,
      endDate: `${month}-${String(finalDay).padStart(2, "0")}`,
      label: new Date(year, monthNumber - 1, 1).toLocaleDateString(undefined, { year: "numeric", month: "long" }),
    };
  }
  if (period === "range") {
    const startDate = form.elements.start_date.value;
    const endDate = form.elements.end_date.value;
    if (!startDate || !endDate) throw new Error("Choose both dates for the inclusive range.");
    if (startDate > endDate) throw new Error("The start date must be on or before the end date.");
    return { startDate, endDate, label: `${displayDate(startDate)} – ${displayDate(endDate)}` };
  }
  return { startDate: "", endDate: "", label: "All time" };
}

function renderDashboard(transactions, label) {
  const groups = new Map();
  for (const transaction of transactions) {
    const key = transaction.category_id || "__uncategorized__";
    if (!groups.has(key)) {
      groups.set(key, { name: categoryName(transaction.category_id), transactions: [], subcategories: new Map() });
    }
    const group = groups.get(key);
    group.transactions.push(transaction);
    const subcategoryId = transaction.subcategory_id || "__none__";
    if (!group.subcategories.has(subcategoryId)) {
      group.subcategories.set(subcategoryId, { name: subcategoryName(transaction.subcategory_id) === "—" ? "No subcategory" : subcategoryName(transaction.subcategory_id), amounts: [] });
    }
    group.subcategories.get(subcategoryId).amounts.push(transaction.amount);
  }

  const total = sumAmounts(transactions.map((transaction) => transaction.amount));
  $("#summary-total").textContent = formatAmount(total);
  $("#summary-period-label").textContent = label;
  const ordered = [...groups.entries()].sort((left, right) =>
    sumAmounts(right[1].transactions.map((item) => item.amount)).localeCompare(
      sumAmounts(left[1].transactions.map((item) => item.amount)), undefined, { numeric: true },
    ));
  $("#dashboard-categories").innerHTML = ordered.map(([, group]) => {
    const groupTotal = sumAmounts(group.transactions.map((transaction) => transaction.amount));
    const subcategoryRows = [...group.subcategories.values()]
      .map((subcategory) => ({ ...subcategory, total: sumAmounts(subcategory.amounts) }))
      .sort((left, right) => right.total.localeCompare(left.total, undefined, { numeric: true }));
    return `<details class="breakdown-item">
      <summary>
        <span class="breakdown-title"><span class="category-pill">${escapeHTML(group.name)}</span><span class="breakdown-meta">${group.transactions.length} ${group.transactions.length === 1 ? "expense" : "expenses"}</span></span>
        <span class="breakdown-total">${escapeHTML(formatAmount(groupTotal))}</span>
      </summary>
      <div class="subcategory-breakdown">${subcategoryRows.map((subcategory) => `
        <div class="subcategory-breakdown-row"><span>${escapeHTML(subcategory.name)}</span><strong>${escapeHTML(formatAmount(subcategory.total))}</strong></div>`).join("")}
      </div>
    </details>`;
  }).join("");
  $("#dashboard-empty").hidden = transactions.length > 0;
}

async function updateDashboard() {
  try {
    const period = dashboardPeriod();
    const params = new URLSearchParams();
    if (period.startDate) {
      params.set("start_date", period.startDate);
      params.set("end_date", period.endDate);
    }
    const suffix = params.size ? `?${params}` : "";
    const transactions = await api(`/transactions${suffix}`);
    renderDashboard(transactions, period.label);
  } catch (error) {
    showNotice(error.message, true);
  }
}

function bindEvents() {
  window.addEventListener("hashchange", setPage);
  $("#transaction-form").addEventListener("submit", submitTransaction);
  $("#transaction-category").addEventListener("change", refreshTransactionCategoryInputs);
  $("#transaction-filter").addEventListener("submit", (event) => {
    event.preventDefault();
    loadTransactions();
  });
  $("#clear-transaction-filter").addEventListener("click", () => {
    $("#transaction-filter").reset();
    loadTransactions();
  });
  $("#transactions-body").addEventListener("click", (event) => {
    const row = event.target.closest("[data-transaction-id]");
    if (row) openEditDialog(state.transactions.find((item) => item.id === row.dataset.transactionId));
  });
  $("#transactions-body").addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const row = event.target.closest("[data-transaction-id]");
    if (row) {
      event.preventDefault();
      openEditDialog(state.transactions.find((item) => item.id === row.dataset.transactionId));
    }
  });
  $("#previous-page").addEventListener("click", () => {
    state.transactionPage = Math.max(0, state.transactionPage - 1);
    renderTransactions();
  });
  $("#next-page").addEventListener("click", () => {
    state.transactionPage += 1;
    renderTransactions();
  });
  $("#edit-form").addEventListener("submit", saveTransactionEdit);
  $("#edit-form [name=category_id]").addEventListener("change", (event) => {
    populateSubcategorySelect($("#edit-form [name=subcategory_id]"), event.target.value);
  });
  $("#delete-transaction").addEventListener("click", deleteCurrentTransaction);
  $("#close-edit").addEventListener("click", () => $("#edit-dialog").close());
  $("#cancel-edit").addEventListener("click", () => $("#edit-dialog").close());
  $("#dashboard-filter").elements.period.addEventListener("change", (event) => {
    const period = event.target.value;
    $("#dashboard-month-field").hidden = period !== "month";
    $("#dashboard-start-field").hidden = period !== "range";
    $("#dashboard-end-field").hidden = period !== "range";
  });
  $("#dashboard-filter").addEventListener("submit", (event) => {
    event.preventDefault();
    updateDashboard();
  });
  bindCategoryActions();
}

async function initialize() {
  $("#transaction-date").value = localDateString();
  $("#dashboard-filter").elements.month.value = localMonthString();
  $("#dashboard-filter").elements.start_date.value = localDateString(new Date(new Date().getFullYear(), new Date().getMonth(), 1));
  $("#dashboard-filter").elements.end_date.value = localDateString();
  bindEvents();
  try {
    await loadReferenceData();
    await loadTransactions();
    setPage();
  } catch (error) {
    showNotice(error.message, true);
  }
}

document.addEventListener("DOMContentLoaded", initialize);
