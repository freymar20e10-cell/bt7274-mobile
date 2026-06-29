# BT-7274 Mobile 📱

App móvil de BT-7274 para Android. Funciona sin la PC.

## Capacidades en modo móvil

- 💬 Chat con IA (OpenRouter, gratis)
- 🎤 Voz (reconocimiento nativo de Chrome Android)
- 🎵 Spotify (abre canciones en la app)
- 📝 Notas y memoria
- 🌤️ Clima
- 📰 Noticias

## Cómo desplegar

### 1. Backend (Render.com — gratis)

1. Crea cuenta en https://render.com
2. Conecta tu GitHub (o sube la carpeta `backend/`)
3. Crea un "Web Service"
4. Configura las variables de entorno (las de .env)
5. Deploy → te da una URL tipo `https://bt7274-mobile.onrender.com`

### 2. Frontend (tu celular)

1. Abre Chrome en tu Redmi
2. Ve a la URL del backend
3. Chrome te pregunta "Agregar a pantalla de inicio" → dale
4. Se instala como app

## Estructura

```
mobile/
├── backend/
│   ├── app.py           → Servidor Flask
│   ├── requirements.txt → Dependencias
│   ├── .env             → API keys
│   ├── Procfile         → Para Render
│   └── render.yaml      → Config de Render
└── frontend/
    ├── index.html       → App móvil (PWA)
    ├── manifest.json    → Config PWA
    └── sw.js            → Service Worker
```
