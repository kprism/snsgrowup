from __future__ import annotations

import json
import re
from dataclasses import dataclass

from django.conf import settings
from openai import OpenAI


@dataclass
class AIPostDraft:
    message: str
    tags: list[str]

    @property
    def hashtag_text(self) -> str:
        return " ".join(f"#{tag.lstrip('#').strip()}" for tag in self.tags if tag.strip())


def _normalize_tags(values) -> list[str]:
    tags: list[str] = []
    for value in values or []:
        tag = re.sub(r"[^0-9A-Za-z가-힣_]", "", str(value).lstrip("#").strip())
        if tag and tag not in tags:
            tags.append(tag)
        if len(tags) >= 8:
            break
    return tags


def generate_facebook_post(*, title: str, body: str, source_url: str = "") -> AIPostDraft:
    if not settings.OPENAI_API_KEY:
        raise ValueError("OpenAI API Key가 설정되지 않았습니다.")

    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    prompt = f"""
다음 한국어 뉴스 기사를 Facebook 페이지용 게시문으로 바꿔라.

규칙:
- 사실관계를 추가하거나 과장하지 않는다.
- 핵심 내용을 자연스럽고 읽기 쉽게 3~6문장으로 작성한다.
- 제목을 그대로 반복하지 않는다.
- 불필요한 인사말과 광고성 표현을 쓰지 않는다.
- 마지막 문장은 독자의 관심을 유도하되 억지 질문은 피한다.
- 기사와 직접 관련된 한국어 태그를 5~8개 추천한다.
- 태그에는 # 문자를 넣지 않는다.
- 반드시 JSON 객체 하나만 반환한다.

반환 형식:
{{"message":"게시문","tags":["태그1","태그2"]}}

제목: {title}
본문: {body[:6000]}
원문 URL: {source_url}
""".strip()

    response = client.responses.create(
        model=settings.OPENAI_MODEL,
        input=prompt,
    )
    raw = (response.output_text or "").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise ValueError("AI 응답을 해석할 수 없습니다.")
        data = json.loads(match.group(0))

    message = str(data.get("message") or "").strip()
    tags = _normalize_tags(data.get("tags"))
    if not message:
        raise ValueError("AI가 게시문을 생성하지 못했습니다.")
    return AIPostDraft(message=message, tags=tags)
