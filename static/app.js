const form = document.querySelector("#solver-form");
const taskInput = document.querySelector("#task");
const taskCount = document.querySelector("#task-count");
const launchButton = document.querySelector("#launch-button");
const launchLabel = launchButton.querySelector(".button-label");
const formError = document.querySelector("#form-error");
const resultsSection = document.querySelector("#results-section");
const runHistory = document.querySelector("#run-history");
const runTemplate = document.querySelector("#run-template");
const resultTemplate = document.querySelector("#result-template");
const temperatureInputs = [...document.querySelectorAll(".temperature-input")];
let runCounter = 0;

document.querySelectorAll(".temperature-control").forEach((control) => {
  const slider = control.querySelector(".temperature-slider");
  const number = control.querySelector(".temperature-input");
  const output = control.querySelector("output");

  const showValue = (value) => {
    output.value = formatTemperature(value);
    slider.style.setProperty("--range-progress", `${(Number(value) / 2) * 100}%`);
  };

  slider.addEventListener("input", () => {
    number.value = slider.value;
    showValue(slider.value);
  });

  number.addEventListener("input", () => {
    const value = Number(number.value);
    if (number.value.trim() !== "" && Number.isFinite(value) && value >= 0 && value <= 2) {
      slider.value = String(value);
      showValue(value);
    }
  });

  showValue(slider.value);
});

taskInput.addEventListener("input", () => {
  taskCount.textContent = taskInput.value.length.toLocaleString("ru-RU");
  if (taskInput.value.trim()) formError.textContent = "";
});

document.querySelector("#example-button").addEventListener("click", () => {
  taskInput.value = "Придумай три необычных концепции кафе для небольшого сибирского города. Для каждой опиши идею, целевую аудиторию и одну фирменную деталь.";
  taskInput.dispatchEvent(new Event("input"));
  taskInput.focus();
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const task = taskInput.value.trim();
  if (!task) {
    formError.textContent = "Сначала введите запрос.";
    taskInput.focus();
    return;
  }

  const temperatures = readTemperatures();
  if (!temperatures) return;

  formError.textContent = "";
  launchButton.disabled = true;
  launchLabel.textContent = "Запросы выполняются…";

  const batch = createBatch(task, temperatures);
  resultsSection.hidden = false;
  runHistory.prepend(batch.element);
  window.setTimeout(() => batch.element.scrollIntoView({ behavior: "smooth", block: "start" }), 80);

  const settled = await Promise.all(
    temperatures.map((temperature, index) => runTemperature(batch, temperature, index))
  );
  batch.results = settled;
  const successful = settled.filter((result) => result.ok);
  batch.progress.textContent = `Готово: ${successful.length} из 3`;
  batch.saveButton.disabled = false;

  if (successful.length === 3) {
    batch.compareButton.disabled = false;
  } else {
    batch.message.textContent = "Сравнение доступно только когда получены все три ответа. Пачку с ошибками всё равно можно сохранить.";
  }

  launchButton.disabled = false;
  launchLabel.textContent = "Запустить ещё раз";
});

function readTemperatures() {
  const values = [];
  for (const input of temperatureInputs) {
    const value = Number(input.value);
    if (input.value.trim() === "" || !Number.isFinite(value) || value < 0 || value > 2) {
      formError.textContent = "Каждая температура должна быть числом от 0 до 2.";
      input.focus();
      return null;
    }
    values.push(value);
  }
  return values;
}

function createBatch(task, temperatures) {
  runCounter += 1;
  const element = runTemplate.content.firstElementChild.cloneNode(true);
  const createdAt = new Date();
  const batch = {
    element,
    task,
    temperatures,
    createdAt: createdAt.toISOString(),
    results: [],
    comparison: null,
    progress: element.querySelector(".batch-progress"),
    message: element.querySelector(".batch-message"),
    compareButton: element.querySelector(".compare-button"),
    saveButton: element.querySelector(".save-button"),
  };

  element.querySelector(".batch-title").textContent = `Запуск ${runCounter} · ${createdAt.toLocaleString("ru-RU")}`;
  element.querySelector(".batch-task").textContent = task;
  const grid = element.querySelector(".result-grid");
  temperatures.forEach((temperature, index) => {
    const card = resultTemplate.content.firstElementChild.cloneNode(true);
    card.dataset.resultIndex = String(index);
    card.querySelector(".result-number").textContent = String(index + 1).padStart(2, "0");
    card.querySelector(".result-title").textContent = `temperature = ${formatTemperature(temperature)}`;
    grid.append(card);
  });

  batch.compareButton.addEventListener("click", () => runComparison(batch));
  batch.saveButton.addEventListener("click", () => saveBatch(batch));
  return batch;
}

async function runTemperature(batch, temperature, index) {
  const card = batch.element.querySelector(`[data-result-index="${index}"]`);
  try {
    const response = await fetch("/api/solve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task: batch.task, temperature }),
    });
    const data = await readResponse(response);
    if (!response.ok || !data.ok) throw new Error(data.error || `Ошибка HTTP ${response.status}`);
    renderSuccess(card, data);
    updateBatchProgress(batch);
    return { ok: true, ...data };
  } catch (error) {
    const message = error.message || String(error);
    renderFailure(card, message);
    updateBatchProgress(batch);
    return { ok: false, temperature, error: message };
  }
}

function updateBatchProgress(batch) {
  const completed = batch.element.querySelectorAll(".status-badge.success, .status-badge.failed").length;
  batch.progress.textContent = `Выполняется: ${completed} из 3`;
}

async function readResponse(response) {
  const type = response.headers.get("content-type") || "";
  if (type.includes("application/json")) return response.json();
  const text = await response.text();
  throw new Error(text || `Сервер вернул ошибку ${response.status}`);
}

function renderSuccess(card, data) {
  card.querySelector(".loading-state").hidden = true;
  card.querySelector(".error-state").hidden = true;
  const content = card.querySelector(".result-content");
  content.hidden = false;
  content.querySelector(".answer-text").textContent = data.answer;

  const status = card.querySelector(".status-badge");
  status.textContent = "Готово";
  status.classList.add("success");

  const metadata = [
    `${data.elapsed_seconds} сек.`,
    `${data.usage.input_tokens} вход`,
    `${data.usage.output_tokens} выход`,
    `${data.usage.total_tokens} всего`,
    "Reasoning выкл.",
  ];
  const meta = content.querySelector(".result-meta");
  metadata.forEach((text) => {
    const pill = document.createElement("span");
    pill.className = "meta-pill";
    pill.textContent = text;
    meta.append(pill);
  });

  const copyButton = content.querySelector(".copy-button");
  copyButton.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(data.answer);
      copyButton.textContent = "Скопировано";
      window.setTimeout(() => (copyButton.textContent = "Копировать ответ"), 1400);
    } catch {
      copyButton.textContent = "Не удалось скопировать";
    }
  });
}

function renderFailure(card, message) {
  card.querySelector(".loading-state").hidden = true;
  const errorState = card.querySelector(".error-state");
  errorState.hidden = false;
  errorState.textContent = message;
  const status = card.querySelector(".status-badge");
  status.textContent = "Ошибка";
  status.classList.add("failed");
}

async function runComparison(batch) {
  const comparisonCard = batch.element.querySelector(".comparison-card");
  const status = comparisonCard.querySelector(".comparison-status");
  const answer = comparisonCard.querySelector(".comparison-answer");
  comparisonCard.hidden = false;
  status.textContent = "DeepSeek сравнивает эту пачку…";
  answer.textContent = "";
  batch.message.textContent = "";
  batch.compareButton.disabled = true;
  batch.compareButton.textContent = "Сравнение выполняется…";

  try {
    const answers = batch.results.map((result) => ({
      temperature: result.temperature,
      answer: result.answer,
    }));
    const response = await fetch("/api/compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task: batch.task, answers }),
    });
    const data = await readResponse(response);
    if (!response.ok || !data.ok) throw new Error(data.error || `Ошибка HTTP ${response.status}`);
    batch.comparison = data;
    status.textContent = `${data.elapsed_seconds} сек. · ${data.usage.total_tokens} токенов`;
    answer.textContent = data.answer;
    batch.compareButton.textContent = "Сравнить ещё раз";
  } catch (error) {
    status.textContent = "Сравнение завершилось с ошибкой";
    answer.textContent = error.message || String(error);
    batch.compareButton.textContent = "Повторить сравнение";
  } finally {
    batch.compareButton.disabled = false;
  }
}

async function saveBatch(batch) {
  batch.saveButton.disabled = true;
  batch.saveButton.textContent = "Сохранение…";
  batch.message.textContent = "";
  try {
    const response = await fetch("/api/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        task: batch.task,
        created_at: batch.createdAt,
        results: batch.results,
        comparison: batch.comparison,
      }),
    });
    const data = await readResponse(response);
    if (!response.ok || !data.ok) throw new Error(data.error || `Ошибка HTTP ${response.status}`);
    batch.message.replaceChildren();
    batch.message.append("Сохранено в ", document.createTextNode(data.folder), ". ");
    const link = document.createElement("a");
    link.href = data.report_url;
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = "Открыть отчёт";
    batch.message.append(link);
    batch.saveButton.textContent = "Сохранить ещё одну копию";
  } catch (error) {
    batch.message.textContent = error.message || String(error);
    batch.saveButton.textContent = "Повторить сохранение";
  } finally {
    batch.saveButton.disabled = false;
  }
}

function formatTemperature(value) {
  return Number(value).toLocaleString("ru-RU", { maximumFractionDigits: 2 });
}
