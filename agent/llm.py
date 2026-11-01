"""Claude client wrapper with retries and strict JSON parsing."""

import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Type, TypeVar, Union
import anthropic
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Base exception for LLM operations."""
    pass


class LLMParseError(LLMError):
    """Raised when JSON parsing or schema validation of LLM output fails."""
    pass


def extract_json_string(text: str) -> str:
    """Extract a JSON substring from a text response that may include markdown code blocks.

    Args:
        text: Raw text string potentially containing markdown JSON code blocks.

    Returns:
        Extracted clean JSON string.
    """
    text = text.strip()
    # Check for markdown code fences: ```json ... ``` or ``` ... ```
    match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?```", text)
    if match:
        return match.group(1).strip()

    # If first char is '{' or '[', attempt to find the outermost matching block
    brace_start = text.find("{")
    bracket_start = text.find("[")

    if brace_start != -1 and (bracket_start == -1 or brace_start < bracket_start):
        brace_end = text.rfind("}")
        if brace_end != -1:
            return text[brace_start:brace_end + 1].strip()
    elif bracket_start != -1:
        bracket_end = text.rfind("]")
        if bracket_end != -1:
            return text[bracket_start:bracket_end + 1].strip()

    return text


class ClaudeClient:
    """Thin wrapper around the Anthropic Claude API with exponential backoff and JSON extraction."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        default_model: str = "claude-3-5-sonnet-20241022",
        max_retries: int = 3,
        base_delay: float = 1.0,
        timeout: float = 60.0,
    ) -> None:
        """Initialize Claude client.

        Args:
            api_key: Anthropic API key. If omitted, uses ANTHROPIC_API_KEY from environment.
            default_model: Model name to use for completions.
            max_retries: Number of retry attempts on rate limit or transient errors.
            base_delay: Base delay in seconds for exponential backoff.
            timeout: Request timeout in seconds.
        """
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.default_model = default_model
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.timeout = timeout
        self._client: Optional[anthropic.Anthropic] = None

    @property
    def client(self) -> anthropic.Anthropic:
        """Lazy initialization of the Anthropic client."""
        if self._client is None:
            if not self.api_key:
                raise LLMError(
                    "ANTHROPIC_API_KEY is not set. Please add it to your .env file or environment variables."
                )
            self._client = anthropic.Anthropic(api_key=self.api_key, timeout=self.timeout)
        return self._client

    def generate_text(
        self,
        prompt: str,
        system: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: int = 2048,
        temperature: float = 0.2,
    ) -> str:
        """Generate text from Claude with automatic retries on transient errors.

        Args:
            prompt: User message prompt.
            system: Optional system instruction prompt.
            model: Optional model override.
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature (0.0 to 1.0).

        Returns:
            Generated text response.
        """
        model_name = model or self.default_model
        messages = [{"role": "user", "content": prompt}]

        for attempt in range(self.max_retries + 1):
            try:
                kwargs: Dict[str, Any] = {
                    "model": model_name,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "messages": messages,
                }
                if system:
                    kwargs["system"] = system

                response = self.client.messages.create(**kwargs)
                # Concatenate all text content blocks
                text_content = "".join(
                    block.text for block in response.content if hasattr(block, "text")
                )
                return text_content.strip()

            except (
                anthropic.RateLimitError,
                anthropic.APIConnectionError,
                anthropic.InternalServerError,
            ) as e:
                if attempt == self.max_retries:
                    logger.error("Max retries exceeded for Claude API call: %s", e)
                    raise LLMError(f"Claude API failed after {self.max_retries} retries: {e}") from e

                delay = self.base_delay * (2 ** attempt)
                logger.warning(
                    "Transient Claude API error (attempt %d/%d): %s. Retrying in %.1fs...",
                    attempt + 1,
                    self.max_retries,
                    e,
                    delay,
                )
                time.sleep(delay)

            except anthropic.APIStatusError as e:
                # Retry on 5xx status codes
                if e.status_code >= 500 and attempt < self.max_retries:
                    delay = self.base_delay * (2 ** attempt)
                    logger.warning("5xx Server error (%d). Retrying in %.1fs...", e.status_code, delay)
                    time.sleep(delay)
                    continue
                raise LLMError(f"Claude API status error {e.status_code}: {e.message}") from e

            except Exception as e:
                raise LLMError(f"Unexpected error calling Claude API: {e}") from e

        raise LLMError("Exceeded retry loop without response.")

    def generate_json(
        self,
        prompt: str,
        schema: Optional[Type[T]] = None,
        system: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> Union[Dict[str, Any], List[Any], T]:
        """Generate structured JSON output and validate against an optional Pydantic schema.

        Args:
            prompt: User message prompt asking for JSON.
            schema: Optional Pydantic model class to validate and parse output into.
            system: Optional system instruction prompt.
            model: Optional model override.
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature (default 0.0 for deterministic JSON).

        Returns:
            Parsed JSON object (dict, list) or Pydantic model instance if schema was provided.
        """
        system_instruction = (
            "You are a strict data-processing engine. "
            "Output ONLY valid JSON. Do not wrap in markdown or include conversational text, "
            "explanations, or comments outside the JSON structure."
        )
        if system:
            system_instruction = f"{system}\n\n{system_instruction}"

        raw_response = self.generate_text(
            prompt=prompt,
            system=system_instruction,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        json_str = extract_json_string(raw_response)

        try:
            parsed = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error("Failed to decode JSON from Claude output: %s\nRaw output:\n%s", e, raw_response)
            raise LLMParseError(f"Failed to parse JSON response: {e}") from e

        if schema is not None:
            try:
                if isinstance(parsed, dict):
                    return schema.model_validate(parsed)
                elif isinstance(parsed, list):
                    # For root list models
                    return schema.model_validate(parsed)
                else:
                    raise LLMParseError(f"Expected dict or list matching schema {schema.__name__}, got {type(parsed)}")
            except ValidationError as e:
                logger.error("Schema validation failed: %s\nParsed data:\n%s", e, parsed)
                raise LLMParseError(f"JSON does not conform to schema {schema.__name__}: {e}") from e

        return parsed

    def summarize_readme(self, readme_text: str, max_words: int = 80) -> str:
        """Create a concise, achievement/capability-focused summary of a project README.

        Args:
            readme_text: Raw Markdown or text of the README.
            max_words: Target maximum words for the summary.

        Returns:
            Concise summary string.
        """
        # Trim very large readmes to fit comfortably within token budgets
        truncated = readme_text[:6000]
        prompt = (
            f"Summarize the following repository README in at most {max_words} words. "
            "Highlight the core purpose, technology stack, and key technical capabilities. "
            "Do not include boilerplate, install commands, or marketing fluff.\n\n"
            f"README CONTENT:\n{truncated}"
        )
        return self.generate_text(prompt=prompt, max_tokens=256, temperature=0.2)
