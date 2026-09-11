"""Provider-switchable LLM factory.

Mirrors the LLMFactory pattern from emt-chatbot src/LLM/llm_client.py, minus the
channel handling this service has no use for. Temperature is 0: this is
extraction, not generation.
"""
from functools import lru_cache

from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI

from src.utils.config import (
    DEFAULT_GROQ_MODEL,
    DEFAULT_OPENAI_MODEL,
    GROQ_API_KEY,
    LLM_PROVIDER,
    LLM_TEMPERATURE,
    OPENAI_API_KEY,
    PROVIDER_GROQ,
    PROVIDER_OPENAI,
)


class LLMFactory:
    def get_llm_model(self, provider: str = None, llm_name: str = None):
        provider = (provider or LLM_PROVIDER).strip().lower()
        try:
            if provider == PROVIDER_GROQ:
                return self._get_groq_model(llm_name)
            if provider == PROVIDER_OPENAI:
                return self._get_openai_model(llm_name)
            raise ValueError(f"Unsupported provider: {provider}")
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(f"Error initializing {provider} LLM: {exc}") from exc

    def _get_groq_model(self, llm_name: str = None) -> ChatGroq:
        if not GROQ_API_KEY:
            raise ValueError("Groq API key is missing. Set GROQ_API_KEY.")
        return ChatGroq(
            api_key=GROQ_API_KEY,
            model=llm_name or DEFAULT_GROQ_MODEL,
            temperature=LLM_TEMPERATURE,
        )

    def _get_openai_model(self, llm_name: str = None) -> ChatOpenAI:
        if not OPENAI_API_KEY:
            raise ValueError("OpenAI API key is missing. Set OPENAI_API_KEY.")
        return ChatOpenAI(
            api_key=OPENAI_API_KEY,
            model=llm_name or DEFAULT_OPENAI_MODEL,
            temperature=LLM_TEMPERATURE,
        )


@lru_cache(maxsize=8)
def get_structured_llm(provider: str = None, llm_name: str = None):
    """A model bound to the FilterPatch schema. Cached per provider/model."""
    from src.schema.patch import FilterPatch

    llm = LLMFactory().get_llm_model(provider, llm_name)
    return llm.with_structured_output(FilterPatch)
