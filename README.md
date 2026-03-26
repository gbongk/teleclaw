# TeleClaw

[![Ko-fi](https://img.shields.io/badge/Ko--fi-Support-ff5e5b?logo=ko-fi&logoColor=white)](https://ko-fi.com/gbongk)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776ab.svg)](https://python.org)

**Remote-control your Claude Code sessions from Telegram.**

Keep Claude Code working on your projects while you're away from your desk — monitor progress, send instructions, and manage multiple sessions from your phone.

## How it Works

TeleClaw uses the [Claude Code SDK](https://www.npmjs.com/package/@anthropic-ai/claude-code) to spawn and manage Claude Code as subprocesses. Each project gets its own long-lived SDK session with preserved context — so Claude remembers what it was working on across messages.

```
You (Telegram) → TeleClaw → Claude Code SDK → Claude Code subprocess
                                ↑ streaming events (text, tool_use, result)
                    TeleClaw ←──┘ editMessage back to Telegram in real-time
```

No hooks or plugins required — TeleClaw receives all events directly through the SDK streaming API.

## Features

- **Telegram remote control** — Send messages to Claude Code, see live-streamed responses
- **Multi-session management** — Run multiple projects simultaneously with independent bots
- **Persistent sessions** — Context preserved across messages via Claude Code SDK
- **Auto-recovery** — DEAD/STUCK detection with 3-stage restart + auto-resume
- **Dual watchdog** — Process-level wrapper (exponential backoff) + async health check loop
- **Live streaming** — 3-second buffered editMessage for real-time response updates
- **Tool tracking** — See which files Claude reads/edits in real-time via Telegram
- **i18n** — Korean and English UI (`lang: "en"` in config)
- **Cross-platform** — Windows, Linux, macOS
- **System service** — `teleclaw install` for systemd (Linux) or Task Scheduler (Windows)

## Architecture

```
┌──────────────┐
│   Telegram   │  You send a message from your phone
└──────┬───────┘
       │ long poll
┌──────▼───────────────────────────────────┐
│            TeleClaw (asyncio)            │
│                                          │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐    │
│  │ Project1│ │ Project2│ │ Project3│ .. │  N independent sessions
│  │  bot    │ │  bot    │ │  bot    │    │
│  └────┬────┘ └────┬────┘ └────┬────┘    │
│       │           │           │          │
│  Health check (2min) · Watchdog (5min)   │
└───────┼───────────┼───────────┼──────────┘
        │           │           │
┌───────▼───────────▼───────────▼──────────┐
│          Claude Code SDK sessions         │
│   (persistent context, auto-resume)       │
└──────────────────────────────────────────┘
```

## Quick Start

### Prerequisites

- Python 3.11+
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated
- Telegram bot token (create one via [@BotFather](https://t.me/BotFather))

### Install

```bash
# Using uv (recommended — isolated environment)
uv tool install git+https://github.com/gbongk/teleclaw@v0.1.0

# Or using pip
pip install git+https://github.com/gbongk/teleclaw@v0.1.0

# From source (for development)
git clone https://github.com/gbongk/teleclaw.git
cd teleclaw
pip install -e .
```

### Configure

```bash
cp config.example.yaml config.yaml
```

Edit `config.yaml`:

```yaml
lang: "en"
chat_id: "YOUR_TELEGRAM_CHAT_ID"
allowed_users: ""

projects:
  MyProject:
    cwd: "/path/to/your/project"
    bot_token: "BOT_TOKEN_FROM_BOTFATHER"
```

You can add multiple projects — each gets its own Telegram bot:

```yaml
projects:
  Frontend:
    cwd: "/home/user/frontend"
    bot_token: "111:AAA..."
  Backend:
    cwd: "/home/user/backend"
    bot_token: "222:BBB..."
```

### Language

TeleClaw supports English and Korean. Set `lang` in `config.yaml`:

```yaml
lang: "en"   # English (default)
lang: "ko"   # Korean
```

All Telegram messages, CLI output, and system notifications will use the selected language.

### Run

```bash
# Install as system service (recommended)
# Starts immediately + auto-start on boot/login
teleclaw install

# Management commands
teleclaw status        # check if running
teleclaw logs          # view logs
teleclaw uninstall     # remove service
```

Or run manually:
```bash
# With auto-restart wrapper
python -m src.teleclaw_daemon

# Direct (no auto-restart, for debugging)
teleclaw
```

## Telegram Commands

| Command | Description |
|---|---|
| *(any message)* | Send instruction to Claude Code |
| `/status` (`/s`) | Session status (OK / DEAD / STUCK) |
| `/usage` (`/u`) | Claude usage (5h / 7d limits) |
| `/ctx` | Context window usage per session |
| `/restart` (`/r`) `[name]` | Restart session (with auto-resume) |
| `/reset [name]` | Reset session (clear context) |
| `/pause` (`/p`) `<name>` | Pause session |
| `/esc <name>` | Interrupt current task |
| `/log` (`/l`) `[N]` | Recent logs (default 20 lines) |
| `/sys` | System info (CPU / memory / processes) |
| `/ask <question>` | Quick question (separate session) |
| `/help` (`/h`) | Command list |

## CLI Commands

`teleclaw_ctl` provides the same management from the terminal:

```bash
python -m src.teleclaw_ctl <command> [args]
```

| Command | Short | Description |
|---|---|---|
| `sys` | | System CPU/RAM status |
| `ps` | `s` | Process list (PID, memory, Q/E/R) |
| `ctx` | `c` | Context window usage per session |
| `usage` | `u` | Token usage (5h/7d) |
| `restart [name]` | `r` | Restart session (default: current project) |
| `tc` | | Restart TeleClaw itself |
| `reset [name]` | | Reset session (clear context) |
| `pause [name]` | `p` | Pause session |
| `log [N]` | `l` | Recent logs (default 20 lines) |
| `help` | `h` | Command list |

All state (pause, restart commands) is stored in SQLite — no flag files.

## Auto-Recovery

TeleClaw has two layers of protection:

### 1. Health Check (session level)

Every 2 minutes, each session is assessed:
- **DEAD** — client disconnected or None
- **STUCK** — busy for 30+ minutes, or queue not draining
- **OK** — normal

DEAD/STUCK triggers automatic `_restart_session()` with resume.

### 2. Wrapper (process level)

`teleclaw_daemon.py` monitors the TeleClaw process itself:

```
Normal exit (alive > 30s)  →  restart after 3s
Crash (alive < 30s)        →  exponential backoff: 3s → 6s → 12s → ... → 30min max
```

During backoff, the wrapper still polls Telegram for emergency commands (`/restart`, `/kill`).

### What if the wrapper itself dies?

If you used `teleclaw install`, the system service (systemd/Task Scheduler) will restart the wrapper on login/boot. Otherwise, you need to manually start `python -m src.teleclaw_daemon` again.

To check if everything is running:
```bash
# Via Telegram
/status

# Via CLI
python -m src.teleclaw_ctl ps

# Via system service
teleclaw status
```

## Telegram Helper

`telegram_helper.py` lets Claude Code sessions send messages directly to Telegram — independent of TeleClaw's automatic streaming.

```bash
# Text message
python telegram_helper.py text "Build complete!"

# Photo with optional caption
python telegram_helper.py photo screenshot.png "Latest UI"

# File with optional caption
python telegram_helper.py file report.csv "Analysis result"
```

The bot token is auto-matched based on your current working directory and `config.yaml`.

## Project Structure

```
teleclaw/
+-- src/                       # Main package
|   +-- teleclaw.py            # TeleClaw class (core)
|   +-- teleclaw_daemon.py             # Auto-restart wrapper
|   +-- teleclaw_ctl.py               # CLI management tool
|   +-- telegram_helper.py     # CLI: send text/photo/file to Telegram
|   +-- telegram_api.py        # Telegram API (sync/async, text/photo/file)
|   +-- channel.py             # Abstract channel interface
|   +-- channel_telegram.py    # Telegram channel implementation
|   +-- commands.py            # Command handlers
|   +-- messages.py            # i18n messages (ko/en)
|   +-- session.py             # SessionState dataclass
|   +-- config.py              # config.yaml loader
|   +-- state_db.py            # SQLite state management
|   +-- service.py             # systemd / Task Scheduler support
|   +-- process_utils.py       # Cross-platform process utils
|   +-- usage_fmt.py           # Usage formatting
|   +-- logging_utils.py       # Logging utils
+-- tests/                     # Unit + smoke tests
+-- config.example.yaml        # Config template
+-- pyproject.toml              # Package metadata
+-- LICENSE                     # MIT
```

## Support

If you find TeleClaw useful, consider buying me a coffee:

[![Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/gbongk)

## License

MIT
