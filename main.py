from kokoro import KPipeline
import soundfile as sf

pipeline = KPipeline(lang_code='a')  # English

text = """
Hello, this is Kokoro TTS running on GitHub Actions.
"""

generator = pipeline(text, voice='af_heart')

for i, (gs, ps, audio) in enumerate(generator):
    sf.write(f'output_{i}.wav', audio, 24000)
