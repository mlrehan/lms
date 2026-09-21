"""Course image processing, price parsing, code abbreviation and the image-URL guard."""

from __future__ import annotations

import io

import pytest
from PIL import Image
from pydantic import ValidationError as PydanticError

from backend.core.errors import ValidationError
from backend.integrations import lait_academic as a
from backend.schemas.course import CourseCreateRequest, CourseUpdateRequest
from backend.services import images
from backend.services.course_service import CourseService


def _png(size=(2000, 500), colour=(10, 120, 200), mode="RGB") -> bytes:  # noqa: ANN001
    out = io.BytesIO()
    Image.new(mode, size, colour).save(out, "PNG")
    return out.getvalue()


# ------------------------------------------------------------------ images


def test_a_wide_banner_is_scaled_to_fit_not_cropped() -> None:
    result = Image.open(io.BytesIO(images.process_course_image(_png((2000, 500)), "full")))
    assert result.format == "WEBP" and result.size == (1600, 400)  # aspect ratio kept


def test_the_thumbnail_fits_its_box() -> None:
    result = Image.open(io.BytesIO(images.process_course_image(_png((1000, 800)), "small")))
    assert max(result.size) == 320 and result.size == (320, 256)


def test_a_small_image_is_never_enlarged() -> None:
    result = Image.open(io.BytesIO(images.process_course_image(_png((100, 60)), "full")))
    assert result.size == (100, 60)


def test_metadata_is_removed_and_transparency_kept() -> None:
    exif = Image.Exif()
    exif[0x010F] = "SecretCameraMaker"
    out = io.BytesIO()
    Image.new("RGB", (64, 64)).save(out, "JPEG", exif=exif)
    assert b"SecretCameraMaker" in out.getvalue()
    assert b"SecretCameraMaker" not in images.process_course_image(out.getvalue(), "small")
    assert "A" in Image.open(io.BytesIO(images.process_course_image(_png((50, 50), (0, 0, 0, 0), "RGBA"), "small"))).getbands()


@pytest.mark.parametrize("payload", [b"", b"not an image", b"<svg xmlns='http://www.w3.org/2000/svg'><script>1</script></svg>", b"<html></html>"])
def test_non_images_are_refused(payload: bytes) -> None:
    with pytest.raises(ValidationError):
        images.process_course_image(payload, "full")


def test_a_gif_and_an_unknown_kind_are_refused() -> None:
    out = io.BytesIO()
    Image.new("RGB", (10, 10)).save(out, "GIF")
    with pytest.raises(ValidationError, match="JPEG, PNG or WebP"):
        images.process_course_image(out.getvalue(), "full")
    with pytest.raises(ValidationError):
        images.process_course_image(_png(), "huge")


def test_oversize_uploads_are_refused_before_decoding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(images.Image, "open", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("decoded")))
    with pytest.raises(ValidationError, match="larger than"):
        images.process_course_image(b"\x00" * (images.MAX_UPLOAD_BYTES + 1), "full")


# ------------------------------------------------------------------- price


def _price(html_inner: str) -> float | None:
    return a.parse_course_page(f'<span id="MainContent_lblPrice">{html_inner}</span>').price


def test_the_regular_price_is_read() -> None:
    assert _price("<span style='x'>Regular Price: £540</span>") == 540.0


@pytest.mark.parametrize("text,value", [("£1,250.50", 1250.5), ("£ 99", 99.0), ("$120", 120.0), ("€75.5", 75.5)])
def test_price_formats(text: str, value: float) -> None:
    assert _price(f"Price: {text}") == value


@pytest.mark.parametrize("text", ["Free", "Contact us", "", "TBC"])
def test_a_page_without_a_price_yields_none(text: str) -> None:
    assert _price(text) is None


def test_the_batch_and_group_prices_are_not_the_course_price() -> None:
    html = (
        '<span id="MainContent_lblPrice">Regular Price: £540</span>'
        '<span id="MainContent_lblMinimumFee">Batch Price: From <b>£420</b></span>'
        '<span id="MainContent_lblCorporatePriceFrom">From <b>£360</b></span>'
    )
    assert a.parse_course_page(html).price == 540.0


# -------------------------------------------------------------- code suggestion


@pytest.mark.parametrize("title,prefix", [
    ("Python Programming for Beginners", "PPB"),
    ("Web Design for Beginners", "WDB"),
    ("SQL for Beginners", "SQLB"),
    ("Agentic AI & Automation with Python", "AAAP"),
    ("Data Science and Machine Learning with Python", "DSML"),
    ("Excel", "EXC"),
    ("", "CRS"),
    ("the of and", "CRS"),
])
def test_abbreviations(title: str, prefix: str) -> None:
    assert CourseService._abbreviation(title) == prefix


def test_an_abbreviation_only_ever_holds_letters_and_digits() -> None:
    assert CourseService._abbreviation("C++ & C# for /// Kids!!").isalnum()


# ------------------------------------------------------- image URL guard


@pytest.mark.parametrize("model", [CourseCreateRequest, CourseUpdateRequest])
@pytest.mark.parametrize("field", ["course_image", "small_course_image"])
@pytest.mark.parametrize("bad", ["avatars/abc/def.webp", "/etc/passwd", "../secret", "javascript:alert(1)", "courses/other/full/x.webp"])
def test_a_request_can_never_set_a_storage_key_as_an_image(model, field: str, bad: str) -> None:  # noqa: ANN001
    """If it could, the image endpoint would serve any stored object the key names."""
    body = {"title": "Valid title"} if model is CourseCreateRequest else {}
    with pytest.raises(PydanticError):
        model(**body, **{field: bad})


@pytest.mark.parametrize("field", ["course_image", "small_course_image"])
def test_external_urls_are_accepted(field: str) -> None:
    assert getattr(CourseCreateRequest(title="Valid title", **{field: "https://x.test/a.jpg"}), field) == "https://x.test/a.jpg"


# ------------------------------------------------------ response shape


def _course(**over):  # noqa: ANN003, ANN202
    import uuid
    from datetime import datetime, timezone

    from backend.models.course import Course
    from backend.utils.enums import CourseStatus, Levels

    c = Course(title="T", status=CourseStatus.PUBLISHED, level=Levels.BEGINNER, created_at=datetime.now(timezone.utc), **over)
    c.public_id = uuid.uuid4()
    c.category = c.department = None
    c.tags, c.tutors, c.batches = [], [], []
    return c


def _respond(course):  # noqa: ANN001, ANN202
    """`_course_response` now takes the caller (which tutors to show depends on who is looking); an
    administrator sees them all, which is what these image tests are not about."""
    import asyncio
    from types import SimpleNamespace

    from backend.api.v1.courses import _course_response

    admin = SimpleNamespace(id=1, roles=[SimpleNamespace(permissions=[SimpleNamespace(name="institution.view_all")])])
    return asyncio.run(_course_response(None, admin, course))


def test_the_detail_response_carries_the_image_urls() -> None:
    """`CourseResponse` declares its image fields with a validation alias; building it with the
    plain field names silently dropped both (the list worked, the detail page did not)."""
    r = _respond(_course(course_image="https://x/full.jpg", small_course_image="https://x/small.jpg"))
    assert (r.course_image, r.small_course_image) == ("https://x/full.jpg", "https://x/small.jpg")


def test_an_uploaded_image_is_exposed_as_a_path_and_never_as_the_storage_key() -> None:
    c = _course(course_image="courses/abc/full/0123456789abcdef.webp")
    r = _respond(c)
    assert r.course_image == f"/courses/{c.public_id}/image/full?v=0123456789ab"
    assert "courses/abc" not in r.course_image and r.small_course_image is None


def test_the_list_summary_carries_them_too() -> None:
    from backend.schemas.course import CourseSummary

    s = CourseSummary.model_validate(_course(small_course_image="https://x/small.jpg"))
    assert s.small_course_image == "https://x/small.jpg"
