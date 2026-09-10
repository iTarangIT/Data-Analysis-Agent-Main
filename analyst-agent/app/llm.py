import os

from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import get_settings


def configure_tracing() -> None:
    s = get_settings()
    if s.langsmith_tracing and s.langsmith_api_key:
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_API_KEY"] = s.langsmith_api_key.get_secret_value()
        os.environ["LANGSMITH_PROJECT"] = s.langsmith_project


def get_llm() -> ChatGoogleGenerativeAI:
    # No temperature: the Gemini 3 flash models use fixed sampling and warn when it is set.
    s = get_settings()
    return ChatGoogleGenerativeAI(
        model=s.gemini_model,
        google_api_key=s.gemini_api_key.get_secret_value(),
        timeout=60,
        max_retries=2,
    )
