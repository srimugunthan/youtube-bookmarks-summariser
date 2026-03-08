import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from youtubesynth.services.gemini_client import GeminiClient, GeminiResponse
from youtubesynth.exceptions import GeminiError


def _make_response(text: str, input_tokens: int = 100, output_tokens: int = 50):
    """Build a mock GenerateContentResponse."""
    usage = MagicMock()
    usage.prompt_token_count = input_tokens
    usage.candidates_token_count = output_tokens

    resp = MagicMock()
    resp.text = text
    resp.usage_metadata = usage
    return resp


def _make_client(side_effect=None, return_value=None):
    """
    Return a GeminiClient whose underlying aio.models.generate_content
    is replaced with an AsyncMock.
    """
    client = GeminiClient.__new__(GeminiClient)
    mock_genai_client = MagicMock()
    mock_generate = AsyncMock()

    if side_effect is not None:
        mock_generate.side_effect = side_effect
    elif return_value is not None:
        mock_generate.return_value = return_value

    mock_genai_client.aio.models.generate_content = mock_generate
    client._client = mock_genai_client
    return client, mock_generate


# ------------------------------------------------------------------
# Happy path
# ------------------------------------------------------------------

async def test_successful_generate():
    resp = _make_response("Hello world", input_tokens=200, output_tokens=80)
    client, mock_gen = _make_client(return_value=resp)

    result = await client.generate("gemini-1.5-flash", "Say hello")

    assert isinstance(result, GeminiResponse)
    assert result.text == "Hello world"
    assert result.input_tokens == 200
    assert result.output_tokens == 80
    mock_gen.assert_awaited_once()


async def test_token_counts_populated():
    resp = _make_response("Output text", input_tokens=1500, output_tokens=300)
    client, _ = _make_client(return_value=resp)

    result = await client.generate("gemini-1.5-pro", "Some prompt")

    assert result.input_tokens == 1500
    assert result.output_tokens == 300


# ------------------------------------------------------------------
# Retry behaviour
# ------------------------------------------------------------------

async def test_rate_limit_retries_then_succeeds():
    from google.genai import errors as genai_errors

    rate_limit_err = genai_errors.ClientError(429, {"message": "rate limited"}, None)
    success_resp = _make_response("Retry worked")

    client, mock_gen = _make_client(
        side_effect=[rate_limit_err, rate_limit_err, success_resp]
    )

    with patch("youtubesynth.services.gemini_client.asyncio.sleep", new_callable=AsyncMock):
        result = await client.generate("gemini-1.5-flash", "prompt")

    assert result.text == "Retry worked"
    assert mock_gen.await_count == 3


async def test_server_error_retries_then_succeeds():
    from google.genai import errors as genai_errors

    server_err = genai_errors.ServerError(503, {"message": "unavailable"}, None)
    success_resp = _make_response("Server recovered")

    client, mock_gen = _make_client(side_effect=[server_err, success_resp])

    with patch("youtubesynth.services.gemini_client.asyncio.sleep", new_callable=AsyncMock):
        result = await client.generate("gemini-1.5-flash", "prompt")

    assert result.text == "Server recovered"
    assert mock_gen.await_count == 2


async def test_max_retries_raises_gemini_error():
    from google.genai import errors as genai_errors

    rate_limit_err = genai_errors.ClientError(429, {"message": "quota"}, None)

    client, mock_gen = _make_client(
        side_effect=[rate_limit_err] * GeminiClient.MAX_RETRIES
    )

    with patch("youtubesynth.services.gemini_client.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(GeminiError, match="retries"):
            await client.generate("gemini-1.5-flash", "prompt")

    assert mock_gen.await_count == GeminiClient.MAX_RETRIES


async def test_invalid_argument_no_retry():
    from google.genai import errors as genai_errors

    bad_request = genai_errors.ClientError(400, {"message": "invalid"}, None)

    client, mock_gen = _make_client(side_effect=bad_request)

    with patch("youtubesynth.services.gemini_client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        with pytest.raises(GeminiError, match="Invalid request"):
            await client.generate("gemini-1.5-flash", "bad prompt")

    # Should have been called exactly once — no retries
    mock_gen.assert_awaited_once()
    mock_sleep.assert_not_awaited()
