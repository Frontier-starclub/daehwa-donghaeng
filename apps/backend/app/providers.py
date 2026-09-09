from dataclasses import asdict, dataclass
from typing import Annotated, Protocol

import httpx
from fastapi import Depends
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.schemas import MedicationDraft


@dataclass(slots=True)
class RecognizedMedication:
    name: str
    ingredient_name: str | None = None
    ingredient_code: str | None = None
    item_seq: str | None = None
    dose_frequency_per_day: int | None = None
    confidence: float | None = None


@dataclass(slots=True)
class MedicationForCheck:
    id: str
    name: str
    ingredient_code: str | None
    item_seq: str | None


@dataclass(slots=True)
class DurProviderWarning:
    warning_type: str
    medication_ids: list[str]
    message: str
    source_code: str | None = None


class OCRProvider(Protocol):
    name: str

    def recognize(self, image: bytes, scenario: str) -> list[RecognizedMedication]: ...


class DURProvider(Protocol):
    name: str

    def check(
        self, medications: list[MedicationForCheck], scenario: str
    ) -> list[DurProviderWarning]: ...


class ChatProvider(Protocol):
    name: str

    def opening_message(self) -> str: ...

    def reply(self, user_message_count: int, content: str) -> str: ...


class MockOCRProvider:
    name = "mock"

    def recognize(self, image: bytes, scenario: str) -> list[RecognizedMedication]:
        if scenario == "failure":
            raise RuntimeError("mock OCR provider failure")
        if scenario == "empty":
            return []
        return [
            RecognizedMedication(
                name="아모잘탄정",
                dose_frequency_per_day=1,
                confidence=0.96,
            ),
            RecognizedMedication(
                name="메트포르민서방정",
                dose_frequency_per_day=2,
                confidence=0.93,
            ),
        ]


class MockDURProvider:
    name = "mock"

    def check(
        self, medications: list[MedicationForCheck], scenario: str
    ) -> list[DurProviderWarning]:
        if scenario == "failure":
            raise RuntimeError("mock DUR provider failure")
        if scenario == "warning" and len(medications) >= 2:
            return [
                DurProviderWarning(
                    warning_type="demo_warning",
                    medication_ids=[medications[0].id, medications[1].id],
                    message="시연용 주의사항입니다. 실제 의약 정보가 아닙니다.",
                    source_code="MOCK-001",
                )
            ]
        return []


class MockChatProvider:
    name = "mock"
    _replies = (
        "그랬군요. 오늘 그중에서 가장 기억에 남은 일은 무엇이었나요?",
        "말씀해 주셔서 고마워요. 그때 기분은 어떠셨어요?",
        "천천히 들려주셔도 괜찮아요. 조금 더 이야기해 주시겠어요?",
    )

    def opening_message(self) -> str:
        return "오늘 하루 어떻게 보내셨어요?"

    def reply(self, user_message_count: int, content: str) -> str:
        return self._replies[(user_message_count - 1) % len(self._replies)]


class ProviderError(RuntimeError):
    """Transport or response contract failure at the AI service boundary."""


class _OCRResponse(BaseModel):
    items: list[MedicationDraft]


class _DURWarning(BaseModel):
    warning_type: str = Field(min_length=1, max_length=40)
    medication_ids: list[str]
    message: str
    source_code: str | None = Field(default=None, max_length=50)


class _DURResponse(BaseModel):
    warnings: list[_DURWarning]


class _ChatResponse(BaseModel):
    content: str = Field(min_length=1)


class _HttpProvider:
    name = "remote"

    def __init__(
        self,
        base_url: str,
        timeout: float,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self.transport = transport

    def _post[ResponseT: BaseModel](
        self, path: str, response_type: type[ResponseT], **kwargs
    ) -> ResponseT:
        try:
            with httpx.Client(
                base_url=self.base_url,
                timeout=self.timeout,
                transport=self.transport,
                trust_env=False,
            ) as client:
                response = client.post(path, **kwargs)
                response.raise_for_status()
                return response_type.model_validate(response.json(), strict=True)
        except (httpx.HTTPError, ValueError) as exc:
            # Never expose upstream bodies, prompts or image data to the caller.
            raise ProviderError(f"AI service call failed: {path}") from exc


class HttpOCRProvider(_HttpProvider):
    def recognize(self, image: bytes, scenario: str) -> list[RecognizedMedication]:
        # The existing Protocol carries bytes only. Preserve PNG/JPEG media type
        # from the signature without extending the backend's public API.
        is_png = image.startswith(b"\x89PNG\r\n\x1a\n")
        filename, media_type = (
            ("label.png", "image/png") if is_png else ("label.jpg", "image/jpeg")
        )
        result = self._post(
            "/v1/ocr/prescription-label",
            _OCRResponse,
            files={"image": (filename, image, media_type)},
        )
        return [RecognizedMedication(**item.model_dump()) for item in result.items]


class HttpDURProvider(_HttpProvider):
    def check(
        self, medications: list[MedicationForCheck], scenario: str
    ) -> list[DurProviderWarning]:
        result = self._post(
            "/v1/dur/check",
            _DURResponse,
            json={"medications": [asdict(item) for item in medications]},
        )
        requested_ids = {item.id for item in medications}
        if any(set(item.medication_ids) - requested_ids for item in result.warnings):
            raise ProviderError("AI DUR response references unrequested medications")
        return [DurProviderWarning(**item.model_dump()) for item in result.warnings]


class HttpChatProvider(_HttpProvider):
    def opening_message(self) -> str:
        return self._reply(opening=True, user_message_count=0, content="")

    def reply(self, user_message_count: int, content: str) -> str:
        return self._reply(
            opening=False, user_message_count=user_message_count, content=content
        )

    def _reply(self, *, opening: bool, user_message_count: int, content: str) -> str:
        return self._post(
            "/v1/chat/reply",
            _ChatResponse,
            json={
                "opening": opening,
                "user_message_count": user_message_count,
                "content": content,
            },
        ).content


# Resolve settings through FastAPI dependencies, never at module import. Tests
# can override settings/providers without reloading the app or global instances.
ProviderSettings = Annotated[Settings, Depends(get_settings)]


def get_ocr_provider(settings: ProviderSettings) -> OCRProvider:
    if settings.provider_mode == "remote":
        return HttpOCRProvider(str(settings.ai_service_url), settings.ai_service_timeout)
    return MockOCRProvider()


def get_dur_provider(settings: ProviderSettings) -> DURProvider:
    if settings.provider_mode == "remote":
        return HttpDURProvider(str(settings.ai_service_url), settings.ai_service_timeout)
    return MockDURProvider()


def get_chat_provider(settings: ProviderSettings) -> ChatProvider:
    if settings.provider_mode == "remote":
        return HttpChatProvider(str(settings.ai_service_url), settings.ai_service_timeout)
    return MockChatProvider()
