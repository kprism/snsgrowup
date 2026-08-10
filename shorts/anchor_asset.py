from __future__ import annotations

import base64
from pathlib import Path

# Synthetic, photorealistic Korean female news-anchor sample approved for the
# SNSGROWUP Shorts prototype. Keeping it embedded lets Codespaces rebuild the
# same composition without requiring a separate binary asset upload.
ANCHOR_FEMALE_JPEG_BASE64 = "PLACEHOLDER"


def write_anchor_sample(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(base64.b64decode(ANCHOR_FEMALE_JPEG_BASE64))
    return path
