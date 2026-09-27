import pytest

from scripts.dev_stack import API_KEYS, ai_environment, clean_environment


def test_gemini_requires_only_its_own_key_and_dur():
    config = {
        "LLM_PROVIDER": "gemini",
        "GEMINI_API_KEY": " gemini-secret ",
        "DATA_GO_KR_SERVICE_KEY": "dur-secret",
        "ANTHROPIC_API_KEY": "unused-secret",
        "OCR_MODEL": "claude-existing",
        "GEMINI_OCR_MODEL": "gemini-selected",
    }
    env = ai_environment(config)
    assert env["GEMINI_API_KEY"] == "gemini-secret"
    assert "ANTHROPIC_API_KEY" not in env
    assert env["GEMINI_OCR_MODEL"] == "gemini-selected"
    assert env["GEMINI_CHAT_MODEL"] == "gemini-3.8-flash"
    assert env["PROVIDER_MODE"] == "remote"


def test_missing_key_error_lists_names_only():
    with pytest.raises(SystemExit) as error:
        ai_environment({"LLM_PROVIDER": "gemini", "ANTHROPIC_API_KEY": "private-secret"})
    assert str(error.value) == ".env에 입력할 키: GEMINI_API_KEY, DATA_GO_KR_SERVICE_KEY"


def test_existing_claude_setup_and_cli_override():
    config = {"ANTHROPIC_API_KEY": "claude-secret", "DATA_GO_KR_SERVICE_KEY": "dur-secret"}
    assert ai_environment(config)["LLM_PROVIDER"] == "anthropic"
    config["LLM_PROVIDER"] = "gemini"
    env = ai_environment(config, llm_provider="anthropic")
    assert env["ANTHROPIC_API_KEY"] == "claude-secret" and "GEMINI_API_KEY" not in env


@pytest.mark.parametrize("provider", ["gemini", "anthropic"])
def test_fixture_uses_only_synthetic_keys(provider):
    env = ai_environment(
        dict.fromkeys(API_KEYS, "real-secret"), fixture=True, llm_provider=provider
    )
    assert "real-secret" not in env.values()
    assert env["DATA_GO_KR_SERVICE_KEY"] == "e2e-fixture"


def test_invalid_provider_is_not_silently_ignored():
    with pytest.raises(SystemExit, match="LLM_PROVIDER"):
        ai_environment({"LLM_PROVIDER": "typo"}, fixture=True)


def test_backend_and_postgres_environment_never_inherit_api_keys():
    source = {**dict.fromkeys(API_KEYS, "private-secret"), "PATH": "/bin"}
    assert clean_environment(source) == {"PATH": "/bin"}
    assert source["GEMINI_API_KEY"] == "private-secret"
