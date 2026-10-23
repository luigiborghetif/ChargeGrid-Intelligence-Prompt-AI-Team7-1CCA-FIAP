"""Configurações centralizadas do ChargeGrid Intelligence."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"


class ConfigurationError(ValueError):
    """Indica uma variável de ambiente ausente ou inválida."""


def _read_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    try:
        return float(raw_value)
    except ValueError as exc:
        raise ConfigurationError(
            f"A variável {name} deve ser um número; recebido: {raw_value!r}."
        ) from exc


def _read_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    try:
        return int(raw_value)
    except ValueError as exc:
        raise ConfigurationError(
            f"A variável {name} deve ser um número inteiro; recebido: {raw_value!r}."
        ) from exc


def _resolve_project_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (PROJECT_ROOT / path).resolve()


def _read_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, str(default)).strip().casefold()
    if raw not in {"true", "false", "1", "0"}:
        raise ConfigurationError(f"{name} deve ser true ou false.")
    return raw in {"true", "1"}


@dataclass(frozen=True, slots=True)
class Settings:
    """Configurações imutáveis usadas pela aplicação."""

    ollama_base_url: str
    ollama_model: str
    data_path: Path
    prompt_path: Path
    temperature: float
    top_p: float
    max_tokens: int
    memory_token_limit: int
    planner_enabled: bool = True
    planner_prompt_path: Path = PROJECT_ROOT / "prompts/planejador_v1.md"
    planner_response_prompt_path: Path = PROJECT_ROOT / "prompts/resposta_tools_v1.md"

    @classmethod
    def from_env(cls) -> Settings:
        """Cria as configurações usando o ambiente e valores padrão locais."""
        load_dotenv(ENV_FILE, override=False)

        settings = cls(
            ollama_base_url=os.getenv(
                "OLLAMA_BASE_URL", "http://localhost:11434"
            ).rstrip("/"),
            ollama_model=os.getenv("OLLAMA_MODEL", "gemma4:31b-cloud").strip(),
            data_path=_resolve_project_path(
                os.getenv("CHARGEGRID_DATA_PATH", "data/exemplo_operacao.json")
            ),
            prompt_path=_resolve_project_path(
                os.getenv("CHARGEGRID_PROMPT_PATH", "prompts/system_prompt_v2.md")
            ),
            temperature=_read_float("MODEL_TEMPERATURE", 0.2),
            top_p=_read_float("MODEL_TOP_P", 0.9),
            max_tokens=_read_int("MODEL_MAX_TOKENS", 1200),
            memory_token_limit=_read_int("MEMORY_TOKEN_LIMIT", 4000),
            planner_enabled=_read_bool("CHARGEGRID_USAR_PLANEJADOR", True),
            planner_prompt_path=_resolve_project_path(
                os.getenv("PLANNER_PROMPT_PATH", "prompts/planejador_v1.md")
            ),
            planner_response_prompt_path=_resolve_project_path(
                os.getenv(
                    "PLANNER_RESPONSE_PROMPT_PATH", "prompts/resposta_tools_v1.md"
                )
            ),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        """Valida configurações que poderiam causar falhas pouco claras."""
        if not self.ollama_base_url.startswith(("http://", "https://")):
            raise ConfigurationError(
                "OLLAMA_BASE_URL deve começar com http:// ou https://."
            )
        if not self.ollama_model:
            raise ConfigurationError("OLLAMA_MODEL não pode estar vazio.")
        if not 0.0 <= self.temperature <= 2.0:
            raise ConfigurationError("MODEL_TEMPERATURE deve estar entre 0 e 2.")
        if not 0.0 < self.top_p <= 1.0:
            raise ConfigurationError("MODEL_TOP_P deve estar entre 0 e 1.")
        if self.max_tokens <= 0:
            raise ConfigurationError("MODEL_MAX_TOKENS deve ser maior que zero.")
        if self.memory_token_limit <= 0:
            raise ConfigurationError("MEMORY_TOKEN_LIMIT deve ser maior que zero.")


settings = Settings.from_env()
