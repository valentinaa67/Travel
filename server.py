"""
Маленький сервер-посредник между сайтом и ИИ.
Задача: держать ключ ИИ в секрете на сервере, принимать анкету с сайта
и возвращать три варианта поездки (тот же запрос, что и в Telegram-боте).

Файлы проекта:
  server.py          - этот файл
  requirements.txt   - список библиотек
  .env               - сюда кладём ключ (не публикуется никуда)
"""

import os
import re
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from anthropic import Anthropic

app = Flask(__name__)
CORS(app)  # разрешаем сайту (другой домен) обращаться к этому серверу

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://clodex.xyz")
MODEL_NAME = os.environ.get("MODEL_NAME", "claude-fable-5")

client = Anthropic(api_key=ANTHROPIC_API_KEY, base_url=ANTHROPIC_BASE_URL, max_retries=0)


def build_prompt(data, exclude=None, forced_destination=None):
    """Собирает текст запроса к ИИ на основе анкеты с сайта."""
    parts = []
    parts.append(f"Город вылета: {data.get('city', '')}")
    parts.append(f"Взрослых: {data.get('adults', '')}")
    children = str(data.get("children", "0"))
    if children in ("", "Нет"):
        children = "0"
    parts.append(f"Детей: {children}")
    if children != "0":
        parts.append(f"Возраст детей: {data.get('children_ages', '')}")
    parts.append(f"Гражданство: {data.get('citizenship', '')}")
    parts.append(f"Даты: {data.get('dates', '')}")
    parts.append(f"Ночей: {data.get('nights', '')}")
    parts.append(f"Погода: {data.get('weather', '')}")
    parts.append(f"Бюджет, руб: {data.get('budget', '')}")
    parts.append(f"Всё включено: {data.get('all_inclusive', '')}")

    exclude_text = ""
    if exclude:
        exclude_text = "Не предлагай снова: " + ", ".join(exclude) + ". "

    if forced_destination:
        task_text = (
            f"Дай только один вариант — город {forced_destination}. "
            "Если для этого гражданства туда сложно/нужна виза, добавь "
            "короткую строку 'Важно: ...' с пояснением."
        )
    else:
        task_text = "Предложи 3 варианта направления для поездки."

    system = (
        "Ты туристический помощник. Пиши живо и коротко, на русском. "
        "Учитывай гражданство при выборе стран (не предлагай места, "
        "куда сложно попасть с этим паспортом). "
        "Для каждого варианта обязательно укажи: город и страну, "
        "даты и число ночей, почему это подходит, название отеля с "
        "примерной ценой в рублях. Не добавляй ссылки сам — это добавит "
        "программа отдельно. " + exclude_text + task_text
    )

    return system, "\n".join(parts)


def add_links(block, city_country):
    """Добавляет ссылки на Островок и Aviasales в конец блока направления."""
    query = city_country.split(",")[0].strip()
    ostrovok = f"https://ostrovok.ru/hotel/search/?q={query}"
    aviasales = "https://www.aviasales.ru"
    return block.rstrip() + f"\n\n🏨 Отель: {ostrovok}\n✈️ Билеты: {aviasales}"


def split_destinations(text):
    """Разбивает ответ ИИ на отдельные направления по нумерации '1.', '2.'..."""
    parts = re.split(r"\n(?=\d+\.\s)", text.strip())
    return [p.strip() for p in parts if p.strip()]


@app.route("/suggest", methods=["POST"])
def suggest():
    data = request.get_json(force=True) or {}
    exclude = data.get("exclude", [])
    forced_destination = data.get("forced_destination")

    system, user_text = build_prompt(data, exclude=exclude, forced_destination=forced_destination)

    try:
        response = client.messages.create(
            model=MODEL_NAME,
            max_tokens=1500,
            system=system,
            messages=[{"role": "user", "content": user_text}],
            timeout=50,
        )
        ai_text = response.content[0].text
    except Exception as e:
        return jsonify({"error": f"Не получилось получить ответ от ИИ: {e}"}), 502

    blocks = split_destinations(ai_text)

    # Пытаемся вытащить "Город, Страна" из первой строки каждого блока,
    # чтобы подставить в ссылки. Если не получится - используем как есть.
    results = []
    for block in blocks:
        first_line = block.split("\n")[0]
        title = re.sub(r"^\d+\.\s*", "", first_line).strip()
        results.append({
            "title": title,
            "text": add_links(block, title),
        })

    return jsonify({"destinations": results})


@app.route("/", methods=["GET"])
def index():
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), "index.html")


@app.route("/health", methods=["GET"])
def health():
    return "OK, сервер работает"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
