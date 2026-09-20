"""Testes do schema estruturado das respostas do assistente."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from schemas.consulta_recarga import (
    AnaliseFinanceira,
    CarregadorRelacionado,
    ConsultaRecarga,
    EstadoCarregador,
    NivelRisco,
)


def _resposta_valida() -> dict:
    return {
        "resumo_executivo": "A demanda atingiu nível crítico no pico.",
        "evidencias": ["Pico de 78,4 kW às 14:00.", "Uso de 98% do limite."],
        "impacto": "A margem operacional ficou limitada a 1,6 kW.",
        "recomendacoes": ["Preparar throttling preventivo acima de 76 kW."],
        "nivel_risco": "critico",
        "carregadores_relacionados": [
            {
                "id": "ev-01",
                "estado": "pico_critico",
                "potencia_kw": 11.0,
            }
        ],
        "potencia_total_kw": 78.4,
        "energia_total_kwh": 302.0,
        "limitacoes": [
            "Não há duração individual das sessões para definir prioridade."
        ],
    }


def test_valida_e_normaliza_resposta_completa() -> None:
    resposta = ConsultaRecarga.model_validate(_resposta_valida())

    assert resposta.nivel_risco is NivelRisco.CRITICO
    assert resposta.carregadores_relacionados == [
        CarregadorRelacionado(
            id="EV-01",
            estado=EstadoCarregador.PICO_CRITICO,
            potencia_kw=11.0,
        )
    ]
    assert resposta.model_dump(mode="json")["nivel_risco"] == "critico"


def test_rejeita_id_de_carregador_invalido() -> None:
    dados = _resposta_valida()
    dados["carregadores_relacionados"][0]["id"] = "carregador-1"

    with pytest.raises(ValidationError, match="formato EV-XX"):
        ConsultaRecarga.model_validate(dados)


def test_rejeita_valores_operacionais_negativos() -> None:
    dados = _resposta_valida()
    dados["potencia_total_kw"] = -1

    with pytest.raises(ValidationError, match="potencia_total_kw"):
        ConsultaRecarga.model_validate(dados)


def test_rejeita_carregadores_duplicados() -> None:
    dados = _resposta_valida()
    dados["carregadores_relacionados"].append(
        {
            "id": "EV-01",
            "estado": "normal",
            "potencia_kw": 5.0,
        }
    )

    with pytest.raises(ValidationError, match="não pode repetir IDs"):
        ConsultaRecarga.model_validate(dados)


def test_analise_financeira_exige_premissas() -> None:
    with pytest.raises(ValidationError, match="premissas"):
        AnaliseFinanceira(
            resultado_brl=100.0,
            premissas=[],
            formula="energia não entregue × tarifa média",
        )


def test_rejeita_campos_nao_definidos_no_schema() -> None:
    dados = _resposta_valida()
    dados["causa_inventada"] = "Falha técnica sem evidência."

    with pytest.raises(ValidationError, match="causa_inventada"):
        ConsultaRecarga.model_validate(dados)


def test_remove_evidencias_repetidas_e_espacos() -> None:
    dados = _resposta_valida()
    dados["evidencias"] = ["  Pico de 78,4 kW.  ", "Pico de 78,4 kW."]

    resposta = ConsultaRecarga.model_validate(dados)

    assert resposta.evidencias == ["Pico de 78,4 kW."]
