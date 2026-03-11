import discord
from utils.state import MetronomeState

TOTAL_BUTTONS = 25  # always show 25 buttons

class StatusView(discord.ui.View):
    """
    Interactive view for /met and /status
    - 25 buttons always shown (rows 0~4, 5 per row)
    - Green = active, Grey = excluded/out of range
    - Click to toggle immediately — no Apply needed
    """

    def __init__(self, state: MetronomeState, apply_callback):
        super().__init__(timeout=300)
        self.state = state
        self.apply_callback = apply_callback
        self._build_buttons()

    def _build_buttons(self):
        self.clear_items()
        for n in range(1, TOTAL_BUTTONS + 1):
            out_of_range = n > self.state.max_num
            excluded = n in self.state.excluded
            btn = NumberButton(n, excluded, out_of_range)
            self.add_item(btn)

    def rebuild(self):
        self._build_buttons()

    def make_embed(self) -> discord.Embed:
        active = self.state.get_active_numbers()
        excluded_sorted = sorted(self.state.excluded)

        excluded_str = ", ".join(str(n) for n in excluded_sorted) if excluded_sorted else "none"
        active_str = ", ".join(str(n) for n in active) if active else "none"

        embed = discord.Embed(title="📊 Metronome Status", color=0x5865F2)
        embed.add_field(name="⏱️ Interval", value=f"{self.state.interval}s", inline=True)
        embed.add_field(name="📋 Range", value=f"1 ~ {self.state.max_num}", inline=True)
        embed.add_field(name="❌ Excluded", value=excluded_str, inline=True)
        embed.add_field(name="✅ Active", value=active_str, inline=False)
        embed.set_footer(text="Click to toggle numbers on/off instantly")

        return embed


class NumberButton(discord.ui.Button):
    def __init__(self, num: int, excluded: bool, out_of_range: bool):
        if out_of_range:
            # out of range: grey, disabled-looking
            style = discord.ButtonStyle.secondary
        elif excluded:
            # excluded: red
            style = discord.ButtonStyle.danger
        else:
            # active: green
            style = discord.ButtonStyle.success

        super().__init__(
            label=str(num),
            style=style,
            custom_id=f"num_{num}",
            row=(num - 1) // 5  # 1~5=row0, 6~10=row1, ..., 21~25=row4
        )
        self.num = num
        self.out_of_range = out_of_range
        self.excluded = excluded

    async def callback(self, interaction: discord.Interaction):
        view: StatusView = self.view
        state = view.state

        if self.out_of_range:
            # clicking an out-of-range button adds it to the range
            state.include(self.num)
        elif self.num in state.excluded:
            state.include(self.num)
        else:
            state.exclude(self.num)

        # apply immediately
        await view.apply_callback(interaction=interaction)

        view.rebuild()
        await interaction.response.edit_message(embed=view.make_embed(), view=view)
