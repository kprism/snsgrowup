from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from publishing.models import PublishingBatch
from publishing.services import create_publishing_batch
from social_channels.models import SocialAccount

from .forms import ContentItemForm
from .models import ContentItem


@login_required
def content_list(request):
    items = ContentItem.objects.filter(owner=request.user).order_by("-created_at")
    channels = SocialAccount.objects.filter(user=request.user, is_active=True).select_related("platform")

    if request.method == "POST":
        content_ids = request.POST.getlist("content_ids")
        channel_ids = request.POST.getlist("channel_ids")
        action = request.POST.get("action", "")

        selected_contents = ContentItem.objects.filter(owner=request.user, pk__in=content_ids)
        selected_channels = SocialAccount.objects.filter(user=request.user, is_active=True, pk__in=channel_ids)

        if not selected_contents.exists():
            messages.error(request, "작업할 콘텐츠를 한 건 이상 선택해 주세요.")
        elif not selected_channels.exists():
            messages.error(request, "발행할 SNS 채널을 한 개 이상 선택해 주세요.")
        elif action not in PublishingBatch.Action.values:
            messages.error(request, "실행할 작업을 선택해 주세요.")
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

    return render(
        request,
        "contents/content_list.html",
        {
            "items": items,
            "channels": channels,
            "action_choices": PublishingBatch.Action.choices,
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
        item.delete()
        messages.success(request, "콘텐츠가 삭제되었습니다.")
        return redirect("contents:content_list")
    return render(request, "contents/content_confirm_delete.html", {"item": item})
