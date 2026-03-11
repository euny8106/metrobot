import os
import asyncio
from pathlib import Path

AUDIO_DIR = Path(__file__).parent.parent / "audio"

async def generate_number_audio(num: int) -> Path:
    """Generate TTS mp3 for a number (generates if not cached)"""
    AUDIO_DIR.mkdir(exist_ok=True)
    path = AUDIO_DIR / f"{num}.mp3"

    if not path.exists():
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _generate_tts, num, path)

    return path

def _generate_tts(num: int, path: Path):
    from gtts import gTTS
    tts = gTTS(text=str(num), lang="en", slow=False)
    tts.save(str(path))

async def pregenerate_audio(max_num: int):
    """Pre-generate audio on bot start or range expansion"""
    tasks = []
    for n in range(1, max_num + 1):
        path = AUDIO_DIR / f"{n}.mp3"
        if not path.exists():
            tasks.append(generate_number_audio(n))
    if tasks:
        await asyncio.gather(*tasks)
        print(f"✅ Generated {len(tasks)} audio files")
    print(f"✅ Audio ready for 1~{max_num}")
