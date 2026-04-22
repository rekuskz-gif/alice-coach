import json
import os
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler

# Сколько слов отправлять Алисе за один раз
CHUNK_SIZE = 25

# Токен бота и куда слать — берём из секретных переменных Render
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Промт коуча вшит прямо в код — так сервер не тратит время на загрузку из Google Docs
SYSTEM_PROMPT = """
1. ПРИОРИТЕТ для тебя №1: Узнай имя клиента и ВСЕГДА используй его в ответе.
2. ПРИОРИТЕТ для тебя №2: Лимит — 15 слов. Если слов больше, сокращай. Считай перед отправкой.
3. ПРИОРИТЕТ №3: Максимум 2 предложения. Второе — всегда вопрос.
4. ПРИОРИТЕТ №4: Озвучь правила, чтоб клиент всегда в начале обращения к тебе проговаривал твое имя Алиса, спроси "Хорошо?"

Ты умная колонка Алиса женского пола — профессиональный ИИ бизнес-коуч девушка женского рода имя твое "Алиса" ты Девушка тебе 18 лет женского пола.

Проводить сессию через Алису колонку сертифицированный по стандартам ICF, эксперт в методологии «Стрела» (ARROW).

Твоя цель: провести меня через полноценную коуч-сессию, помогая мне самому найти ответы и прийти к результату.

Правила твоей работы:
Не давай советов и готовых решений. Твоя сила — в глубоких, открытых вопросах.
Соблюдай структуру «Стрелы»:
Контракт (определение цели на сессию) Анонимность 45 минут;
Формат результата (проверка цели на важность и реалистичность);
Создание опыта (исследование ситуации и поиск идей);
Шаги (конкретный план действий);
Ценность (подведение итогов).
Иди шаг за шагом. Задавай только один вопрос за раз. Жди моего ответа, прежде чем переходить к следующему этапу или вопросу.
Будь эмпатичным, внимательно анализируй мои слова и подсвечивай важные моменты или противоречия, которые заметишь.

Запрещено: проговаривать символы #, *, **, [], слово проблема. Только чистый текст без форматирования.
Запрещено заканчивать ответ без вопроса. Говорить что ты текстовый ии, говорить что ты Claude.

Пиши от женского пола. Ты интегрирована в умную колонку Алису, пользователь обращается к тебе по имени Алиса женского пола. Сначала выполни 1 ПРИОРИТЕТ и спроси имя, дождись ответа, после узнай имя и озвучь четвертый ПРИОРИТЕТ и спроси у клиента "Хорошо?"
"""


def ask_claude(history):
    # Отправляем историю разговора в Claude и получаем ответ коуча
    payload = json.dumps({
        "model": "claude-haiku-4-5",
        "max_tokens": 80,
        "system": SYSTEM_PROMPT,
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
    # Отправляем диалог в Telegram чтобы видеть историю разговоров
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram: переменные не заданы")
        return
    try:
        message = f"👤 Пользователь: {user_text}\n🤖 Алиса: {coach_reply}"
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
        print("Telegram: сообщение отправлено")
    except Exception as e:
        # Если Telegram не ответил — не ломаем основной разговор
        print(f"Telegram error: {e}")


def split_into_chunks(text, chunk_size=CHUNK_SIZE):
    # Разбиваем длинный ответ на маленькие кусочки для Алисы
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
        tts = chunk + ' <speaker audio="alice-sounds-things-switch-1.opus"> '
    else:
        tts = chunk + ' <speaker audio="alice-sounds-things-switch-1.opus">'

    return tts, is_last


class AliceHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        # Отключаем стандартные логи сервера
        pass

    def do_POST(self):
        # Сюда приходит каждый запрос от Алисы
        body = {}
        coach_reply = "Извините, отвлеклась. Повторите ещё раз."
        tts_reply = coach_reply
        history = []
        end_session = False

        try:
            # Читаем что прислала Алиса
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8"))

            # Достаём текст который сказал пользователь
            user_text = body.get("request", {}).get("original_utterance", "").lower().strip()
            # Достаём сохранённые данные сессии
            session_state = body.get("state", {}).get("session", {})
            history = session_state.get("history", [])
            chunks = session_state.get("chunks", [])
            chunk_index = session_state.get("chunk_index", 0)

            # Проверяем новая ли это сессия
            is_new_session = body.get("session", {}).get("new", False)

            if is_new_session:
                # Новая сессия — обнуляем всё
                history = []
                chunks = []
                chunk_index = 0
                user_text = "начни"

            if chunks and chunk_index < len(chunks):
                # Продолжаем говорить несказанные кусочки
                tts_reply, is_last = build_tts(chunks, chunk_index)
                coach_reply = chunks[chunk_index]
                chunk_index += 1

                if is_last:
                    chunks = []
                    chunk_index = 0

            else:
                # Новый вопрос — спрашиваем Клода
                history.append({"role": "user", "content": user_text})
                full_reply = ask_claude(history)
                history.append({"role": "assistant", "content": full_reply})

                # Ограничиваем историю 20 сообщениями
                if len(history) > 20:
                    history = history[-20:]

                # Отправляем диалог в Telegram
                send_to_telegram(user_text, full_reply)

                # Разбиваем ответ на кусочки
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
            # Если что-то сломалось — пишем ошибку
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
            # Сохраняем историю для следующего запроса
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
        # Сюда стучится UptimeRobot каждые 5 минут
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Alice coach is running!")


if __name__ == "__main__":
    # Запускаем сервер
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), AliceHandler)
    print(f"Server started on port {port}")
    server.serve_forever()
