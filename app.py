import json
import os
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler

# ───────────────────────────────────────────────
# СИСТЕМНЫЙ ПРОМТ — инструкция для коуча
# Именно здесь задаётся личность и поведение Claude
# ───────────────────────────────────────────────
SYSTEM_PROMPT = """Ты — коуч. Твоя задача помогать пользователю ставить цели и находить препятствия на пути к ним.

Правила:
- Задавай только ОДИН вопрос за раз. Никогда не задавай два вопроса подряд.
- Не давай советов и готовых ответов — только задавай вопросы.
- Помогай пользователю думать самостоятельно.
- Если пользователь назвал цель — помоги уточнить её и найти возможные препятствия.
- Если пользователь назвал препятствие — помоги разобраться что за ним стоит.
- Говори коротко и по делу. Ответы не длиннее 2-3 предложений.
- Общайся на русском языке.
- Начни первую сессию с вопроса: О какой цели вы хотите поговорить сегодня?
"""

# ───────────────────────────────────────────────
# ФУНКЦИЯ ЗАПРОСА К CLAUDE
# Используем urllib — встроенная библиотека Python
# Никаких внешних зависимостей не нужно
# ───────────────────────────────────────────────
def ask_claude(history):
    api_key = os.environ.get("ANTHROPIC_API_KEY")

    # Формируем тело запроса
    payload = json.dumps({
        "model": "claude-sonnet-4-6",
        "max_tokens": 300,
        "system": SYSTEM_PROMPT,
        "messages": history
    }).encode("utf-8")

    # Создаём HTTP запрос к серверам Anthropic
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        },
        method="POST"
    )

    # Отправляем и получаем ответ
    with urllib.request.urlopen(req, timeout=9) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    return result["content"][0]["text"]


# ───────────────────────────────────────────────
# ОБРАБОТЧИК ЗАПРОСОВ ОТ АЛИСЫ
# Render запускает веб-сервер — Алиса шлёт сюда запросы
# ───────────────────────────────────────────────
class AliceHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        # Отключаем лишние логи чтобы не засорять консоль
        pass

    def do_POST(self):
        try:
            # Читаем тело запроса от Алисы
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            body = json.loads(raw.decode("utf-8"))

            # Достаём что сказал пользователь
            user_text = body.get("request", {}).get("original_utterance", "")

            # Достаём историю разговора из памяти сессии
            session_state = body.get("state", {}).get("session", {})
            history = session_state.get("history", [])

            # Если новая сессия — начинаем заново
            is_new_session = body.get("session", {}).get("new", False)
            if is_new_session:
                history = []
                user_text = "Начни сессию"

            # Добавляем сообщение пользователя в историю
            history.append({
                "role": "user",
                "content": user_text
            })

            # Получаем ответ от Claude
            coach_reply = ask_claude(history)

            # Добавляем ответ коуча в историю
            history.append({
                "role": "assistant",
                "content": coach_reply
            })

            # Оставляем только последние 10 сообщений
            # чтобы не превысить лимит памяти Алисы
            if len(history) > 10:
                history = history[-10:]

        except Exception as e:
            # Если ошибка — говорим пользователю понятно
            print(f"ERROR: {e}")
            coach_reply = "Извините, произошла ошибка. Попробуйте ещё раз."
            history = []

        # Формируем ответ в формате который ожидает Алиса
        response = {
            "version": body.get("version", "1.0"),
            "session": body.get("session", {}),
            "response": {
                "text": coach_reply,
                "tts": coach_reply,
                "end_session": False
            },
            "session_state": {
                "history": history
            }
        }

        # Отправляем ответ обратно Алисе
        response_bytes = json.dumps(response, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(response_bytes))
        self.end_headers()
        self.wfile.write(response_bytes)

    def do_GET(self):
        # Простая проверка что сервер живой
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Alice Coach is running!")


# ───────────────────────────────────────────────
# ЗАПУСК СЕРВЕРА
# Render сам говорит на каком порту запускаться
# ───────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), AliceHandler)
    print(f"Server started on port {port}")
    server.serve_forever()
