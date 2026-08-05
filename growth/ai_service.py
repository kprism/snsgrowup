from __future__ import annotations

import json
import re
from dataclasses import dataclass

from django.conf import settings
from openai import OpenAI


@dataclass
class GrowthPlan:
    actions: list[dict]


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
) -> GrowthPlan:
    if not settings.OPENAI_API_KEY:
        raise ValueError("OpenAI API Key가 설정되지 않았습니다.")

    samples = "\n".join(
        f"- {item.get('title', '')}: {item.get('body', '')[:500]}"
        for item in content_samples[:20]
    ) or "- 분석할 게시 콘텐츠가 아직 없음"

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    prompt = f"""
너는 한국어 SNS 성장 전략가다. 실제 등록 채널은 {platform_name}이고 계정명은 {profile_name}이다.
최근 콘텐츠를 참고하여 오늘 수행할 수동 성장 미션 5개를 설계하라.
다른 SNS로 이동시키지 말고 반드시 {platform_name} 안에서 수행할 작업만 제안한다.
자동 좋아요, 자동 팔로우, 자동 댓글 등 정책을 우회하는 행동은 제안하지 않는다.

중요:
- 모든 미션은 서로 독립적이다.
- 각 미션마다 그 미션과 정확히 일치하는 search_keyword를 별도로 만든다.
- 질병 댓글 미션이면 질병명·보건 주제가 검색어에 반드시 들어가야 한다.
- 팔로우 미션이면 찾을 기관·업종·지역이 검색어에 들어가야 한다.
- 게시 미션이면 내 콘텐츠 중 무엇을 활용할지 찾기 쉬운 구체적 주제가 검색어에 들어가야 한다.
- story 미션은 내 관련 콘텐츠로 제작하도록 한다.
- '경남소식', '지역정보'처럼 지나치게 넓은 검색어를 반복 사용하지 않는다.

최근 콘텐츠:
{samples}

반드시 유효한 JSON 객체 하나만 반환한다. 마크다운과 설명은 출력하지 않는다.
형식:
{{
  "actions": [
    {{
      "type": "post|like|comment|follow|story",
      "title": "미션 제목",
      "reason": "추천 이유",
      "score": 90,
      "search_keyword": "이 미션만을 위한 구체적 검색어",
      "comment": "댓글 미션일 때만 추천 댓글"
    }}
  ]
}}

규칙:
- actions는 정확히 5개다.
- type은 post, like, comment, follow, story 중 하나다.
- score는 60부터 100 사이 정수다.
- search_keyword는 각 미션의 핵심 대상과 주제를 포함한 2~6어절이다.
- 같은 search_keyword를 두 미션에서 재사용하지 않는다.
- 댓글은 검색 결과의 실제 게시물 맥락을 확인한 뒤 사용자가 수정할 수 있는 자연스러운 초안이다.
""".strip()

    response = client.responses.create(model=settings.OPENAI_MODEL, input=prompt)
    try:
        data = _parse_json(response.output_text)
    except ValueError:
        data = _repair_json(client, response.output_text)

    actions = data.get("actions") if isinstance(data.get("actions"), list) else []
    actions = [item for item in actions if isinstance(item, dict)][:5]
    if len(actions) < 5:
        raise ValueError("AI가 미션 5개를 충분히 생성하지 못했습니다.")
    for item in actions:
        if not str(item.get("search_keyword") or "").strip():
            raise ValueError("AI가 미션별 검색키워드를 생성하지 못했습니다.")
    return GrowthPlan(actions=actions)
