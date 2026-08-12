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


def _platform_strategy(platform_code: str, platform_name: str) -> str:
    if platform_code == "instagram":
        return f"""
플랫폼은 {platform_name}이다. Facebook식 페이지·그룹 탐색 전략을 절대 사용하지 않는다.
Instagram의 핵심은 비팔로워 도달, Reels, 저장·공유, 프로필 방문, 댓글 관계 형성이다.

미션 구성 원칙:
- post: 최근 콘텐츠 중 Instagram에서 반응 가능성이 높은 주제를 골라 피드 또는 Reel 후보로 제안한다.
- story: 최근 게시/기사 중 Story 재노출에 적합한 주제를 제안한다.
- comment: 관련 키워드의 상위 게시물/계정을 사용자가 직접 방문해 맥락을 확인한 뒤 남길 댓글 초안을 만든다.
- like: 관련 키워드의 상위 게시물 1~5위를 직접 확인하도록 안내한다. 자동 좋아요는 제안하지 않는다.
- follow: 관련 키워드의 상위 계정 1~5위를 직접 확인하고 실제 관련성이 있을 때만 팔로우를 검토하도록 한다.
- '공공기관 10곳 팔로우', '그룹 가입', '페이지 좋아요' 같은 Facebook식 대량 미션은 금지한다.
- 검색 결과를 실제 API로 확보하지 못한 상태에서 특정 계정명·순위·팔로워 수를 지어내지 않는다.
- 사용자가 Instagram에서 직접 실행할 행동과 SNSGROWUP이 자동 준비할 콘텐츠/댓글 초안을 구분한다.
""".strip()
    if platform_code == "facebook":
        return """
플랫폼은 Facebook이다. 페이지, 그룹, 게시물, 지역 기관·사람과의 관계 형성, 공유 가능한 게시물을 중심으로 미션을 만든다.
페이지/그룹/게시물 검색을 활용할 수 있고, 좋아요·댓글·팔로우 등 실제 행동은 사용자가 직접 수행하도록 한다.
""".strip()
    if platform_code == "youtube":
        return """
플랫폼은 YouTube이다. Shorts 주제 선정, 제목·키워드 개선, 시청지속시간, 댓글 응답, 구독 전환에 초점을 둔다.
Facebook 페이지/그룹/팔로우 미션은 만들지 않는다.
""".strip()
    if platform_code == "threads":
        return """
플랫폼은 Threads이다. 첫 문장 Hook, 짧은 연속 게시, 답글 대화, 관련 주제 검색과 대화 참여에 초점을 둔다.
Facebook 페이지/그룹 미션은 만들지 않는다.
""".strip()
    return f"플랫폼은 {platform_name}이다. 해당 플랫폼 고유의 성장 방식만 사용한다."


def generate_growth_plan(
    *,
    profile_name: str,
    platform_name: str,
    platform_code: str,
    content_samples: list[dict],
) -> GrowthPlan:
    if not settings.OPENAI_API_KEY:
        raise ValueError("OpenAI API Key가 설정되지 않았습니다.")

    samples = "\n".join(
        f"- {item.get('title', '')}: {item.get('body', '')[:500]}"
        for item in content_samples[:20]
    ) or "- 분석할 게시 콘텐츠가 아직 없음"

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    strategy = _platform_strategy(platform_code, platform_name)
    prompt = f"""
너는 한국어 SNS 성장 전략가다. 실제 등록 채널은 {platform_name}이고 계정명은 {profile_name}이다.
최근 콘텐츠를 참고하여 오늘 수행할 성장 미션 5개를 설계하라.
다른 SNS로 이동시키지 말고 반드시 {platform_name} 안에서 수행할 작업만 제안한다.
자동 좋아요, 자동 팔로우, 자동 댓글, 무차별 DM, 정책 우회 행동은 제안하지 않는다.

플랫폼 전용 전략:
{strategy}

공통 규칙:
- 모든 미션은 서로 독립적이다.
- 각 미션마다 정확히 일치하는 search_keyword를 별도로 만든다.
- 게시 미션은 내 콘텐츠 중 무엇을 활용할지 찾기 쉬운 구체적 주제를 검색어에 넣는다.
- 댓글/좋아요/팔로우 미션은 사용자가 검색 결과를 직접 확인한 뒤 실행하는 수동 관계 행동이다.
- 실제 검색 결과를 받지 않았으므로 존재하지 않는 계정명, 순위, 수치, 성과를 만들지 않는다.
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
- 댓글 초안은 검색 결과의 실제 맥락을 확인한 뒤 사용자가 수정할 수 있는 자연스러운 문장으로 만든다.
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
