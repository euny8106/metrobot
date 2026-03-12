import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import re

from utils.state import MetronomeState, MAX_CLERICS, is_officer
from utils.audio import pregenerate_audio, MetronomeAudioSource, _pcm_cache
from utils.ui import StatusView, ControlView

# per-guild metronome state
guild_states: dict[int, MetronomeState] = {}
# per-guild metronome tasks
guild_tasks: dict[int, asyncio.Task] = {}
# per-guild bot messages to delete on /stop  (list of discord.Message)
guild_messages: dict[int, list[discord.Message]] = {}


class MetronomeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.CheckFailure):
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Officer role required.", ephemeral=True)

    # ──────────────────────────────────────────────
    # /met command
    # ──────────────────────────────────────────────
    @app_commands.command(name="met", description="Start or configure the metronome")
    @app_commands.describe(args="e.g. 3  /  3 - 4 6  /  -19 -c  /  +9 -c  /  -c")
    @app_commands.check(is_officer)
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

        # ── Case 4: /met N [- X Y ...] → new metronome ──
        new_match = re.match(r'^(\d+(?:\.\d+)?)(?:\s+-\s*([\d\s]+))?$', args)
        if new_match or args == "":
            if args == "":
                # show modal
                await interaction.response.send_modal(MetronomeModal())
                return

            interval = float(new_match.group(1))
            excluded_str = new_match.group(2) or ""
            excluded = set(int(x) for x in excluded_str.split() if x.isdigit())

            if interval < 0.5:
                await interaction.response.send_message("❌ Interval must be at least 0.5s.", ephemeral=True)
                return

            state = MetronomeState(interval=interval, excluded=excluded)
            guild_states[guild_id] = state

            await pregenerate_audio(MAX_CLERICS)
            await self._start_metronome(interaction, state)
            return

        await interaction.response.send_message("❌ Invalid format.\nExamples: `/met 3` or `/met 3 - 4 6`", ephemeral=True)

    # ──────────────────────────────────────────────
    # /stop command
    # ──────────────────────────────────────────────
    @app_commands.command(name="stop", description="Stop the metronome")
    @app_commands.check(is_officer)
    async def stop(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id
        await self._cancel_task(guild_id)
        guild_states.pop(guild_id, None)

        # disconnect from voice channel
        if interaction.guild.voice_client:
            await interaction.guild.voice_client.disconnect()

        # delete all bot messages spawned by this metronome session
        msgs = guild_messages.pop(guild_id, [])
        for msg in msgs:
            try:
                await msg.delete()
            except discord.NotFound:
                pass

        await interaction.response.send_message("⏹️ Metronome stopped.", ephemeral=True, delete_after=5)

    # ──────────────────────────────────────────────
    # /status command
    # ──────────────────────────────────────────────
    @app_commands.command(name="status", description="Check and manage metronome status")
    @app_commands.check(is_officer)
    async def status(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id
        state = guild_states.get(guild_id)

        if not state:
            await interaction.response.send_message("❌ No metronome is currently running.", ephemeral=True)
            return

        async def apply_callback(excluded: set):
            state.excluded = excluded

        view = StatusView(state, apply_callback)
        embed = view.make_embed()
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    # ──────────────────────────────────────────────
    # internal metronome loop
    # ──────────────────────────────────────────────
    async def _start_metronome(self, interaction: discord.Interaction, state: MetronomeState, already_deferred=False, is_restart=False):
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
        state.is_paused = False
        state.current_num = 1

        if not already_deferred:
            async def apply_callback(excluded: set):
                state.excluded = excluded
            view = StatusView(state, apply_callback)
            embed = view.make_embed()
            prefix = "🔄 Metronome restarted!" if is_restart else "▶️ Metronome started!"
            status_msg = await interaction.response.send_message(
                f"{prefix} `{state.interval}s` interval",
                embed=embed,
                view=view
            )
            # fetch the sent message so we can delete it later
            status_msg = await interaction.original_response()

            # build transport controls
            control_view = ControlView(
                state,
                on_play=self._ctrl_play,
                on_pause=self._ctrl_pause,
                on_stop=self._ctrl_stop,
                on_restart=lambda i: self._restart_metronome(i, state, already_deferred=True)
            )
            ctrl_msg = await interaction.followup.send(view=control_view, wait=True)

            # track both messages for deletion on /stop
            guild_messages[guild_id] = [status_msg, ctrl_msg]

        # single continuous source — stays speaking the whole session
        audio_source = MetronomeAudioSource()
        print(f"DEBUG: connecting vc={vc}, is_connected={vc.is_connected()}, is_playing={vc.is_playing()}")
        vc.play(audio_source)
        print(f"DEBUG: vc.play called, is_playing={vc.is_playing()}")
        task = asyncio.create_task(self._metronome_loop(guild_id, vc, state, audio_source))
        guild_tasks[guild_id] = task

    # ── transport control callbacks ─────────────────
    async def _ctrl_play(self, interaction: discord.Interaction):
        """Resume a paused metronome (noop if already playing)"""
        state = guild_states.get(interaction.guild_id)
        if state:
            state.is_paused = False

    async def _ctrl_pause(self, interaction: discord.Interaction):
        """Pause the metronome loop"""
        state = guild_states.get(interaction.guild_id)
        if state:
            state.is_paused = True

    async def _ctrl_stop(self, interaction: discord.Interaction):
        """Stop and clean up — mirrors /stop but called from a button"""
        guild_id = interaction.guild_id
        await self._cancel_task(guild_id)
        guild_states.pop(guild_id, None)
        if interaction.guild.voice_client:
            await interaction.guild.voice_client.disconnect()
        msgs = guild_messages.pop(guild_id, [])
        for msg in msgs:
            try:
                await msg.delete()
            except discord.NotFound:
                pass

    async def _restart_metronome(self, interaction: discord.Interaction, state: MetronomeState, already_deferred=False):
        guild_id = interaction.guild_id
        await self._cancel_task(guild_id)
        state.is_running = False
        await self._start_metronome(interaction, state, already_deferred, is_restart=True)

    async def _metronome_loop(self, guild_id: int, vc: discord.VoiceClient, state: MetronomeState, source: MetronomeAudioSource):
        """Core loop: play active numbers at the set interval"""
        import time
        print(f"DEBUG: metronome loop started for guild {guild_id}")
        try:
            t_origin = time.monotonic()
            slot = 0
            pause_elapsed = 0.0  # total time spent paused (to keep drift-free timing)
            last_interval = state.interval  # track for rebase on change

            while state.is_running:
                for num in range(1, state.max_num + 1):
                    if not state.is_running:
                        return

                    state.current_num = num

                    # real-time exclude check — skip without consuming a slot
                    if num in state.excluded:
                        continue

                    # absolute target time for this slot
                    t_target = t_origin + slot * state.interval + pause_elapsed
                    slot += 1

                    # wait until target time, handling pause and interval changes
                    while True:
                        # Interval changed via dropdown — rebase timing so next beat is
                        # new_interval seconds from now, with no burst or long stall
                        if state.interval != last_interval:
                            last_interval = state.interval
                            now = time.monotonic()
                            t_origin = now
                            t_target = now   # play current beat immediately
                            slot = 1         # next beat: t_origin + 1 * new_interval
                            pause_elapsed = 0.0

                        if state.is_paused:
                            pause_start = time.monotonic()
                            while state.is_paused and state.is_running:
                                await asyncio.sleep(0.1)
                            pause_elapsed += time.monotonic() - pause_start
                            t_target = t_origin + (slot - 1) * state.interval + pause_elapsed
                            if not state.is_running:
                                return
                        remaining = t_target - time.monotonic()
                        if remaining <= 0.01:
                            break
                        await asyncio.sleep(min(remaining, 0.05))

                    if not state.is_running:
                        return

                    print(f"DEBUG: arming num {num}")
                    source.arm(_pcm_cache[num])

        except asyncio.CancelledError:
            if vc.is_playing():
                vc.stop()
        except Exception as e:
            print(f"❌ Metronome loop error: {e}")
        finally:
            # _cancel_task pops guild_tasks before cancelling, so if it's still
            # present here the loop ended from an unhandled crash — clean up.
            if guild_tasks.pop(guild_id, None) is not None:
                guild_states.pop(guild_id, None)

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
    exclude = discord.ui.TextInput(
        label="Exclude (optional, e.g. 4 6)",
        placeholder="space-separated",
        required=False,
        max_length=50
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not is_officer(interaction):
            await interaction.response.send_message("❌ Officer role required.", ephemeral=True)
            return
        try:
            interval_val = float(self.interval.value)
            excluded_val = set(int(x) for x in self.exclude.value.split() if x.isdigit())
        except ValueError:
            await interaction.response.send_message("❌ Invalid number format.", ephemeral=True)
            return

        if interval_val < 0.5:
            await interaction.response.send_message("❌ Interval must be at least 0.5s.", ephemeral=True)
            return

        cog = interaction.client.cogs.get("MetronomeCog")
        if not cog:
            return

        state = MetronomeState(interval=interval_val, excluded=excluded_val)
        guild_states[interaction.guild_id] = state
        await pregenerate_audio(MAX_CLERICS)
        await cog._start_metronome(interaction, state)


async def setup(bot):
    await bot.add_cog(MetronomeCog(bot))
