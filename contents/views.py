from io import BytesIO

from PIL import Image
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from publishing.models import AutomationSetting, PublishingBatch
from publishing.services import create_publishing_batch, enqueue_batch_tasks
from social_channels.models import SocialAccount

from .ai_service import generate_facebook_post
from .forms import ContentItemForm
from .models import ContentItem


PREVIEW_SESSION_KEY = "publishing_preview_selection"
BULK_DELETE_ACTION = "delete"
QUICK_PUBLISH_COMMAND = "quick_publish"


def _selected_objects(*, user, content_ids, channel_ids):
    contents = ContentItem.objects.filter(owner=user, pk__in=content_ids).order_by("-created_at")
    channels = SocialAccount.objects.filter(user=user, is_active=True, pk__in=channel_ids).select_related("platform")
    return contents, channels


def _delete_selected_contents(*, user, content_ids) -> int:
    selected = list(ContentItem.objects.filter(owner=user, pk__in=content_ids))
    for item in selected:
        if item.representative_image:
            item.representative_image.delete(save=False)
        item.delete()
    return len(selected)


def _absolute_image_url(request, content):
    if not content.representative_image:
        return ""
    from django.conf import settings
    token = signing.TimestampSigner(salt="instagram-media").sign(str(content.pk))
    path = reverse("contents:instagram_media", kwargs={"pk": content.pk, "token": token})
    base = getattr(settings, "PUBLIC_BASE_URL", "").strip().rstrip("/")
    if base:
        return f"{base}{path}"
    return request.build_absolute_uri(path)


def instagram_media(request, pk, token):
    """Public, short-lived JPEG endpoint so Meta can fetch an RSS image."""
    try:
        signed_pk = signing.TimestampSigner(salt="instagram-media").unsign(token, max_age=3600)
    except signing.BadSignature:
        return HttpResponse(status=404)
    if str(pk) != str(signed_pk):
        return HttpResponse(status=404)

    content = get_object_or_404(ContentItem, pk=pk)
    if not content.representative_image:
        return HttpResponse(status=404)

    try:
        with Image.open(content.representative_image.path) as source:
            image = source.convert("RGB")
            output = BytesIO()
            image.save(output, format="JPEG", quality=92, optimize=True)
    except Exception:
        return HttpResponse(status=404)

    response = HttpResponse(output.getvalue(), content_type="image/jpeg")
    response["Cache-Control"] = "public, max-age=3600"
    response["Content-Disposition"] = f'inline; filename="instagram-{content.pk}.jpg"'
    return response


def _quick_publish_payloads(*, request, owner, contents, channels):
    setting, _ = AutomationSetting.objects.get_or_create(owner=owner)
    payloads = {}
    ai_fallbacks = 0

    for content in contents:
        message = content.body.strip() or content.title
        hashtags = ""
        if setting.use_ai:
            try:
                draft = generate_facebook_post(title=content.title, body=content.body, source_url=content.source_url)
                message = draft.message.strip() or message
                if setting.auto_tags:
                    hashtags = draft.hashtag_text.strip()
            except Exception:
                ai_fallbacks += 1

        for channel in channels:
            platform = channel.platform.code
            payload = {
                "title": content.title,
                "message": message,
                "hashtags": hashtags,
                "include_link": bool(content.source_url) if platform == "facebook" else False,
                "include_image": bool(content.representative_image),
                "link": content.source_url or "",
                "image": _absolute_image_url(request, content) if content.representative_image else "",
                "quick_publish": True,
                "platform": platform,
                "youtube_mode": "short" if platform == "youtube" else "",
            }
            payloads[(content.pk, channel.pk)] = payload
    return payloads, ai_fallbacks


@login_required
def content_list(request):
    items = ContentItem.objects.filter(owner=request.user).order_by("-created_at")
    channels = SocialAccount.objects.filter(user=request.user, is_active=True).select_related("platform")

    if request.method == "POST":
        content_ids = request.POST.getlist("content_ids")
        channel_ids = request.POST.getlist("channel_ids")
        action = request.POST.get("action", "")
        command = request.POST.get("command", "")

        if not content_ids:
            messages.error(request, "작업할 콘텐츠를 한 건 이상 선택해 주세요.")
            return redirect("contents:content_list")

        if action == BULK_DELETE_ACTION:
            deleted_count = _delete_selected_contents(user=request.user, content_ids=content_ids)
            messages.success(request, f"선택한 콘텐츠 {deleted_count}건을 삭제했습니다.")
            return redirect("contents:content_list")

        selected_contents, selected_channels = _selected_objects(user=request.user, content_ids=content_ids, channel_ids=channel_ids)

        if not selected_channels.exists():
            messages.error(request, "발행할 SNS 채널을 한 개 이상 선택해 주세요.")
        elif command == QUICK_PUBLISH_COMMAND:
            unsupported = selected_channels.exclude(platform__code__in=["facebook", "instagram", "youtube"])
            if unsupported.exists():
                messages.error(request, "AI 바로 게시는 현재 Facebook, Instagram, YouTube 연결 채널을 지원합니다.")
                return redirect("contents:content_list")
            image_required = selected_channels.filter(platform__code__in=["instagram", "youtube"]).exists()
            if image_required and selected_contents.filter(representative_image="").exists():
                messages.error(request, "Instagram 게시와 YouTube 쇼츠 생성에는 대표이미지가 필요합니다. 대표이미지가 없는 콘텐츠를 제외해 주세요.")
                return redirect("contents:content_list")
            task_payloads, ai_fallbacks = _quick_publish_payloads(
                request=request,
                owner=request.user,
                contents=list(selected_contents),
                channels=list(selected_channels),
            )
            batch = create_publishing_batch(
                owner=request.user,
                contents=selected_contents,
                channels=selected_channels,
                action=PublishingBatch.Action.UPLOAD,
                task_payloads=task_payloads,
            )
            queued = enqueue_batch_tasks(batch=batch)
            if queued:
                message = f"선택한 콘텐츠 {queued}건을 채널별 AI 처리 후 랜덤 발행 Queue에 등록했습니다."
                if selected_channels.filter(platform__code="youtube").exists():
                    message += " YouTube는 10초 한국어 음성 쇼츠를 자동 생성해 비공개 테스트 업로드합니다."
                if ai_fallbacks:
                    message += f" AI 생성에 실패한 {ai_fallbacks}건은 원문으로 등록했습니다."
                messages.success(request, message)
                return redirect("publishing:publish_result", pk=batch.pk)
            messages.warning(request, "Queue에 등록할 수 있는 SNS 작업이 없습니다. 채널 연결 상태를 확인해 주세요.")
            return redirect("publishing:batch_detail", pk=batch.pk)
        elif action not in PublishingBatch.Action.values:
            messages.error(request, "실행할 작업을 선택해 주세요.")
        elif action == PublishingBatch.Action.UPLOAD and selected_channels.filter(platform__code="facebook").exists():
            request.session[PREVIEW_SESSION_KEY] = {
                "content_ids": list(selected_contents.values_list("pk", flat=True)),
                "channel_ids": list(selected_channels.values_list("pk", flat=True)),
                "action": action,
            }
            request.session.modified = True
            return redirect("contents:facebook_preview")
        else:
            batch = create_publishing_batch(owner=request.user, contents=selected_contents, channels=selected_channels, action=action)
            messages.success(request, f"{batch.get_action_display()} 작업 {batch.tasks.count()}건이 생성되었습니다.")
            return redirect("publishing:batch_detail", pk=batch.pk)

    action_choices = list(PublishingBatch.Action.choices) + [(BULK_DELETE_ACTION, "선택 콘텐츠 삭제")]
    return render(request, "contents/content_list.html", {"items": items, "channels": channels, "action_choices": action_choices})


@login_required
@require_POST
def ai_facebook_draft(request):
    selection = request.session.get(PREVIEW_SESSION_KEY) or {}
    allowed_ids = {str(value) for value in selection.get("content_ids") or []}
    content_id = str(request.POST.get("content_id") or "")
    if not content_id or content_id not in allowed_ids:
        return JsonResponse({"ok": False, "message": "AI 생성 대상 콘텐츠가 아닙니다."}, status=400)

    content = get_object_or_404(ContentItem, pk=content_id, owner=request.user)
    try:
        draft = generate_facebook_post(title=content.title, body=content.body, source_url=content.source_url)
    except Exception as exc:
        return JsonResponse({"ok": False, "message": str(exc)}, status=400)

    return JsonResponse({"ok": True, "content_id": content.pk, "message": draft.message, "tags": draft.tags, "hashtag_text": draft.hashtag_text})


@login_required
def facebook_preview(request):
    selection = request.session.get(PREVIEW_SESSION_KEY) or {}
    content_ids = selection.get("content_ids") or []
    channel_ids = selection.get("channel_ids") or []
    action = selection.get("action")

    contents, channels = _selected_objects(user=request.user, content_ids=content_ids, channel_ids=channel_ids)
    facebook_channels = channels.filter(platform__code="facebook")

    if action != PublishingBatch.Action.UPLOAD or not contents.exists() or not channels.exists() or not facebook_channels.exists():
        messages.warning(request, "미리보기 선택 정보가 없거나 만료되었습니다. 콘텐츠를 다시 선택해 주세요.")
        return redirect("contents:content_list")

    if request.method == "POST":
        if request.POST.get("command") == "cancel":
            request.session.pop(PREVIEW_SESSION_KEY, None)
            request.session.modified = True
            return redirect("contents:content_list")

        publish_content_ids = request.POST.getlist("publish_content_ids")
        selected_contents = contents.filter(pk__in=publish_content_ids)
        if not selected_contents.exists():
            messages.error(request, "게시할 콘텐츠를 한 건 이상 선택해 주세요.")
            return render(request, "contents/facebook_preview.html", {"contents": contents, "channels": channels, "facebook_channels": facebook_channels})

        common_hashtags = request.POST.get("hashtags", "").strip()
        task_payloads = {}
        for content in selected_contents:
            message = request.POST.get(f"message_{content.pk}", content.body).strip()
            include_link = request.POST.get(f"include_link_{content.pk}") == "on"
            include_image = request.POST.get(f"include_image_{content.pk}") == "on"
            entered_tags = request.POST.get(f"tags_{content.pk}", "").strip()
            recommended_tags = request.POST.get(f"recommended_tags_{content.pk}", "").strip()
            hashtags = entered_tags or common_hashtags or recommended_tags
            payload = {
                "title": content.title,
                "message": message,
                "hashtags": hashtags,
                "include_link": include_link,
                "include_image": include_image,
                "link": content.source_url if include_link else "",
                "image": content.representative_image.url if include_image and content.representative_image else "",
            }
            for channel in channels:
                task_payloads[(content.pk, channel.pk)] = payload.copy()

        batch = create_publishing_batch(owner=request.user, contents=selected_contents, channels=channels, action=action, task_payloads=task_payloads)
        queued = enqueue_batch_tasks(batch=batch)

        request.session.pop(PREVIEW_SESSION_KEY, None)
        request.session.modified = True
        if queued:
            messages.success(request, f"Facebook 콘텐츠 {queued}건을 랜덤 간격 발행 Queue에 등록했습니다.")
        else:
            messages.warning(request, "Queue에 등록할 수 있는 Facebook 작업이 없습니다. 채널 연결 상태를 확인해 주세요.")
        return redirect("publishing:publish_result", pk=batch.pk)

    return render(request, "contents/facebook_preview.html", {"contents": contents, "channels": channels, "facebook_channels": facebook_channels})


@login_required
def content_create(request):
    if request.method == "POST":
        form = ContentItemForm(request.POST, request.FILES)
        if form.is_valid():
            item = form.save(commit=False)
            item.owner = request.user
            item.source_type = ContentItem.SourceType.DIRECT
            item.save()
            messages.success(request, "콘텐츠가 저장되었습니다.")
            return redirect("contents:content_list")
    else:
        form = ContentItemForm()
    return render(request, "contents/content_form.html", {"form": form, "item": None})


@login_required
def content_update(request, pk):
    item = get_object_or_404(ContentItem, pk=pk, owner=request.user)
    if request.method == "POST":
        form = ContentItemForm(request.POST, request.FILES, instance=item)
        if form.is_valid():
            form.save()
            messages.success(request, "콘텐츠가 수정되었습니다.")
            return redirect("contents:content_list")
    else:
        form = ContentItemForm(instance=item)
    return render(request, "contents/content_form.html", {"form": form, "item": item})


@login_required
def content_delete(request, pk):
    item = get_object_or_404(ContentItem, pk=pk, owner=request.user)
    if request.method == "POST":
        if item.representative_image:
            item.representative_image.delete(save=False)
        item.delete()
        messages.success(request, "콘텐츠가 삭제되었습니다.")
        return redirect("contents:content_list")
    return render(request, "contents/content_confirm_delete.html", {"item": item})
