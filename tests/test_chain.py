"""Testes da construção da chain LCEL, sem chamadas ao Ollama Cloud."""

from __future__ import annotations

import json

import pytest
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama

from chain.builder import (
    ErroChain,
    carregar_system_prompt,
    construir_chain,
    construir_contexto_operacional,
    criar_entrada_chain,
)
from chargegrid.dados import carregar_operacao


def test_carrega_prompt_v2_com_placeholders_obrigatorios() -> None:
    prompt = carregar_system_prompt("prompts/system_prompt_v2.md")

    assert "{contexto_operacional}" in prompt
    assert "{format_instructions}" in prompt
    assert "<seguranca>" in prompt


def test_contexto_usa_totais_calculados_e_registra_inconsistencia() -> None:
    operacao = carregar_operacao(alertar_inconsistencias=False)
    contexto = json.loads(construir_contexto_operacional(operacao))

    assert contexto["resumo_calculado"]["energia_total_calculada_kwh"] == 302.0
    assert contexto["resumo_calculado"]["pico"]["percentual_limite"] == 98.0
    assert contexto["inconsistencias_dados"] == [
        {
            "campo": "resumo_operacional_informado.energia_total_kwh",
            "informado": 342.0,
            "calculado": 302.0,
        }
    ]


def test_constroi_chain_na_ordem_prompt_llm_parser() -> None:
    chain = construir_chain()

    assert len(chain.steps) == 3
    assert isinstance(chain.steps[0], ChatPromptTemplate)
    assert isinstance(chain.steps[1], ChatOllama)
    assert isinstance(chain.steps[2], PydanticOutputParser)
    assert chain.steps[1].model == "gemma4:31b-cloud"
    assert chain.steps[1].num_predict == 1200
    assert chain.steps[1].format == "json"


def test_cria_entrada_para_pergunta_valida() -> None:
    operacao = carregar_operacao(alertar_inconsistencias=False)

    entrada = criar_entrada_chain("  Qual foi o pico?  ", operacao)

    assert entrada["pergunta"] == "Qual foi o pico?"
    assert json.loads(entrada["contexto_operacional"])["resumo_calculado"]


def test_rejeita_pergunta_vazia() -> None:
    operacao = carregar_operacao(alertar_inconsistencias=False)

    with pytest.raises(ErroChain, match="não pode estar vazia"):
        criar_entrada_chain("   ", operacao)


def test_rejeita_prompt_com_placeholder_desconhecido(tmp_path) -> None:
    arquivo = tmp_path / "prompt.md"
    arquivo.write_text(
        "{contexto_operacional}\n{format_instructions}\n{campo_inexistente}",
        encoding="utf-8",
    )

    with pytest.raises(ErroChain, match="campo_inexistente"):
        carregar_system_prompt(arquivo)
