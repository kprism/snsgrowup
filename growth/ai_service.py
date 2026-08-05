from __future__ import annotations

import json
import re
from dataclasses import dataclass

from django.conf import settings
from openai import OpenAI


@dataclass
class GrowthPlan:
    keywords: list[str]
    actions: list[dict]
    summary: str


def _parse_json(raw: str) -> dict:
    raw = (raw or "").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise ValueError("AI 성장 전략 응답을 해석할 수 없습니다.")
        return json.loads(match.group(0))


def generate_growth_plan(*, profile_name: str, content_samples: list[dict], requested_keyword: str = "") -> GrowthPlan:
    if not settings.OPENAI_API_KEY:
        raise ValueError("OpenAI API Key가 설정되지 않았습니다.")

    samples = "\n".join(
        f"- {item.get('title', '')}: {item.get('body', '')[:400]}"
        for item in content_samples[:15]
    ) or "- 분석할 게시 콘텐츠가 아직 없음"

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    prompt = f"""
너는 한국어 SNS 페이지 성장 전략가다. 아래 Facebook 페이지명과 최근 콘텐츠 성향을 분석하여,
동종 관심사를 가진 계정과 자연스럽게 상호작용하기 좋은 성장 키워드와 오늘의 수동 실행 미션을 설계하라.
자동 좋아요, 자동 팔로우, 자동 댓글 등 플랫폼 정책을 우회하는 행동은 제안하지 않는다.
사용자가 직접 실행할 수 있도록 구체적이고 짧게 작성한다.

페이지명: {profile_name}
사용자가 입력한 키워드: {requested_keyword or '없음'}
최근 콘텐츠:
{samples}

반드시 JSON 객체 하나만 반환한다.
형식:
{{
  "summary": "콘텐츠 성향 분석 요약 1~2문장",
  "keywords": ["추천 키워드1", "추천 키워드2", "추천 키워드3", "추천 키워드4", "추천 키워드5"],
  "actions": [
    {{"type":"post|like|comment|follow|story", "title":"미션 제목", "reason":"추천 이유", "score":90, "comment":"댓글 미션일 때만 추천 댓글"}}
  ]
}}

규칙:
- keywords는 5개, 한국어 중심, 너무 넓지 않고 동종 관심사 계정을 찾기 쉬운 표현으로 작성한다.
- actions는 정확히 5개 작성한다.
- score는 60~100 사이 정수다.
- 같은 행동만 반복하지 않는다.
- 댓글은 홍보성·복붙 티가 나지 않게 콘텐츠 맥락을 확인한 뒤 사용할 수 있는 문장으로 작성한다.
""".strip()

    response = client.responses.create(model=settings.OPENAI_MODEL, input=prompt)
    data = _parse_json(response.output_text)
    keywords = [str(v).strip() for v in data.get("keywords", []) if str(v).strip()][:5]
    actions = data.get("actions") if isinstance(data.get("actions"), list) else []
    if not keywords or not actions:
        raise ValueError("AI가 성장 키워드와 미션을 충분히 생성하지 못했습니다.")
    return GrowthPlan(
        keywords=keywords,
        actions=actions[:5],
        summary=str(data.get("summary") or "").strip(),
    )
