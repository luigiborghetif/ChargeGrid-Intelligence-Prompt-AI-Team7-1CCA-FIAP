"""Construção da chain LCEL do ChargeGrid com Ollama."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from string import Formatter
from typing import Any

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import Runnable
from langchain_ollama import ChatOllama

from chargegrid.config import PROJECT_ROOT, Settings, settings
from chargegrid.dados import Operacao, validar_totais
from chargegrid.indicadores import IndicadoresOperacionais, calcular_indicadores
from schemas.consulta_recarga import ConsultaRecarga

PLACEHOLDERS_OBRIGATORIOS = {"contexto_operacional", "format_instructions"}


class ErroChain(ValueError):
    """Indica uma configuração inválida na construção da chain."""


def _resolver_caminho_prompt(caminho: str | Path | None) -> Path:
    if caminho is None:
        return settings.prompt_path

    resolved = Path(caminho).expanduser()
    if not resolved.is_absolute():
        resolved = PROJECT_ROOT / resolved
    return resolved.resolve()


def carregar_system_prompt(caminho: str | Path | None = None) -> str:
    """Carrega um prompt versionado e valida seus placeholders."""
    arquivo = _resolver_caminho_prompt(caminho)

    try:
        prompt = arquivo.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise ErroChain(f"System prompt não encontrado: {arquivo}") from exc
    except OSError as exc:
        raise ErroChain(f"Não foi possível ler o system prompt: {arquivo}") from exc

    if not prompt:
        raise ErroChain(f"O system prompt está vazio: {arquivo}")

    placeholders = {
        campo for _, campo, _, _ in Formatter().parse(prompt) if campo is not None
    }
    ausentes = PLACEHOLDERS_OBRIGATORIOS - placeholders
    desconhecidos = placeholders - PLACEHOLDERS_OBRIGATORIOS
    if ausentes:
        raise ErroChain(
            "Placeholders obrigatórios ausentes no system prompt: "
            + ", ".join(sorted(ausentes))
        )
    if desconhecidos:
        raise ErroChain(
            "Placeholders desconhecidos no system prompt: "
            + ", ".join(sorted(desconhecidos))
        )

    return prompt


def construir_contexto_operacional(
    operacao: Operacao,
    indicadores: IndicadoresOperacionais | None = None,
) -> str:
    """Serializa dados validados e indicadores em um contexto JSON compacto."""
    if indicadores is None:
        indicadores = calcular_indicadores(operacao)

    contexto = {
        "site": operacao.site.model_dump(mode="json"),
        "resumo_calculado": asdict(indicadores),
        "demanda_horaria": [
            registro.model_dump(mode="json") for registro in operacao.demanda_horaria
        ],
        "snapshot_carregadores": operacao.snapshot_carregadores.model_dump(mode="json"),
        "inconsistencias_dados": [
            asdict(inconsistencia) for inconsistencia in validar_totais(operacao)
        ],
    }
    return json.dumps(contexto, ensure_ascii=False, separators=(",", ":"))


def criar_parser() -> PydanticOutputParser[ConsultaRecarga]:
    """Cria o parser que valida toda resposta contra ConsultaRecarga."""
    return PydanticOutputParser(pydantic_object=ConsultaRecarga)


def criar_prompt(
    parser: PydanticOutputParser[ConsultaRecarga],
    caminho_prompt: str | Path | None = None,
) -> ChatPromptTemplate:
    """Monta o chat prompt e injeta as instruções do schema Pydantic."""
    system_prompt = carregar_system_prompt(caminho_prompt)
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt),
            MessagesPlaceholder(variable_name="history", optional=True),
            ("human", "{pergunta}"),
        ]
    )
    return prompt.partial(
        format_instructions=parser.get_format_instructions(),
    )


def criar_llm(configuracao: Settings | None = None) -> ChatOllama:
    """Configura o ChatOllama sem realizar uma chamada durante a criação."""
    config = configuracao or settings
    return ChatOllama(
        model=config.ollama_model,
        base_url=config.ollama_base_url,
        temperature=config.temperature,
        top_p=config.top_p,
        num_predict=config.max_tokens,
        format="json",
        reasoning=False,
        validate_model_on_init=False,
    )


def construir_chain(
    configuracao: Settings | None = None,
    caminho_prompt: str | Path | None = None,
) -> Runnable[dict[str, Any], ConsultaRecarga]:
    """Constrói a chain LCEL obrigatória: prompt | llm | parser."""
    config = configuracao or settings
    parser = criar_parser()
    prompt = criar_prompt(parser, caminho_prompt or config.prompt_path)
    llm = criar_llm(config)

    chain = prompt | llm | parser
    return chain


def criar_entrada_chain(
    pergunta: str,
    operacao: Operacao,
    indicadores: IndicadoresOperacionais | None = None,
) -> dict[str, str]:
    """Prepara a entrada mínima para invocar a chain sem memória."""
    pergunta = pergunta.strip()
    if not pergunta:
        raise ErroChain("A pergunta não pode estar vazia.")

    return {
        "pergunta": pergunta,
        "contexto_operacional": construir_contexto_operacional(
            operacao,
            indicadores,
        ),
    }
