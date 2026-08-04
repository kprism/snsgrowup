from celery import shared_task

from .models import PressProfile
from .services import collect_feed


@shared_task(bind=True)
def collect_rss_task(self, profile_id: int, user_id: int):
    profile = PressProfile.objects.select_related("user").get(pk=profile_id, user_id=user_id)

    def report(current: int, total: int, message: str):
        percent = round((current / total) * 100) if total else 0
        self.update_state(
            state="PROGRESS",
            meta={
                "current": current,
                "total": total,
                "percent": percent,
                "message": message,
            },
        )

    result = collect_feed(profile, progress_callback=report)
    return {
        "current": 1,
        "total": 1,
        "percent": 100,
        "message": "RSS 수집이 완료되었습니다.",
        "created": result.created,
        "skipped": result.skipped,
        "failed": result.failed,
        "feed_title": result.feed_title,
    }
