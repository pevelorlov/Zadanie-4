"""Локальные тесты без реальных запросов и расходов DeepSeek API."""

import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import CompletionResult, app, call_model, friendly_api_error, require_temperature
from main import find_available_port


def fake_result(answer: str = "Тестовый ответ") -> CompletionResult:
    return CompletionResult(
        answer=answer,
        model="test-model",
        usage={"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
        elapsed_seconds=0.25,
    )


class TemperatureTests(unittest.TestCase):
    def test_temperature_accepts_assignment_values(self):
        values = [require_temperature(value) for value in (0, 0.7, 1.2)]
        self.assertEqual(values, [0, 0.7, 1.2])

    def test_temperature_rejects_out_of_range_value(self):
        with self.assertRaises(ValueError):
            require_temperature(2.1)

    @patch("app.get_client")
    def test_call_disables_thinking_and_sends_temperature(self, mocked_get_client):
        response = type("Response", (), {})()
        response.choices = [type("Choice", (), {"message": type("Message", (), {"content": "Ответ"})()})()]
        response.usage = None
        response.model = "test-model"
        mocked_get_client.return_value.chat.completions.create.return_value = response
        call_model([{"role": "user", "content": "Тест"}], 0.7)
        kwargs = mocked_get_client.return_value.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["temperature"], 0.7)
        self.assertEqual(kwargs["extra_body"], {"thinking": {"type": "disabled"}})

    def test_launcher_skips_an_occupied_port(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
            occupied.bind(("127.0.0.1", 0))
            port = occupied.getsockname()[1]
            self.assertEqual(find_available_port(port, port + 1), port + 1)


class ApiTests(unittest.TestCase):
    def setUp(self):
        app.config.update(TESTING=True)
        self.client = app.test_client()

    def test_index_shows_reasoning_notice_and_defaults(self):
        text = self.client.get("/").get_data(as_text=True)
        self.assertIn("Reasoning выключен", text)
        self.assertEqual(text.count('type="range"'), 3)
        self.assertIn('value="0.7"', text)
        self.assertIn('value="1.2"', text)

    def test_connection_error_has_practical_message(self):
        message = friendly_api_error(RuntimeError("Connection error."))
        self.assertIn("соединение с DeepSeek", message)
        self.assertIn("перезапустите", message)

    def test_empty_task_is_rejected(self):
        response = self.client.post("/api/solve", json={"task": "", "temperature": 0})
        self.assertEqual(response.status_code, 400)

    @patch("app.call_model")
    def test_solve_passes_temperature(self, mocked_call):
        mocked_call.return_value = fake_result()
        response = self.client.post("/api/solve", json={"task": "Тест", "temperature": 1.2})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mocked_call.call_args.args[1], 1.2)
        self.assertFalse(response.get_json()["reasoning_enabled"])

    @patch("app.call_model")
    def test_comparison_requires_three_answers_and_uses_zero(self, mocked_call):
        mocked_call.return_value = fake_result("Сравнение")
        answers = [
            {"temperature": value, "answer": f"Ответ {index}"}
            for index, value in enumerate((0, 0.7, 1.2), start=1)
        ]
        response = self.client.post("/api/compare", json={"task": "Тест", "answers": answers})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mocked_call.call_args.args[1], 0.0)
        self.assertEqual(response.get_json()["comparison_temperature"], 0.0)

    def test_comparison_rejects_incomplete_batch(self):
        response = self.client.post(
            "/api/compare",
            json={"task": "Тест", "answers": [{"temperature": 0, "answer": "Один"}]},
        )
        self.assertEqual(response.status_code, 400)

    def test_save_creates_json_and_standalone_html(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch("app.SAVED_RUNS_DIR", Path(temp_dir)):
            response = self.client.post(
                "/api/save",
                json={
                    "task": "<Проверяем экранирование>",
                    "results": [{
                        "ok": True,
                        "temperature": 0,
                        "answer": "Ответ",
                        "model": "test-model",
                        "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
                        "elapsed_seconds": 0.1,
                    }],
                    "comparison": {"answer": "Анализ", "model": "test-model"},
                },
            )
            self.assertEqual(response.status_code, 200)
            run_dir = Path(temp_dir) / response.get_json()["run_id"]
            data = json.loads((run_dir / "data.json").read_text(encoding="utf-8"))
            report = (run_dir / "report.html").read_text(encoding="utf-8")
            self.assertEqual(data["task"], "<Проверяем экранирование>")
            self.assertIn("Reasoning выключен", report)
            self.assertIn("&lt;Проверяем экранирование&gt;", report)
            self.assertNotIn("<Проверяем экранирование>", report)


if __name__ == "__main__":
    unittest.main()
