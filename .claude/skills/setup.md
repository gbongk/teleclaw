---
name: setup
description: TeleClaw initial setup — create config.yaml, install dependencies, and start the service.
---

# /setup — TeleClaw Initial Setup

Guide the user through setting up TeleClaw step by step.

## Step 1: Check Prerequisites

Verify these are available:
- `python --version` → 3.11+
- `claude --version` → Claude Code CLI installed

If anything is missing, tell the user how to install it and stop.

## Step 2: Install Dependencies

```bash
pip install -e .
```

## Step 3: Create config.yaml

Ask the user for:
1. **Telegram Bot Token** — "Create a bot via @BotFather on Telegram and paste the token"
2. **Chat ID** — "Send a message to your bot, then visit `https://api.telegram.org/bot<TOKEN>/getUpdates` to find your chat ID"
3. **Project path** — "Which directory should Claude Code work in?"
4. **Project name** — "Give this project a short name (e.g., MyApp)"
5. **Language** — "en (English) or ko (Korean)?"

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

Test by sending a message via telegram_helper:
```bash
python telegram_helper.py text "TeleClaw setup complete!"
```

If it fails, ask the user to double-check the token and chat_id.

## Step 5: Start

```bash
teleclaw install
```

This registers TeleClaw as a system service and starts it immediately.

## Step 6: Add More Projects (Optional)

Ask: "Do you want to add more projects? Each project gets its own Telegram bot."

If yes, repeat Step 3 for each project (new bot token + project path) and append to config.yaml.

## Done

Print summary:
```
TeleClaw is running!

Send a message to your Telegram bot to start using Claude Code remotely.

Useful commands:
  /status          — check session health
  /help            — all commands
  teleclaw status  — service status
  teleclaw logs    — view logs
```
