import os

from langchain_openai import ChatOpenAI

from app.config import get_settings


def configure_tracing() -> None:
    s = get_settings()
    if s.langsmith_tracing and s.langsmith_api_key:
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_API_KEY"] = s.langsmith_api_key.get_secret_value()
        os.environ["LANGSMITH_PROJECT"] = s.langsmith_project


def get_llm(temperature: float = 0.0) -> ChatOpenAI:
    s = get_settings()
    return ChatOpenAI(
        model=s.openrouter_model,
        api_key=s.openrouter_api_key.get_secret_value(),
        base_url=s.openrouter_base_url,
        temperature=temperature,
        timeout=60,
        max_retries=2,
    )
