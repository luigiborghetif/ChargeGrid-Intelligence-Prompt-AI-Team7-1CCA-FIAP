"""Testes do executor de avaliações sem chamadas ao modelo."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from chargegrid.assistente import RespostaAssistente, StatusResposta
from schemas.consulta_recarga import ConsultaRecarga, NivelRisco

CAMINHO_RUNNER = Path(__file__).resolve().parents[1] / "evals/run_evals.py"
SPEC = importlib.util.spec_from_file_location("run_evals", CAMINHO_RUNNER)
assert SPEC and SPEC.loader
run_evals = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = run_evals
SPEC.loader.exec_module(run_evals)


def test_casos_possuem_ids_unicos() -> None:
    casos = run_evals.carregar_casos()

    assert len(casos) == 10
    assert len({caso["id"] for caso in casos}) == len(casos)


def test_avalia_recusa_correta() -> None:
    caso = {"esperado": {"status": "recusada", "codigo": "fora_do_escopo"}}
    resposta = RespostaAssistente(
        status=StatusResposta.RECUSADA,
        codigo="fora_do_escopo",
        mensagem="Fora do escopo.",
    )

    verificacoes = run_evals.avaliar_resposta(caso, resposta)

    assert all(item.passou for item in verificacoes)


def test_avalia_fatos_da_resposta_estruturada() -> None:
    caso = {
        "esperado": {
            "status": "sucesso",
            "nivel_risco": "critico",
            "potencia_total_kw": 78.4,
            "carregadores_contem": ["EV-01"],
            "texto_contem": ["14:00"],
            "limitacoes_contem": ["diverg"],
        }
    }
    dados = ConsultaRecarga(
        resumo_executivo="Pico de 78,4 kW às 14:00.",
        evidencias=["Pico registrado às 14:00."],
        impacto="Margem reduzida.",
        recomendacoes=["Reduzir a demanda."],
        nivel_risco=NivelRisco.CRITICO,
        carregadores_relacionados=[{"id": "EV-01"}],
        potencia_total_kw=78.4,
        limitacoes=["Há divergência nos dados de energia."],
    )
    resposta = RespostaAssistente(
        StatusResposta.SUCESSO,
        "consulta_concluida",
        dados.resumo_executivo,
        dados,
    )

    verificacoes = run_evals.avaliar_resposta(caso, resposta)

    assert all(item.passou for item in verificacoes)


def test_metricas_marcam_execucao_com_erro_como_invalida() -> None:
    resultados = [
        {
            "status": "erro",
            "latencia_segundos": 0.1,
            "tokens_entrada_estimados": 10,
            "tokens_saida_estimados": 5,
            "verificacoes": [],
        }
    ]

    metricas = run_evals.consolidar_metricas(resultados)

    assert metricas["execucao_valida"] is False
    assert metricas["erros_execucao"] == 1


def test_aceita_uma_das_formulacoes_equivalentes() -> None:
    caso = {
        "esperado": {
            "status": "sucesso",
            "texto_contem_um_de": ["não é possível", "não há evidências"],
        }
    }
    dados = ConsultaRecarga(
        resumo_executivo="Não há evidências de defeito técnico.",
        evidencias=["O carregador está ocioso."],
        impacto="Causa indeterminada.",
        recomendacoes=["Verificar os logs."],
        nivel_risco=NivelRisco.INDETERMINADO,
    )
    resposta = RespostaAssistente(
        StatusResposta.SUCESSO,
        "consulta_concluida",
        dados.resumo_executivo,
        dados,
    )

    verificacoes = run_evals.avaliar_resposta(caso, resposta)

    assert all(item.passou for item in verificacoes)
