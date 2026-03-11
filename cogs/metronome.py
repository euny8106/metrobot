import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import re
from typing import Optional

from utils.state import MetronomeState
from utils.audio import generate_number_audio, pregenerate_audio
from utils.ui import StatusView

# per-guild metronome state
guild_states: dict[int, MetronomeState] = {}
# per-guild metronome tasks
guild_tasks: dict[int, asyncio.Task] = {}


class MetronomeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ──────────────────────────────────────────────
    # /met command
    # ──────────────────────────────────────────────
    @app_commands.command(name="met", description="Start or configure the metronome")
    @app_commands.describe(args="e.g. 3 10  /  3 10 - 4 6  /  -19 -c  /  +9 -c  /  -c")
    async def met(self, interaction: discord.Interaction, args: str = ""):
        guild_id = interaction.guild_id
        args = args.strip()

        # ── Case 1: /met -c alone → reset excluded list ──
        if args == "-c":
            state = guild_states.get(guild_id)
            if not state:
                await interaction.response.send_message("❌ No metronome is currently running.", ephemeral=True)
                return
            state.reset_excluded()
            await interaction.response.send_message("✅ All numbers restored from the next call.", ephemeral=True)
            return

        # ── Case 2: /met -N -c or /met +N -c ──
        delta_match = re.fullmatch(r'([+\-])(\d+)\s+-c', args)
        if delta_match:
            sign, num_str = delta_match.group(1), delta_match.group(2)
            num = int(num_str)
            state = guild_states.get(guild_id)
            if not state:
                await interaction.response.send_message("❌ No metronome is currently running.", ephemeral=True)
                return
            if sign == "-":
                state.exclude(num)
                await interaction.response.send_message(f"✅ #{num} excluded from the next call.", ephemeral=True)
            else:
                state.include(num)
                if num > state.max_num:
                    await pregenerate_audio(num)
                await interaction.response.send_message(f"✅ #{num} added from the next call.", ephemeral=True)
            return

        # ── Case 3: /met -N or /met +N (immediate restart) ──
        delta_only = re.fullmatch(r'([+\-])(\d+)', args)
        if delta_only:
            sign, num_str = delta_only.group(1), delta_only.group(2)
            num = int(num_str)
            state = guild_states.get(guild_id)
            if not state:
                await interaction.response.send_message("❌ No metronome is currently running.", ephemeral=True)
                return
            if sign == "-":
                state.exclude(num)
            else:
                state.include(num)
                if num > state.max_num:
                    await pregenerate_audio(num)
            await self._restart_metronome(interaction, state)
            return

        # ── Case 4: /met N M [- X Y ...] → new metronome ──
        new_match = re.match(r'^(\d+(?:\.\d+)?)\s+(\d+)(?:\s+-\s*([\d\s]+))?$', args)
        if new_match or args == "":
            if args == "":
                # show modal
                await interaction.response.send_modal(MetronomeModal())
                return

            interval = float(new_match.group(1))
            max_num = int(new_match.group(2))
            excluded_str = new_match.group(3) or ""
            excluded = set(int(x) for x in excluded_str.split() if x.isdigit())

            if interval <= 0 or max_num <= 0:
                await interaction.response.send_message("❌ Interval and number must be greater than 0.", ephemeral=True)
                return

            state = MetronomeState(interval=interval, max_num=max_num, excluded=excluded)
            guild_states[guild_id] = state

            await pregenerate_audio(max_num)
            await self._start_metronome(interaction, state)
            return

        await interaction.response.send_message("❌ Invalid format.\nExamples: `/met 3 10` or `/met -5 -c`", ephemeral=True)

    # ──────────────────────────────────────────────
    # /stop command
    # ──────────────────────────────────────────────
    @app_commands.command(name="stop", description="Stop the metronome")
    async def stop(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id
        await self._cancel_task(guild_id)
        guild_states.pop(guild_id, None)

        # disconnect from voice channel
        if interaction.guild.voice_client:
            await interaction.guild.voice_client.disconnect()

        await interaction.response.send_message("⏹️ Metronome stopped.")

    # ──────────────────────────────────────────────
    # /status command
    # ──────────────────────────────────────────────
    @app_commands.command(name="status", description="Check and manage metronome status")
    async def status(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id
        state = guild_states.get(guild_id)

        if not state:
            await interaction.response.send_message("❌ No metronome is currently running.", ephemeral=True)
            return

        async def apply_callback(interaction: discord.Interaction):
            # state is already updated by the button click — nothing extra needed
            pass

        view = StatusView(state, apply_callback)
        embed = view.make_embed()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    # ──────────────────────────────────────────────
    # internal metronome loop
    # ──────────────────────────────────────────────
    async def _start_metronome(self, interaction: discord.Interaction, state: MetronomeState, already_deferred=False):
        guild_id = interaction.guild_id

        # connect to voice channel
        voice_channel = interaction.user.voice.channel if interaction.user.voice else None
        if not voice_channel:
            if not already_deferred:
                await interaction.response.send_message("❌ Please join a voice channel first.", ephemeral=True)
            return

        vc = interaction.guild.voice_client
        if vc and vc.channel != voice_channel:
            await vc.move_to(voice_channel)
        elif not vc:
            vc = await voice_channel.connect()

        # cancel existing task
        await self._cancel_task(guild_id)

        state.is_running = True
        state.current_num = 1

        task = asyncio.create_task(self._metronome_loop(vc, state))
        guild_tasks[guild_id] = task

        if not already_deferred:
            async def apply_callback(interaction: discord.Interaction):
                pass

            view = StatusView(state, apply_callback)
            embed = view.make_embed()
            await interaction.response.send_message(
                f"▶️ Metronome started! `{state.interval}s` | Range `1~{state.max_num}`",
                embed=embed,
                view=view
            )

    async def _restart_metronome(self, interaction: discord.Interaction, state: MetronomeState, already_deferred=False):
        guild_id = interaction.guild_id
        await self._cancel_task(guild_id)
        state.is_running = False
        await self._start_metronome(interaction, state, already_deferred)

    async def _metronome_loop(self, vc: discord.VoiceClient, state: MetronomeState):
        """Core loop: play active numbers at the set interval"""
        import time
        try:
            t_origin = time.monotonic()
            slot = 0

            while state.is_running:
                for num in range(1, state.max_num + 1):
                    if not state.is_running:
                        return

                    state.current_num = num

                    # real-time exclude check — skip without consuming a slot
                    if num in state.excluded:
                        continue

                    # absolute target time for this slot
                    t_target = t_origin + slot * state.interval
                    slot += 1

                    # wait until target time
                    while True:
                        remaining = t_target - time.monotonic()
                        if remaining <= 0.01:
                            break
                        await asyncio.sleep(min(remaining, 0.05))

                    if not vc.is_connected():
                        return

                    audio_path = await generate_number_audio(num)
                    source = discord.FFmpegPCMAudio(str(audio_path))

                    if vc.is_playing():
                        vc.stop()
                    vc.play(source)

        except asyncio.CancelledError:
            if vc.is_playing():
                vc.stop()
        except Exception as e:
            print(f"❌ Metronome loop error: {e}")

    async def _cancel_task(self, guild_id: int):
        task = guild_tasks.pop(guild_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


# ──────────────────────────────────────────────
# Modal shown when /met is used with no arguments
# ──────────────────────────────────────────────
class MetronomeModal(discord.ui.Modal, title="🎵 Metronome Setup"):
    interval = discord.ui.TextInput(
        label="Interval (seconds)",
        placeholder="e.g. 3",
        required=True,
        max_length=5
    )
    clerics = discord.ui.TextInput(
        label="Number of Clerics",
        placeholder="e.g. 10",
        required=True,
        max_length=3
    )
    exclude = discord.ui.TextInput(
        label="Exclude (optional, e.g. 4 6)",
        placeholder="space-separated",
        required=False,
        max_length=50
    )
    mode = discord.ui.TextInput(
        label="Mode: continue / reset",
        placeholder="reset (default)",
        required=False,
        default="reset",
        max_length=10
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            interval_val = float(self.interval.value)
            max_num_val = int(self.clerics.value)
            excluded_val = set(int(x) for x in self.exclude.value.split() if x.isdigit())
            mode_val = self.mode.value.strip().lower()
        except ValueError:
            await interaction.response.send_message("❌ Invalid number format.", ephemeral=True)
            return

        cog = interaction.client.cogs.get("MetronomeCog")
        if not cog:
            return

        guild_id = interaction.guild_id
        existing = guild_id in cog.__class__.__dict__  # always False, handled below

        if mode_val == "continue" and guild_id in guild_states:
            state = guild_states[guild_id]
            state.excluded = excluded_val
            await interaction.response.send_message("✅ Applied in Continue mode.", ephemeral=True)
        else:
            state = MetronomeState(interval=interval_val, max_num=max_num_val, excluded=excluded_val)
            guild_states[guild_id] = state
            await pregenerate_audio(max_num_val)
            await cog._start_metronome(interaction, state)


async def setup(bot):
    await bot.add_cog(MetronomeCog(bot))
