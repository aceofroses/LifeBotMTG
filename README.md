# MTG Commander Life Counter Bot

A Discord bot for tracking Commander game state during a session. Handles life totals, commander damage, poison counters, and commander tax for up to 4 players. Everything is controlled through buttons and slash commands directly in Discord.

---

## What It Does

When a game starts, the bot posts two things in the channel:

**Board embed** — a shared view of every player's current stats that updates automatically whenever anyone interacts with the bot. Everyone in the channel can see it at all times.

**Control panels** — each player gets their own personal panel with buttons for the most common actions. No typing required during gameplay.

### What gets tracked per player

- **Life total** — starts at 40, adjusted via buttons or the `/life` command
- **Commander damage** — tracked per attacker separately, since 21 from a single commander is lethal
- **Poison counters** — tracked 0 to 10, lethal at 10
- **Commander tax** — increments by 2 each time a commander is recast, displayed as extra mana cost
- **Deck info** — optionally linked via an Archidekt URL, shows deck name and commander on the board

---

## How to Use It

### Starting a game

1. One player runs `/newgame` to open a lobby — they become the host
2. Other players run `/join` to enter the lobby (up to 4 total)
3. Anyone can optionally run `/deck [archidekt url]` to link their deck before starting
4. The host runs `/start` — the board and control panels are posted immediately

### During the game

Use the buttons on your personal control panel for most actions:

- `-5` / `-1` / `+1` / `+5` to adjust your life total
- `+Poison` / `-Poison` to track poison counters
- `Recast Cmd` to add +2 to your commander tax

For commander damage, run `/cmddamage` — the bot will show a button for each opponent, tap the one you dealt damage to. Each tap adds 1 commander damage from you to that player.

The board embed updates automatically after every button press.

### Ending the game

- Any player can run `/concede` to remove themselves — the bot will announce a winner if only one player remains
- The host can run `/endgame` at any time to close the session entirely

---

## All Commands

| Command | Who can use it | Description |
|---|---|---|
| `/newgame` | Anyone | Opens a lobby |
| `/join` | Anyone | Joins the open lobby |
| `/deck [url]` | Players in lobby | Links an Archidekt deck (optional) |
| `/start` | Host only | Starts the game |
| `/cmddamage` | Players in game | Records commander damage dealt |
| `/life @player [amount]` | Anyone | Manually adjusts a player's life (e.g. `-7`) |
| `/status` | Anyone | Reposts a fresh board embed |
| `/concede` | Players in game | Removes you from the game |
| `/endgame` | Host only | Ends the session |

---

## Troubleshooting

**The buttons stopped working mid-game**
The bot was likely restarted. The board embed will still show the last known state, but the buttons are no longer active. The host should run `/endgame` to clear the old session, then start a new game with `/newgame`.

**Slash commands are not showing up in Discord**
Commands can take up to an hour to register after the bot first joins a server. If they still don't appear after that, the bot may not have the `applications.commands` permission — remove it from the server and re-invite it using a link that includes that scope.

**The board embed is not updating**
Run `/status` to post a fresh board. This sometimes helps if the original embed was posted a long time ago or the channel had a lot of activity since.

**Commander damage is showing wrong values**
Commander damage is tracked per attacker, so `/cmddamage` needs to be run by the player who dealt the damage, not the one who received it. Each tap of the opponent button adds exactly 1 damage — run it once per point of damage dealt.

**A player joined by mistake or needs to be removed**
Currently, players cannot be removed from a lobby once joined short of the host running `/endgame` and starting over. If a player needs to drop mid-game they can use `/concede`.

**The bot is online but not responding to commands**
Make sure the bot has `Send Messages` and `Embed Links` permissions in the channel you are using. If the channel is restricted, the bot may be blocked from posting.

**Archidekt deck link is not working**
The bot fetches deck info from the Archidekt public API. Make sure the deck is set to public visibility on Archidekt. Private decks will not return any data. The URL format should look like `https://archidekt.com/decks/123456/deck-name`.