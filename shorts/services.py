from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

import requests
from django.conf import settings
from openai import OpenAI
from PIL import Image


class ShortsGenerationError(RuntimeError):
    pass


def _short_script(*, title: str, body: str) -> str:
    """Generate a compact Korean voiceover intended to fit a 10-second Short."""
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


def generate_news_short(*, content, task_id: int) -> tuple[Path, str]:
    """Create a 10-second 1080x1920 MP4 with Korean TTS and gentle image motion."""
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
        _image_jpeg(image_path, jpg_path)
        _speech_mp3(text=script, output_path=speech_path)

        # 10-second vertical Short. The background slowly zooms and subtly pans.
        filter_complex = (
            "scale=1200:2134:force_original_aspect_ratio=increase,"
            "crop=1200:2134,"
            "zoompan=z='min(zoom+0.00045,1.10)':"
            "x='iw/2-(iw/zoom/2)+sin(on/35)*8':"
            "y='ih/2-(ih/zoom/2)+cos(on/42)*8':"
            "d=1:s=1080x1920:fps=30,"
            "format=yuv420p"
        )
        command = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", str(jpg_path),
            "-i", str(speech_path),
            "-filter_complex", f"[0:v]{filter_complex}[v]",
            "-map", "[v]", "-map", "1:a:0",
            "-t", "10",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-c:a", "aac", "-b:a", "128k",
            "-af", "apad=pad_dur=10",
            "-movflags", "+faststart",
            str(output_path),
        ]
        process = subprocess.run(command, capture_output=True, text=True, timeout=150)
        if process.returncode != 0 or not output_path.exists():
            error = (process.stderr or process.stdout or "ffmpeg 실패")[-1800:]
            raise ShortsGenerationError(f"쇼츠 영상 생성 실패: {error}")

    return output_path, script
