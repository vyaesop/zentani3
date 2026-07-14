# Hugging Face Image Worker (Reference-Guided)

This worker powers the hosted image generation flow. It accepts the full reference-guided
payload from the dashboard and returns generated images to be attached to product media
automatically.

> **Canonical source:** the worker's code lives in the deployed Hugging Face Space repo
> (`vyaesop/zentanee`), which has its own git history. The duplicated `hf_image_worker/`
> copy was removed from this repo — clone the Space to change the worker.

## Setup (Hugging Face Spaces)
Your Space already exists: `vyaesop/zentanee`. It runs a Docker-based FastAPI worker
exposing a clean `POST /generate` endpoint.

### Working on the worker
```
git clone https://huggingface.co/spaces/vyaesop/zentanee
```
When prompted for a password, use your Hugging Face access token with write permissions.
Edit `app.py` / `requirements.txt` / `Dockerfile` there, commit, and push — the Space
redeploys automatically.

### 4) Set Space environment variables
In the Space settings, add:
- `SDXL_BASE_MODEL` (default: `stabilityai/stable-diffusion-xl-base-1.0`)
- `SDXL_NUM_STEPS` (default: `8` on CPU, `30` on GPU)
- `SDXL_GUIDANCE_SCALE` (default: `5.5`)
- `SDXL_IMAGE_WIDTH` (default: `768` on CPU, `1024` on GPU)
- `SDXL_IMAGE_HEIGHT` (default: `768` on CPU, `1024` on GPU)
- `IMAGE_WORKER_ALLOWED_ORIGINS` (default: `*`, or set it to your storefront/dashboard origin)

GPU is recommended for speed and quality.

## API Endpoint
The FastAPI worker exposes:
```
POST /generate
```
Body: the exact JSON payload produced by `build_generator_payload` in `store/ai_enrichment.py`.

For a quick liveness check:
```
GET /health
```

## Connect the Django App
Set these variables in `.env`:
```
AI_IMAGE_GENERATOR_ENDPOINT=https://vyaesop-zentanee.hf.space/generate
AI_IMAGE_GENERATOR_TOKEN=
AI_IMAGE_GENERATOR_TIMEOUT=300
AI_IMAGE_GENERATOR_RETRIES=2
AI_IMAGE_GENERATOR_SHOTS_PER_REQUEST=1
AI_IMAGE_GENERATOR_FALLBACK_TO_LOCAL=False
```
The token is optional unless you restrict the Space.

## Notes
- This implementation uses SDXL img2img for reference-guided generation.
- It respects the `reference_strength` sent by the dashboard.
- If you provide a secondary reference image, the worker blends it lightly with
  the primary reference before generation.
- The Django app now sends one shot per request by default, which is more reliable on
  a free CPU Space than generating several images in a single HTTP response.
- The dashboard can call the Space directly from the browser now, which avoids Vercel's
  300-second function timeout during long image generation.

If you later want stronger fidelity, you can add IP-Adapter or ControlNet to this
worker without changing the dashboard payload format.
