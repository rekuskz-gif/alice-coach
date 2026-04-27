import json
import os
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler

# ID гугл документа где хранится системный промт коуча
GOOGLE_DOC_ID = "1pBAau6Z9313yJkxveI5bSVzxJVsk4eaHIttzAj_xmls"

# Сколько слов отправлять Алисе за один раз (чтобы не было длинных пауз)
CHUNK_SIZE = 7

# Токен бота и куда слать — берём из секретных переменных Render
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def load_prompt():
    # Загружаем системный промт коуча из Google Docs
    url = f"https://docs.google.com/document/d/{GOOGLE_DOC_ID}/export?format=txt"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.read().decode("utf-8").strip()


def ask_claude(history, prompt):
    # Отправляем историю разговора в Claude и получаем ответ коуча
    payload = json.dumps({
        "model": "claude-haiku-4-5",
        "max_tokens": 80,
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


def send_to_telegram(user_text, coach_reply):
    # Отправляем диалог в Telegram бот чтобы видеть историю разговоров
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        # Если переменные не заданы — просто пропускаем, не ломаем разговор
        return
    try:
        # Формируем красивое сообщение с эмодзи
        message = f"👤 Пользователь: {user_text}\n🤖 Коуч: {coach_reply}"
        # Кодируем текст для отправки через интернет
        data = json.dumps({
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message
        }).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        # Если Telegram не ответил — не ломаем основной разговор с Алисой
        print(f"Telegram error: {e}")


def split_into_chunks(text, chunk_size=CHUNK_SIZE):
    # Разбиваем длинный ответ коуча на маленькие кусочки для Алисы
    words = text.split()
    chunks = []
    current = []

    for word in words:
        current.append(word)
        if len(current) >= chunk_size and word.endswith(('.', '!', '?', ',', '…')):
            chunks.append(' '.join(current))
            current = []

    if current:
        chunks.append(' '.join(current))

    return chunks


def build_tts(chunks, current_index):
    # Собираем кусочек текста который Алиса произнесёт вслух
    if current_index >= len(chunks):
        return chunks[-1] if chunks else "", True

    chunk = chunks[current_index]
    is_last = current_index >= len(chunks) - 1

    if not is_last:
        # Добавляем звук переключения между кусочками
        tts = chunk + ' <speaker audio="alice-sounds-things-switch-1.opus"> '
    else:
        tts = chunk + ' <speaker audio="alice-sounds-things-switch-1.opus">'

    return tts, is_last


class AliceHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        # Отключаем стандартные логи сервера чтобы не засорять консоль
        pass

    def do_POST(self):
        # Сюда приходит каждый запрос от Алисы когда пользователь что-то сказал
        body = {}
        coach_reply = "Извините отвлеклась. повторите ещё раз."
        tts_reply = coach_reply
        history = []
        end_session = False

        try:
            # Читаем что прислала Алиса
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8"))

            # Достаём текст который сказал пользователь
            user_text = body.get("request", {}).get("original_utterance", "").lower().strip()
            # Достаём сохранённые данные сессии (история, кусочки текста)
            session_state = body.get("state", {}).get("session", {})
            history = session_state.get("history", [])
            chunks = session_state.get("chunks", [])
            chunk_index = session_state.get("chunk_index", 0)

            # Проверяем новая ли это сессия (пользователь только открыл навык)
            is_new_session = body.get("session", {}).get("new", False)

            if is_new_session:
                # Если новая сессия — обнуляем всё и начинаем заново
                history = []
                chunks = []
                chunk_index = 0
                user_text = "начни"

            if chunks and chunk_index < len(chunks):
                # Если есть несказанные кусочки — продолжаем говорить их
                tts_reply, is_last = build_tts(chunks, chunk_index)
                coach_reply = chunks[chunk_index]
                chunk_index += 1

                if is_last:
                    chunks = []
                    chunk_index = 0

            else:
                # Новый вопрос от пользователя — добавляем в историю и спрашиваем Клода
                history.append({"role": "user", "content": user_text})
                full_reply = ask_claude(history, load_prompt())
                history.append({"role": "assistant", "content": full_reply})

                # Ограничиваем историю 20 сообщениями чтобы не перегружать память
                if len(history) > 20:
                    history = history[-20:]

                # Отправляем диалог в Telegram чтобы видеть историю разговоров
                send_to_telegram(user_text, full_reply)

                # Разбиваем ответ на кусочки для Алисы
                chunks = split_into_chunks(full_reply)
                chunk_index = 0

                tts_reply, is_last = build_tts(chunks, chunk_index)
                coach_reply = chunks[chunk_index] if chunks else full_reply
                chunk_index += 1

                if is_last:
                    chunks = []
                    chunk_index = 0

            print(f"TTS: {tts_reply[:80]}...")

        except Exception as e:
            # Если что-то сломалось — пишем ошибку в лог и отвечаем стандартной фразой
            print(f"ERROR {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            chunks = []
            chunk_index = 0

        # Формируем ответ для Алисы
        response = {
            "version": body.get("version", "1.0"),
            "session": body.get("session", {}),
            "response": {
                "text": coach_reply,
                "tts": tts_reply,
                "end_session": end_session
            },
            # Сохраняем историю и кусочки текста для следующего запроса
            "session_state": {
                "history": history,
                "chunks": chunks,
                "chunk_index": chunk_index
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
        # Сюда стучится UptimeRobot каждые 5 минут чтобы сервер не засыпал
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Claude-alice is running!")


if __name__ == "__main__":
    # Запускаем сервер на порту который задал Render
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), AliceHandler)
    print(f"Server started on port {port}")
    server.serve_forever()
