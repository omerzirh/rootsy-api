import os
import logging
from typing import Optional, List, Dict, Any
import httpx

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterService:
    """OpenRouter.ai API client for chat and vision tasks."""

    def __init__(self):
        self.api_key = os.getenv("OPENROUTER_API_KEY")
        self.chat_model = os.getenv("OPENROUTER_CHAT_MODEL", "anthropic/claude-haiku-4-5")
        self.vision_model = os.getenv("OPENROUTER_VISION_MODEL", "anthropic/claude-haiku-4-5")
        if not self.api_key:
            logger.warning("OPENROUTER_API_KEY not set — AI calls will fail")

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://rootsy.app",
            "X-Title": "Rootsy Garden App",
        }

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
    ) -> str:
        """Send a chat completion request. Returns the assistant's text response."""
        payload_messages = []
        if system_prompt:
            payload_messages.append({"role": "system", "content": system_prompt})
        payload_messages.extend(messages)

        payload = {
            "model": model or self.chat_model,
            "messages": payload_messages,
            "max_tokens": 1024,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        return data["choices"][0]["message"]["content"]

    async def analyze_image(
        self,
        image_base64: str,
        mime_type: str,
        prompt: str,
        system_prompt: Optional[str] = None,
    ) -> str:
        """Send an image + text prompt to a vision-capable model."""
        image_content = {
            "type": "image_url",
            "image_url": {"url": f"data:{mime_type};base64,{image_base64}"},
        }
        user_message = {
            "role": "user",
            "content": [image_content, {"type": "text", "text": prompt}],
        }
        payload_messages = []
        if system_prompt:
            payload_messages.append({"role": "system", "content": system_prompt})
        payload_messages.append(user_message)

        payload = {
            "model": self.vision_model,
            "messages": payload_messages,
            "max_tokens": 2048,
        }

        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        return data["choices"][0]["message"]["content"]


openrouter_service = OpenRouterService()
