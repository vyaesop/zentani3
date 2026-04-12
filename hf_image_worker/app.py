import base64
import io
import os
from typing import List, Optional

import requests
import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from PIL import Image
from diffusers import StableDiffusionXLImg2ImgPipeline


MODEL_ID = os.getenv("SDXL_BASE_MODEL", "stabilityai/stable-diffusion-xl-base-1.0")
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
DTYPE = torch.float16 if DEVICE == "cuda" else torch.float32

DEFAULT_STEPS = int(os.getenv("SDXL_NUM_STEPS", "8" if DEVICE == "cpu" else "30"))
DEFAULT_GUIDANCE = float(os.getenv("SDXL_GUIDANCE_SCALE", "5.5"))
DEFAULT_IMAGE_WIDTH = int(os.getenv("SDXL_IMAGE_WIDTH", "768" if DEVICE == "cpu" else "1024"))
DEFAULT_IMAGE_HEIGHT = int(os.getenv("SDXL_IMAGE_HEIGHT", "768" if DEVICE == "cpu" else "1024"))


app = FastAPI(title="Zentanee Image Worker")


class ReferenceImage(BaseModel):
    label: str
    url: str


class ShotPayload(BaseModel):
    name: str
    prompt: str
    negative_prompt: Optional[str] = ""
    aspect_ratio: Optional[str] = "1:1"
    reference_images: Optional[List[str]] = None
    priority: Optional[int] = 1


class GenerationPayload(BaseModel):
    draft_id: int
    sku: str
    vendor_hint: Optional[str] = ""
    product_title_hint: Optional[str] = ""
    reference_images: List[ReferenceImage]
    reference_preservation_notes: Optional[str] = ""
    negative_prompt: Optional[str] = ""
    mode: Optional[str] = "reference-guided"
    reference_strength: Optional[str] = "high"
    notes: Optional[str] = ""
    shots: List[ShotPayload]


def _load_image(url: str) -> Image.Image:
    try:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to fetch reference image: {url}") from exc
    return Image.open(io.BytesIO(response.content)).convert("RGB")


def _pick_reference_images(payload: GenerationPayload, shot: ShotPayload) -> List[Image.Image]:
    label_map = {ref.label: ref.url for ref in payload.reference_images}
    labels = shot.reference_images or ["primary"]
    urls = [label_map.get(label) for label in labels if label_map.get(label)]
    if not urls:
        urls = [payload.reference_images[0].url]
    return [_load_image(url) for url in urls]


def _reference_strength_to_value(reference_strength: str) -> float:
    value = (reference_strength or "high").lower()
    if value == "low":
        return 0.65
    if value == "medium":
        return 0.5
    return 0.35


def _aspect_ratio_to_size(aspect_ratio: str) -> tuple[int, int]:
    ratio = (aspect_ratio or "1:1").strip()
    if ratio == "4:5":
        if DEVICE == "cpu":
            return (768, 960)
        return (1024, 1280)
    return (DEFAULT_IMAGE_WIDTH, DEFAULT_IMAGE_HEIGHT)


def _combine_references(references: List[Image.Image]) -> Image.Image:
    if len(references) == 1:
        return references[0]
    base = references[0].copy()
    overlay = references[1].resize(base.size)
    return Image.blend(base, overlay, 0.35)


@app.on_event("startup")
def _load_pipeline():
    global PIPELINE
    PIPELINE = StableDiffusionXLImg2ImgPipeline.from_pretrained(
        MODEL_ID,
        torch_dtype=DTYPE,
        use_safetensors=True,
        variant="fp16" if DTYPE == torch.float16 else None,
    )
    PIPELINE.to(DEVICE)
    PIPELINE.enable_xformers_memory_efficient_attention() if DEVICE == "cuda" else None


@app.get("/health")
def healthcheck():
    return {
        "status": "ok",
        "device": DEVICE,
        "model": MODEL_ID,
        "steps": DEFAULT_STEPS,
    }


@app.post("/generate")
def generate_images(payload: GenerationPayload):
    if not payload.reference_images:
        raise HTTPException(status_code=400, detail="At least one reference image is required.")

    results = []
    strength = _reference_strength_to_value(payload.reference_strength)

    for shot in sorted(payload.shots, key=lambda item: item.priority or 1):
        references = _pick_reference_images(payload, shot)
        init_image = _combine_references(references)
        width, height = _aspect_ratio_to_size(shot.aspect_ratio or "1:1")
        init_image = init_image.resize((width, height))

        prompt = shot.prompt
        if payload.product_title_hint and payload.product_title_hint not in prompt:
            prompt = f"{payload.product_title_hint}, {prompt}"

        negative = shot.negative_prompt or payload.negative_prompt or ""

        output = PIPELINE(
            prompt=prompt,
            negative_prompt=negative,
            image=init_image,
            strength=strength,
            num_inference_steps=DEFAULT_STEPS,
            guidance_scale=DEFAULT_GUIDANCE,
        )
        image = output.images[0]

        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=92, optimize=True)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")

        results.append(
            {
                "shot_name": shot.name,
                "prompt": shot.prompt,
                "aspect_ratio": shot.aspect_ratio,
                "content_type": "image/jpeg",
                "image_base64": encoded,
            }
        )

    return {"images": results}
