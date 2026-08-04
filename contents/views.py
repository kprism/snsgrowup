from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .forms import ContentItemForm
from .models import ContentItem


@login_required
def content_list(request):
    items = ContentItem.objects.filter(owner=request.user).order_by("-created_at")
    return render(request, "contents/content_list.html", {"items": items})


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
