"""Validação de escopo das perguntas dirigidas ao ChargeGrid."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from guardrails.moderation import normalizar_texto


class CategoriaEscopo(StrEnum):
    """Classificações possíveis para o domínio da pergunta."""

    OPERACIONAL = "operacional"
    SAUDACAO = "saudacao"
    CONTINUACAO = "continuacao"
    FORA_DO_ESCOPO = "fora_do_escopo"


@dataclass(frozen=True, slots=True)
class ResultadoEscopo:
    """Resultado explicável da validação temática."""

    dentro_escopo: bool
    categoria: CategoriaEscopo
    mensagem: str | None = None


TERMOS_OPERACIONAIS = {
    "carregador",
    "carregadores",
    "chargegrid",
    "goodwe",
    "eletroposto",
    "recarga",
    "recargas",
    "sessao",
    "sessoes",
    "demanda",
    "potencia",
    "energia",
    "kwh",
    "kw",
    "pico",
    "limite",
    "throttling",
    "faturamento",
    "tarifa",
    "ociosidade",
    "ocioso",
    "operacao",
    "operacional",
    "ev-",
}

SAUDACOES = {
    "oi",
    "ola",
    "bom dia",
    "boa tarde",
    "boa noite",
    "tudo bem",
}

INDICADORES_CONTINUACAO = (
    "e qual",
    "e quais",
    "e quanto",
    "por que",
    "explique",
    "detalhe",
    "continue",
    "mensagem anterior",
    "resposta anterior",
    "essa meta",
    "esse valor",
    "esses dados",
)


def validar_escopo(texto: str) -> ResultadoEscopo:
    """Aceita temas operacionais, saudações e continuações contextuais."""
    normalizado = normalizar_texto(texto)

    if normalizado in SAUDACOES:
        return ResultadoEscopo(True, CategoriaEscopo.SAUDACAO)

    palavras = set(re.findall(r"\b[\w-]+\b", normalizado))
    menciona_carregador = any(palavra.startswith("ev-") for palavra in palavras)
    if menciona_carregador or not TERMOS_OPERACIONAIS.isdisjoint(palavras):
        return ResultadoEscopo(True, CategoriaEscopo.OPERACIONAL)

    if any(normalizado.startswith(indicador) for indicador in INDICADORES_CONTINUACAO):
        return ResultadoEscopo(True, CategoriaEscopo.CONTINUACAO)

    return ResultadoEscopo(
        dentro_escopo=False,
        categoria=CategoriaEscopo.FORA_DO_ESCOPO,
        mensagem=(
            "Essa solicitação está fora do escopo do ChargeGrid. Posso ajudar "
            "com demanda, energia, sessões, carregadores e faturamento do eletroposto."
        ),
    )
