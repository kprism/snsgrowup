from __future__ import annotations

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


def _short_script(*, title: str, body: str) -> str:
    fallback = re.sub(r"\s+", " ", (body or title).strip())[:70]
    if not settings.OPENAI_API_KEY:
        return fallback or title[:70]

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    prompt = f"""
다음 뉴스 기사로 10초짜리 유튜브 쇼츠 한국어 음성 멘트를 만들어라.
규칙:
- 1~2문장만 작성한다.
- 약 45~65자의 자연스러운 한국어로 쓴다.
- 사실을 추가하거나 과장하지 않는다.
- 인사말, 해시태그, 이모지, 따옴표를 넣지 않는다.
- 제목을 그대로 전부 반복하지 않는다.
- 결과는 멘트 본문만 출력한다.

제목: {title}
본문: {(body or '')[:3500]}
""".strip()
    try:
        response = client.responses.create(model=settings.OPENAI_MODEL, input=prompt)
        text = re.sub(r"\s+", " ", (response.output_text or "").strip())
        return text[:120] or fallback or title[:70]
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
            "instructions": "한국어 뉴스 아나운서처럼 또렷하고 차분하게, 약간 빠른 속도로 읽어주세요.",
            "response_format": "mp3",
            "speed": 1.12,
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
        image.save(output_path, format="JPEG", quality=94, optimize=True)


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
    canvas = Image.new("RGBA", (1080, 460), TRANSPARENT)
    draw = ImageDraw.Draw(canvas)
    font = _font(48)
    lines = _wrap_text(draw, script, font, 900, 3)
    if not lines:
        canvas.save(output_path)
        return
    line_height = 68
    total_height = len(lines) * line_height
    y = max(30, (460 - total_height) // 2)
    for line in lines:
        box = draw.textbbox((0, 0), line, font=font, stroke_width=4)
        width = box[2] - box[0]
        x = max(40, (1080 - width) // 2)
        draw.text(
            (x, y),
            line,
            font=font,
            fill=WHITE,
            stroke_width=4,
            stroke_fill=(0, 0, 0, 220),
        )
        y += line_height
    canvas.save(output_path)


def _make_anchor_card(*, output_path: Path) -> None:
    source_path = output_path.with_suffix(".source.jpg")
    write_anchor_sample(source_path)
    with Image.open(source_path) as source:
        anchor = ImageOps.fit(source.convert("RGB"), (360, 570), method=Image.Resampling.LANCZOS)
    rounded = Image.new("RGBA", anchor.size, TRANSPARENT)
    mask = Image.new("L", anchor.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, anchor.width - 1, anchor.height - 1), radius=28, fill=255)
    rounded.paste(anchor.convert("RGBA"), (0, 0), mask)
    border = ImageDraw.Draw(rounded)
    border.rounded_rectangle(
        (1, 1, anchor.width - 2, anchor.height - 2),
        radius=28,
        outline=(255, 255, 255, 230),
        width=4,
    )
    rounded.save(output_path)
    source_path.unlink(missing_ok=True)


def generate_news_short(*, content, task_id: int) -> tuple[Path, str]:
    """Create a 10-second vertical news Short with TTS, motion, title, captions and anchor."""
    if not content.representative_image:
        raise ShortsGenerationError("YouTube 쇼츠 생성에는 대표이미지가 필요합니다.")

    image_path = Path(content.representative_image.path)
    if not image_path.exists():
        raise ShortsGenerationError("대표이미지 파일을 찾을 수 없습니다.")

    output_dir = Path(settings.MEDIA_ROOT) / "shorts"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"youtube-short-{task_id}.mp4"
    script = _short_script(title=content.title, body=content.body)

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
        _make_anchor_card(output_path=anchor_path)

        background_filter = (
            "scale=1260:2240:force_original_aspect_ratio=increase,"
            "crop=1260:2240,"
            "zoompan=z='min(zoom+0.00065,1.18)':"
            "x='iw/2-(iw/zoom/2)+sin(on/24)*16':"
            "y='ih/2-(ih/zoom/2)+cos(on/31)*12':"
            "d=1:s=1080x1920:fps=30,"
            "format=yuv420p"
        )
        filter_complex = (
            f"[0:v]{background_filter}[bg];"
            "[1:v]format=rgba[title];"
            "[2:v]format=rgba[caption];"
            "[3:v]format=rgba[anchor];"
            "[bg][title]overlay=0:0:format=auto[v1];"
            "[v1][caption]overlay=0:350:format=auto[v2];"
            "[v2][anchor]overlay=W-w-36:H-h-54+4*sin(2*PI*t/3):format=auto[v]"
        )
        command = [
            "ffmpeg", "-y",
            "-framerate", "30", "-loop", "1", "-i", str(jpg_path),
            "-framerate", "30", "-loop", "1", "-i", str(title_path),
            "-framerate", "30", "-loop", "1", "-i", str(caption_path),
            "-framerate", "30", "-loop", "1", "-i", str(anchor_path),
            "-i", str(speech_path),
            "-filter_complex", filter_complex,
            "-map", "[v]", "-map", "4:a:0",
            "-t", "10",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-c:a", "aac", "-b:a", "128k",
            "-af", "apad=pad_dur=10",
            "-movflags", "+faststart",
            str(output_path),
        ]
        process = subprocess.run(command, capture_output=True, text=True, timeout=180)
        if process.returncode != 0 or not output_path.exists():
            error = (process.stderr or process.stdout or "ffmpeg 실패")[-2200:]
            raise ShortsGenerationError(f"쇼츠 영상 생성 실패: {error}")

    return output_path, script
