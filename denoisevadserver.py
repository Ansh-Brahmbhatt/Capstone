from flask import Flask
import socketio

from appConfig import AppConfig
from denoiseVADHandler import DenoiseVADHandler

config = AppConfig.get_instance()

# Flask + python-socketio (threading mode keeps things simple)
app = Flask(__name__)
sio = socketio.Server(
    async_mode='threading',
    cors_allowed_origins="*",
    ping_interval=25,
    ping_timeout=60
)

app.wsgi_app = socketio.WSGIApp(sio, app.wsgi_app)

# --- Socket.IO events ---

@sio.event
def connect(sid, environ):
    print(f"🔌 Client connected: {sid}")
    DenoiseVADHandler.add_instance(
        sid, sio,
        vad_aggr=config.VAD_AGGRESSIVENESS,
        converter=config.RESAMPLE_CONVERTER
    )

@sio.event
def disconnect(sid):
    print(f"❌ Client disconnected: {sid}")
    DenoiseVADHandler.remove_instance(sid)

@sio.on("streamMedia")
def stream_media(sid, data):
    handler = DenoiseVADHandler.get_instance(sid)
    if handler is None:
        # if this happens, create one on the fly (shouldn't normally)
        handler = DenoiseVADHandler.add_instance(
            sid, sio,
            vad_aggr=config.VAD_AGGRESSIVENESS,
            converter=config.RESAMPLE_CONVERTER
        )
    handler.handle_stream_media(data)  # this will emit back to the same sid

if __name__ == "__main__":
    print(f"🚀 Server listening on {config.HOST}:{config.PORT}")
    app.run(host=config.HOST, port=config.PORT)