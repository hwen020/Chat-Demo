from app.providers import MockProvider

def test_mock_is_deterministic_and_uses_conversation():
    provider = MockProvider()
    history = [{"role": "user", "content": "Explain SQL"}]
    first = list(provider.stream(history))
    assert first == list(provider.stream(history))
    assert len(first) > 4
    assert "turn 1" in "".join(first)
    assert "Explain SQL" in "".join(first)
    later = history + [{"role": "assistant", "content": "Text"},
                       {"role": "user", "content": "Now test it"}]
    assert "turn 2" in "".join(provider.stream(later))
