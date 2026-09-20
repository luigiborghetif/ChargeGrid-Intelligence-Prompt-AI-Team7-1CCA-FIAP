"""Testes dos indicadores e das regras operacionais."""

from __future__ import annotations

import pytest

from chargegrid.dados import carregar_operacao
from chargegrid.indicadores import (
    NivelDemanda,
    calcular_indicadores,
    classificar_demanda,
    recomendar_throttling,
)


@pytest.fixture
def operacao():
    return carregar_operacao(alertar_inconsistencias=False)


def test_calcula_indicadores_do_exemplo(operacao) -> None:
    indicadores = calcular_indicadores(operacao)

    assert indicadores.total_sessoes == 47
    assert indicadores.energia_total_calculada_kwh == pytest.approx(302.0)
    assert indicadores.potencia_total_snapshot_kw == pytest.approx(78.4)
    assert indicadores.pico.hora == "14:00"
    assert indicadores.pico.potencia_kw == pytest.approx(78.4)
    assert indicadores.pico.percentual_limite == pytest.approx(98.0)
    assert indicadores.pico.margem_ate_limite_kw == pytest.approx(1.6)
    assert indicadores.pico.nivel is NivelDemanda.CRITICO


@pytest.mark.parametrize(
    ("potencia_kw", "nivel_esperado"),
    [
        (70.0, NivelDemanda.NORMAL),
        (70.1, NivelDemanda.ATENCAO),
        (76.0, NivelDemanda.ATENCAO),
        (76.1, NivelDemanda.CRITICO),
        (80.0, NivelDemanda.CRITICO),
        (80.1, NivelDemanda.INCIDENTE),
    ],
)
def test_classifica_demanda_nos_limites(
    potencia_kw: float,
    nivel_esperado: NivelDemanda,
) -> None:
    assert classificar_demanda(potencia_kw, 80.0) is nivel_esperado


def test_identifica_carregadores_criticos_e_ociosos(operacao) -> None:
    indicadores = calcular_indicadores(operacao)

    assert indicadores.carregadores_criticos == (
        "EV-01",
        "EV-02",
        "EV-04",
        "EV-06",
    )
    assert indicadores.carregadores_ociosos == ("EV-08",)


def test_projeta_throttling_para_o_pico(operacao) -> None:
    recomendacao = recomendar_throttling(operacao)

    assert recomendacao.necessario is True
    assert recomendacao.carregadores_elegiveis == (
        "EV-01",
        "EV-02",
        "EV-04",
        "EV-06",
    )
    assert recomendacao.reducao_total_kw == pytest.approx(12.0)
    assert recomendacao.demanda_projetada_kw == pytest.approx(66.4)
    assert recomendacao.demanda_projetada_kw < recomendacao.demanda_alvo_kw
    assert "tempo de cada sessão" in recomendacao.limitacao


def test_nao_recomenda_throttling_abaixo_do_limiar(operacao) -> None:
    recomendacao = recomendar_throttling(operacao, demanda_atual_kw=75.0)

    assert recomendacao.necessario is False
    assert recomendacao.carregadores_elegiveis == ()
    assert recomendacao.reducao_total_kw == 0.0
    assert recomendacao.demanda_projetada_kw == 75.0


def test_rejeita_demanda_negativa(operacao) -> None:
    with pytest.raises(ValueError, match="não pode ser negativa"):
        recomendar_throttling(operacao, demanda_atual_kw=-1.0)
