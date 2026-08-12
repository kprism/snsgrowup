from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from contents.models import ContentItem
from shorts.services import ShortsGenerationError, generate_news_short

from .models import GrowthAction


@login_required
@require_POST
def generate_instagram_news_reel(request, pk: int, content_pk: int):
    """Create an Instagram Reel with the same anchor/TTS/news renderer used by YouTube Shorts."""
    action = get_object_or_404(
        GrowthAction,
        pk=pk,
        owner=request.user,
        platform="instagram",
        action_type=GrowthAction.ActionType.POST,
    )
    content = get_object_or_404(ContentItem, pk=content_pk, owner=request.user)

    if not content.representative_image:
        messages.error(request, "AI 뉴스 릴스 제작에는 대표이미지가 필요합니다.")
        return redirect("growth:prepare_action", pk=action.pk)

    # generate_news_short() already contains the stable production pipeline:
    # article image + title bar + Korean TTS + captions + chroma-key anchor
    # + multi-gesture anchor sequence matched to the narration duration.
    render_id = (int(action.pk) * 1_000_000) + int(content.pk)

    try:
        rendered_path, _script = generate_news_short(content=content, task_id=render_id)
    except ShortsGenerationError as exc:
        messages.error(request, f"AI 뉴스 릴스 제작에 실패했습니다: {exc}")
        return redirect("growth:prepare_action", pk=action.pk)
    except Exception as exc:
        messages.error(request, f"AI 뉴스 릴스 제작 중 오류가 발생했습니다: {exc}")
        return redirect("growth:prepare_action", pk=action.pk)

    if not rendered_path.exists() or rendered_path.stat().st_size < 1024:
        messages.error(request, "AI 뉴스 릴스 영상 파일이 정상적으로 생성되지 않았습니다.")
        return redirect("growth:prepare_action", pk=action.pk)

    export_dir = Path(settings.MEDIA_ROOT) / "instagram_reels" / str(request.user.pk)
    export_dir.mkdir(parents=True, exist_ok=True)
    export_path = export_dir / f"instagram-reel-{content.pk}-{uuid.uuid4().hex[:8]}.mp4"
    shutil.copy2(rendered_path, export_path)

    if action.status != GrowthAction.Status.COMPLETED:
        action.status = GrowthAction.Status.STARTED
        action.started_at = timezone.now()
        action.save(update_fields=["status", "started_at"])

    return FileResponse(
        open(export_path, "rb"),
        as_attachment=True,
        filename=f"SNSGROWUP_instagram_reel_{content.pk}.mp4",
        content_type="video/mp4",
    )
