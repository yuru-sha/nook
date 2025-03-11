"""
Gemini API Client for Lambda functions.

This module provides a common interface for interacting with the Gemini API.
"""

import logging
import os
import time
from dataclasses import dataclass
from threading import Lock
from typing import Any, ClassVar

from google import genai
from google.genai import types
from google.genai.errors import ClientError
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class RateLimiter:
    """シングルトンパターンを使用したレート制限の実装。"""

    _instance: ClassVar[Any | None] = None
    _lock: ClassVar[Lock] = Lock()

    def __new__(cls) -> "RateLimiter":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        """複数回の初期化を防ぐ。"""
        if self._initialized:
            return

        with self._lock:
            if not self._initialized:
                # 1分あたり10リクエストの制限
                self.capacity = 10  # 最大10トークン
                self.refill_rate = (
                    10 / 60
                )  # 1分で10トークン（1秒あたり約0.167トークン）
                self.tokens = self.capacity
                self.last_refill_time = time.time()
                self._initialized = True

    def _refill(self) -> None:
        """経過時間に応じてトークンを補充する。"""
        now = time.time()
        elapsed = now - self.last_refill_time
        new_tokens = elapsed * self.refill_rate
        self.tokens = min(self.capacity, self.tokens + new_tokens)
        self.last_refill_time = now

    def consume(self, tokens: int = 1, timeout: float | None = None) -> bool:
        """
        指定した数のトークンを消費する。

        Parameters
        ----------
        tokens : int
            消費するトークンの数（デフォルト: 1）
        timeout : float | None
            タイムアウトまでの秒数（デフォルト: None）

        Returns
        -------
        bool
            トークンが消費できた場合はTrue、できなかった場合はFalse
        """
        start_time = time.time()

        while True:
            with self._lock:
                self._refill()

                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return True

                # タイムアウトのチェック
                if timeout is not None:
                    if time.time() - start_time > timeout:
                        return False

                # 次のトークンが利用可能になるまでの待ち時間を計算
                tokens_needed = tokens - self.tokens
                wait_time = tokens_needed / self.refill_rate

            # 短い時間待機してから再試行
            time.sleep(min(1.0, wait_time))


@dataclass
class GeminiClientConfig:
    """Configuration for the Gemini client."""

    model: str = "gemini-2.0-flash-exp"
    temperature: float = 1.0
    top_p: float = 0.95
    top_k: int = 40
    max_output_tokens: int = 8192
    response_mime_type: str = "text/plain"
    timeout: int = 60000
    use_search: bool = False

    def update(self, **kwargs) -> None:
        """Update the configuration with the given keyword arguments."""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
            else:
                raise ValueError(f"Invalid configuration key: {key}")


class GeminiClient:
    """Client for interacting with the Gemini API."""

    def __init__(self, config: GeminiClientConfig | None = None, **kwargs):
        """
        Initialize the Gemini client.

        Parameters
        ----------
        config : GeminiClientConfig | None
            Configuration for the Gemini client.
            If not provided, default values will be used.
        """
        self._api_key = os.environ.get("GEMINI_API_KEY")
        if not self._api_key:
            raise ValueError("GEMINI_API_KEY environment variable is not set")

        self._config = config or GeminiClientConfig()
        self._config.update(**kwargs)

        self._client = genai.Client(
            api_key=self._api_key,
            http_options=types.HttpOptions(timeout=self._config.timeout),
        )
        self._chat = None
        self._rate_limiter = RateLimiter()

    def _wait_for_rate_limit(self, timeout: float | None = None) -> bool:
        """
        レート制限に従ってトークンを消費する。

        Parameters
        ----------
        timeout : float | None
            タイムアウトまでの秒数（デフォルト: None）

        Returns
        -------
        bool
            トークンが消費できた場合はTrue、できなかった場合はFalse
        """
        return self._rate_limiter.consume(tokens=1, timeout=timeout)

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        retry=retry_if_exception(lambda e: isinstance(e, (ClientError, TimeoutError))),
        before_sleep=lambda retry_state: logger.info(
            f"Retrying due to {retry_state.outcome.exception() if retry_state.outcome else 'unknown error'}..."
        ),
    )
    def generate_content(
        self,
        contents: str | list[str],
        system_instruction: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        top_k: int | None = None,
        max_output_tokens: int | None = None,
        response_mime_type: str | None = None,
    ) -> str:
        """
        Generate content using the Gemini API.

        Parameters
        ----------
        contents : str | list[str]
            The content to generate from.
        system_instruction : str | None
            The system instruction to use.
        model : str | None
            The model to use.
            If not provided, the model from the config will be used.
        temperature : float | None
            The temperature to use.
            If not provided, the temperature from the config will be used.
        top_p : float | None
            The top_p to use.
            If not provided, the top_p from the config will be used.
        top_k : int | None
            The top_k to use.
            If not provided, the top_k from the config will be used.
        max_output_tokens : int | None
            The max_output_tokens to use.
            If not provided, the max_output_tokens from the config will be used.
        response_mime_type : str | None
            The response_mime_type to use.
            If not provided, the response_mime_type from the config will be used.

        Returns
        -------
        str
            The generated content.

        Raises
        ------
        TimeoutError
            If unable to acquire rate limit token within timeout.
        """
        # レート制限のチェック（30秒のタイムアウト）
        if not self._wait_for_rate_limit(timeout=30):
            raise TimeoutError("Rate limit timeout exceeded")

        if isinstance(contents, str):
            contents = [contents]

        config_params = {
            "temperature": temperature or self._config.temperature,
            "top_p": top_p or self._config.top_p,
            "top_k": top_k or self._config.top_k,
            "max_output_tokens": max_output_tokens or self._config.max_output_tokens,
            "response_mime_type": response_mime_type or self._config.response_mime_type,
            "safety_settings": self._get_default_safety_settings(),
        }

        if system_instruction:
            config_params["system_instruction"] = system_instruction

        response = self._client.models.generate_content(
            model=model or self._config.model,
            contents=contents,
            config=types.GenerateContentConfig(**config_params),
        )

        return response.candidates[0].content.parts[0].text

    def create_chat(
        self,
        model: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        top_k: int | None = None,
        max_output_tokens: int | None = None,
    ) -> None:
        """
        Create a new chat session.

        Parameters
        ----------
        model : str | None
            The model to use.
            If not provided, the model from the config will be used.
        temperature : float | None
            The temperature to use.
            If not provided, the temperature from the config will be used.
        top_p : float | None
            The top_p to use.
            If not provided, the top_p from the config will be used.
        top_k : int | None
            The top_k to use.
            If not provided, the top_k from the config will be used.
        max_output_tokens : int | None
            The max_output_tokens to use.
            If not provided, the max_output_tokens from the config will be used.
        """
        config_params = {
            "temperature": temperature or self._config.temperature,
            "top_p": top_p or self._config.top_p,
            "top_k": top_k or self._config.top_k,
            "max_output_tokens": max_output_tokens or self._config.max_output_tokens,
            "response_modalities": ["TEXT"],
        }

        if self._config.use_search:
            google_search_tool = types.Tool(google_search=types.GoogleSearch())
            config_params["tools"] = [google_search_tool]

        self._chat = self._client.chats.create(
            model=model or self._config.model,
            config=types.GenerateContentConfig(**config_params),
        )

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        retry=retry_if_exception(lambda e: isinstance(e, (ClientError, TimeoutError))),
        before_sleep=lambda retry_state: logger.info(
            f"Retrying due to {retry_state.outcome.exception() if retry_state.outcome else 'unknown error'}..."
        ),
    )
    def send_message(self, message: str) -> str:
        """
        Send a message to the chat and get the response.

        Parameters
        ----------
        message : str
            The message to send.

        Returns
        -------
        str
            The response from the chat.

        Raises
        ------
        ValueError
            If no chat has been created.
        TimeoutError
            If unable to acquire rate limit token within timeout.
        """
        if not self._chat:
            raise ValueError("No chat has been created. Call create_chat() first.")

        # レート制限のチェック（30秒のタイムアウト）
        if not self._wait_for_rate_limit(timeout=30):
            raise TimeoutError("Rate limit timeout exceeded")

        response = self._chat.send_message(message)
        return response.text

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        retry=retry_if_exception(lambda e: isinstance(e, (ClientError, TimeoutError))),
        before_sleep=lambda retry_state: logger.info(
            f"Retrying due to {retry_state.outcome.exception() if retry_state.outcome else 'unknown error'}..."
        ),
    )
    def chat_with_search(self, message: str, model: str | None = None) -> str:
        """
        Create a new chat with search capability and send a message.

        This is a convenience method that combines create_chat() and send_message().

        Parameters
        ----------
        message : str
            The message to send.
        model : str | None
            The model to use.
            If not provided, the model from the config will be used.

        Returns
        -------
        str
            The response from the chat.

        Raises
        ------
        TimeoutError
            If unable to acquire rate limit token within timeout.
        """
        original_use_search = self._config.use_search
        self._config.use_search = True

        try:
            # レート制限のチェック（30秒のタイムアウト）
            if not self._wait_for_rate_limit(timeout=30):
                raise TimeoutError("Rate limit timeout exceeded")

            self.create_chat(model=model)
            return self.send_message(message)
        finally:
            self._config.use_search = original_use_search

    def _get_default_safety_settings(self) -> list[types.SafetySetting]:
        """
        Get the default safety settings.

        Returns
        -------
        list[types.SafetySetting]
            The default safety settings.
        """
        return [
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                threshold=types.HarmBlockThreshold.BLOCK_NONE,
            ),
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                threshold=types.HarmBlockThreshold.BLOCK_NONE,
            ),
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                threshold=types.HarmBlockThreshold.BLOCK_NONE,
            ),
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
                threshold=types.HarmBlockThreshold.BLOCK_NONE,
            ),
            types.SafetySetting(
                category=types.HarmCategory.HARM_CATEGORY_CIVIC_INTEGRITY,
                threshold=types.HarmBlockThreshold.BLOCK_NONE,
            ),
        ]


def create_client(config: dict[str, Any] | None = None, **kwargs) -> GeminiClient:
    """
    Create a Gemini client with the given configuration.

    Parameters
    ----------
    config : dict[str, Any] | None
        Configuration for the Gemini client.
        If not provided, default values will be used.

    Returns
    -------
    GeminiClient
        The Gemini client.
    """
    if config:
        client_config = GeminiClientConfig(
            model=config.get("model", "gemini-2.0-flash"),
            temperature=config.get("temperature", 1.0),
            top_p=config.get("top_p", 0.95),
            top_k=config.get("top_k", 40),
            max_output_tokens=config.get("max_output_tokens", 8192),
            response_mime_type=config.get("response_mime_type", "text/plain"),
            timeout=config.get("timeout", 60000),
            use_search=config.get("use_search", False),
        )
    else:
        client_config = None

    return GeminiClient(client_config, **kwargs)
