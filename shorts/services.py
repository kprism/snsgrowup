from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

import requests
from django.conf import settings
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .anchor_asset import write_anchor_sample


class ShortsGenerationError(RuntimeError):
    pass


BLUE = (22, 78, 190, 255)
WHITE = (255, 255, 255, 255)
TRANSPARENT = (0, 0, 0, 0)
FONT_CANDIDATES = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
)


def _font(size: int):
    for candidate in FONT_CANDIDATES:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int, max_lines: int) -> list[str]:
    compact = re.sub(r"\s+", " ", text.strip())
    if not compact:
        return []
    lines: list[str] = []
    current = ""
    for char in compact:
        trial = current + char
        box = draw.textbbox((0, 0), trial, font=font, stroke_width=0)
        if current and box[2] - box[0] > max_width:
            lines.append(current.rstrip())
            current = char.lstrip()
            if len(lines) >= max_lines:
                break
        else:
            current = trial
    if current and len(lines) < max_lines:
        lines.append(current.rstrip())
    if len(lines) == max_lines:
        consumed = "".join(lines)
        if len(consumed) < len(compact):
            last = lines[-1]
            while last and draw.textbbox((0, 0), last + "…", font=font)[2] > max_width:
                last = last[:-1]
            lines[-1] = last.rstrip() + "…"
    return lines


def _polite_fallback(text: str) -> str:
    compact = re.sub(r"\s+", " ", text.strip())[:90]
    replacements = (
        (r"연다\.$", "엽니다."),
        (r"한다\.$", "합니다."),
        (r"된다\.$", "됩니다."),
        (r"나선다\.$", "나섭니다."),
        (r"밝혔다\.$", "밝혔습니다."),
        (r"개최한다\.$", "개최합니다."),
        (r"진행한다\.$", "진행합니다."),
        (r"추진한다\.$", "추진합니다."),
        (r"예정이다\.$", "예정입니다."),
        (r"계획이다\.$", "계획입니다."),
    )
    for pattern, replacement in replacements:
        compact = re.sub(pattern, replacement, compact)
    return compact


def _short_script(*, title: str, body: str) -> str:
    fallback = _polite_fallback(body or title) or _polite_fallback(title)
    if not settings.OPENAI_API_KEY:
        return fallback or title[:70]

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    prompt = f"""
다음 뉴스 기사로 10초짜리 유튜브 쇼츠용 한국어 뉴스 브리핑 멘트를 작성하세요.
규칙:
- 반드시 존댓말 뉴스 브리핑체로 작성하세요.
- 문장 종결은 자연스럽게 '~합니다', '~했습니다', '~입니다', '~예정입니다' 형태를 사용하세요.
- 반말 기사체인 '~한다', '~된다', '~연다', '~밝혔다'로 끝내지 마세요.
- 1~2문장만 작성하세요.
- 약 45~70자의 자연스러운 한국어로 작성하세요.
- 기사에 없는 사실을 추가하거나 과장하지 마세요.
- 인사말, 해시태그, 이모지, 따옴표를 넣지 마세요.
- 제목 전체를 그대로 반복하지 마세요.
- 화면 자막과 TTS가 그대로 이 문장을 사용하므로 말로 들었을 때 자연스러워야 합니다.
- 결과는 멘트 본문만 출력하세요.

제목: {title}
본문: {(body or '')[:3500]}
""".strip()
    try:
        response = client.responses.create(model=settings.OPENAI_MODEL, input=prompt)
        text = re.sub(r"\s+", " ", (response.output_text or "").strip())
        return text[:140] or fallback or title[:70]
    except Exception:
        return fallback or title[:70]


def _speech_mp3(*, text: str, output_path: Path) -> None:
    if not settings.OPENAI_API_KEY:
        raise ShortsGenerationError("쇼츠 한국어 음성을 만들려면 OpenAI API Key가 필요합니다.")

    response = requests.post(
        "https://api.openai.com/v1/audio/speech",
        headers={
            "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": getattr(settings, "SHORTS_TTS_MODEL", "gpt-4o-mini-tts"),
            "voice": getattr(settings, "SHORTS_TTS_VOICE", "marin"),
            "input": text,
            "instructions": "한국의 30대 여성 뉴스 앵커처럼 또렷하고 신뢰감 있게 존댓말로 브리핑해 주세요. 지나치게 감정적이지 않게, 10초 뉴스 쇼츠에 맞춰 약간 빠르고 자연스럽게 읽어주세요.",
            "response_format": "mp3",
            "speed": 1.10,
        },
        timeout=90,
    )
    if not response.ok:
        try:
            error = response.json()
        except ValueError:
            error = response.text
        raise ShortsGenerationError(f"OpenAI 음성 생성 실패: {error}")
    output_path.write_bytes(response.content)


def _image_jpeg(source_path: Path, output_path: Path) -> None:
    with Image.open(source_path) as source:
        image = source.convert("RGB")
        image.save(output_path, format="JPEG", quality=97, optimize=True, subsampling=0)


def _make_title_bar(*, title: str, output_path: Path) -> None:
    canvas = Image.new("RGBA", (1080, 280), BLUE)
    draw = ImageDraw.Draw(canvas)
    label_font = _font(30)
    title_font = _font(62)
    draw.text((54, 30), "SNSGROWUP NEWS", font=label_font, fill=(210, 226, 255, 255))
    lines = _wrap_text(draw, title, title_font, 970, 2)
    y = 78
    for line in lines:
        draw.text((54, y), line, font=title_font, fill=WHITE)
        y += 76
    canvas.save(output_path)


def _make_caption(*, script: str, output_path: Path) -> None:
    canvas = Image.new("RGBA", (700, 390), TRANSPARENT)
    draw = ImageDraw.Draw(canvas)
    font = _font(43)
    lines = _wrap_text(draw, script, font, 610, 3)
    if not lines:
        canvas.save(output_path)
        return
    line_height = 62
    total_height = len(lines) * line_height
    y = max(26, (390 - total_height) // 2)
    for line in lines:
        draw.text(
            (34, y),
            line,
            font=font,
            fill=WHITE,
            stroke_width=4,
            stroke_fill=(0, 0, 0, 220),
        )
        y += line_height
    canvas.save(output_path)


def _make_anchor_card(*, output_path: Path) -> None:
    """Temporary fallback presenter.

    It is intentionally kept completely still. Once a real green-screen or alpha
    presenter video is configured, that video replaces this fallback automatically.
    """
    source_path = output_path.with_suffix(".source.jpg")
    write_anchor_sample(source_path)
    with Image.open(source_path) as source:
        anchor = ImageOps.fit(source.convert("RGB"), (360, 570), method=Image.Resampling.LANCZOS)
    rounded = Image.new("RGBA", anchor.size, TRANSPARENT)
    mask = Image.new("L", anchor.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, anchor.width - 1, anchor.height - 1), radius=28, fill=255)
    rounded.paste(anchor.convert("RGBA"), (0, 0), mask)
    ImageDraw.Draw(rounded).rounded_rectangle(
        (1, 1, anchor.width - 2, anchor.height - 2),
        radius=28,
        outline=(255, 255, 255, 230),
        width=4,
    )
    rounded.save(output_path)
    source_path.unlink(missing_ok=True)


def _anchor_video_candidates() -> list[Path]:
    """Return reusable presenter gesture clips in stable filename order."""
    raw_dir = os.getenv("SHORTS_ANCHOR_VIDEO_DIR", "shorts/assets/anchors").strip() or "shorts/assets/anchors"
    directory = Path(raw_dir)
    if not directory.is_absolute():
        directory = Path(settings.BASE_DIR) / directory

    pattern = os.getenv("SHORTS_ANCHOR_VIDEO_PATTERN", "anchor_female_gesture_*.mp4").strip() or "anchor_female_gesture_*.mp4"
    if directory.exists():
        candidates = sorted(path for path in directory.glob(pattern) if path.is_file())
        if candidates:
            return candidates

    # Backward-compatible single-video fallback.
    raw = os.getenv("SHORTS_ANCHOR_VIDEO_PATH", "").strip()
    if raw:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = Path(settings.BASE_DIR) / candidate
        if candidate.exists():
            return [candidate]
    return []


def _configured_anchor_video(*, task_id: int) -> Path | None:
    candidates = _anchor_video_candidates()
    if not candidates:
        return None
    # Stable round-robin selection keeps retries deterministic while still rotating
    # gestures across consecutive publishing tasks.
    return candidates[(max(int(task_id), 1) - 1) % len(candidates)]


def generate_news_short(*, content, task_id: int) -> tuple[Path, str]:
    """Create a static-background 10-second vertical news Short."""
    if not content.representative_image:
        raise ShortsGenerationError("YouTube 쇼츠 생성에는 대표이미지가 필요합니다.")

    image_path = Path(content.representative_image.path)
    if not image_path.exists():
        raise ShortsGenerationError("대표이미지 파일을 찾을 수 없습니다.")

    output_dir = Path(settings.MEDIA_ROOT) / "shorts"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"youtube-short-{task_id}.mp4"
    script = _short_script(title=content.title, body=content.body)
    anchor_video_path = _configured_anchor_video(task_id=task_id)

    with tempfile.TemporaryDirectory(prefix="snsgrowup-short-") as temp_dir:
        temp_dir = Path(temp_dir)
        jpg_path = temp_dir / "source.jpg"
        speech_path = temp_dir / "speech.mp3"
        title_path = temp_dir / "title.png"
        caption_path = temp_dir / "caption.png"
        anchor_path = temp_dir / "anchor.png"

        _image_jpeg(image_path, jpg_path)
        _speech_mp3(text=script, output_path=speech_path)
        _make_title_bar(title=content.title, output_path=title_path)
        _make_caption(script=script, output_path=caption_path)
        if not anchor_video_path:
            _make_anchor_card(output_path=anchor_path)

        # Keep the article image completely still. Lanczos scaling preserves detail
        # better than the previous zoompan pipeline and avoids visible frame motion.
        background_filter = (
            "scale=1080:1920:force_original_aspect_ratio=increase:flags=lanczos,"
            "crop=1080:1920,setsar=1,format=yuv420p"
        )

        command = [
            "ffmpeg", "-y",
            "-framerate", "30", "-loop", "1", "-i", str(jpg_path),
            "-framerate", "30", "-loop", "1", "-i", str(title_path),
            "-framerate", "30", "-loop", "1", "-i", str(caption_path),
        ]

        if anchor_video_path:
            command += ["-i", str(anchor_video_path)]
            anchor_has_alpha = os.getenv("SHORTS_ANCHOR_HAS_ALPHA", "0").strip().lower() in {"1", "true", "yes", "on"}
            if anchor_has_alpha:
                anchor_filter = "[3:v]fps=30,scale=430:-1:flags=lanczos:force_original_aspect_ratio=decrease,format=rgba[anchor]"
            else:
                similarity = os.getenv("SHORTS_ANCHOR_CHROMA_SIMILARITY", "0.22").strip() or "0.22"
                blend = os.getenv("SHORTS_ANCHOR_CHROMA_BLEND", "0.08").strip() or "0.08"
                anchor_filter = (
                    f"[3:v]fps=30,scale=430:-1:flags=lanczos:force_original_aspect_ratio=decrease,"
                    f"chromakey=0x00FF00:{similarity}:{blend},format=rgba[anchor]"
                )
        else:
            command += ["-framerate", "30", "-loop", "1", "-i", str(anchor_path)]
            anchor_filter = "[3:v]format=rgba[anchor]"

        command += ["-i", str(speech_path)]

        filter_complex = (
            f"[0:v]{background_filter}[bg];"
            "[1:v]format=rgba[title];"
            "[2:v]format=rgba[caption];"
            f"{anchor_filter};"
            "[bg][title]overlay=0:0:format=auto[v1];"
            "[v1][caption]overlay=26:1110:format=auto[v2];"
            "[v2][anchor]overlay=W-w-24:H-h-30:format=auto[v]"
        )

        command += [
            "-filter_complex", filter_complex,
            "-map", "[v]", "-map", "4:a:0",
            "-t", "10",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k",
            "-af", "apad=pad_dur=10",
            "-movflags", "+faststart",
            str(output_path),
        ]
        process = subprocess.run(command, capture_output=True, text=True, timeout=240)
        if process.returncode != 0 or not output_path.exists():
            error = (process.stderr or process.stdout or "ffmpeg 실패")[-2600:]
            raise ShortsGenerationError(f"쇼츠 영상 생성 실패: {error}")

    return output_path, script
