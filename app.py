import json
import os
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler

GOOGLE_DOC_ID = "1pBAau6Z9313yJkxveI5bSVzxJVsk4eaHIttzAj_xmls"

def load_prompt():
    url = f"https://docs.google.com/document/d/{GOOGLE_DOC_ID}/export?format=txt"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.read().decode("utf-8").strip()

def ask_claude(history, prompt):
    payload = json.dumps({
        "model": "claude-haiku-4-5",
        "max_tokens": 800,
        "system": prompt,
        "messages": history
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "x-api-key": os.environ.get("ANTHROPIC_API_KEY"),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=9) as resp:
        return json.loads(resp.read().decode("utf-8"))["content"][0]["text"]

class AliceHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass

    def do_POST(self):
        body = {}
        coach_reply = "Извините, произошла ошибка. Попробуйте ещё раз."
        history = []

        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8"))

            user_text = body.get("request", {}).get("original_utterance", "")
            history = body.get("state", {}).get("session", {}).get("history", [])

            if body.get("session", {}).get("new", False):
                history = []
                user_text = "начни"

            history.append({"role": "user", "content": user_text})
            coach_reply = ask_claude(history, load_prompt())
            history.append({"role": "assistant", "content": coach_reply})

            if len(history) > 20:
                history = history[-20:]

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
            "session_state": {"history": history}
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
