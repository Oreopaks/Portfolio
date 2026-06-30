"""
OCR-обёртка (EasyOCR) для цен на фото/кадрах Instagram. Reader ленивый —
модели (~100МБ) грузятся при первом вызове. RU+EN, CPU.
"""
from __future__ import annotations

import io

_reader = None


def get_reader():
    global _reader
    if _reader is None:
        import easyocr
        _reader = easyocr.Reader(["ru", "en"], gpu=False, verbose=False)
    return _reader


def ocr_image_bytes(data: bytes) -> str:
    """Байты картинки -> распознанный текст (строки через \\n)."""
    import numpy as np
    from PIL import Image
    img = Image.open(io.BytesIO(data)).convert("RGB")
    lines = get_reader().readtext(np.array(img), detail=0, paragraph=True)
    return "\n".join(lines)
