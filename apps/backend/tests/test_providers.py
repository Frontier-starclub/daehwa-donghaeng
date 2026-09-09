import json
from dataclasses import asdict
from email.parser import BytesParser
from email.policy import default

import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.providers import (
    HttpChatProvider,
    HttpDURProvider,
    HttpOCRProvider,
    MedicationForCheck,
    MockChatProvider,
    MockDURProvider,
    MockOCRProvider,
    ProviderError,
    RecognizedMedication,
    get_chat_provider,
    get_dur_provider,
    get_ocr_provider,
)
from scripts.smoke_test import PNG_1X1

MEDICATIONS = [
    MedicationForCheck("a", "아모잘탄정", None, "123"),
    MedicationForCheck("b", "메트포르민서방정", "456", None),
]


def test_mock_regression():
    ocr = MockOCRProvider()
    assert ocr.name == "mock"
    assert ocr.recognize(b"image", "success") == [
        RecognizedMedication("아모잘탄정", dose_frequency_per_day=1, confidence=0.96),
        RecognizedMedication("메트포르민서방정", dose_frequency_per_day=2, confidence=0.93),
    ]
    assert ocr.recognize(b"image", "empty") == []
    with pytest.raises(RuntimeError):
        ocr.recognize(b"image", "failure")
    dur = MockDURProvider()
    assert dur.name == "mock"
    assert dur.check(MEDICATIONS, "none") == []
    assert dur.check(MEDICATIONS[:1], "warning") == []
    assert asdict(dur.check(MEDICATIONS, "warning")[0]) == {
        "warning_type": "demo_warning",
        "medication_ids": ["a", "b"],
        "message": "시연용 주의사항입니다. 실제 의약 정보가 아닙니다.",
        "source_code": "MOCK-001",
    }
    with pytest.raises(RuntimeError):
        dur.check(MEDICATIONS, "failure")
    chat = MockChatProvider()
    assert chat.name == "mock"
    assert chat.opening_message() == "오늘 하루 어떻게 보내셨어요?"
    assert [chat.reply(i, "hello") for i in range(1, 5)] == [
        "그랬군요. 오늘 그중에서 가장 기억에 남은 일은 무엇이었나요?",
        "말씀해 주셔서 고마워요. 그때 기분은 어떠셨어요?",
        "천천히 들려주셔도 괜찮아요. 조금 더 이야기해 주시겠어요?",
        "그랬군요. 오늘 그중에서 가장 기억에 남은 일은 무엇이었나요?",
    ]


@pytest.mark.parametrize(
    "image,media_type", [(PNG_1X1, "image/png"), (b"\xff\xd8\xff", "image/jpeg")]
)
def test_ocr_multipart_and_conversion(image, media_type):
    def handler(request):
        assert request.method == "POST"
        assert request.url.path == "/v1/ocr/prescription-label"
        assert not request.url.query
        assert request.headers["content-type"].startswith("multipart/form-data; boundary=")
        mime = BytesParser(policy=default).parsebytes(
            f"Content-Type: {request.headers['content-type']}\r\n\r\n".encode() + request.read()
        )
        parts = list(mime.iter_parts())
        assert len(parts) == 1
        assert parts[0].get_param("name", header="content-disposition") == "image"
        assert parts[0].get_content_type() == media_type
        assert parts[0].get_payload(decode=True) == image
        assert request.extensions["timeout"] == dict.fromkeys(
            ["connect", "read", "write", "pool"], 1.25
        )
        return httpx.Response(200, json={"items": [{"name": "약", "confidence": 0.9}]})

    provider = HttpOCRProvider("http://ai:8100", 1.25, transport=httpx.MockTransport(handler))
    assert provider.recognize(image, "failure") == [RecognizedMedication("약", confidence=0.9)]


def test_dur_request_and_warning_conversion():
    warning = {
        "warning_type": "usjnt_taboo",
        "medication_ids": ["a", "b"],
        "message": "상담 필요",
        "source_code": "DUR-1234",
    }

    def handler(request):
        assert request.method == "POST" and request.url.path == "/v1/dur/check"
        assert not request.url.query
        assert json.loads(request.content) == {"medications": [asdict(m) for m in MEDICATIONS]}
        return httpx.Response(200, json={"warnings": [warning]})

    provider = HttpDURProvider("http://ai:8100", 1, transport=httpx.MockTransport(handler))
    assert [asdict(w) for w in provider.check(MEDICATIONS, "failure")] == [warning]


@pytest.mark.parametrize("opening", [True, False])
def test_chat_request(opening):
    def handler(request):
        assert request.method == "POST" and request.url.path == "/v1/chat/reply"
        assert not request.url.query
        assert json.loads(request.content) == {
            "opening": opening,
            "user_message_count": 0 if opening else 3,
            "content": "" if opening else "오늘 손주가 왔어요",
        }
        return httpx.Response(200, json={"content": "반가워요"})

    provider = HttpChatProvider("http://ai:8100", 1, transport=httpx.MockTransport(handler))
    result = provider.opening_message() if opening else provider.reply(3, "오늘 손주가 왔어요")
    assert result == "반가워요"


PROVIDER_CASES = [
    (HttpOCRProvider, lambda p: p.recognize(PNG_1X1, "success")),
    (HttpDURProvider, lambda p: p.check(MEDICATIONS, "none")),
    (HttpChatProvider, lambda p: p.opening_message()),
    (HttpChatProvider, lambda p: p.reply(1, "hello")),
]


@pytest.mark.parametrize("provider_type,invoke", PROVIDER_CASES)
@pytest.mark.parametrize(
    "failure", ["timeout", "connection", 400, 422, 500, 503, "json", "missing"]
)
def test_all_remote_failures(provider_type, invoke, failure):
    def handler(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("timeout", request=request)
        if failure == "connection":
            raise httpx.ConnectError("offline", request=request)
        if isinstance(failure, int):
            return httpx.Response(failure, json={"code": "UPSTREAM_ERROR"})
        if failure == "json":
            return httpx.Response(200, content=b"not-json")
        return httpx.Response(200, json={})

    provider = provider_type("http://ai:8100", 1, transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError):
        invoke(provider)


@pytest.mark.parametrize(
    "provider_type,invoke,payload",
    [
        (HttpOCRProvider, PROVIDER_CASES[0][1], {"items": [{}]}),
        (HttpOCRProvider, PROVIDER_CASES[0][1], {"items": [{"name": 12}]}),
        (HttpOCRProvider, PROVIDER_CASES[0][1], {"items": [{"name": "약", "confidence": 1.1}]}),
        (
            HttpOCRProvider,
            PROVIDER_CASES[0][1],
            {"items": [{"name": "약", "dose_frequency_per_day": "2"}]},
        ),
        (HttpOCRProvider, PROVIDER_CASES[0][1], {"items": None}),
        (HttpDURProvider, PROVIDER_CASES[1][1], {"warnings": [{}]}),
        (
            HttpDURProvider,
            PROVIDER_CASES[1][1],
            {
                "warnings": [
                    {"warning_type": "demo_warning", "medication_ids": [42], "message": "caution"}
                ]
            },
        ),
        (
            HttpDURProvider,
            PROVIDER_CASES[1][1],
            {
                "warnings": [
                    {
                        "warning_type": "demo_warning",
                        "medication_ids": ["foreign-id"],
                        "message": "caution",
                    }
                ]
            },
        ),
        (
            HttpDURProvider,
            PROVIDER_CASES[1][1],
            {
                "warnings": [
                    {"warning_type": "x" * 41, "medication_ids": ["a"], "message": "caution"}
                ]
            },
        ),
        (HttpChatProvider, PROVIDER_CASES[2][1], {"content": None}),
        (HttpChatProvider, PROVIDER_CASES[3][1], {"content": []}),
        (HttpChatProvider, PROVIDER_CASES[3][1], {"content": ""}),
        (HttpChatProvider, PROVIDER_CASES[3][1], []),
    ],
)
def test_invalid_contract(provider_type, invoke, payload):
    provider = provider_type(
        "http://ai:8100",
        1,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )
    with pytest.raises(ProviderError):
        invoke(provider)


@pytest.mark.parametrize(
    "factory,remote_type,mock_type",
    [
        (get_ocr_provider, HttpOCRProvider, MockOCRProvider),
        (get_dur_provider, HttpDURProvider, MockDURProvider),
        (get_chat_provider, HttpChatProvider, MockChatProvider),
    ],
)
def test_factory_can_switch_after_import(monkeypatch, factory, remote_type, mock_type):
    for mode, expected in [("mock", mock_type), ("remote", remote_type), ("mock", mock_type)]:
        monkeypatch.setenv("PROVIDER_MODE", mode)
        get_settings.cache_clear()
        assert isinstance(factory(get_settings()), expected)


@pytest.mark.parametrize(
    "values",
    [
        {"provider_mode": "typo"},
        {"ai_service_timeout": 0},
        {"ai_service_timeout": -1},
        {"ai_service_timeout": float("inf")},
        {"ai_service_url": "file:///tmp/ai"},
    ],
)
def test_invalid_settings_fail_fast(values):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)
