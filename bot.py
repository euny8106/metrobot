import discord
from discord.ext import commands
import os
import glob
from dotenv import load_dotenv
from utils.audio import pregenerate_audio
from utils.state import MAX_CLERICS

load_dotenv()

# Load libopus — Debian path (Dockerfile), then fallbacks for other environments
if not discord.opus.is_loaded():
    for _name in ['libopus.so.0', '/usr/lib/x86_64-linux-gnu/libopus.so.0',
                   '/usr/lib/aarch64-linux-gnu/libopus.so.0', 'libopus.so', 'opus']:
        try:
            discord.opus.load_opus(_name)
            print(f"✅ Loaded libopus: {_name}")
            break
        except Exception:
            pass

if not discord.opus.is_loaded():
    for _path in sorted(glob.glob('/nix/store/*/lib/libopus.so*')):
        try:
            discord.opus.load_opus(_path)
            print(f"✅ Loaded libopus from nix: {_path}")
            break
        except Exception:
            pass

if not discord.opus.is_loaded():
    raise RuntimeError("❌ libopus not found — voice audio will not work. Install libopus on the server.")

intents = discord.Intents.default()
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ {bot.user} 온라인!")
    await bot.tree.sync()
    print("✅ Slash commands synced")
    await pregenerate_audio(MAX_CLERICS)
    print("✅ Audio cache ready")

async def main():
    async with bot:
        await bot.load_extension("cogs.metronome")
        await bot.start(os.getenv("DISCORD_TOKEN"))

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
