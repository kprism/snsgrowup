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


def _json_candidate(raw: str) -> str:
    text = (raw or "").strip().replace("```json", "").replace("```", "")
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("AI 성장 전략 응답에서 JSON 객체를 찾지 못했습니다.")
    text = text[start : end + 1]
    text = text.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    text = re.sub(r",\s*([}\]])", r"\1", text)
    return text


def _parse_json(raw: str) -> dict:
    candidate = _json_candidate(raw)
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError(f"AI 응답 JSON 형식 오류: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise ValueError("AI 성장 전략 응답이 JSON 객체가 아닙니다.")
    return data


def _repair_json(client: OpenAI, raw: str) -> dict:
    repair_prompt = f"""
아래 텍스트를 의미를 바꾸지 말고 유효한 JSON 객체 하나로만 복구하라.
마크다운, 설명, 코드펜스는 절대 출력하지 않는다.
문자열 안의 따옴표와 줄바꿈을 JSON 규칙에 맞게 이스케이프한다.

원문:
{raw[:12000]}
""".strip()
    repaired = client.responses.create(model=settings.OPENAI_MODEL, input=repair_prompt)
    return _parse_json(repaired.output_text)


def generate_growth_plan(
    *,
    profile_name: str,
    platform_name: str,
    content_samples: list[dict],
    requested_keyword: str = "",
) -> GrowthPlan:
    if not settings.OPENAI_API_KEY:
        raise ValueError("OpenAI API Key가 설정되지 않았습니다.")

    samples = "\n".join(
        f"- {item.get('title', '')}: {item.get('body', '')[:400]}"
        for item in content_samples[:15]
    ) or "- 분석할 게시 콘텐츠가 아직 없음"

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    prompt = f"""
너는 한국어 SNS 성장 전략가다. 사용자가 실제 등록한 채널은 {platform_name}이다.
아래 페이지명과 최근 콘텐츠 성향을 분석하여 같은 관심사를 가진 계정과 자연스럽게 교류하기 좋은 키워드와 오늘의 수동 실행 미션을 설계하라.
다른 SNS 플랫폼으로 이동시키지 말고 반드시 {platform_name} 안에서 수행할 작업만 제안한다.
자동 좋아요, 자동 팔로우, 자동 댓글 등 플랫폼 정책을 우회하는 행동은 제안하지 않는다.

페이지명: {profile_name}
사용자가 입력한 키워드: {requested_keyword or '없음'}
최근 콘텐츠:
{samples}

반드시 유효한 JSON 객체 하나만 반환한다. 마크다운과 설명을 출력하지 않는다.
형식:
{{
  "summary": "콘텐츠 성향 분석 요약",
  "keywords": ["키워드1", "키워드2", "키워드3", "키워드4", "키워드5"],
  "actions": [
    {{"type":"post", "title":"미션 제목", "reason":"추천 이유", "score":90, "comment":""}},
    {{"type":"like", "title":"미션 제목", "reason":"추천 이유", "score":85, "comment":""}},
    {{"type":"comment", "title":"미션 제목", "reason":"추천 이유", "score":80, "comment":"추천 댓글"}}
  ]
}}

규칙:
- keywords는 정확히 5개다.
- actions는 정확히 5개다.
- type은 post, like, comment, follow, story 중 하나다.
- score는 60부터 100 사이 정수다.
- 문자열 내부에 큰따옴표가 필요하면 반드시 이스케이프한다.
- 댓글은 게시물 맥락을 확인한 뒤 사용자가 수정할 수 있는 자연스러운 초안으로 작성한다.
""".strip()

    response = client.responses.create(model=settings.OPENAI_MODEL, input=prompt)
    try:
        data = _parse_json(response.output_text)
    except ValueError:
        data = _repair_json(client, response.output_text)

    keywords = [str(v).strip() for v in data.get("keywords", []) if str(v).strip()][:5]
    actions = data.get("actions") if isinstance(data.get("actions"), list) else []
    actions = [item for item in actions if isinstance(item, dict)][:5]
    if not keywords or not actions:
        raise ValueError("AI가 성장 키워드와 미션을 충분히 생성하지 못했습니다.")
    return GrowthPlan(
        keywords=keywords,
        actions=actions,
        summary=str(data.get("summary") or "").strip(),
    )
