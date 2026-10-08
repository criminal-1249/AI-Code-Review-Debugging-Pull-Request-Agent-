from typing import Any, TypeVar

from langchain.chat_models import init_chat_model
from pydantic import BaseModel

from app.config import get_settings


class LLMConfigError(RuntimeError):
    pass


T = TypeVar("T", bound=BaseModel)


def structured(schema: type[T]):
    """Return a runnable whose .invoke(messages) yields a validated `schema` instance.

    Agents go through this single seam, so tests can replace it with a fake.
    """
    s = get_settings()

    kwargs: dict[str, Any] = {}
    
    if s.llm_provider == "groq":
        if not s.groq_api_key:
            raise LLMConfigError("GROQ_API_KEY is not set (add it to .env)")
        kwargs["api_key"] = s.groq_api_key
    
    llm = init_chat_model(s.llm_model, model_provider=s.llm_provider, **kwargs)
    if s.llm_provider == "groq":
        # Constrained JSON-schema decoding is far more reliable than tool-call parsing
        # for large outputs (e.g. whole-file contents) on Groq.
        return llm.with_structured_output(schema, method="json_schema")
    return llm.with_structured_output(schema)
