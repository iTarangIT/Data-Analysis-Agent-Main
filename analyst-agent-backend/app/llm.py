import os

from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from app.config import get_settings


def configure_tracing() -> None:
    """Hand the LangSmith settings to the SDK, which reads nothing but `os.environ`.

    pydantic-settings reads `.env` without exporting it, so every process that runs the agent
    must call this: the API's lifespan and the worker's startup both do.
    """
    s = get_settings()
    if s.langsmith_tracing and s.langsmith_api_key:
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_API_KEY"] = s.langsmith_api_key.get_secret_value()
        os.environ["LANGSMITH_PROJECT"] = s.langsmith_project
        if s.langsmith_endpoint:
            os.environ["LANGSMITH_ENDPOINT"] = s.langsmith_endpoint


def get_llm() -> BaseChatModel:
    s = get_settings()
    if s.llm_provider == "openai":
        # No temperature: the GPT-5 models reason before answering and reject one. The reasoning
        # also makes a call slower than a flash model's, hence the longer timeout.
        return ChatOpenAI(
            model=s.openai_model,
            api_key=s.openai_api_key.get_secret_value(),
            timeout=120,
            max_retries=2,
        )
    # No temperature: the Gemini 3 flash models use fixed sampling and warn when it is set.
    return ChatGoogleGenerativeAI(
        model=s.gemini_model,
        google_api_key=s.gemini_api_key.get_secret_value(),
        timeout=60,
        max_retries=2,
    )
