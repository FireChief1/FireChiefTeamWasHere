"""Optional local vision analysis for Project Chat image attachments."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass

from app.llm.pool import Capability, LLMPool, get_pool

SUPPORTED_IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True)
class ImageAttachment:
    """Validated image payload accepted by the local Project Chat API."""

    name: str
    mime_type: str
    data_base64: str
    byte_size: int


def normalize_image_attachment(raw: object) -> ImageAttachment | None:
    """Validate and normalize a JSON image attachment payload.

    The React UI sends `{name, mimeType, data}` where data may be a plain
    base64 string or a `data:image/...;base64,...` URL.
    """
    if raw in (None, "", {}):
        return None
    if not isinstance(raw, dict):
        raise ValueError("Image attachment must be an object.")

    mime_type = str(raw.get("mimeType") or raw.get("mime_type") or "").strip()
    name = str(raw.get("name") or "attached-image").strip() or "attached-image"
    data = str(raw.get("data") or raw.get("base64") or "").strip()
    if not data:
        raise ValueError("Image attachment data is required.")

    detected_mime, data_base64 = _split_data_url(data)
    if detected_mime:
        mime_type = detected_mime
    if mime_type not in SUPPORTED_IMAGE_MIME_TYPES:
        allowed = ", ".join(sorted(SUPPORTED_IMAGE_MIME_TYPES))
        raise ValueError(f"Unsupported image type. Allowed: {allowed}.")

    try:
        decoded = base64.b64decode(data_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Image attachment is not valid base64.") from exc

    if not decoded:
        raise ValueError("Image attachment is empty.")
    if len(decoded) > MAX_IMAGE_BYTES:
        max_mb = MAX_IMAGE_BYTES // (1024 * 1024)
        raise ValueError(f"Image attachment is too large; max {max_mb} MB.")

    return ImageAttachment(
        name=name[:120],
        mime_type=mime_type,
        data_base64=data_base64,
        byte_size=len(decoded),
    )


async def analyze_image_attachment(
    *,
    message: str,
    image: ImageAttachment,
    project_context: str = "",
    pool: LLMPool | None = None,
) -> str:
    """Ask the optional vision model to describe a Project Chat image."""
    llm_pool = pool or get_pool()
    prompt = _vision_prompt(message, image, project_context)
    response = await llm_pool.agenerate_with_image(
        prompt,
        image_base64=image.data_base64,
        capability=Capability.VISION,
        temperature=0.1,
    )
    return response.strip()


def _split_data_url(data: str) -> tuple[str, str]:
    """Return `(mime_type, base64)` for data URLs, otherwise `("", data)`."""
    prefix, separator, payload = data.partition(",")
    if separator and prefix.startswith("data:") and ";base64" in prefix:
        mime_type = prefix.removeprefix("data:").split(";", 1)[0]
        return mime_type, payload.strip()
    return "", data


def _vision_prompt(message: str, image: ImageAttachment, project_context: str) -> str:
    """Build the first-version Project Chat vision prompt."""
    context = project_context.strip() or "(no project context)"
    return (
        "You are the optional vision capability for a local project assistant. "
        "Analyze the attached image or screenshot and answer in the user's "
        "language. If the user message is Turkish, answer in Turkish. Focus "
        "on visible facts: UI text, error messages, layout "
        "issues, controls, and what the image appears to show. If the image is "
        "a UI screenshot, summarize the visible problem and likely next check. "
        "Do not claim that files were read, changed, tested, committed, or "
        "pushed. Do not start coding; a separate workflow will handle code "
        "changes only when the user explicitly asks for them.\n\n"
        f"Project context:\n{context}\n\n"
        f"Image name: {image.name}\n"
        f"Image type: {image.mime_type}\n"
        f"User message:\n{message or 'Bu görseli yorumla.'}"
    )
