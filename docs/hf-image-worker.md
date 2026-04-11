# Hugging Face Image Worker (Reference-Guided)

This worker powers the hosted image generation flow. It accepts the full reference-guided
payload from the dashboard and returns generated images to be attached to product media
automatically.

## Setup (Hugging Face Spaces)
Your Space already exists: `vyaesop/zentanee`. We will deploy a Docker-based FastAPI worker
so we can expose a clean `POST /generate` endpoint.

### 1) Clone the Space repo
```
git clone https://huggingface.co/spaces/vyaesop/zentanee
```
When prompted for a password, use your Hugging Face access token with write permissions.

### 2) Copy the worker files into the Space
Copy everything from `hf_image_worker/` into the root of the Space repo:
- `app.py`
- `requirements.txt`
- `Dockerfile`
- `README.md`

The provided `README.md` already sets `sdk: docker` and `app_port: 7860`.

### 3) Commit + push
```
git add app.py requirements.txt Dockerfile README.md
git commit -m "Deploy Zentanee FastAPI image worker"
git push
```

### 4) Set Space environment variables
In the Space settings, add:
- `SDXL_BASE_MODEL` (default: `stabilityai/stable-diffusion-xl-base-1.0`)
- `SDXL_NUM_STEPS` (default: `30`)
- `SDXL_GUIDANCE_SCALE` (default: `5.5`)

GPU is recommended for speed and quality.

## API Endpoint
The FastAPI worker exposes:
```
POST /generate
```
Body: the exact JSON payload produced by `build_generator_payload` in `store/ai_enrichment.py`.

## Connect the Django App
Set these variables in `.env`:
```
AI_IMAGE_GENERATOR_ENDPOINT=https://vyaesop-zentanee.hf.space/generate
AI_IMAGE_GENERATOR_TOKEN=
```
The token is optional unless you restrict the Space.

## Notes
- This implementation uses SDXL img2img for reference-guided generation.
- It respects the `reference_strength` sent by the dashboard.
- If you provide a secondary reference image, the worker blends it lightly with
  the primary reference before generation.

If you later want stronger fidelity, you can add IP-Adapter or ControlNet to this
worker without changing the dashboard payload format.
