from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: str = "groq"
    llm_model: str = "openai/gpt-oss-20b"
    groq_api_key: str = ""

    github_token: str = ""
    github_api_url: str = "https://api.github.com"

    accept_score_threshold: float = 8.0
    max_fix_iterations: int = 5
    # Minimum score gain between consecutive reviews; less than this routes to human review.
    min_score_improvement: float = 0.3

    execution_timeout_seconds: int = 60
    log_level: str = "INFO"
    # pytest EXECUTES the PR's code on this machine (no real sandbox), so it is opt-in.
    # py_compile only parses code and always runs.
    enable_test_execution: bool = False
    workspace_dir: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
