from TTS.api import TTS
import torch
import os

TEXT = """
Halo semuanya.
Ini adalah suara AI Indonesia menggunakan XTTS v2.
Hasilnya jauh lebih natural dan stabil.
"""

if not os.path.exists("jokowi.mp3"):
    raise FileNotFoundError("speaker.wav tidak ditemukan")

device = "cpu"

tts = TTS(
    model_name="tts_models/multilingual/multi-dataset/xtts_v2"
).to(device)

tts.tts_to_file(
    text=TEXT,
    speaker_wav="jokowi.mp3",
    language="id",
    file_path="output.wav"
)

print("Selesai")
