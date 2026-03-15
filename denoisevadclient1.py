import socketio
import os
import wave
import base64
import time
from dotenv import load_dotenv  # NEW

# Load variables from .env
load_dotenv()

class DenoiseVADClient:
    def __init__(self, server_url: str,
                 input_path: str = "input1.wav",
                 output_path: str = "output1.wav"):
        self.sio = socketio.Client()
        self.server_url = server_url
        self.input_path = input_path
        self.output_path = output_path

        self.frames_to_send = []
        self.total_frames = 0
        self.frames_received = 0
        self.wav_params = None
        self.wf_out = None

        self._register_events()

    def _register_events(self):
        @self.sio.event
        def connect():
            print(f"✅ Connected to {self.server_url}. Preparing frames…")
            wf_in = wave.open(self.input_path, 'rb')
            self.wav_params = wf_in.getparams()
            framerate = wf_in.getframerate()
            frame_size = int(framerate * 0.03)  # 30 ms

            data = wf_in.readframes(frame_size)
            while data:
                self.frames_to_send.append(data)
                data = wf_in.readframes(frame_size)
            wf_in.close()

            self.total_frames = len(self.frames_to_send)
            print(f"📤 Sending {self.total_frames} frames…")

            self.wf_out = wave.open(self.output_path, 'wb')
            self.wf_out.setparams(self.wav_params)

            for idx, frame in enumerate(self.frames_to_send):
                self.send_media(idx, frame)
                time.sleep(0.03)

        @self.sio.event
        def disconnect():
            print("❌ Disconnected from server.")

        @self.sio.on('streamMedia')
        def stream_media(data):
            seq = data['seq']
            base64_data = data['data']
            is_speech = data.get('is_speech', True)
            raw_bytes = base64.b64decode(base64_data)

            if is_speech:
                self.wf_out.writeframes(raw_bytes)
                print(f"💬 Wrote speech frame {seq}")
            else:
                print(f"🚫 Skipped non-speech frame {seq}")

            self.frames_received += 1
            if self.frames_received == self.total_frames:
                self.wf_out.close()
                print(f"💾 Completed writing speech-only audio to {self.output_path}")
                self.disconnect()

    def connect(self):
        try:
            self.sio.connect(self.server_url)
            self.sio.wait()
        except Exception as e:
            print(f"Connection error: {e}")

    def disconnect(self):
        self.sio.disconnect()

    def send_media(self, seq: int, media: bytes):
        encoded = base64.b64encode(media).decode('utf-8')
        payload = {"seq": seq, "data": encoded}
        self.sio.emit('streamMedia', payload)
        print(f"📤 Sent frame {seq}")


if __name__ == "__main__":
    SERVER_URL = os.getenv("SERVER_URL")
    if not SERVER_URL or not SERVER_URL.startswith("http"):
        raise RuntimeError(f"Invalid SERVER_URL in .env: {SERVER_URL!r}")
    client = DenoiseVADClient(SERVER_URL)
    client.connect()
