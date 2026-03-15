# denoiseVADHandler.py

import base64
import numpy as np
import samplerate
import webrtcvad
from pyrnnoise.rnnoise import create, process_mono_frame, FRAME_SIZE

class DenoiseVADHandler:
    """
    One handler per connected Socket.IO client (keyed by its sid).
    Now entirely local: no WebPubSub imports or calls.
    """
    _instances: dict[str, "DenoiseVADHandler"] = {}

    def __init__(self, socket_id: str, sio, *, vad_aggr: int = 2, converter: str = "sinc_fastest"):
        self.socket_id = socket_id
        self.sio = sio

        # --- Initialize RNNoise & VAD once per client ---
        self.rn_state   = create()
        self.vad        = webrtcvad.Vad(vad_aggr)     # aggressiveness (0..3)
        self.converter  = converter
        self.ratio_up   = 48000 / 16000               # 3.0
        self.ratio_down = 16000 / 48000               # 1/3

    @staticmethod
    def add_instance(socket_id: str, sio, *, vad_aggr: int = 2, converter: str = "sinc_fastest"):
        if socket_id not in DenoiseVADHandler._instances:
            DenoiseVADHandler._instances[socket_id] = DenoiseVADHandler(
                socket_id, sio, vad_aggr=vad_aggr, converter=converter
            )
            print(f"Instance added for socket_id: {socket_id}")
        return DenoiseVADHandler._instances[socket_id]

    @staticmethod
    def remove_instance(socket_id: str):
        if socket_id in DenoiseVADHandler._instances:
            del DenoiseVADHandler._instances[socket_id]
            print(f"Instance removed for socket_id: {socket_id}")

    @staticmethod
    def get_instance(socket_id: str):
        return DenoiseVADHandler._instances.get(socket_id)

    def handle_stream_media(self, data: dict):
        """
        Expects:
        data = {
          "seq": <int>,
          "data": "<base64-encoded 30ms PCM16 frame @ 16kHz>"
        }
        Emits back to the same `sid` on event 'streamMedia' with:
        { "seq": int, "data": base64, "is_speech": bool }
        """
        seq        = data["seq"]
        b64_frame  = data["data"]
        raw_bytes  = base64.b64decode(b64_frame)

        # 1) To numpy int16 @16k
        frame16 = np.frombuffer(raw_bytes, dtype=np.int16)

        # 2) Upsample → 48 kHz
        frame48 = samplerate.resample(frame16, self.ratio_up, self.converter)
        frame48 = np.clip(frame48, -32768, 32767).astype(np.int16)

        # 3) RNNoise denoise in 10 ms (FRAME_SIZE) chunks
        denoised_chunks = []
        for i in range(0, len(frame48), FRAME_SIZE):
            chunk = frame48[i : i + FRAME_SIZE]
            if len(chunk) < FRAME_SIZE:
                # zero pad last chunk
                chunk = np.pad(chunk, (0, FRAME_SIZE - len(chunk)), mode="constant")
            clean_chunk, _ = process_mono_frame(self.rn_state, chunk)
            denoised_chunks.append(clean_chunk)
        denoised48 = np.concatenate(denoised_chunks) if denoised_chunks else np.zeros(0, dtype=np.int16)

        # 4) Downsample → 16 kHz
        if denoised48.size:
            denoised16 = samplerate.resample(denoised48, self.ratio_down, self.converter)
            denoised16 = np.clip(denoised16, -32768, 32767).astype(np.int16)
        else:
            denoised16 = np.zeros_like(frame16)

        # 5) VAD check (30 ms @ 16k)
        buf       = memoryview(denoised16).cast("B")
        is_speech = self.vad.is_speech(buf, 16000)

        # 6) Zero out non-speech (maintains frame count)
        if not is_speech:
            denoised16 = np.zeros_like(denoised16)

        # 7) Re-encode to base64 and attach flag
        out_b64 = base64.b64encode(denoised16.tobytes()).decode("utf-8")
        payload = {
            "seq":       seq,
            "data":      out_b64,
            "is_speech": is_speech
        }

        # 8) Emit back directly to this sid
        self.sio.emit("streamMedia", payload, to=self.socket_id)