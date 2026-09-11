"""Centralized configuration. Values come from the environment / .env."""
import os
from os import getenv

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENV_PATH = os.path.join(BASE_DIR, ".env")
load_dotenv(dotenv_path=ENV_PATH)

PROVIDER_GROQ = "groq"
PROVIDER_OPENAI = "openai"

LLM_PROVIDER = (getenv("LLM_PROVIDER") or PROVIDER_GROQ).strip().lower()

GROQ_API_KEY = getenv("GROQ_API_KEY")
DEFAULT_GROQ_MODEL = getenv("GROQ_MODEL") or "llama-3.3-70b-versatile"

OPENAI_API_KEY = getenv("OPENAI_API_KEY")
DEFAULT_OPENAI_MODEL = getenv("OPENAI_MODEL") or "gpt-4o-mini"

# Extraction, not generation - keep it deterministic.
LLM_TEMPERATURE = 0.0
