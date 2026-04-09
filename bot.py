"""
MTG Commander Life Counter Discord Bot
--------------------------------------
Tracks: Life Total, Commander Damage, Poison Counters, Commander Tax
Button-driven UI with slash command support.
Optional Archidekt deck reading.
"""

from dotenv import load_dotenv
import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import asyncio
from typing import Optional
import os

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
# ─── Config ────────────────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "YOUR_TOKEN_HERE")
STARTING_LIFE = 40

print(f"Token loaded: {BOT_TOKEN[:10]}...")

# ─── Game State ────────────────────────────────────────────────────────────────

class PlayerState:
    def __init__(self, member: discord.Member, deck_url: Optional[str] = None):
        self.member = member
        self.life = STARTING_LIFE
        self.poison = 0
        self.commander_tax = 0          # extra mana cost (increments +2 per recast)
        self.deck_url = deck_url
        self.deck_name: Optional[str] = None
        self.bracket: Optional[str] = None
        self.deck_cost: Optional[str] = None
        self.commander_name: Optional[str] = None
        # commander_damage[attacker_id] = damage received from that player's commander
        self.commander_damage: dict[int, int] = {}

    @property
    def is_eliminated(self) -> bool:
        if self.life <= 0:
            return True
        if self.poison >= 10:
            return True
        if any(dmg >= 21 for dmg in self.commander_damage.values()):
            return True
        return False

    def display_name(self) -> str:
        return self.member.display_name

    def life_bar(self) -> str:
        """Visual life bar out of 40."""
        pct = max(0, self.life / STARTING_LIFE)
        filled = round(pct * 10)
        bar = "█" * filled + "░" * (10 - filled)
        return bar

    def status_emoji(self) -> str:
        if self.is_eliminated:
            return "💀"
        if self.life <= 5:
            return "🩸"
        if self.life <= 15:
            return "⚠️"
        return "❤️"


class GameSession:
    def __init__(self, guild_id: int, channel_id: int, host: discord.Member):
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.host = host
        self.players: dict[int, PlayerState] = {}  # member_id -> PlayerState
        self.started = False
        self.board_message: Optional[discord.Message] = None  # the pinned board embed

    def add_player(self, member: discord.Member) -> bool:
        if len(self.players) >= 4:
            return False
        if member.id in self.players:
            return False
        self.players[member.id] = PlayerState(member)
        # Initialize commander damage tracking for all existing players
        for pid, p in self.players.items():
            for other_pid in self.players:
                if other_pid not in p.commander_damage:
                    p.commander_damage[other_pid] = 0
        return True

    def get_player(self, member_id: int) -> Optional[PlayerState]:
        return self.players.get(member_id)

    def active_players(self) -> list[PlayerState]:
        return [p for p in self.players.values() if not p.is_eliminated]

    def check_winner(self) -> Optional[PlayerState]:
        alive = self.active_players()
        if len(alive) == 1:
            return alive[0]
        if len(alive) == 0:
            return None
        return None


# Global sessions: guild_id -> GameSession
sessions: dict[int, GameSession] = {}


# Board Embed Builder 

def build_board_embed(session: GameSession) -> discord.Embed:
    embed = discord.Embed(
        title="⚔️ Commander Board",
        color=discord.Color.dark_purple()
    )

    for player in session.players.values():
        status = player.status_emoji()
        eliminated = " ~~ELIMINATED~~" if player.is_eliminated else ""

        # Life + bar
        life_line = f"{status} **{player.life}** life  `{player.life_bar()}`"

        # Poison
        poison_line = f"🧪 Poison: **{player.poison}**/10" if player.poison > 0 else ""

        # Commander tax
        tax_val = player.commander_tax
        tax_line = f"👑 Cmd Tax: +{tax_val} mana" if tax_val > 0 else ""

        # Commander damage received
        cmd_dmg_parts = []
        for attacker_id, dmg in player.commander_damage.items():
            if dmg > 0 and attacker_id in session.players:
                atk_name = session.players[attacker_id].display_name()
                warn = " ⚠️" if dmg >= 15 else ""
                lethal = " 💀**LETHAL**" if dmg >= 21 else ""
                cmd_dmg_parts.append(f"  └ from {atk_name}: **{dmg}**{warn}{lethal}")
        cmd_dmg_line = "\n".join(cmd_dmg_parts) if cmd_dmg_parts else ""

        # Deck info
        deck_line = ""
        if player.deck_name:
            deck_line = f"🃏 [{player.deck_name}]({player.deck_url})"
            if player.bracket:
                deck_line += f" — {player.bracket}"
            if player.deck_cost:
                deck_line += f" — {player.deck_cost}"
        elif player.commander_name:
            deck_line = f"🃏 {player.commander_name}"
 
        value_parts = [life_line]
        if poison_line:
            value_parts.append(poison_line)
        if tax_line:
            value_parts.append(tax_line)
        if cmd_dmg_line:
            value_parts.append(f"⚔️ Cmd Damage:\n{cmd_dmg_line}")
        if deck_line:
            value_parts.append(deck_line)

        field_name = f"{player.display_name()}{eliminated}"
        embed.add_field(name=field_name, value="\n".join(value_parts), inline=False)

    winner = session.check_winner()
    if winner:
        embed.set_footer(text=f"🏆 {winner.display_name()} wins! Game over.")
    else:
        alive_count = len(session.active_players())
        embed.set_footer(text=f"{alive_count} player(s) remaining")

    return embed


# ─── Button Views ───────────────────────────────────────────────────────────────

class LifeButtons(discord.ui.View):
    """Quick life adjustment buttons shown per player."""

    def __init__(self, target_id: int, guild_id: int):
        super().__init__(timeout=None)  # persistent
        self.target_id = target_id
        self.guild_id = guild_id

    async def _update_board(self, interaction: discord.Interaction):
        session = sessions.get(self.guild_id)
        if not session or not session.board_message:
            return
        try:
            await session.board_message.edit(embed=build_board_embed(session))
        except discord.NotFound:
            pass

    async def _adjust_life(self, interaction: discord.Interaction, delta: int):
        session = sessions.get(self.guild_id)
        if not session:
            await interaction.response.send_message("No active game.", ephemeral=True)
            return
        player = session.get_player(self.target_id)
        if not player:
            await interaction.response.send_message("Player not found.", ephemeral=True)
            return
        player.life += delta
        sign = "+" if delta > 0 else ""
        await interaction.response.send_message(
            f"{sign}{delta} life → **{player.display_name()}** now at **{player.life}** ❤️",
            ephemeral=True
        )
        await self._update_board(interaction)

    @discord.ui.button(label="-5", style=discord.ButtonStyle.danger, custom_id="life_m5", row=0)
    async def life_minus5(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._adjust_life(interaction, -5)

    @discord.ui.button(label="-1", style=discord.ButtonStyle.danger, custom_id="life_m1", row=0)
    async def life_minus1(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._adjust_life(interaction, -1)

    @discord.ui.button(label="+1", style=discord.ButtonStyle.success, custom_id="life_p1", row=0)
    async def life_plus1(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._adjust_life(interaction, 1)

    @discord.ui.button(label="+5", style=discord.ButtonStyle.success, custom_id="life_p5", row=0)
    async def life_plus5(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._adjust_life(interaction, 5)

    @discord.ui.button(label="🧪 +Poison", style=discord.ButtonStyle.secondary, custom_id="poison_p1", row=1)
    async def poison_plus(self, interaction: discord.Interaction, button: discord.ui.Button):
        session = sessions.get(self.guild_id)
        if not session:
            return
        player = session.get_player(self.target_id)
        if not player:
            return
        player.poison += 1
        await interaction.response.send_message(
            f"🧪 +1 poison → **{player.display_name()}** now at **{player.poison}**/10",
            ephemeral=True
        )
        await self._update_board(interaction)

    @discord.ui.button(label="🧪 -Poison", style=discord.ButtonStyle.secondary, custom_id="poison_m1", row=1)
    async def poison_minus(self, interaction: discord.Interaction, button: discord.ui.Button):
        session = sessions.get(self.guild_id)
        if not session:
            return
        player = session.get_player(self.target_id)
        if not player:
            return
        if player.poison > 0:
            player.poison -= 1
        await interaction.response.send_message(
            f"🧪 -1 poison → **{player.display_name()}** now at **{player.poison}**/10",
            ephemeral=True
        )
        await self._update_board(interaction)

    @discord.ui.button(label="👑 Recast Cmd", style=discord.ButtonStyle.primary, custom_id="tax_up", row=1)
    async def recast(self, interaction: discord.Interaction, button: discord.ui.Button):
        session = sessions.get(self.guild_id)
        if not session:
            return
        player = session.get_player(self.target_id)
        if not player:
            return
        player.commander_tax += 2
        await interaction.response.send_message(
            f"👑 Commander recast! **{player.display_name()}**'s tax is now +**{player.commander_tax}** mana",
            ephemeral=True
        )
        await self._update_board(interaction)


class CmdDamageView(discord.ui.View):
    """Commander damage buttons — attacker selects who they dealt damage to."""
 
    def __init__(self, session: GameSession, attacker_id: int, amount: int):
        super().__init__(timeout=60)
        self.session = session
        self.attacker_id = attacker_id
        self.amount = amount
 
        # Dynamically add a button for each opponent
        for pid, player in session.players.items():
            if pid == attacker_id:
                continue
            btn = discord.ui.Button(
                label=f"→ {player.display_name()}",
                style=discord.ButtonStyle.danger,
                custom_id=f"cdmg_{attacker_id}_{pid}"
            )
            btn.callback = self._make_callback(pid)
            self.add_item(btn)
 
    def _make_callback(self, target_id: int):
        async def callback(interaction: discord.Interaction):
            target = self.session.get_player(target_id)
            attacker = self.session.get_player(self.attacker_id)
            if not target or not attacker:
                await interaction.response.send_message("Player not found.", ephemeral=True)
                return
            target.commander_damage[self.attacker_id] = target.commander_damage.get(self.attacker_id, 0) + self.amount
            dmg = target.commander_damage[self.attacker_id]
            warn = " ⚠️ Getting close!" if 15 <= dmg < 21 else ""
            lethal = " 💀 **LETHAL!**" if dmg >= 21 else ""
            await interaction.response.send_message(
                f"⚔️ Commander damage: **{attacker.display_name()}** → **{target.display_name()}**: **{dmg}**/21{warn}{lethal}",
                ephemeral=True
            )
            # Update board
            if self.session.board_message:
                try:
                    await self.session.board_message.edit(embed=build_board_embed(self.session))
                except discord.NotFound:
                    pass
            self.stop()
        return callback


# ─── Archidekt Helper ───────────────────────────────────────────────────────────

# ─── Archidekt Helper ───────────────────────────────────────────────────────────
 
async def fetch_archidekt_deck(url: str) -> dict | None:
    """
    Fetch deck info from the Archidekt public API.
    Returns dict with name, commander, bracket, cost, url — or None on failure.
    """
    try:
        # Extract deck ID from URL formats:
        # archidekt.com/decks/12345/deck-name  or  archidekt.com/decks/12345
        parts = url.rstrip("/").split("/")
        deck_id = None
        for i, part in enumerate(parts):
            if part == "decks" and i + 1 < len(parts):
                deck_id = parts[i + 1]
                break
 
        if not deck_id or not deck_id.isdigit():
            return None
 
        api_url = f"https://archidekt.com/api/decks/{deck_id}/"
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    print(f"[Archidekt] HTTP {resp.status} for deck {deck_id}")
                    return None
                data = await resp.json()
 
        # ── Basic info ──────────────────────────────────────────────────────────
        name = data.get("name", "Unknown Deck")
 
        # ── Bracket ─────────────────────────────────────────────────────────────
        bracket_raw = data.get("edhBracket")
        bracket_str = f"Bracket {bracket_raw}" if bracket_raw else None
 
        # ── Commander(s) ────────────────────────────────────────────────────────
        commanders = set()
        total_cost = 0.0
        for card in data.get("cards", []):

            # Commander detection
            cats = card.get("categories", [])
            if "Commander" in cats:
                card_name = card.get("card", {}).get("oracleCard", {}).get("name", "")
                if card_name:
                    commanders.add(card_name)

            # Cost — TCG price × quantity per card
            quantity = card.get("quantity", 1)
            tcg_price = card.get("card", {}).get("prices", {}).get("tcg") or 0.0
            total_cost += tcg_price * quantity

        # These two lines must be outside the for loop (no indentation under it)
        commander_str = " & ".join(commanders) if commanders else None
        cost_str = f"${total_cost:.2f}" if total_cost > 0 else None
 
        return {
            "name": name,
            "commander": commander_str,
            "bracket": bracket_str,
            "cost": cost_str,
            "url": f"https://archidekt.com/decks/{deck_id}",
        }
 
    except Exception as e:
        print(f"[Archidekt] Error: {e}")
        return None


# ─── Bot Setup ──────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree


@bot.event
async def on_ready():
    guild = discord.Object(id=1095597247485464668)  # replace with your server ID
    tree.copy_global_to(guild=guild)
    await tree.sync(guild=guild)
    print(f"MTG Bot ready as {bot.user}")


# ─── Slash Commands ─────────────────────────────────────────────────────────────

@tree.command(name="newgame", description="Start a new Commander game lobby")
async def newgame(interaction: discord.Interaction):
    guild_id = interaction.guild_id
    if guild_id in sessions and sessions[guild_id].started:
        await interaction.response.send_message(
            "A game is already in progress! Use `/endgame` first.", ephemeral=True
        )
        return

    session = GameSession(guild_id, interaction.channel_id, interaction.user)
    session.add_player(interaction.user)
    sessions[guild_id] = session

    embed = discord.Embed(
        title="🃏 New Commander Game",
        description=f"**{interaction.user.display_name}** has opened a lobby!\n\nUse `/join` to join (up to 4 players).\nHost can use `/start` when ready.",
        color=discord.Color.dark_purple()
    )
    embed.add_field(name="Players (1/4)", value=f"1. {interaction.user.display_name} 👑 (host)")
    await interaction.response.send_message(embed=embed)


@tree.command(name="join", description="Join the open Commander game lobby")
async def join(interaction: discord.Interaction):
    session = sessions.get(interaction.guild_id)
    if not session:
        await interaction.response.send_message("No open lobby. Use `/newgame` to start one.", ephemeral=True)
        return
    if session.started:
        await interaction.response.send_message("Game already started.", ephemeral=True)
        return

    if not session.add_player(interaction.user):
        if interaction.user.id in session.players:
            await interaction.response.send_message("You're already in the lobby!", ephemeral=True)
        else:
            await interaction.response.send_message("Lobby is full (4 players max).", ephemeral=True)
        return

    names = [f"{i+1}. {p.display_name()}" for i, p in enumerate(session.players.values())]
    embed = discord.Embed(
        title="🃏 Commander Lobby",
        description=f"**{interaction.user.display_name}** joined!\n\n" + "\n".join(names),
        color=discord.Color.dark_purple()
    )
    embed.set_footer(text="Host: use /start when everyone is ready")
    await interaction.response.send_message(embed=embed)


@tree.command(name="deck", description="Optionally link your Archidekt deck")
@app_commands.describe(url="Your Archidekt deck URL")
async def deck(interaction: discord.Interaction, url: str):
    session = sessions.get(interaction.guild_id)
    if not session:
        await interaction.response.send_message("No active game.", ephemeral=True)
        return
 
    player = session.get_player(interaction.user.id)
    if not player:
        await interaction.response.send_message("You're not in this game.", ephemeral=True)
        return
 
    await interaction.response.defer(ephemeral=True)
    deck_data = await fetch_archidekt_deck(url)
 
    if deck_data:
        player.deck_url = deck_data["url"]
        player.deck_name = deck_data["name"]
        player.commander_name = deck_data["commander"]
        player.bracket = deck_data.get("bracket")
        player.deck_cost = deck_data.get("cost")
        msg = f"✅ Deck linked: **{deck_data['name']}**"
        if deck_data.get("commander"):
            msg += f"\nCommander: **{deck_data['commander']}**"
        if deck_data.get("bracket"):
            msg += f"\n{deck_data['bracket']}"
        if deck_data.get("cost"):
            msg += f"\nEstimated cost: **{deck_data['cost']}**"
    else:
        player.deck_url = url
        msg = "⚠️ Could not fetch deck details, but URL saved."
 
    await interaction.followup.send(msg, ephemeral=True)


@tree.command(name="start", description="Start the game (host only)")
async def start(interaction: discord.Interaction):
    session = sessions.get(interaction.guild_id)
    if not session:
        await interaction.response.send_message("No lobby found.", ephemeral=True)
        return
    if interaction.user.id != session.host.id:
        await interaction.response.send_message("Only the host can start the game.", ephemeral=True)
        return
    if len(session.players) < 2:
        await interaction.response.send_message("Need at least 2 players to start.", ephemeral=True)
        return
    if session.started:
        await interaction.response.send_message("Game already started.", ephemeral=True)
        return

    session.started = True

    # Post the board embed
    board_embed = build_board_embed(session)
    board_msg = await interaction.channel.send(embed=board_embed)
    session.board_message = board_msg

    await interaction.response.send_message(
        "⚔️ **Game started!** Each player's control panel is below. Use the buttons to track your stats.",
        ephemeral=False
    )

    # Send each player a personal control panel with buttons
    for pid, player in session.players.items():
        # Create a unique view per player
        view = LifeButtons(target_id=pid, guild_id=interaction.guild_id)
        panel_embed = discord.Embed(
            title=f"🎮 {player.display_name()}'s Controls",
            description="Use the buttons to update your stats. The board above will update live.",
            color=discord.Color.blurple()
        )
        if player.deck_name:
            panel_embed.add_field(name="Deck", value=f"[{player.deck_name}]({player.deck_url})")
        if player.commander_name:
            panel_embed.add_field(name="Commander", value=player.commander_name)

        await interaction.channel.send(embed=panel_embed, view=view)


@tree.command(name="status", description="Refresh the board state embed")
async def status(interaction: discord.Interaction):
    session = sessions.get(interaction.guild_id)
    if not session or not session.started:
        await interaction.response.send_message("No active game.", ephemeral=True)
        return

    embed = build_board_embed(session)
    # Post a fresh board
    msg = await interaction.channel.send(embed=embed)
    session.board_message = msg
    await interaction.response.send_message("Board refreshed! ✅", ephemeral=True)


@tree.command(name="cmddamage", description="Record commander damage you dealt to an opponent")
@app_commands.describe(amount="How much commander damage you dealt this combat")
async def cmddamage(interaction: discord.Interaction, amount: int):
    session = sessions.get(interaction.guild_id)
    if not session or not session.started:
        await interaction.response.send_message("No active game.", ephemeral=True)
        return
    if interaction.user.id not in session.players:
        await interaction.response.send_message("You're not in this game.", ephemeral=True)
        return
    if amount <= 0:
        await interaction.response.send_message("Amount must be greater than 0.", ephemeral=True)
        return

    view = CmdDamageView(session, attacker_id=interaction.user.id, amount=amount)
    await interaction.response.send_message(
        f"⚔️ You dealt **{amount}** commander damage — select who received it:",
        view=view,
        ephemeral=True
    )


@tree.command(name="life", description="Manually set or adjust a player's life total")
@app_commands.describe(
    player="The player to adjust",
    amount="Amount to change (e.g. -7 or +3) or absolute value"
)
async def life(interaction: discord.Interaction, player: discord.Member, amount: int):
    session = sessions.get(interaction.guild_id)
    if not session or not session.started:
        await interaction.response.send_message("No active game.", ephemeral=True)
        return

    target = session.get_player(player.id)
    if not target:
        await interaction.response.send_message("That player isn't in the game.", ephemeral=True)
        return

    target.life += amount
    sign = "+" if amount > 0 else ""
    await interaction.response.send_message(
        f"❤️ {sign}{amount} → **{target.display_name()}** is now at **{target.life}** life"
    )
    if session.board_message:
        await session.board_message.edit(embed=build_board_embed(session))


@tree.command(name="concede", description="Concede from the current game")
async def concede(interaction: discord.Interaction):
    session = sessions.get(interaction.guild_id)
    if not session or not session.started:
        await interaction.response.send_message("No active game.", ephemeral=True)
        return
    player = session.get_player(interaction.user.id)
    if not player:
        await interaction.response.send_message("You're not in this game.", ephemeral=True)
        return

    player.life = 0  # Marks as eliminated
    await interaction.response.send_message(
        f"🏳️ **{player.display_name()}** has conceded. Better luck next game!"
    )
    if session.board_message:
        await session.board_message.edit(embed=build_board_embed(session))

    winner = session.check_winner()
    if winner:
        await interaction.channel.send(f"🏆 **{winner.display_name()} wins the game!** GG everyone!")


@tree.command(name="endgame", description="End the current game and clear the session (host only)")
async def endgame(interaction: discord.Interaction):
    session = sessions.get(interaction.guild_id)
    if not session:
        await interaction.response.send_message("No active game.", ephemeral=True)
        return
    if interaction.user.id != session.host.id:
        await interaction.response.send_message("Only the host can end the game.", ephemeral=True)
        return

    del sessions[interaction.guild_id]
    await interaction.response.send_message(
        "🛑 Game ended. Thanks for playing! Use `/newgame` to start again."
    )


# ─── Run ────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    bot.run(BOT_TOKEN)
