from melo.api import TTS

text = """
Halo semuanya...

Hari ini kita akan membahas teknologi AI terbaru.

Dan hasilnya keren banget.
"""

model = TTS(language='ID')

model.tts_to_file(
    text=text,
    speaker_id=0,
    output_path='output.wav',
    speed=1.0
)

print("Selesai generate")
