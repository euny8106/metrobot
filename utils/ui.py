import discord
from utils.state import MetronomeState, MAX_CLERICS, is_officer

# rows 0~3: 5 number buttons each = 20; row 4: up to 5 number buttons
MAX_BUTTON_NUMS = MAX_CLERICS  # matches the global maximum

class StatusView(discord.ui.View):
    """
    Interactive view for /status
    - Click number button → instantly toggle exclude/include on the live metronome
    """

    def __init__(self, state: MetronomeState, apply_callback):
        super().__init__(timeout=None)
        self.state = state
        self.preview_excluded = set(state.excluded)
        self.preview_max = state.max_num
        self.apply_callback = apply_callback  # async (excluded: set) -> None
        self._build_buttons(state.max_num)

    def _build_buttons(self, max_num: int):
        self.clear_items()
        if max_num <= MAX_BUTTON_NUMS:
            for n in range(1, max_num + 1):
                excluded = n in self.preview_excluded
                btn = NumberButton(n, excluded)
                self.add_item(btn)

    def toggle_number(self, num: int):
        if num in self.preview_excluded:
            self.preview_excluded.discard(num)
        else:
            self.preview_excluded.add(num)

    def rebuild(self):
        self._build_buttons(self.preview_max)

    def make_embed(self) -> discord.Embed:
        active = [n for n in range(1, self.preview_max + 1) if n not in self.preview_excluded]
        excluded_sorted = sorted(self.preview_excluded)

        excluded_str = ", ".join(str(n) for n in excluded_sorted) if excluded_sorted else "none"
        active_str = ", ".join(str(n) for n in active) if active else "none"

        embed = discord.Embed(title="📊 Metronome Status", color=0x5865F2)
        embed.add_field(name="⏱️ Interval", value=f"{self.state.interval}s", inline=True)
        embed.add_field(name="📋 Range", value=f"1 ~ {self.preview_max}", inline=True)
        embed.add_field(name="❌ Excluded", value=excluded_str, inline=True)
        embed.add_field(name="✅ Active", value=active_str, inline=False)

        if self.preview_max > MAX_BUTTON_NUMS:
            embed.set_footer(text=f"More than {MAX_BUTTON_NUMS} numbers — button UI unavailable. Use commands instead.")
        else:
            embed.set_footer(text="Click a number to instantly exclude/include it")

        return embed


class NumberButton(discord.ui.Button):
    def __init__(self, num: int, excluded: bool):
        style = discord.ButtonStyle.secondary if excluded else discord.ButtonStyle.primary
        # 1~20: rows 0~3 (5 per row)
        # 21~23: row 4 (shares with Mode + Apply, max 5 per row)
        if num <= 20:
            row = (num - 1) // 5
        else:
            row = 4
        super().__init__(
            label=str(num),
            style=style,
            custom_id=f"num_{num}",
            row=row
        )
        self.num = num
        self.excluded = excluded

    async def callback(self, interaction: discord.Interaction):
        if not is_officer(interaction):
            await interaction.response.send_message("❌ Officer role required.", ephemeral=True)
            return
        view: StatusView = self.view
        view.toggle_number(self.num)
        await view.apply_callback(view.preview_excluded)
        view.rebuild()
        await interaction.response.edit_message(embed=view.make_embed(), view=view)


# ──────────────────────────────────────────────
# Control bar: Play / Pause / Stop / Restart
# ──────────────────────────────────────────────
class ControlView(discord.ui.View):
    """
    Persistent transport controls posted below the status message.
    Callbacks are async callables supplied by MetronomeCog.
    """

    def __init__(self, state: MetronomeState, *,
                 on_play, on_pause, on_stop, on_restart):
        super().__init__(timeout=None)  # never time out
        self.state = state
        self._on_play = on_play
        self._on_pause = on_pause
        self._on_stop = on_stop
        self._on_restart = on_restart
        self._refresh_buttons()

    def _refresh_buttons(self):
        self.clear_items()
        # Play  (disabled while already running and not paused)
        play_btn = discord.ui.Button(
            label="▶ Play",
            style=discord.ButtonStyle.success,
            disabled=self.state.is_running and not self.state.is_paused,
            row=0
        )
        play_btn.callback = self._play
        self.add_item(play_btn)

        # Pause (disabled when not running or already paused)
        pause_btn = discord.ui.Button(
            label="⏸ Pause",
            style=discord.ButtonStyle.primary,
            disabled=not self.state.is_running or self.state.is_paused,
            row=0
        )
        pause_btn.callback = self._pause
        self.add_item(pause_btn)

        # Stop
        stop_btn = discord.ui.Button(
            label="⏹ Stop",
            style=discord.ButtonStyle.danger,
            row=0
        )
        stop_btn.callback = self._stop
        self.add_item(stop_btn)

        # Restart from 1
        restart_btn = discord.ui.Button(
            label="⏮ Restart",
            style=discord.ButtonStyle.secondary,
            row=0
        )
        restart_btn.callback = self._restart
        self.add_item(restart_btn)

        # Interval selector
        self.add_item(IntervalSelect(self.state.interval))

    async def _play(self, interaction: discord.Interaction):
        if not is_officer(interaction):
            await interaction.response.send_message("❌ Officer role required.", ephemeral=True)
            return
        await self._on_play(interaction)
        self._refresh_buttons()
        await interaction.response.edit_message(view=self)

    async def _pause(self, interaction: discord.Interaction):
        if not is_officer(interaction):
            await interaction.response.send_message("❌ Officer role required.", ephemeral=True)
            return
        await self._on_pause(interaction)
        self._refresh_buttons()
        await interaction.response.edit_message(view=self)

    async def _stop(self, interaction: discord.Interaction):
        if not is_officer(interaction):
            await interaction.response.send_message("❌ Officer role required.", ephemeral=True)
            return
        # Stop deletes messages itself — disable all buttons first
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)
        await self._on_stop(interaction)

    async def _restart(self, interaction: discord.Interaction):
        if not is_officer(interaction):
            await interaction.response.send_message("❌ Officer role required.", ephemeral=True)
            return
        await self._on_restart(interaction)
        self._refresh_buttons()
        await interaction.response.edit_message(view=self)


INTERVAL_VALUES = [1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5, 6, 7, 8, 9, 10, 11, 12]


class IntervalSelect(discord.ui.Select):
    def __init__(self, current_interval: float):
        options = [
            discord.SelectOption(
                label=f"{v}s",
                value=str(v),
                default=(v == current_interval)
            )
            for v in INTERVAL_VALUES
        ]
        super().__init__(
            placeholder="⏱️ Change interval…",
            options=options,
            row=1
        )

    async def callback(self, interaction: discord.Interaction):
        if not is_officer(interaction):
            await interaction.response.send_message("❌ Officer role required.", ephemeral=True)
            return
        view: ControlView = self.view
        new_interval = float(self.values[0])
        view.state.interval = new_interval
        # rebuild so the new default is reflected
        view._refresh_buttons()
        await interaction.response.edit_message(view=view)
