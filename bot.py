import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
from utils.audio import pregenerate_audio
from utils.state import MAX_CLERICS

load_dotenv()

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
