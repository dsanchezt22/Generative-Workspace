from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from src import llm

router = APIRouter()


class GenerateRequest(BaseModel):
    prompt: str
    system: Optional[str] = None


class GenerateResponse(BaseModel):
    text: str


@router.post("/generate", response_model=GenerateResponse)
async def generate_text(body: GenerateRequest) -> GenerateResponse:
    if not body.prompt.strip():
        raise HTTPException(status_code=422, detail="Prompt cannot be empty")
    text = llm.generate(body.prompt, body.system)
    return GenerateResponse(text=text)
