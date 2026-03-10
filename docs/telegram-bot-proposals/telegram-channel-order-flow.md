# Telegram Channel -> Bot Order Flow Setup

This project now supports:

- Auto-posting new products to your Telegram channel
- Beautified product posts with a `Choose Size` button
- Existing bot deep-link order intake flow (`/start order_<product_id>`)
- Admin alert message when customer submits order details in bot chat

## Configure environment

Set these in `.env` and production environment variables:

- `TELEGRAM_BOT_TOKEN=<your_bot_token>`
- `TELEGRAM_ALERT_CHAT_ID=<your_admin_chat_id>`
- `TELEGRAM_CHANNEL_CHAT_ID=@zentanee_channel`
- `TELEGRAM_BOT_USERNAME=zentanee_admin_bot`
- `TELEGRAM_WEBHOOK_SECRET=<random-secret-string>`
- `SITE_URL=https://your-domain.com` (recommended so channel posts can include product images)

## Bot and channel permissions

- Add `@zentanee_admin_bot` as an admin in `@zentanee_channel`.
- Ensure bot has permission to post messages.

## Set webhook

Run this after deployment (replace placeholders):

```text
https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook?url=https://<YOUR_DOMAIN>/telegram/webhook/&secret_token=<TELEGRAM_WEBHOOK_SECRET>
```

Verify:

```text
https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getWebhookInfo
```

## Flow behavior

1. You create a new active product in Django admin.
2. Product is auto-posted to `@zentanee_channel`.
3. Post contains `Choose Size` button -> opens bot private chat.
4. Bot collects:
   - size
   - quantity
   - full name
   - phone
   - city
   - address
5. Bot asks for YES/NO confirmation.
6. On YES, admin receives detailed order request via Telegram alert chat.

## Notes

- Auto channel posting currently triggers for newly created products that are active and not sold out.
- No second bot is required.
- This flow captures order requests for manual acceptance/fulfillment.
