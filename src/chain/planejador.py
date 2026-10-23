"""Planejamento e resposta com LCEL e JSON validado por Pydantic."""

from dataclasses import replace
from pathlib import Path
from string import Formatter

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate

from chain.builder import ErroChain, criar_llm
from chargegrid.config import Settings
from schemas.plano_consulta import PlanoConsulta
from schemas.resposta_rag import RespostaFundamentada


def _construir(config: Settings, caminho: Path, contrato, campos: set[str]):
    try:
        texto = caminho.read_text(encoding="utf-8").strip()
        encontrados = {campo for _, campo, _, _ in Formatter().parse(texto) if campo}
    except (OSError, ValueError) as exc:
        raise ErroChain("Não foi possível carregar o prompt do planejador.") from exc
    if encontrados != campos | {"format_instructions"}:
        raise ErroChain("Placeholders inválidos no prompt do planejador.")
    parser = PydanticOutputParser(pydantic_object=contrato)
    prompt = ChatPromptTemplate.from_messages(
        [("system", texto), ("human", "{pergunta}")]
    ).partial(format_instructions=parser.get_format_instructions())
    return prompt | criar_llm(replace(config, temperature=0.0)) | parser


def construir_planejador(config: Settings):
    return _construir(
        config,
        config.planner_prompt_path,
        PlanoConsulta,
        {"historico_usuario", "ferramentas"},
    )


def construir_resposta_planejada(config: Settings):
    return _construir(
        config,
        config.planner_response_prompt_path,
        RespostaFundamentada,
        {"historico_usuario", "plano", "resultados", "fontes"},
    )
