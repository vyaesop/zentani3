---
title: Zentanee Image Worker
emoji: "📸"
colorFrom: stone
colorTo: amber
sdk: docker
app_port: 7860
---

# Zentanee Image Worker

This Space runs a FastAPI service that generates reference-guided product images.

## Endpoints
- `POST /generate`

Send the JSON payload produced by `build_generator_payload` in the Django app.
