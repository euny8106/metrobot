import asyncio
import subprocess
import threading
from pathlib import Path
import discord

AUDIO_DIR = Path(__file__).parent.parent / "audio"
_generating: set[int] = set()
_pcm_cache: dict[int, bytes] = {}  # num → raw PCM bytes, loaded once at startup

# Discord expects 48kHz stereo s16le; each read() call = 20ms = 3840 bytes
_FRAME_SIZE = 3840


class MetronomeAudioSource(discord.AudioSource):
    """
    Continuous audio source. Emits silence between beats.
    Call arm(pcm) from the timing loop — the audio thread picks it up instantly
    with no subprocess startup, no speaking-state round-trip.
    """

    def __init__(self):
        self._silence = bytes(_FRAME_SIZE)
        self._pcm: bytes | None = None
        self._pos: int = 0
        self._lock = threading.Lock()

    def arm(self, pcm: bytes):
        """Called by the timing loop when a beat fires."""
        with self._lock:
            self._pcm = pcm
            self._pos = 0

    def read(self) -> bytes:
        with self._lock:
            if self._pcm is not None:
                chunk = self._pcm[self._pos:self._pos + _FRAME_SIZE]
                if len(chunk) == _FRAME_SIZE:
                    self._pos += _FRAME_SIZE
                    return chunk
                self._pcm = None  # exhausted
        return self._silence

    def is_opus(self) -> bool:
        return False


def _generate_tts(num: int, path: Path):
    from gtts import gTTS
    tts = gTTS(text=str(num), lang="en", slow=False)
    tts.save(str(path))


def _decode_to_pcm(path: Path) -> bytes:
    """Decode an mp3 to raw 48kHz stereo s16le PCM bytes using ffmpeg."""
    result = subprocess.run(
        ['ffmpeg', '-i', str(path), '-f', 's16le', '-ar', '48000', '-ac', '2', 'pipe:1'],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    return result.stdout


async def _ensure_mp3(num: int) -> Path:
    """Generate TTS mp3 for a number if not already on disk."""
    AUDIO_DIR.mkdir(exist_ok=True)
    path = AUDIO_DIR / f"{num}.mp3"
    if not path.exists() and num not in _generating:
        _generating.add(num)
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _generate_tts, num, path)
        finally:
            _generating.discard(num)
    return path


async def pregenerate_audio(max_num: int):
    """Generate any missing mp3s, then decode all into the PCM cache."""
    # Step 1: generate missing mp3s (concurrently)
    tasks = [_ensure_mp3(n) for n in range(1, max_num + 1)
             if not (AUDIO_DIR / f"{n}.mp3").exists()]
    if tasks:
        await asyncio.gather(*tasks)
        print(f"✅ Generated {len(tasks)} TTS mp3 files (1~{max_num})")

    # Step 2: decode any not yet in cache
    loop = asyncio.get_running_loop()
    decode_tasks = []
    for n in range(1, max_num + 1):
        if n not in _pcm_cache:
            decode_tasks.append(
                loop.run_in_executor(None, _decode_to_pcm, AUDIO_DIR / f"{n}.mp3")
            )
    if decode_tasks:
        results = await asyncio.gather(*[asyncio.ensure_future(t) for t in decode_tasks])
        nums = [n for n in range(1, max_num + 1) if n not in _pcm_cache]
        for n, pcm in zip(nums, results):
            _pcm_cache[n] = pcm
        print(f"✅ Loaded {len(decode_tasks)} audio files into memory (1~{max_num})")
