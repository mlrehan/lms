"""Processing for uploaded course images.

Same principles as `avatar.py` -- the claimed type is ignored, the pixel budget is
checked before decoding, and what is stored is a fresh WebP encoding so EXIF and
appended payloads are gone -- but a course image is *not* cropped to a square: a
banner or a logo is composed on purpose, and cutting its edges off would be a
worse surprise than a different aspect ratio. It is scaled down to fit a box.
"""

from __future__ import annotations

import io

from PIL import Image, ImageOps, UnidentifiedImageError

from backend.core.errors import ValidationError

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 40_000_000
ACCEPTED_FORMATS = {"JPEG", "PNG", "WEBP"}
CONTENT_TYPE = "image/webp"

# kind -> the box it must fit inside
BOXES = {"small": (320, 320), "full": (1600, 1200)}


def process_course_image(data: bytes, kind: str) -> bytes:
    if kind not in BOXES:
        raise ValidationError("Unknown image kind.")
    if not data:
        raise ValidationError("The file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValidationError(f"The picture is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")

    try:
        image = Image.open(io.BytesIO(data))
        if image.format not in ACCEPTED_FORMATS:
            raise ValidationError("Use a JPEG, PNG or WebP image.")
        width, height = image.size
        if width * height > MAX_PIXELS:
            raise ValidationError("That image is too large to process. Use one under 40 megapixels.")
        image.load()
    except ValidationError:
        raise
    except Image.DecompressionBombError:
        raise ValidationError("That image is too large to process. Use one under 40 megapixels.") from None
    except (UnidentifiedImageError, OSError, ValueError):
        raise ValidationError("That file is not a readable JPEG, PNG or WebP image.") from None

    image = ImageOps.exif_transpose(image)
    image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
    image.thumbnail(BOXES[kind], Image.Resampling.LANCZOS)  # never enlarges, keeps the aspect ratio

    out = io.BytesIO()
    image.save(out, format="WEBP", quality=85, method=4)
    return out.getvalue()
