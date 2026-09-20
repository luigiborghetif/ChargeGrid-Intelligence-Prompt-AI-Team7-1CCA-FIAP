"""Indicadores e regras de negócio da operação ChargeGrid."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from chargegrid.dados import Carregador, Operacao

LIMITE_ALERTA_KW = 70.0
LIMITE_CRITICO_KW = 76.0
POTENCIA_THROTTLING_KW = 8.0
DEMANDA_ALVO_THROTTLING_KW = 72.0
OCIOSIDADE_MAXIMA_HORAS = 2.0


class NivelDemanda(StrEnum):
    """Classificação operacional da demanda agregada do site."""

    NORMAL = "normal"
    ATENCAO = "atencao"
    CRITICO = "critico"
    INCIDENTE = "incidente"


@dataclass(frozen=True, slots=True)
class PicoDemandaCalculado:
    hora: str
    potencia_kw: float
    percentual_limite: float
    margem_ate_limite_kw: float
    nivel: NivelDemanda


@dataclass(frozen=True, slots=True)
class RecomendacaoThrottling:
    necessario: bool
    demanda_atual_kw: float
    demanda_alvo_kw: float
    potencia_recomendada_por_carregador_kw: float
    carregadores_elegiveis: tuple[str, ...]
    reducao_total_kw: float
    demanda_projetada_kw: float
    limitacao: str | None = None


@dataclass(frozen=True, slots=True)
class IndicadoresOperacionais:
    total_sessoes: int
    energia_total_calculada_kwh: float
    faturamento_estimado_brl: float
    potencia_total_snapshot_kw: float
    pico: PicoDemandaCalculado
    carregadores_criticos: tuple[str, ...]
    carregadores_ociosos: tuple[str, ...]
    throttling: RecomendacaoThrottling


def calcular_total_sessoes(operacao: Operacao) -> int:
    """Soma as sessões detalhadas de todos os carregadores."""
    return sum(
        carregador.total_sessoes
        for carregador in operacao.snapshot_carregadores.carregadores
    )


def calcular_energia_total(operacao: Operacao) -> float:
    """Soma a energia detalhada, evitando depender do resumo informado."""
    return round(
        sum(
            carregador.energia_entregue_kwh
            for carregador in operacao.snapshot_carregadores.carregadores
        ),
        3,
    )


def calcular_potencia_snapshot(operacao: Operacao) -> float:
    """Soma a potência dos carregadores no instante do snapshot."""
    return round(
        sum(
            carregador.potencia_kw
            for carregador in operacao.snapshot_carregadores.carregadores
        ),
        3,
    )


def calcular_percentual_limite(potencia_kw: float, limite_kw: float) -> float:
    """Calcula quanto da demanda contratada está sendo utilizado."""
    if potencia_kw < 0:
        raise ValueError("A potência não pode ser negativa.")
    if limite_kw <= 0:
        raise ValueError("O limite contratado deve ser maior que zero.")
    return round(potencia_kw / limite_kw * 100, 2)


def classificar_demanda(
    potencia_kw: float,
    limite_contratado_kw: float,
) -> NivelDemanda:
    """Classifica a demanda segundo as regras operacionais do projeto."""
    if potencia_kw < 0:
        raise ValueError("A potência não pode ser negativa.")
    if limite_contratado_kw <= 0:
        raise ValueError("O limite contratado deve ser maior que zero.")
    if potencia_kw > limite_contratado_kw:
        return NivelDemanda.INCIDENTE
    if potencia_kw > LIMITE_CRITICO_KW:
        return NivelDemanda.CRITICO
    if potencia_kw > LIMITE_ALERTA_KW:
        return NivelDemanda.ATENCAO
    return NivelDemanda.NORMAL


def identificar_pico(operacao: Operacao) -> PicoDemandaCalculado:
    """Encontra o maior registro de demanda e calcula seu impacto."""
    registro = max(
        operacao.demanda_horaria,
        key=lambda item: item.potencia_media_kw,
    )
    limite = operacao.site.infraestrutura.limite_demanda_contratada_kw

    return PicoDemandaCalculado(
        hora=registro.hora,
        potencia_kw=registro.potencia_media_kw,
        percentual_limite=calcular_percentual_limite(
            registro.potencia_media_kw,
            limite,
        ),
        margem_ate_limite_kw=round(
            limite - registro.potencia_media_kw,
            3,
        ),
        nivel=classificar_demanda(registro.potencia_media_kw, limite),
    )


def identificar_carregadores_criticos(operacao: Operacao) -> tuple[str, ...]:
    """Retorna carregadores marcados como críticos no snapshot."""
    return tuple(
        carregador.id
        for carregador in operacao.snapshot_carregadores.carregadores
        if carregador.status == "pico_critico"
    )


def _ociosidade_relevante(carregador: Carregador) -> bool:
    periodo = carregador.periodo_ociosidade
    return bool(
        periodo
        and periodo.durante_janela_pico
        and periodo.duracao_horas > OCIOSIDADE_MAXIMA_HORAS
    )


def identificar_carregadores_ociosos(operacao: Operacao) -> tuple[str, ...]:
    """Identifica ociosidade superior a duas horas durante a janela de pico."""
    return tuple(
        carregador.id
        for carregador in operacao.snapshot_carregadores.carregadores
        if _ociosidade_relevante(carregador)
    )


def recomendar_throttling(
    operacao: Operacao,
    demanda_atual_kw: float | None = None,
) -> RecomendacaoThrottling:
    """Projeta a redução dos carregadores que operam em potência máxima."""
    if demanda_atual_kw is None:
        demanda_atual_kw = identificar_pico(operacao).potencia_kw
    if demanda_atual_kw < 0:
        raise ValueError("A demanda atual não pode ser negativa.")

    potencia_maxima = operacao.site.infraestrutura.potencia_unitaria_maxima_kw
    carregadores = operacao.snapshot_carregadores.carregadores
    elegiveis = tuple(
        carregador
        for carregador in carregadores
        if math.isclose(
            carregador.potencia_kw,
            potencia_maxima,
            rel_tol=1e-9,
            abs_tol=1e-9,
        )
    )

    necessario = demanda_atual_kw > LIMITE_CRITICO_KW
    if not necessario:
        return RecomendacaoThrottling(
            necessario=False,
            demanda_atual_kw=demanda_atual_kw,
            demanda_alvo_kw=DEMANDA_ALVO_THROTTLING_KW,
            potencia_recomendada_por_carregador_kw=POTENCIA_THROTTLING_KW,
            carregadores_elegiveis=(),
            reducao_total_kw=0.0,
            demanda_projetada_kw=demanda_atual_kw,
        )

    reducao_por_carregador = max(
        potencia_maxima - POTENCIA_THROTTLING_KW,
        0.0,
    )
    reducao_total = round(reducao_por_carregador * len(elegiveis), 3)
    demanda_projetada = round(max(demanda_atual_kw - reducao_total, 0.0), 3)

    limitacao = None
    if not elegiveis:
        limitacao = "Nenhum carregador operava na potência máxima no snapshot."
    elif demanda_projetada >= DEMANDA_ALVO_THROTTLING_KW:
        limitacao = (
            "A redução proposta não é suficiente para manter a demanda "
            "abaixo do alvo de 72 kW."
        )
    else:
        limitacao = (
            "Os dados não incluem o tempo de cada sessão ativa; não é possível "
            "ordenar os carregadores pelo menor tempo de sessão."
        )

    return RecomendacaoThrottling(
        necessario=True,
        demanda_atual_kw=demanda_atual_kw,
        demanda_alvo_kw=DEMANDA_ALVO_THROTTLING_KW,
        potencia_recomendada_por_carregador_kw=POTENCIA_THROTTLING_KW,
        carregadores_elegiveis=tuple(item.id for item in elegiveis),
        reducao_total_kw=reducao_total,
        demanda_projetada_kw=demanda_projetada,
        limitacao=limitacao,
    )


def calcular_indicadores(operacao: Operacao) -> IndicadoresOperacionais:
    """Calcula o conjunto de indicadores consumido pelo dashboard e pela IA."""
    return IndicadoresOperacionais(
        total_sessoes=calcular_total_sessoes(operacao),
        energia_total_calculada_kwh=calcular_energia_total(operacao),
        faturamento_estimado_brl=(
            operacao.resumo_operacional_informado.faturamento_estimado_brl
        ),
        potencia_total_snapshot_kw=calcular_potencia_snapshot(operacao),
        pico=identificar_pico(operacao),
        carregadores_criticos=identificar_carregadores_criticos(operacao),
        carregadores_ociosos=identificar_carregadores_ociosos(operacao),
        throttling=recomendar_throttling(operacao),
    )
