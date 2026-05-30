"""Tests for optional Project Chat vision attachments."""

from __future__ import annotations

import pytest

from app.vision import normalize_image_attachment


def test_normalize_image_attachment_accepts_data_url():
    image = normalize_image_attachment(
        {
            "name": "screen.png",
            "mimeType": "image/png",
            "data": "data:image/png;base64,aGVsbG8=",
        }
    )

    assert image is not None
    assert image.name == "screen.png"
    assert image.mime_type == "image/png"
    assert image.data_base64 == "aGVsbG8="
    assert image.byte_size == 5


def test_normalize_image_attachment_rejects_unsupported_mime_type():
    with pytest.raises(ValueError, match="Unsupported image type"):
        normalize_image_attachment(
            {
                "name": "file.gif",
                "mimeType": "image/gif",
                "data": "R0lGODlh",
            }
        )


def test_normalize_image_attachment_rejects_invalid_base64():
    with pytest.raises(ValueError, match="not valid base64"):
        normalize_image_attachment(
            {
                "name": "broken.png",
                "mimeType": "image/png",
                "data": "not base64!",
            }
        )
