"""One structured call to an OpenAI chat model, shared by the enrichment and the rewrite.

Structured outputs (`response_format` with a Pydantic model) make the API constrain
the answer to the JSON schema of that model, so the code receives a validated object
instead of free text to parse.

Reasoning models (gpt-5 family, o-series) reject `temperature` and spend hidden
"reasoning" tokens before answering; they get `reasoning_effort` instead, which at
"minimal" keeps those tokens, the cost and the latency low. The other models get
`temperature=0`, so the same input gives (almost always) the same output.
"""

import logging
from typing import Protocol, TypeVar

import openai
from openai import OpenAI
from pydantic import BaseModel

from app.core.config import Settings
from app.core.exceptions import LLMError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

REASONING_MODEL_PREFIXES = ("gpt-5", "o1", "o3", "o4")


class StructuredLLM(Protocol):
    """Asks a model for an answer shaped like a Pydantic model.

    Attributes:
        model_name: Identifier of the model (stored in manifests and shown in the UI).
    """

    model_name: str

    def complete(self, system: str, user: str, schema: type[T]) -> T:
        """Send one system + user message and parse the answer.

        Args:
            system: Instructions.
            user: Input of this call.
            schema: Pydantic model the answer must follow.

        Returns:
            The parsed answer.

        Raises:
            LLMError: If the call fails or the model refuses.
        """
        ...


def is_reasoning_model(model_name: str) -> bool:
    """Tell whether a model is a reasoning model (no temperature, has reasoning effort).

    Args:
        model_name: OpenAI model id.

    Returns:
        True for the gpt-5 family and the o-series.
    """
    return model_name.lower().startswith(REASONING_MODEL_PREFIXES)


class OpenAIStructuredLLM:
    """`StructuredLLM` backed by the OpenAI Chat Completions API.

    Args:
        client: OpenAI client (timeouts and retries are configured on it).
        model_name: OpenAI model id.
        reasoning_effort: Effort for reasoning models; empty sends nothing.
    """

    def __init__(self, client: OpenAI, model_name: str, reasoning_effort: str = "") -> None:
        self._client = client
        self.model_name = model_name
        self._reasoning_effort = reasoning_effort

    def complete(self, system: str, user: str, schema: type[T]) -> T:
        """Send one system + user message and parse the answer.

        Args:
            system: Instructions.
            user: Input of this call.
            schema: Pydantic model the answer must follow.

        Returns:
            The parsed answer.

        Raises:
            LLMError: If the call fails or the model refuses.
        """
        options: dict[str, object] = {}
        if is_reasoning_model(self.model_name):
            if self._reasoning_effort:
                options["reasoning_effort"] = self._reasoning_effort
        else:
            options["temperature"] = 0
        try:
            completion = self._client.chat.completions.parse(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format=schema,
                **options,  # type: ignore[arg-type]
            )
        except openai.OpenAIError as exc:
            raise LLMError(f"OpenAI request to {self.model_name} failed: {exc}") from exc

        message = completion.choices[0].message
        if message.parsed is None:
            reason = message.refusal or completion.choices[0].finish_reason
            raise LLMError(f"{self.model_name} returned no usable answer ({reason}).")
        return message.parsed


def build_llm(settings: Settings, model_name: str) -> StructuredLLM:
    """Create a structured LLM client from the settings.

    Args:
        settings: Application settings (key, timeout, retries, reasoning effort).
        model_name: OpenAI model id.

    Returns:
        The client.

    Raises:
        LLMError: If no OpenAI key is configured.
    """
    if not settings.has_openai_api_key or settings.openai_api_key is None:
        raise LLMError("OPENAI_API_KEY is not set.")
    client = OpenAI(
        api_key=settings.openai_api_key.get_secret_value(),
        timeout=settings.llm_timeout,
        max_retries=settings.llm_max_retries,
    )
    return OpenAIStructuredLLM(client, model_name, settings.llm_reasoning_effort)
