import json
import os
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler

# ───────────────────────────────────────────────
# ID твоего Google документа с промтом
# Это часть ссылки между /d/ и /edit
# ───────────────────────────────────────────────
GOOGLE_DOC_ID = "1pBAau6Z9313yJkxveI5bSVzxJVsk4eaHIttzAj_xmls"

# ───────────────────────────────────────────────
# ЗАГРУЗКА ПРОМТА ИЗ GOOGLE DOCS
# Google позволяет скачать документ как обычный текст
# Это значит можно менять промт прямо в документе
# без изменения кода
# ───────────────────────────────────────────────
def load_prompt_from_google_doc():
    try:
        # Формируем ссылку для скачивания документа как текста
        url = f"https://docs.google.com/document/d/{GOOGLE_DOC_ID}/export?format=txt"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            prompt = resp.read().decode("utf-8").strip()
            print(f"Промт загружен из Google Doc: {len(prompt)} символов")
            return prompt
    except Exception as e:
        # Если документ недоступен — используем запасной промт
        print(f"Не удалось загрузить промт из Google Doc: {e}")
        return """Ты — коуч. Твоя задача помогать пользователю ставить цели и находить препятствия на пути к ним.
Задавай только ОДИН вопрос за раз. Не давай советов — только задавай вопросы.
Говори коротко, не длиннее 2-3 предложений. Общайся на русском языке.
Начни с вопроса: О какой цели вы хотите поговорить сегодня?"""


# ───────────────────────────────────────────────
# ЗАПРОС К CLAUDE
# Используем claude-haiku — самая быстрая и дешёвая модель
# Для коуча с короткими вопросами этого достаточно
# ───────────────────────────────────────────────
def ask_claude(history, system_prompt):
    api_key = os.environ.get("ANTHROPIC_API_KEY")

    payload = json.dumps({
        "model": "claude-haiku-4-5",  # Самая быстрая и дешёвая модель
        "max_tokens": 300,             # Короткие ответы — коуч говорит кратко
        "system": system_prompt,       # Промт загруженный из Google Doc
        "messages": history            # Вся история разговора
    }).encode("utf-8")

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

    with urllib.request.urlopen(req, timeout=9) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    return result["content"][0]["text"]


# ───────────────────────────────────────────────
# ОБРАБОТЧИК ЗАПРОСОВ ОТ АЛИСЫ
# ───────────────────────────────────────────────
class AliceHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass

    def do_POST(self):
        body = {}
        coach_reply = "Извините, произошла ошибка. Попробуйте ещё раз."
        history = []

        try:
            # Читаем запрос от Алисы
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            body = json.loads(raw.decode("utf-8"))

            # Достаём текст пользователя
            user_text = body.get("request", {}).get("original_utterance", "")

            # ───────────────────────────────────────
            # ИСТОРИЯ РАЗГОВОРА
            # Алиса хранит историю в session_state
            # Это позволяет коучу помнить весь разговор
            # и не терять контекст между репликами
            # ───────────────────────────────────────
            session_state = body.get("state", {}).get("session", {})
            history = session_state.get("history", [])

            # Новая сессия — начинаем заново
            is_new_session = body.get("session", {}).get("new", False)
            if is_new_session:
                history = []
                user_text = "Начни сессию"

            print(f"USER: {user_text} | ИСТОРИЯ: {len(history)} сообщений")

            # Добавляем реплику пользователя в историю
            history.append({"role": "user", "content": user_text})

            # Загружаем промт из Google Doc при каждом запросе
            # Это позволяет менять поведение коуча без перезапуска сервера
            system_prompt = load_prompt_from_google_doc()

            # Получаем ответ от Claude
            coach_reply = ask_claude(history, system_prompt)

            # Добавляем ответ коуча в историю
            history.append({"role": "assistant", "content": coach_reply})

            # ───────────────────────────────────────
            # ЗАЩИТА КОНТЕКСТА
            # Храним последние 20 сообщений (10 пар вопрос-ответ)
            # Этого хватает для полноценной сессии
            # При этом не превышаем лимит памяти Алисы
            # ───────────────────────────────────────
            if len(history) > 20:
                history = history[-20:]

            print(f"COACH: {coach_reply}")

        except Exception as e:
            print(f"ERROR {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()

        # Формируем ответ для Алисы
        response = {
            "version": body.get("version", "1.0"),
            "session": body.get("session", {}),
            "response": {
                "text": coach_reply,
                "tts": coach_reply,
                "end_session": False
            },
            # Сохраняем историю — это главное для сохранения контекста
            "session_state": {
                "history": history
            }
        }

        response_bytes = json.dumps(response, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(response_bytes))
        self.end_headers()
        self.wfile.write(response_bytes)

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Alice Coach is running!")


# ───────────────────────────────────────────────
# ЗАПУСК СЕРВЕРА
# ───────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), AliceHandler)
    print(f"Server started on port {port}")
    server.serve_forever()
