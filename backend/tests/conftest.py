"""
Test fixtures and configuration.
Mocks pytesseract fallback if Tesseract is not installed on the local test machine.
"""
import pytest
import pytesseract
from unittest.mock import patch
from pytesseract import Output


@pytest.fixture(autouse=True)
def mock_tesseract_if_missing():
    try:
        pytesseract.get_tesseract_version()
        yield
    except Exception:
        # Tesseract binary is not installed locally on Windows test runner
        def mock_image_to_data(image, output_type=Output.DICT, *args, **kwargs):
            return {
                "text": ["Scanned", "document", "text", "content"],
                "conf": ["95", "95", "95", "95"],
                "left": [30, 80, 140, 180],
                "top": [50, 50, 50, 50],
                "width": [45, 55, 35, 50],
                "height": [15, 15, 15, 15],
            }

        with patch("pytesseract.image_to_data", side_effect=mock_image_to_data):
            yield
