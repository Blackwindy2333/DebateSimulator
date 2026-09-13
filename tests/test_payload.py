from app.llm import LLMConfig, build_payload


def test_build_payload_thinking_enabled_includes_effort():
    cfg = LLMConfig(nickname="n", api_key="k", base_url="http://x", model="m",
                    temperature=0.5, thinking_enabled=True, reasoning_effort="max")
    payload = build_payload(cfg, [{"role": "user", "content": "hi"}])
    assert payload["thinking"] == {"type": "enabled"}
    assert payload["reasoning_effort"] == "max"
    assert payload["stream"] is True
    assert payload["model"] == "m"
    assert payload["temperature"] == 0.5
    assert "max_tokens" not in payload


def test_build_payload_thinking_disabled_omits_effort():
    cfg = LLMConfig(nickname="n", api_key="k", base_url="http://x", model="m",
                    thinking_enabled=False, reasoning_effort="high")
    payload = build_payload(cfg, [])
    assert payload["thinking"] == {"type": "disabled"}
    assert "reasoning_effort" not in payload
