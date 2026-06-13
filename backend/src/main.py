from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.routes import generate

app = FastAPI(title="Generative Workspace API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(generate.router, prefix="/api")
