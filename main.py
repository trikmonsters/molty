import os
import subprocess

TEXT = """
Halo semuanya.
Ini adalah contoh suara AI Indonesia yang sangat natural
menggunakan F5 TTS dan voice cloning.
"""

REFERENCE_TEXT = """
Halo semuanya saya sedang mencoba teknologi suara AI terbaru.
"""

# simpan text
with open("gen.txt", "w", encoding="utf-8") as f:
    f.write(TEXT)

# generate
cmd = [
    "f5-tts_infer-cli",
    "--model", "F5TTS_v1_Base",
    "--ref_audio", "speaker.wav",
    "--ref_text", REFERENCE_TEXT,
    "--gen_text", TEXT,
    "--output_dir", "output"
]

subprocess.run(cmd, check=True)

print("Selesai generate suara")
