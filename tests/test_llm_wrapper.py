"""Tests for Claude LLM client wrapper and JSON parser."""

from unittest.mock import MagicMock, patch
import anthropic
import pytest
from pydantic import BaseModel

from agent.llm import ClaudeClient, LLMError, LLMParseError, extract_json_string


class SampleModel(BaseModel):
    name: str
    score: int


def test_extract_json_string_clean() -> None:
    raw = '{"key": "value"}'
    assert extract_json_string(raw) == '{"key": "value"}'


def test_extract_json_string_markdown_fence() -> None:
    raw = "Here is your JSON response:\n```json\n{\"skills\": [\"Python\", \"SQL\"]}\n```\nHope that helps!"
    assert extract_json_string(raw) == '{"skills": ["Python", "SQL"]}'


def test_extract_json_string_unfenced_with_surrounding_text() -> None:
    raw = "Result: {\"status\": \"ok\", \"count\": 42} (processed)"
    assert extract_json_string(raw) == '{"status": "ok", "count": 42}'


def test_extract_json_string_array() -> None:
    raw = "```\n[1, 2, 3]\n```"
    assert extract_json_string(raw) == "[1, 2, 3]"


def test_client_missing_api_key_raises_llm_error() -> None:
    with patch.dict("os.environ", {}, clear=True):
        client = ClaudeClient(api_key=None)
        with pytest.raises(LLMError, match="ANTHROPIC_API_KEY is not set"):
            _ = client.client


def test_generate_text_success() -> None:
    client = ClaudeClient(api_key="mock_key")
    mock_block = MagicMock()
    mock_block.text = "Hello from Claude"
    mock_response = MagicMock()
    mock_response.content = [mock_block]

    with patch.object(client, "_client") as mock_anthropic:
        mock_anthropic.messages.create.return_value = mock_response
        result = client.generate_text("Hi")
        assert result == "Hello from Claude"
        mock_anthropic.messages.create.assert_called_once()


def test_generate_text_retry_on_rate_limit() -> None:
    client = ClaudeClient(api_key="mock_key", max_retries=2, base_delay=0.01)
    mock_block = MagicMock()
    mock_block.text = "Recovered response"
    mock_response = MagicMock()
    mock_response.content = [mock_block]

    # Create mock response object for RateLimitError
    fake_http_response = MagicMock()
    fake_http_response.status_code = 429
    fake_http_response.headers = {}
    fake_error = anthropic.RateLimitError(
        message="Rate limit exceeded",
        response=fake_http_response,
        body=None,
    )

    with patch.object(client, "_client") as mock_anthropic:
        # Fail first call with RateLimitError, succeed on second
        mock_anthropic.messages.create.side_effect = [fake_error, mock_response]
        result = client.generate_text("Test prompt")
        assert result == "Recovered response"
        assert mock_anthropic.messages.create.call_count == 2


def test_generate_text_retry_exhaustion() -> None:
    client = ClaudeClient(api_key="mock_key", max_retries=1, base_delay=0.01)
    fake_http_response = MagicMock()
    fake_http_response.status_code = 429
    fake_http_response.headers = {}
    fake_error = anthropic.RateLimitError(
        message="Rate limit exceeded",
        response=fake_http_response,
        body=None,
    )

    with patch.object(client, "_client") as mock_anthropic:
        mock_anthropic.messages.create.side_effect = fake_error
        with pytest.raises(LLMError, match="Claude API failed after 1 retries"):
            client.generate_text("Fail prompt")


def test_generate_json_raw_dict() -> None:
    client = ClaudeClient(api_key="mock_key")
    with patch.object(client, "generate_text", return_value='```json\n{"status": "success", "items": [1, 2]}\n```'):
        result = client.generate_json("Give me status")
        assert result == {"status": "success", "items": [1, 2]}


def test_generate_json_with_pydantic_schema() -> None:
    client = ClaudeClient(api_key="mock_key")
    with patch.object(client, "generate_text", return_value='{"name": "Alice", "score": 95}'):
        obj = client.generate_json("Score Alice", schema=SampleModel)
        assert isinstance(obj, SampleModel)
        assert obj.name == "Alice"
        assert obj.score == 95


def test_generate_json_invalid_json_raises_parse_error() -> None:
    client = ClaudeClient(api_key="mock_key")
    with patch.object(client, "generate_text", return_value="Not valid JSON at all"):
        with pytest.raises(LLMParseError, match="Failed to parse JSON response"):
            client.generate_json("Invalid prompt")


def test_generate_json_schema_mismatch_raises_parse_error() -> None:
    client = ClaudeClient(api_key="mock_key")
    with patch.object(client, "generate_text", return_value='{"name": "Bob", "score": "not_an_int"}'):
        with pytest.raises(LLMParseError, match="JSON does not conform to schema SampleModel"):
            client.generate_json("Invalid score", schema=SampleModel)
