import json
import os
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler

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

def ask_claude(history):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    payload = json.dumps({
        "model": "claude-sonnet-4-6",
        "max_tokens": 300,
        "system": SYSTEM_PROMPT,
        "messages": history
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


class AliceHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass

    def do_POST(self):
        body = {}
        coach_reply = "Извините, произошла ошибка. Попробуйте ещё раз."
        history = []

        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            print(f"RAW REQUEST: {raw[:200]}")
            body = json.loads(raw.decode("utf-8"))

            user_text = body.get("request", {}).get("original_utterance", "")
            session_state = body.get("state", {}).get("session", {})
            history = session_state.get("history", [])

            is_new_session = body.get("session", {}).get("new", False)
            if is_new_session:
                history = []
                user_text = "Начни сессию"

            print(f"USER TEXT: {user_text}")

            history.append({"role": "user", "content": user_text})
            coach_reply = ask_claude(history)
            history.append({"role": "assistant", "content": coach_reply})

            if len(history) > 10:
                history = history[-10:]

            print(f"COACH REPLY: {coach_reply}")

        except Exception as e:
            print(f"ERROR {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()

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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), AliceHandler)
    print(f"Server started on port {port}")
    server.serve_forever()
