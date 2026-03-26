# TeleClaw

[![Ko-fi](https://img.shields.io/badge/Ko--fi-Support-ff5e5b?logo=ko-fi&logoColor=white)](https://ko-fi.com/gbongk)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776ab.svg)](https://python.org)

**Remote-control your Claude Code sessions from Telegram.**

Keep Claude Code working on your projects while you're away from your desk — monitor progress, send instructions, and manage multiple sessions from your phone.

## How is this different?

| | [claude-code-telegram](https://github.com/RichardAtCT/claude-code-telegram) | [NanoClaw](https://github.com/qwibitai/nanoclaw) | **TeleClaw** |
|---|---|---|---|
| **Session model** | New query each message | New agent per chat | **Persistent sessions** (context preserved) |
| **Multi-project** | Single directory | Groups | **N projects, each with its own bot** |
| **Auto-recovery** | None | Container restart | **Health check + watchdog + exponential backoff** |
| **Live streaming** | Tool/reasoning indicators | None | **Real-time response via editMessage** |

Think of it like texting a developer who already knows your codebase — not hiring a new one each time.

## Features

- **Telegram remote control** — Send messages to Claude Code, see live-streamed responses
- **Multi-session management** — Run multiple projects simultaneously with independent bots
- **Auto-recovery** — DEAD/STUCK detection with 3-stage restart + auto-resume
- **Dual watchdog** — Process-level wrapper (exponential backoff) + async health check loop
- **Live streaming** — 3-second buffered editMessage for real-time response updates
- **Tool relay** — See which files Claude reads/edits in real-time via Telegram
- **i18n** — Korean and English UI (`lang: "en"` in config)
- **Cross-platform** — Windows, Linux, macOS
- **System service** — `teleclaw install` for systemd (Linux) or Task Scheduler (Windows)

## Architecture

```
Telegram (mobile)
    | long poll (25s)
    v
TeleClaw (asyncio)
    +-- Bot poll loop (x N projects)
    +-- Session loop (x N) -- SDK query + streaming response
    +-- Health check loop (every 2 min)
    +-- Flag watch loop (every 1s)
    +-- Watchdog loop (every 5 min)
    |
    v
Claude Code SDK (claude-code-sdk)
    |
    v
Claude Code sessions (independent per project)
```

## Quick Start

### Prerequisites

- Python 3.11+
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated
- Telegram bot token (create one via [@BotFather](https://t.me/BotFather))

### Install

```bash
# From source
git clone https://github.com/gbongk/teleclaw.git
cd teleclaw
pip install -e .

# Or via pip
pip install git+https://github.com/gbongk/teleclaw.git
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

### Run

```bash
# Direct
teleclaw

# With auto-restart wrapper (recommended)
python teleclaw-wrapper.py

# As a system service
teleclaw install       # systemd (Linux) or Task Scheduler (Windows)
teleclaw status        # check service status
teleclaw logs          # view logs
teleclaw uninstall     # remove service
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

## Auto-Recovery

TeleClaw has two layers of protection:

### 1. Health Check (session level)

Every 2 minutes, each session is assessed:
- **DEAD** — client disconnected or None
- **STUCK** — busy for 30+ minutes, or queue not draining
- **OK** — normal

DEAD/STUCK triggers automatic `_restart_session()` with resume.

### 2. Wrapper (process level)

`teleclaw-wrapper.py` monitors the TeleClaw process itself:

```
Normal exit (alive > 30s)  →  restart after 3s
Crash (alive < 30s)        →  exponential backoff: 3s → 6s → 12s → ... → 30min max
```

During backoff, the wrapper still polls Telegram for emergency commands (`/restart`, `/kill`).

## Project Structure

```
teleclaw/
+-- hub/                     # Main package
|   +-- teleclaw.py          # TeleClaw class (core)
|   +-- telegram_api.py      # Telegram API (sync/async, text/photo/file)
|   +-- channel.py           # Abstract channel interface
|   +-- channel_telegram.py  # Telegram channel implementation
|   +-- commands.py          # Command handlers
|   +-- messages.py          # i18n messages (ko/en)
|   +-- session.py           # SessionState dataclass
|   +-- config.py            # config.yaml loader
|   +-- state_db.py          # SQLite state management
|   +-- service.py           # systemd / Task Scheduler support
|   +-- process_utils.py     # Cross-platform process utils
|   +-- usage_fmt.py         # Usage formatting
|   +-- logging_utils.py     # Logging utils
+-- teleclaw-wrapper.py      # Auto-restart wrapper
+-- relay-stop.py            # Stop hook (response -> Telegram)
+-- relay-tool-use.py        # PostToolUse hook (tool use -> Telegram)
+-- relay_common.py          # Hook shared utils
+-- svctl.py                 # CLI tool
+-- send_telegram.py         # CLI photo/file sender
+-- config.example.yaml      # Config template
+-- pyproject.toml            # Package metadata
+-- Makefile                  # Dev commands
+-- LICENSE                   # MIT
```

## Support

If you find TeleClaw useful, consider buying me a coffee:

[![Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/gbongk)

## License

MIT
