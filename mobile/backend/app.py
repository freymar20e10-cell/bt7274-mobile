"""
BT-7274 Mobile — Backend (Flask)
Servidor que se hostea gratis en Render.
Chat, voz, Spotify, notas, memoria, clima.
"""

import os
import json
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime
from pathlib import Path

from flask import Flask, request, jsonify, Response, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, static_folder="../frontend", static_url_path="")
CORS(app)

# ═══════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")

OPENROUTER_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"
ASSISTANT_NAME = "BT-7274"
USER_NAME = "Piloto"

# Datos
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
MEMORY_FILE = DATA_DIR / "memory.json"
NOTES_FILE = DATA_DIR / "notes.json"

# Conversaciones
conversations = {}

# Spotify token cache
_spotify_token = None
_spotify_token_expires = 0


# ═══════════════════════════════════════════
# SYSTEM PROMPT
# ═══════════════════════════════════════════

def get_system_prompt():
    memory = _load_memory()
    mem_text = ""
    if memory:
        mem_text = "\n\nMEMORIA DEL USUARIO:\n" + "\n".join(f"- {k}: {v}" for k, v in memory.items())

    return f"""Eres {ASSISTANT_NAME}, un asistente de IA personal tipo JARVIS.
Tu piloto se llama {USER_NAME}. Eres leal, directo, eficiente y con personalidad.
Hablas en español. Eres como el Titan BT-7274 de Titanfall: protector, confiable.

REGLAS ESTRICTAS:
- NUNCA muestres tu proceso de pensamiento ni razonamiento interno.
- NUNCA escribas en inglés ni frases como "Let me think", "Okay", "Wait", "First I should".
- SOLO responde con la respuesta final directa en español.
- Sé conciso: máximo 2-3 oraciones para preguntas simples.
- Usa emojis ocasionalmente.

CAPACIDADES EN MODO MÓVIL:
- Puedes recordar cosas: si el usuario dice "recuerda que X", responde con [MEMORY:clave=valor]
- Puedes reproducir música: si pide una canción, responde con [SPOTIFY:nombre de la canción]
- Puedes abrir YouTube: responde con [YOUTUBE:lo que quiere ver]
- Puedes abrir apps: responde con [OPEN_APP:nombre]
- Para clima usa la ciudad guardada en memoria, o Barrancabermeja por defecto.
- Para la hora, usa UTC-5 (Colombia).

FORMATO ESPECIAL (usa estos tags cuando aplique):
- [MEMORY:ciudad=Bogotá] → guarda en memoria
- [SPOTIFY:Rara vez de Milo J] → reproduce en Spotify
- [OPEN_SPOTIFY] → abre Spotify
- [YOUTUBE:MrBeast último video] → busca en YouTube
- [OPEN_APP:whatsapp] → abre WhatsApp
- [OPEN_APP:camera] → abre la cámara
- [OPEN_APP:instagram] → abre Instagram
- [OPEN_APP:telegram] → abre Telegram
- [OPEN_APP:tiktok] → abre TikTok
- [WHATSAPP:número=mensaje] → abre WhatsApp con mensaje listo (ej: [WHATSAPP:573001234567=Hola qué tal])
- Si el usuario no da número pero sí nombre, usa [WHATSAPP:nombre=mensaje]
{mem_text}
"""


# ═══════════════════════════════════════════
# UTILIDADES
# ═══════════════════════════════════════════

def _load_memory():
    if not MEMORY_FILE.exists():
        return {}
    try:
        return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_memory(mem):
    MEMORY_FILE.write_text(json.dumps(mem, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_notes():
    if not NOTES_FILE.exists():
        return []
    try:
        return json.loads(NOTES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_notes(notes):
    NOTES_FILE.write_text(json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8")


def filter_reasoning(text: str) -> str:
    """Filtra razonamiento interno del modelo."""
    lines = text.split("\n")
    reasoning_starts = ["okay,", "let me", "first,", "wait,", "so,", "looking at",
                       "the user", "i should", "i need to", "but wait", "hmm",
                       "earlier,", "thus,", "response:", "so maybe:", "but since",
                       "now,", "alright", "let's"]

    clean_lines = []
    for line in lines:
        line_lower = line.strip().lower()
        if not any(line_lower.startswith(r) for r in reasoning_starts):
            if line.strip():
                clean_lines.append(line)

    result = "\n".join(clean_lines).strip()
    return result if result else text


def process_tags(response: str) -> dict:
    """Procesa tags especiales en la respuesta [MEMORY:x=y] [SPOTIFY:x] etc."""
    actions = []

    # MEMORY
    import re
    mem_matches = re.findall(r'\[MEMORY:(.+?)=(.+?)\]', response)
    for key, value in mem_matches:
        mem = _load_memory()
        mem[key.strip()] = value.strip()
        _save_memory(mem)
        actions.append({"type": "memory", "key": key.strip(), "value": value.strip()})
        response = response.replace(f"[MEMORY:{key}={value}]", "")

    # SPOTIFY
    spotify_matches = re.findall(r'\[SPOTIFY:(.+?)\]', response)
    for query in spotify_matches:
        actions.append({"type": "spotify_play", "query": query.strip()})
        response = response.replace(f"[SPOTIFY:{query}]", "")

    # OPEN SPOTIFY
    if "[OPEN_SPOTIFY]" in response:
        actions.append({"type": "spotify_open"})
        response = response.replace("[OPEN_SPOTIFY]", "")

    # YOUTUBE
    youtube_matches = re.findall(r'\[YOUTUBE:(.+?)\]', response)
    for query in youtube_matches:
        actions.append({"type": "youtube_play", "query": query.strip()})
        response = response.replace(f"[YOUTUBE:{query}]", "")

    # OPEN APP
    app_matches = re.findall(r'\[OPEN_APP:(.+?)\]', response)
    for app_name in app_matches:
        actions.append({"type": "open_app", "app": app_name.strip().lower()})
        response = response.replace(f"[OPEN_APP:{app_name}]", "")

    # WHATSAPP MESSAGE
    wa_matches = re.findall(r'\[WHATSAPP:(.+?)=(.+?)\]', response)
    for number_or_name, message in wa_matches:
        actions.append({"type": "whatsapp", "to": number_or_name.strip(), "message": message.strip()})
        response = response.replace(f"[WHATSAPP:{number_or_name}={message}]", "")

    return {"response": response.strip(), "actions": actions}


# ═══════════════════════════════════════════
# SPOTIFY API (reproducir directo)
# ═══════════════════════════════════════════

def _get_spotify_token() -> str:
    """Obtiene token de Spotify usando Client Credentials."""
    global _spotify_token, _spotify_token_expires

    if _spotify_token and time.time() < _spotify_token_expires:
        return _spotify_token

    url = "https://accounts.spotify.com/api/token"
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": SPOTIFY_CLIENT_ID,
        "client_secret": SPOTIFY_CLIENT_SECRET,
    }).encode("utf-8")

    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            _spotify_token = result.get("access_token", "")
            _spotify_token_expires = time.time() + result.get("expires_in", 3600) - 60
            return _spotify_token
    except Exception:
        return ""


def spotify_search(query: str) -> dict:
    """Busca una canción en Spotify y devuelve el URI."""
    token = _get_spotify_token()
    if not token:
        return {"error": "No token"}

    # Separar artista si dice "X de Y"
    search_query = query
    for sep in [" de ", " por ", " by "]:
        if sep in query.lower():
            parts = query.lower().split(sep, 1)
            search_query = f"track:{parts[0].strip()} artist:{parts[1].strip()}"
            break

    encoded = urllib.parse.quote(search_query)
    url = f"https://api.spotify.com/v1/search?q={encoded}&type=track&limit=1"

    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}"
    })

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            tracks = data.get("tracks", {}).get("items", [])
            if tracks:
                track = tracks[0]
                return {
                    "name": track["name"],
                    "artist": track["artists"][0]["name"],
                    "uri": track["uri"],
                    "url": track["external_urls"]["spotify"],
                }
    except Exception as e:
        return {"error": str(e)}

    return {"error": "No encontrado"}


# ═══════════════════════════════════════════
# OPENROUTER
# ═══════════════════════════════════════════

def call_openrouter(messages: list) -> str:
    url = "https://openrouter.ai/api/v1/chat/completions"
    formatted = [{"role": "system", "content": get_system_prompt()}] + messages

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": formatted,
        "temperature": 0.7,
        "max_tokens": 512,
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
    })

    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                result = json.loads(response.read().decode("utf-8"))
                choices = result.get("choices", [])
                if choices:
                    content = choices[0].get("message", {}).get("content", "")
                    if content:
                        return content
            time.sleep(2)
        except Exception as e:
            if attempt < 2:
                time.sleep(2)
            else:
                return f"Error de conexión. Intenta de nuevo."

    return "No pude responder. Intenta de nuevo."


# ═══════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════

@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json
    message = data.get("message", "")
    session_id = data.get("session_id", "default")

    if session_id not in conversations:
        conversations[session_id] = []

    # Detectar preguntas directas ANTES de mandar a la IA
    msg_lower = message.lower().strip()

    # CLIMA — responder directo con datos reales
    if any(w in msg_lower for w in ["clima", "temperatura", "hace frío", "hace calor", "tiempo hace"]):
        mem = _load_memory()
        city = mem.get("ciudad", "Barrancabermeja")
        try:
            encoded = urllib.parse.quote(city)
            url = f"https://wttr.in/{encoded}?format=j1"
            req = urllib.request.Request(url, headers={"User-Agent": "BT-7274/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                wdata = json.loads(resp.read().decode("utf-8"))
            current = wdata.get("current_condition", [{}])[0]
            location = wdata.get("nearest_area", [{}])[0]
            city_name = location.get("areaName", [{"value": city}])[0]["value"]
            temp = current.get("temp_C", "?")
            feels = current.get("FeelsLikeC", "?")
            humidity = current.get("humidity", "?")
            weather_resp = f"🌤️ En {city_name} hay {temp}°C (sensación {feels}°C), humedad {humidity}%."
            conversations[session_id].append({"role": "user", "content": message})
            conversations[session_id].append({"role": "assistant", "content": weather_resp})
            return jsonify({"response": weather_resp, "actions": [], "spotify": None})
        except Exception:
            pass

    # HORA — responder directo
    if any(w in msg_lower for w in ["qué hora", "que hora", "hora es"]):
        from datetime import timezone, timedelta
        now = datetime.now(timezone(timedelta(hours=-5)))
        time_resp = f"🕐 Son las {now.strftime('%I:%M %p')} en Colombia ({now.strftime('%A %d de %B')})."
        conversations[session_id].append({"role": "user", "content": message})
        conversations[session_id].append({"role": "assistant", "content": time_resp})
        return jsonify({"response": time_resp, "actions": [], "spotify": None})

    # Para todo lo demás — usar la IA
    conversations[session_id].append({"role": "user", "content": message})
    if len(conversations[session_id]) > 20:
        conversations[session_id] = conversations[session_id][-20:]

    response = call_openrouter(conversations[session_id])
    response = filter_reasoning(response)

    # Procesar tags especiales
    processed = process_tags(response)
    clean_response = processed["response"]
    actions = processed["actions"]

    conversations[session_id].append({"role": "assistant", "content": clean_response})

    # Procesar acciones de Spotify
    spotify_data = None
    for action in actions:
        if action["type"] == "spotify_play":
            spotify_data = spotify_search(action["query"])
        elif action["type"] == "spotify_open":
            spotify_data = {"open": True}

    return jsonify({
        "response": clean_response,
        "actions": actions,
        "spotify": spotify_data,
    })


@app.route("/api/spotify/search", methods=["GET"])
def api_spotify_search():
    query = request.args.get("q", "")
    if not query:
        return jsonify({"error": "No query"}), 400
    result = spotify_search(query)
    return jsonify(result)


@app.route("/api/weather", methods=["GET"])
def weather():
    mem = _load_memory()
    default_city = mem.get("ciudad", "Barrancabermeja")
    city = request.args.get("city", default_city)

    try:
        encoded = urllib.parse.quote(city)
        url = f"https://wttr.in/{encoded}?format=j1"
        req = urllib.request.Request(url, headers={"User-Agent": "BT-7274/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        current = data.get("current_condition", [{}])[0]
        location = data.get("nearest_area", [{}])[0]

        return jsonify({
            "city": location.get("areaName", [{"value": city}])[0]["value"],
            "temp": current.get("temp_C", "?"),
            "feels_like": current.get("FeelsLikeC", "?"),
            "humidity": current.get("humidity", "?"),
            "wind": current.get("windspeedKmph", "?"),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/notes", methods=["GET"])
def get_notes():
    return jsonify({"notes": _load_notes()})


@app.route("/api/notes", methods=["POST"])
def add_note():
    data = request.json
    notes = _load_notes()
    notes.append({"content": data.get("content", ""), "created_at": datetime.now().isoformat()})
    _save_notes(notes)
    return jsonify({"ok": True})


@app.route("/api/memory", methods=["GET"])
def get_memory():
    return jsonify(_load_memory())


@app.route("/api/tts", methods=["POST"])
def text_to_speech():
    data = request.json
    text = data.get("text", "")[:250]
    if not ELEVENLABS_API_KEY or not text:
        return jsonify({"error": "No disponible"}), 400

    voice_id = "iP95p4xoKVk53GoZ742B"  # Carlos - español, serio, claro
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
    payload = json.dumps({
        "text": text,
        "model_id": "eleven_flash_v2_5",
        "voice_settings": {"stability": 0.45, "similarity_boost": 0.75, "style": 0.2}
    }).encode("utf-8")

    req = urllib.request.Request(url, data=payload, method="POST", headers={
        "Content-Type": "application/json",
        "xi-api-key": ELEVENLABS_API_KEY,
        "Accept": "audio/mpeg",
    })

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return Response(resp.read(), mimetype="audio/mpeg")
    except Exception:
        return jsonify({"error": "TTS failed"}), 500


@app.route("/api/status", methods=["GET"])
def status():
    return jsonify({"name": ASSISTANT_NAME, "status": "online", "mode": "mobile"})


@app.route("/", methods=["GET"])
def index():
    return send_from_directory(app.static_folder, "index.html")


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
