"""Profile-picture processing (backend/services/avatar.py)."""

from __future__ import annotations

import io
import struct
import zlib

import pytest
from PIL import Image

from backend.core.errors import ValidationError
from backend.services import avatar


def _encode(fmt: str, size=(300, 200), colour=(200, 30, 30), **kw) -> bytes:  # noqa: ANN001
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, format=fmt, **kw)
    return out.getvalue()


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
def test_accepted_formats_become_a_square_webp(fmt: str) -> None:
    result = avatar.process_avatar(_encode(fmt))
    image = Image.open(io.BytesIO(result))
    assert image.format == "WEBP" and image.size == (avatar.OUTPUT_SIZE, avatar.OUTPUT_SIZE)


def test_a_wide_image_is_cropped_not_squashed() -> None:
    # Left half red, right half blue: a centre crop keeps both; a squash keeps both too,
    # so assert on the *middle* column instead -- fit() must not distort a square.
    img = Image.new("RGB", (400, 100), (0, 0, 255))
    img.paste((255, 0, 0), (0, 0, 200, 100))
    out = io.BytesIO(); img.save(out, "PNG")
    result = Image.open(io.BytesIO(avatar.process_avatar(out.getvalue()))).convert("RGB")
    left, right = result.getpixel((10, 256)), result.getpixel((500, 256))
    assert left[0] > 200 and right[2] > 200  # red on the left edge, blue on the right


def test_exif_including_gps_is_stripped() -> None:
    exif = Image.Exif()
    exif[0x010F] = "SecretCameraMaker"
    exif[0x8825] = {1: "N", 2: (51.0, 30.0, 0.0)}  # GPS IFD
    out = io.BytesIO()
    Image.new("RGB", (64, 64), (1, 2, 3)).save(out, "JPEG", exif=exif)
    assert b"SecretCameraMaker" in out.getvalue()  # the fixture really carries it

    result = avatar.process_avatar(out.getvalue())
    assert b"SecretCameraMaker" not in result
    assert not Image.open(io.BytesIO(result)).getexif()


def test_camera_rotation_is_applied_before_it_is_dropped() -> None:
    exif = Image.Exif(); exif[0x0112] = 6  # "rotate 90 degrees clockwise to view"
    img = Image.new("RGB", (200, 100), (0, 0, 255)); img.paste((255, 0, 0), (0, 0, 100, 100))
    out = io.BytesIO(); img.save(out, "JPEG", exif=exif, quality=100)
    result = Image.open(io.BytesIO(avatar.process_avatar(out.getvalue()))).convert("RGB")
    # Red was on the left; a 90-degree clockwise turn puts it on top.
    assert result.getpixel((256, 20))[0] > 180 and result.getpixel((256, 490))[2] > 180


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"not an image at all",
        b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        b"<html><script>alert(1)</script></html>",
        b"GIF89a\x01\x00\x01\x00\x00\x00\x00;",
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 10,  # a PNG signature and nothing else
    ],
)
def test_anything_that_is_not_a_real_jpeg_png_or_webp_is_refused(payload: bytes) -> None:
    with pytest.raises(ValidationError):
        avatar.process_avatar(payload)


def test_a_gif_is_refused_even_when_it_is_a_valid_gif() -> None:
    with pytest.raises(ValidationError, match="JPEG, PNG or WebP"):
        avatar.process_avatar(_encode("GIF"))


def test_oversized_uploads_are_refused_before_decoding(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a, **k):  # noqa: ANN002, ANN003
        raise AssertionError("decoded an oversized upload")

    monkeypatch.setattr(avatar.Image, "open", boom)
    with pytest.raises(ValidationError, match="larger than"):
        avatar.process_avatar(b"\x00" * (avatar.MAX_UPLOAD_BYTES + 1))


def _png_declaring(width: int, height: int) -> bytes:
    """A tiny, valid-looking PNG whose *header* claims a huge canvas."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    idat = zlib.compress(b"\x00" * 16)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def test_a_decompression_bomb_is_refused_from_its_header(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _png_declaring(30_000, 30_000)
    assert len(payload) < 200  # the whole "attack" fits in a tweet

    real_load = Image.Image.load

    def guarded_load(self, *a, **k):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("pixels were decoded for a bomb")

    monkeypatch.setattr(Image.Image, "load", guarded_load)
    with pytest.raises(ValidationError, match="too large"):
        avatar.process_avatar(payload)
    monkeypatch.setattr(Image.Image, "load", real_load)


def test_transparency_survives() -> None:
    img = Image.new("RGBA", (64, 64), (255, 0, 0, 0))
    out = io.BytesIO(); img.save(out, "PNG")
    result = Image.open(io.BytesIO(avatar.process_avatar(out.getvalue())))
    assert "A" in result.getbands()
