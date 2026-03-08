# Telegram Alerts Only (Zero Budget) - Feasibility

## Is this feasible with 0 budget?

Yes. This is fully feasible at zero direct cost.

You only need:

- A Telegram bot token from `@BotFather` (free)
- Your Telegram chat ID (free)
- Your current Django hosting (already in use for your website)

## What this setup now does

- Sends a Telegram message when a new user signs up.
- Sends a Telegram message when checkout creates new order lines.

Implemented in:

- `store/telegram_notify.py`
- `store/views.py`

## Required environment variables

Add these variables in your local `.env` and production host environment:

- `TELEGRAM_BOT_TOKEN=123456789:xxxxxxxxxxxxxxxxxxxx`
- `TELEGRAM_ALERT_CHAT_ID=123456789`

If either variable is missing, the website still works and notifications are skipped safely.

## How to get your chat ID quickly

1. Open Telegram and message your bot once (for example, `/start`).
2. Open this URL in browser (replace token):
   - `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
3. Find `chat.id` in the JSON response and use it as `TELEGRAM_ALERT_CHAT_ID`.

## Cost notes

- Telegram Bot API usage for these low-volume alerts is free.
- No paid queue/service is required for this basic setup.
- If your site traffic scales heavily, you may later add a queue (Redis/Celery), but that is optional.

## Limits and caveats

- Notifications are sent synchronously in-request (fast enough for basic usage).
- If Telegram API is temporarily unavailable, alerts fail silently and checkout/signup still succeed.
- For group alerts, add your bot to a group and use that group chat ID.
