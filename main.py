"""DeepSeek API. System промт пуст, не отправляется. Thinking - выключен. Каждое новое сообщение - отдельно (assistant промт не отправляется, то есть это не чат)"""

import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


def ask_deepseek(prompt: str) -> None:
    """Отправляет один запрос в LLM и печатает ответ."""
    # Ищем .env рядом с этим файлом, независимо от текущей папки запуска.
    load_dotenv(Path(__file__).with_name(".env"))
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        print("Ошибка: не найден DEEPSEEK_API_KEY в файле .env")
        print("Создайте .env по примеру .env.example и добавьте API-ключ.")
        sys.exit(1)

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    started = time.perf_counter()

    try:
        response = client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=[
                {"role": "user", "content": prompt},
            ],
            extra_body={"thinking": {"type": "disabled"}},
            stream=False,
        )
    except Exception as error:
        print(f"Ошибка при обращении к DeepSeek: {error}")
        return

    answer = response.choices[0].message.content or "(модель не вернула текст)"
    elapsed = time.perf_counter() - started
    print("\nОтвет DeepSeek:\n")
    print(answer)
    print(f"\nМодель: {response.model}")
    print("Reasoning: выключен")
    if response.usage:
        input_tokens = response.usage.prompt_tokens
        output_tokens = response.usage.completion_tokens
        total_tokens = input_tokens + output_tokens
        print(f"Входных токенов: {input_tokens}")
        print(f"Выходных токенов: {output_tokens}")
        print(f"Всего токенов: {total_tokens}")
    print(f"Время ответа: {elapsed:.2f} сек.")


def main() -> None:
    print("DeepSeek API. System промт пуст, не отправляется. Thinking - выключен. Каждое новое сообщение - отдельно (assistant промт не отправляется, то есть это не чат)")
    print("Для выхода напишите: выход, exit или quit.\n")

    # Аргумент командной строки обрабатываем как первый вопрос,
    # а затем переходим в обычный интерактивный режим.
    if len(sys.argv) > 1:
        ask_deepseek(" ".join(sys.argv[1:]).strip())

    while True:
        try:
            prompt = input("\nВведите вопрос: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nРабота завершена.")
            break

        if prompt.lower() in {"выход", "exit", "quit"}:
            print("Работа завершена.")
            break
        if not prompt:
            print("Введите вопрос или команду «выход».")
            continue

        ask_deepseek(prompt)


if __name__ == "__main__":
    main()
