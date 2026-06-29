"""
BT-7274 Mobile — Backend (Flask)
Servidor ligero que se hostea gratis en Render/Railway.
Funciona SIN tu PC: chat, voz, Spotify, notas, clima.
"""

import os
import json
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime
from pathlib import Path

from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
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

# Memoria simple en archivo (en el servidor)
MEMORY_FILE = Path("data/memory.json")
NOTES_FILE = Path("data/notes.json")
MEMORY_FILE.parent.mkdir(exist_ok=True)

# Conversación por sesión
conversations = {}

SYSTEM_PROMPT = f"""Eres {ASSISTANT_NAME}, un asistente de IA personal tipo JARVIS.
Tu piloto se llama {USER_NAME}. Eres leal, directo, eficiente y con personalidad.
Hablas en español. Eres como el Titan BT-7274 de Titanfall: protector, confiable.
Responde de forma concisa pero útil. Usa emojis ocasionalmente.
Estás corriendo en modo móvil — no puedes controlar la PC del usuario ahora,
pero puedes chatear, dar información, controlar Spotify, guardar notas y recordar cosas.

REGLAS ESTRICTAS:
- NUNCA muestres tu proceso de pensamiento ni razonamiento interno.
- NUNCA escribas frases como "Let me think", "Okay, the user is asking", "First I should", "Wait", etc.
- SOLO responde con la respuesta final directa al usuario.
- Responde SIEMPRE en español.
- Sé conciso: máximo 2-3 oraciones para preguntas simples.
"""


# ═══════════════════════════════════════════
# CHAT (OpenRouter)
# ═══════════════════════════════════════════

def filter_reasoning(text: str) -> str:
    """Filtra el razonamiento interno del modelo y deja solo la respuesta final."""
    # Si el modelo piensa en inglés pero responde en español, tomar solo la parte en español
    lines = text.split("\n")
    
    # Detectar patrones de razonamiento
    reasoning_starts = ["okay,", "let me", "first,", "wait,", "so,", "looking at",
                       "the user", "i should", "i need to", "but wait", "hmm",
                       "earlier,", "thus,", "response:", "so maybe:"]
    
    # Buscar dónde empieza la respuesta real
    clean_lines = []
    found_response = False
    
    for line in lines:
        line_lower = line.strip().lower()
        
        # Si encontramos una línea que parece respuesta en español
        if any(c in line for c in "áéíóúñ¿¡") and not line_lower.startswith(tuple(reasoning_starts)):
            found_response = True
        
        # Si empieza con "Response:" tomar lo que sigue
        if line_lower.startswith("response:"):
            clean_lines.append(line[len("response:"):].strip().strip('"'))
            found_response = True
            continue
            
        if found_response and line.strip():
            # Solo agregar líneas que parecen español / respuesta final
            if not any(line_lower.startswith(r) for r in reasoning_starts):
                clean_lines.append(line)
    
    if clean_lines:
        result = "\n".join(clean_lines).strip()
        # Limpiar comillas sobrantes
        result = result.strip('"').strip("'")
        if result:
            return result
    
    # Si no pudo filtrar, devolver todo (mejor algo que nada)
    return text


def call_openrouter(messages: list) -> str:
    url = "https://openrouter.ai/api/v1/chat/completions"
    formatted = [{"role": "system", "content": SYSTEM_PROMPT}] + messages

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": formatted,
        "temperature": 0.7,
        "max_tokens": 1024,
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
                return f"Error: {e}"

    return "No pude obtener respuesta. Intenta de nuevo."


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json
    message = data.get("message", "")
    session_id = data.get("session_id", "default")

    if session_id not in conversations:
        conversations[session_id] = []

    conversations[session_id].append({"role": "user", "content": message})

    # Limitar historial
    if len(conversations[session_id]) > 20:
        conversations[session_id] = conversations[session_id][-20:]

    response = call_openrouter(conversations[session_id])
    
    # Filtrar razonamiento interno del modelo
    response = filter_reasoning(response)
    
    conversations[session_id].append({"role": "assistant", "content": response})

    return jsonify({"response": response})


# ═══════════════════════════════════════════
# CLIMA
# ═══════════════════════════════════════════

@app.route("/api/weather", methods=["GET"])
def weather():
    city = request.args.get("city", "Barrancabermeja")
    try:
        city_encoded = urllib.parse.quote(city)
        url = f"https://wttr.in/{city_encoded}?format=j1"
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
            "description": current.get("weatherDesc", [{"value": ""}])[0]["value"],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ═══════════════════════════════════════════
# NOTAS
# ═══════════════════════════════════════════

def _load_notes():
    if not NOTES_FILE.exists():
        return []
    try:
        return json.loads(NOTES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_notes(notes):
    NOTES_FILE.write_text(json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8")


@app.route("/api/notes", methods=["GET"])
def get_notes():
    return jsonify({"notes": _load_notes()})


@app.route("/api/notes", methods=["POST"])
def add_note():
    data = request.json
    notes = _load_notes()
    notes.append({
        "content": data.get("content", ""),
        "created_at": datetime.now().isoformat(),
    })
    _save_notes(notes)
    return jsonify({"ok": True, "count": len(notes)})


@app.route("/api/notes/<int:index>", methods=["DELETE"])
def delete_note(index):
    notes = _load_notes()
    if 0 <= index < len(notes):
        notes.pop(index)
        _save_notes(notes)
        return jsonify({"ok": True})
    return jsonify({"error": "Nota no encontrada"}), 404


# ═══════════════════════════════════════════
# MEMORIA
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


@app.route("/api/memory", methods=["GET"])
def get_memory():
    return jsonify(_load_memory())


@app.route("/api/memory", methods=["POST"])
def save_memory():
    data = request.json
    mem = _load_memory()
    mem[data.get("key", "")] = data.get("value", "")
    _save_memory(mem)
    return jsonify({"ok": True})


# ═══════════════════════════════════════════
# SPOTIFY
# ═══════════════════════════════════════════

@app.route("/api/spotify/search", methods=["GET"])
def spotify_search():
    query = request.args.get("q", "")
    # Usar Spotify search URI que abre la app del celular
    return jsonify({
        "uri": f"spotify:search:{query}",
        "web_url": f"https://open.spotify.com/search/{urllib.parse.quote(query)}"
    })


# ═══════════════════════════════════════════
# TTS (ElevenLabs)
# ═══════════════════════════════════════════

@app.route("/api/tts", methods=["POST"])
def text_to_speech():
    data = request.json
    text = data.get("text", "")

    if not ELEVENLABS_API_KEY or not text:
        return jsonify({"error": "No API key or empty text"}), 400

    voice_id = "ErXwobaYiN019PkySvjV"  # Antoni
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"

    payload = json.dumps({
        "text": text[:250],
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
            audio = resp.read()
        from flask import Response
        return Response(audio, mimetype="audio/mpeg")
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ═══════════════════════════════════════════
# INFO
# ═══════════════════════════════════════════

@app.route("/api/status", methods=["GET"])
def status():
    return jsonify({
        "name": ASSISTANT_NAME,
        "status": "online",
        "mode": "mobile",
        "time": datetime.now().isoformat(),
    })


@app.route("/", methods=["GET"])
def index():
    return app.send_static_file("index.html")


# Servir archivos estáticos del frontend
app.static_folder = os.path.join(os.path.dirname(__file__), "..", "frontend")
app.static_url_path = ""


if __name__ == "__main__":
    # Redirigir static folder
    import shutil
    frontend_dir = Path(__file__).parent.parent / "frontend"
    if frontend_dir.exists():
        app.static_folder = str(frontend_dir)

    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
