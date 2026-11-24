import asyncio
import json
import logging
import re
from typing import Any

import httpx

from app.config import Settings
from app.schemas import ParsedQuery

logger = logging.getLogger(__name__)

QUERY_PARSE_SYSTEM_PROMPT = """Extract structured prospect search parameters from the user's natural-language query.
Return a single valid JSON object only, with no markdown fences:
{
  "interest": "core topic, sport, industry, or niche (e.g. Football, Digital Marketing, Startups, Cricket, Restaurants)",
  "audience": "target persona phrase (e.g. Football lovers, Digital marketing agency owners)",
  "location": {
    "city": "city name or null",
    "state": "state/province/region if known or null",
    "country": "country name or null"
  },
  "target_type": "individual or business",
  "keywords": ["2 to 4 concise search keywords related to role or interest"]
}
Set "target_type" to "business" when searching for business/agency/restaurant owners or companies, otherwise "individual"."""

RELEVANCE_SYSTEM_PROMPT = """You evaluate public web/social profile candidates discovered for a prospect search query.
Strict rules:
1. Never invent names, URLs, emails, phone numbers, or locations.
2. Mark "relevant": false for listicles ("Top 10...", "Best..."), news articles, job boards, directories, or profiles clearly unrelated to both the target interest/audience and location.
3. Extract a clean person or business "name" from the provided candidate title/snippet only.
4. Set "location" only when supported by the candidate snippet/title or query context; use "" if uncertain.
5. Return raw JSON only:
{
  "decisions": [
    {
      "index": 0,
      "relevant": true,
      "score": 0.85,
      "name": "Clean Name",
      "location": "City, Country"
    }
  ]
}"""


class LLMServiceError(RuntimeError):
    """Raised when LLM requests fail across all configured providers."""


def parse_json_dict(raw_text: str) -> dict[str, Any]:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            obj = json.loads(cleaned[start : end + 1])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError as exc:
            raise LLMServiceError("Malformed JSON returned by LLM.") from exc

    raise LLMServiceError("No JSON object found in LLM output.")


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def has_configured_key(self) -> bool:
        return bool(self.settings.gemini_api_key.strip() or self.settings.openai_api_key.strip())

    async def parse_search_query(self, raw_query: str) -> ParsedQuery:
        data = await self._complete_json(
            system_prompt=QUERY_PARSE_SYSTEM_PROMPT,
            user_prompt=f"Query: {raw_query}",
        )
        t_type = str(data.get("target_type", "individual")).strip().lower()
        if t_type not in ("individual", "business"):
            t_type = "individual"
        data["target_type"] = t_type
        if not isinstance(data.get("location"), dict):
            data["location"] = {}
        return ParsedQuery.model_validate(data)

    async def evaluate_candidates(
        self,
        raw_query: str,
        parsed_query: ParsedQuery,
        candidates_payload: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not candidates_payload:
            return []
        prompt_obj = {
            "search_query": raw_query,
            "expected_interest": parsed_query.interest,
            "expected_audience": parsed_query.audience,
            "expected_location": parsed_query.location.display_label(),
            "candidates": candidates_payload,
        }
        data = await self._complete_json(
            system_prompt=RELEVANCE_SYSTEM_PROMPT,
            user_prompt=json.dumps(prompt_obj, ensure_ascii=False),
        )
        decisions = data.get("decisions")
        return decisions if isinstance(decisions, list) else []

    async def _complete_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        providers = self._provider_order()
        if not providers:
            raise LLMServiceError(
                "Missing LLM credentials. Configure GEMINI_API_KEY or OPENAI_API_KEY in .env."
            )

        last_err: Exception | None = None
        for provider in providers:
            try:
                if provider == "gemini":
                    raw = await self._call_gemini(system_prompt, user_prompt)
                else:
                    raw = await self._call_openai(system_prompt, user_prompt)
                return parse_json_dict(raw)
            except Exception as exc:
                logger.warning("Provider '%s' call failed: %s", provider, exc)
                last_err = exc

        raise LLMServiceError(f"All configured LLM providers failed: {last_err}")

    def _provider_order(self) -> list[str]:
        preferred = self.settings.llm_provider.strip().lower()
        order: list[str] = []
        if preferred == "openai":
            if self.settings.openai_api_key.strip():
                order.append("openai")
            if self.settings.gemini_api_key.strip():
                order.append("gemini")
        else:
            if self.settings.gemini_api_key.strip():
                order.append("gemini")
            if self.settings.openai_api_key.strip():
                order.append("openai")
        return order

    async def _call_gemini(self, system_prompt: str, user_prompt: str) -> str:
        model = self.settings.gemini_model.strip() or "gemini-2.5-flash"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        body = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
            },
        }
        data = await self._post_json(
            url=url,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.settings.gemini_api_key.strip(),
            },
            body=body,
        )
        candidates = data.get("candidates") or []
        if not candidates:
            raise LLMServiceError("Gemini returned empty candidates.")
        parts = candidates[0].get("content", {}).get("parts") or []
        text = "".join(str(p.get("text", "")) for p in parts).strip()
        if not text:
            raise LLMServiceError("Gemini returned empty content.")
        return text

    async def _call_openai(self, system_prompt: str, user_prompt: str) -> str:
        model = self.settings.openai_model.strip() or "gpt-4o-mini"
        body = {
            "model": model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        data = await self._post_json(
            url="https://api.openai.com/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.settings.openai_api_key.strip()}",
            },
            body=body,
        )
        choices = data.get("choices") or []
        if not choices:
            raise LLMServiceError("OpenAI returned empty choices.")
        content = choices[0].get("message", {}).get("content", "")
        if not content:
            raise LLMServiceError("OpenAI returned empty message content.")
        return str(content)

    async def _post_json(
        self,
        url: str,
        headers: dict[str, str],
        body: dict[str, Any],
        max_attempts: int = 2,
    ) -> dict[str, Any]:
        timeout = httpx.Timeout(self.settings.llm_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            for attempt in range(1, max_attempts + 1):
                try:
                    resp = await client.post(url, headers=headers, json=body)
                except (httpx.TimeoutException, httpx.RequestError) as exc:
                    if attempt == max_attempts:
                        raise LLMServiceError(f"LLM network/timeout error: {exc}") from exc
                    await asyncio.sleep(1.0 * attempt)
                    continue

                if resp.status_code in (429, 500, 502, 503, 504) and attempt < max_attempts:
                    await asyncio.sleep(1.5 * attempt)
                    continue

                if resp.status_code >= 400:
                    raise LLMServiceError(f"LLM HTTP {resp.status_code}: {resp.text[:250]}")

                return resp.json()

        raise LLMServiceError("LLM request failed after retries.")
