---
name: setup
description: TeleClaw initial setup — create config.yaml, install dependencies, register hooks, and start the service.
---

# /setup — TeleClaw Initial Setup

Guide the user through setting up TeleClaw step by step.

## Step 1: Check Prerequisites

Verify these are available:
- `python --version` → 3.11+
- `claude --version` → Claude Code CLI installed
- `node --version` → Node.js (required by Claude Code)

If anything is missing, tell the user how to install it and stop.

## Step 2: Install Dependencies

```bash
pip install -e .
```

Or if not cloned:
```bash
pip install git+https://github.com/gbongk/teleclaw.git
```

## Step 3: Create config.yaml

Ask the user for:
1. **Telegram Bot Token** — "Create a bot via @BotFather on Telegram and paste the token"
2. **Chat ID** — "Send a message to your bot, then visit https://api.telegram.org/bot<TOKEN>/getUpdates to find your chat ID"
3. **Project path** — "Which directory should Claude Code work in?"
4. **Project name** — "Give this project a short name (e.g., MyApp)"
5. **Language** — "ko (Korean) or en (English)?"

Then generate `config.yaml`:

```yaml
lang: "{language}"
chat_id: "{chat_id}"
allowed_users: ""

projects:
  {project_name}:
    cwd: "{project_path}"
    bot_token: "{bot_token}"
```

Write this to `config.yaml` in the teleclaw directory.

## Step 4: Verify Connection

Test the bot token by sending a test message:
```bash
python -c "
from hub.telegram_api import send_telegram
mid = send_telegram('TeleClaw setup complete!', '{bot_token}')
print('OK' if mid else 'FAILED')
"
```

If it fails, ask the user to double-check the token and chat_id.

## Step 5: Register Relay Hooks (Optional)

Ask: "Do you want real-time tool use notifications in Telegram? (recommended)"

If yes, explain they need to add hooks to their Claude Code settings. Show the paths:

**Linux/Mac:** `~/.claude/settings.json`
**Windows:** `C:\Users\<username>\.claude\settings.json`

Add to the `hooks` section:
```json
{
  "hooks": {
    "PostToolUse": [
      {
        "type": "command",
        "command": "python /path/to/teleclaw/relay-tool-use.py"
      }
    ],
    "Stop": [
      {
        "type": "command",
        "command": "python /path/to/teleclaw/relay-stop.py"
      }
    ]
  }
}
```

Replace `/path/to/teleclaw/` with the actual teleclaw directory.

## Step 6: Start

Ask: "How do you want to run TeleClaw?"

**Option A: System service (recommended)**
```bash
teleclaw install
```

**Option B: Direct**
```bash
teleclaw
```

**Option C: With auto-restart wrapper**
```bash
python teleclaw-wrapper.py
```

## Step 7: Add More Projects (Optional)

Ask: "Do you want to add more projects? Each project gets its own Telegram bot."

If yes, repeat Step 3 for each project (new bot token + project path) and append to config.yaml.

## Done

Print summary:
```
TeleClaw is running!

Send a message to your Telegram bot to start using Claude Code remotely.

Useful commands:
  /status  — check session health
  /help    — all commands
  teleclaw status  — service status
  teleclaw logs    — view logs
```
