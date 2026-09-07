"""Локальный веб-интерфейс для сравнения температур через DeepSeek API."""

from __future__ import annotations

import html
import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, send_from_directory, url_for
from openai import OpenAI

BASE_DIR = Path(__file__).resolve().parent
SAVED_RUNS_DIR = BASE_DIR / "saved_runs"
load_dotenv(BASE_DIR / ".env")

app = Flask(__name__)
app.json.ensure_ascii = False

DEFAULT_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
MAX_TASK_LENGTH = 20_000
MAX_ANSWER_LENGTH = 50_000
RUN_ID_PATTERN = re.compile(r"^[0-9A-Za-z_-]+$")


@dataclass
class CompletionResult:
    answer: str
    model: str
    usage: dict[str, int]
    elapsed_seconds: float


def get_client() -> OpenAI:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Не найден DEEPSEEK_API_KEY. Добавьте ключ в файл .env и перезапустите программу."
        )
    return OpenAI(
        api_key=api_key,
        base_url="https://api.deepseek.com",
        timeout=180.0,
        max_retries=1,
    )


def require_temperature(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Температура должна быть числом от 0 до 2.")
    temperature = float(value)
    if not 0 <= temperature <= 2:
        raise ValueError("Температура должна находиться в диапазоне от 0 до 2.")
    return temperature


def call_model(messages: list[dict[str, str]], temperature: float) -> CompletionResult:
    """Вызывает DeepSeek только в non-thinking режиме, где temperature действует."""
    started = time.perf_counter()
    response = get_client().chat.completions.create(
        model=DEFAULT_MODEL,
        messages=messages,
        temperature=temperature,
        extra_body={"thinking": {"type": "disabled"}},
        stream=False,
    )
    elapsed = time.perf_counter() - started
    message = response.choices[0].message
    usage = response.usage

    return CompletionResult(
        answer=message.content or "(Модель не вернула текст ответа)",
        model=response.model or DEFAULT_MODEL,
        usage={
            "input_tokens": usage.prompt_tokens if usage else 0,
            "output_tokens": usage.completion_tokens if usage else 0,
            "total_tokens": usage.total_tokens if usage else 0,
        },
        elapsed_seconds=elapsed,
    )


def result_to_dict(result: CompletionResult, temperature: float) -> dict[str, Any]:
    return {
        "answer": result.answer,
        "model": result.model,
        "usage": result.usage,
        "elapsed_seconds": round(result.elapsed_seconds, 2),
        "temperature": temperature,
        "reasoning_enabled": False,
    }


def read_json_body() -> dict[str, Any]:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError("Ожидался JSON-объект.")
    return data


def require_text(data: dict[str, Any], key: str, limit: int) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Поле «{key}» не должно быть пустым.")
    value = value.strip()
    if len(value) > limit:
        raise ValueError(f"Поле «{key}» слишком длинное (максимум {limit} символов).")
    return value


@app.get("/")
def index():
    return render_template("index.html", model=DEFAULT_MODEL)


@app.post("/api/solve")
def solve():
    try:
        data = read_json_body()
        task = require_text(data, "task", MAX_TASK_LENGTH)
        temperature = require_temperature(data.get("temperature"))
        result = call_model([{"role": "user", "content": task}], temperature)
        return jsonify({"ok": True, **result_to_dict(result, temperature)})
    except ValueError as error:
        return jsonify({"ok": False, "error": str(error)}), 400
    except Exception as error:
        app.logger.exception("Ошибка DeepSeek API")
        return jsonify({"ok": False, "error": friendly_api_error(error)}), 502


@app.post("/api/compare")
def compare():
    try:
        data = read_json_body()
        task = require_text(data, "task", MAX_TASK_LENGTH)
        answers = data.get("answers")
        if not isinstance(answers, list) or len(answers) != 3:
            raise ValueError("Для сравнения нужна одна полная пачка из трёх ответов.")

        formatted_answers = []
        for index, item in enumerate(answers, start=1):
            if not isinstance(item, dict):
                raise ValueError("Неверный формат ответов для сравнения.")
            temperature = require_temperature(item.get("temperature"))
            answer = str(item.get("answer", "")).strip()[:MAX_ANSWER_LENGTH]
            if not answer:
                raise ValueError(f"Ответ {index} пуст.")
            formatted_answers.append(
                f"### Ответ {index} — temperature = {temperature:g}\n{answer}"
            )

        judge_prompt = (
            "Ты независимый проверяющий учебного эксперимента с температурой генерации. "
            "Сравни ровно три ответа на один и тот же запрос. Не считай более длинный ответ "
            "автоматически лучшим. Если фактическую точность нельзя установить без внешней "
            "проверки, прямо укажи это.\n\n"
            "Разбери ответы по трём критериям:\n"
            "1. Точность — корректность, конкретность, логические ошибки и необоснованные утверждения.\n"
            "2. Креативность — оригинальность идей и формулировок без ущерба для смысла.\n"
            "3. Разнообразие — широта подходов, примеров и вариантов внутри ответа.\n\n"
            "Затем сформулируй, для каких задач лучше подходит каждая из использованных температур, "
            "и дай короткий общий вывод. Используй понятные заголовки и обязательно ссылайся "
            "на фактические различия между представленными ответами.\n\n"
            f"Исходный запрос:\n{task}\n\n" + "\n\n".join(formatted_answers)
        )
        comparison_temperature = 0.0
        result = call_model(
            [{"role": "user", "content": judge_prompt}], comparison_temperature
        )
        return jsonify(
            {
                "ok": True,
                **result_to_dict(result, comparison_temperature),
                "comparison_temperature": comparison_temperature,
            }
        )
    except ValueError as error:
        return jsonify({"ok": False, "error": str(error)}), 400
    except Exception as error:
        app.logger.exception("Ошибка сравнения")
        return jsonify({"ok": False, "error": friendly_api_error(error)}), 502


@app.post("/api/save")
def save_run():
    try:
        data = read_json_body()
        task = require_text(data, "task", MAX_TASK_LENGTH)
        results = validate_saved_results(data.get("results"))
        comparison = validate_saved_comparison(data.get("comparison"))
        created_at = str(data.get("created_at", ""))[:80]

        now = datetime.now().astimezone()
        run_id = f"{now:%Y-%m-%d_%H-%M-%S}_{uuid.uuid4().hex[:6]}"
        run_dir = SAVED_RUNS_DIR / run_id
        run_dir.mkdir(parents=True, exist_ok=False)

        payload = {
            "run_id": run_id,
            "saved_at": now.isoformat(timespec="seconds"),
            "created_at": created_at,
            "task": task,
            "model": DEFAULT_MODEL,
            "reasoning_enabled": False,
            "results": results,
            "comparison": comparison,
        }
        (run_dir / "data.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (run_dir / "report.html").write_text(
            build_saved_report(payload), encoding="utf-8"
        )
        return jsonify(
            {
                "ok": True,
                "run_id": run_id,
                "folder": str(Path("saved_runs") / run_id),
                "report_url": url_for("saved_report", run_id=run_id),
            }
        )
    except (ValueError, OSError) as error:
        app.logger.exception("Ошибка сохранения запуска")
        return jsonify({"ok": False, "error": f"Не удалось сохранить запуск: {error}"}), 400


def validate_saved_results(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not 1 <= len(value) <= 3:
        raise ValueError("Для сохранения нужен хотя бы один результат из текущей пачки.")
    cleaned = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("Неверный формат сохраняемых результатов.")
        temperature = require_temperature(item.get("temperature"))
        answer = str(item.get("answer", ""))[:MAX_ANSWER_LENGTH]
        error = str(item.get("error", ""))[:2_000]
        if not answer and not error:
            raise ValueError("Сохраняемый результат не содержит ответа или ошибки.")
        usage = item.get("usage") if isinstance(item.get("usage"), dict) else {}
        cleaned.append(
            {
                "ok": bool(item.get("ok")),
                "temperature": temperature,
                "answer": answer,
                "error": error,
                "model": str(item.get("model", DEFAULT_MODEL))[:200],
                "elapsed_seconds": item.get("elapsed_seconds", 0),
                "usage": {
                    key: int(usage.get(key, 0)) if str(usage.get(key, 0)).isdigit() else 0
                    for key in ("input_tokens", "output_tokens", "total_tokens")
                },
            }
        )
    return cleaned


def validate_saved_comparison(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Неверный формат сравнения.")
    answer = str(value.get("answer", ""))[:MAX_ANSWER_LENGTH]
    if not answer:
        return None
    return {
        "answer": answer,
        "temperature": 0,
        "model": str(value.get("model", DEFAULT_MODEL))[:200],
        "elapsed_seconds": value.get("elapsed_seconds", 0),
        "usage": value.get("usage") if isinstance(value.get("usage"), dict) else {},
    }


@app.get("/saved")
def saved_runs():
    SAVED_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    runs = []
    for folder in sorted(SAVED_RUNS_DIR.iterdir(), reverse=True):
        data_path = folder / "data.json"
        if not folder.is_dir() or not data_path.is_file():
            continue
        try:
            data = json.loads(data_path.read_text(encoding="utf-8"))
            runs.append(
                {
                    "run_id": folder.name,
                    "saved_at": data.get("saved_at", ""),
                    "task": str(data.get("task", ""))[:180],
                    "count": len(data.get("results", [])),
                    "has_comparison": bool(data.get("comparison")),
                }
            )
        except (OSError, json.JSONDecodeError):
            continue
    return render_template("saved_runs.html", runs=runs)


@app.get("/saved/<run_id>")
def saved_report(run_id: str):
    if not RUN_ID_PATTERN.fullmatch(run_id):
        return "Неверное имя сохранённого запуска.", 404
    return send_from_directory(SAVED_RUNS_DIR / run_id, "report.html")


def build_saved_report(payload: dict[str, Any]) -> str:
    result_blocks = []
    for index, result in enumerate(payload["results"], start=1):
        body = result["answer"] if result["ok"] else f"Ошибка: {result['error']}"
        usage = result["usage"]
        result_blocks.append(
            "<article><h2>"
            f"Ответ {index} · temperature = {result['temperature']:g}"
            "</h2><div class=\"meta\">"
            f"{html.escape(result['model'])} · {html.escape(str(result['elapsed_seconds']))} сек. · "
            f"{usage.get('total_tokens', 0)} токенов</div>"
            f"<div class=\"text\">{html.escape(body)}</div></article>"
        )
    comparison = payload.get("comparison")
    comparison_block = ""
    if comparison:
        comparison_block = (
            "<article class=\"comparison\"><h2>Сравнение трёх ответов</h2>"
            "<div class=\"meta\">Температура проверяющего: 0</div>"
            f"<div class=\"text\">{html.escape(comparison['answer'])}</div></article>"
        )
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Сохранённый запуск {html.escape(payload['run_id'])}</title>
<style>
body{{margin:0;background:#04110e;color:#f8fafc;font:16px/1.65 system-ui,sans-serif}}main{{width:min(1100px,calc(100% - 32px));margin:48px auto 80px}}a{{color:#6ee7b7}}h1{{line-height:1.15}}.meta{{color:#91b3a8;font-size:13px}}.notice{{padding:12px 16px;border:1px solid #a3e635;border-radius:12px;color:#d9f99d;background:#16220b}}article,.task{{margin-top:20px;padding:24px;border:1px solid rgba(110,231,183,.18);border-radius:18px;background:#0b211b}}.text{{margin-top:16px;color:#d1fae5;white-space:pre-wrap;overflow-wrap:anywhere}}.comparison{{border-color:#2dd4bf}}small{{color:#91b3a8}}
</style></head><body><main>
<p><a href="/saved">← Все сохранённые запуски</a></p>
<h1>Эксперимент с температурой</h1>
<p class="notice"><strong>Reasoning выключен.</strong> Это необходимо, чтобы настройка температуры применялась.</p>
<small>Сохранено: {html.escape(payload['saved_at'])} · Модель: {html.escape(payload['model'])}</small>
<section class="task"><strong>Исходный запрос</strong><div class="text">{html.escape(payload['task'])}</div></section>
{''.join(result_blocks)}{comparison_block}
</main></body></html>"""


def friendly_api_error(error: Exception) -> str:
    text = str(error)
    lowered = text.lower()
    if "api key" in lowered or "authentication" in lowered or "401" in lowered:
        return "DeepSeek отклонил API-ключ. Проверьте DEEPSEEK_API_KEY в файле .env."
    if "429" in lowered or "rate limit" in lowered:
        return "DeepSeek временно ограничил количество запросов. Попробуйте немного позже."
    if "timeout" in lowered or "timed out" in lowered:
        return "DeepSeek не успел ответить. Повторите запрос."
    if "connection" in lowered or "connect" in lowered or "network" in lowered:
        return (
            "Не удалось установить соединение с DeepSeek. Проверьте интернет, VPN или прокси, "
            "затем перезапустите локальный сервер и повторите запрос."
        )
    return f"Не удалось получить ответ DeepSeek: {text}"


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
