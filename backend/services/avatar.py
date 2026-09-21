"""Profile-picture processing.

An avatar is untrusted bytes that will be shown to other people, so it is never
stored as received. It is decoded, and what is stored is a *fresh encoding* of
the pixels:

* **The claimed type is ignored.** `Content-Type` and the filename are
  caller-controlled; Pillow decides what the bytes are, and only JPEG, PNG and
  WebP are accepted. An SVG (script-capable) or HTML file fails to decode.
* **Re-encoding strips everything that is not pixels** -- EXIF (which carries
  GPS coordinates on phone photos), embedded thumbnails, ICC oddities, and any
  payload appended after the image data.
* **Decompression bombs are refused before decoding.** A 30 KB PNG can declare
  40,000 x 40,000 pixels; the dimensions are read from the header and checked
  against a pixel budget first.
* **Output is a square, fixed-size WebP**, so layout never depends on what
  someone chose to upload and every stored avatar costs a few tens of KB.
"""

from __future__ import annotations

import io

from PIL import Image, ImageOps, UnidentifiedImageError

from backend.core.errors import ValidationError

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 40_000_000
OUTPUT_SIZE = 512
ACCEPTED_FORMATS = {"JPEG", "PNG", "WEBP"}
CONTENT_TYPE = "image/webp"


def process_avatar(data: bytes) -> bytes:
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

    image = ImageOps.exif_transpose(image)  # honour the camera's rotation, then drop EXIF
    image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
    image = ImageOps.fit(image, (OUTPUT_SIZE, OUTPUT_SIZE), method=Image.Resampling.LANCZOS)

    out = io.BytesIO()
    image.save(out, format="WEBP", quality=85, method=4)
    return out.getvalue()
