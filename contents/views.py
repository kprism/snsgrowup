from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from publishing.models import PublishingBatch
from publishing.services import create_publishing_batch
from social_channels.models import SocialAccount

from .forms import ContentItemForm
from .models import ContentItem


PREVIEW_SESSION_KEY = "publishing_preview_selection"
BULK_DELETE_ACTION = "delete"


def _selected_objects(*, user, content_ids, channel_ids):
    contents = ContentItem.objects.filter(owner=user, pk__in=content_ids).order_by("-created_at")
    channels = SocialAccount.objects.filter(
        user=user,
        is_active=True,
        pk__in=channel_ids,
    ).select_related("platform")
    return contents, channels


def _delete_selected_contents(*, user, content_ids) -> int:
    selected = list(ContentItem.objects.filter(owner=user, pk__in=content_ids))
    for item in selected:
        if item.representative_image:
            item.representative_image.delete(save=False)
        item.delete()
    return len(selected)


@login_required
def content_list(request):
    items = ContentItem.objects.filter(owner=request.user).order_by("-created_at")
    channels = SocialAccount.objects.filter(user=request.user, is_active=True).select_related("platform")

    if request.method == "POST":
        content_ids = request.POST.getlist("content_ids")
        channel_ids = request.POST.getlist("channel_ids")
        action = request.POST.get("action", "")

        if not content_ids:
            messages.error(request, "작업할 콘텐츠를 한 건 이상 선택해 주세요.")
            return redirect("contents:content_list")

        if action == BULK_DELETE_ACTION:
            deleted_count = _delete_selected_contents(user=request.user, content_ids=content_ids)
            messages.success(request, f"선택한 콘텐츠 {deleted_count}건을 삭제했습니다.")
            return redirect("contents:content_list")

        selected_contents, selected_channels = _selected_objects(
            user=request.user,
            content_ids=content_ids,
            channel_ids=channel_ids,
        )

        if not selected_channels.exists():
            messages.error(request, "발행할 SNS 채널을 한 개 이상 선택해 주세요.")
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
            batch = create_publishing_batch(
                owner=request.user,
                contents=selected_contents,
                channels=selected_channels,
                action=action,
            )
            messages.success(
                request,
                f"{batch.get_action_display()} 작업 {batch.tasks.count()}건이 생성되었습니다.",
            )
            return redirect("publishing:batch_detail", pk=batch.pk)

    action_choices = list(PublishingBatch.Action.choices) + [
        (BULK_DELETE_ACTION, "선택 콘텐츠 삭제"),
    ]
    return render(
        request,
        "contents/content_list.html",
        {
            "items": items,
            "channels": channels,
            "action_choices": action_choices,
        },
    )


@login_required
def facebook_preview(request):
    selection = request.session.get(PREVIEW_SESSION_KEY) or {}
    content_ids = selection.get("content_ids") or []
    channel_ids = selection.get("channel_ids") or []
    action = selection.get("action")

    contents, channels = _selected_objects(
        user=request.user,
        content_ids=content_ids,
        channel_ids=channel_ids,
    )
    facebook_channels = channels.filter(platform__code="facebook")

    if action != PublishingBatch.Action.UPLOAD or not contents.exists() or not channels.exists() or not facebook_channels.exists():
        messages.warning(request, "미리보기 선택 정보가 없거나 만료되었습니다. 콘텐츠를 다시 선택해 주세요.")
        return redirect("contents:content_list")

    if request.method == "POST":
        if request.POST.get("command") == "cancel":
            request.session.pop(PREVIEW_SESSION_KEY, None)
            request.session.modified = True
            return redirect("contents:content_list")

        hashtags = request.POST.get("hashtags", "").strip()
        task_payloads = {}
        for content in contents:
            message = request.POST.get(f"message_{content.pk}", content.body).strip()
            include_link = request.POST.get(f"include_link_{content.pk}") == "on"
            include_image = request.POST.get(f"include_image_{content.pk}") == "on"
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

        batch = create_publishing_batch(
            owner=request.user,
            contents=contents,
            channels=channels,
            action=action,
            task_payloads=task_payloads,
        )
        request.session.pop(PREVIEW_SESSION_KEY, None)
        request.session.modified = True
        messages.success(request, f"Facebook 게시 미리보기를 반영한 작업 {batch.tasks.count()}건이 생성되었습니다.")
        return redirect("publishing:batch_detail", pk=batch.pk)

    return render(
        request,
        "contents/facebook_preview.html",
        {
            "contents": contents,
            "channels": channels,
            "facebook_channels": facebook_channels,
        },
    )


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
