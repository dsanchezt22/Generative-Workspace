import os
from typing import Optional
from google import genai
from dotenv import load_dotenv

load_dotenv()

_client: Optional[genai.Client] = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client


def generate(prompt: str, system: Optional[str] = None) -> str:
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    response = _get_client().models.generate_content(
        model="gemini-2.0-flash",
        contents=full_prompt,
    )
    return response.text
