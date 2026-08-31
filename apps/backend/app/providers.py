from dataclasses import dataclass
from typing import Protocol


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


ocr_provider: OCRProvider = MockOCRProvider()
dur_provider: DURProvider = MockDURProvider()
chat_provider: ChatProvider = MockChatProvider()

