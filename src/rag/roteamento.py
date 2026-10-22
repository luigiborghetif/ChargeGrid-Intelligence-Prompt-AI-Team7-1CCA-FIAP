"""Seleção determinística de fontes e resolução de continuações do usuário."""

from __future__ import annotations

import re
from enum import StrEnum

from guardrails.moderation import normalizar_texto


class TipoConsulta(StrEnum):
    OPERACIONAL = "operacional"
    DOCUMENTAL = "documental"
    MISTA = "mista"


PADRAO_OPERACIONAL = re.compile(
    r"\bev-\d{2}\b|\bpico\b|\bfaturamento\b|\bthrottling\b|\bocios[oa]\b|"
    r"\bociosidade\b|\bontem\b|\bregistrad[oa]s?\b|\bmedid[oa]s?\b|"
    r"\bindicadores?\b|\benergia (?:total|entregue)\b|\btotal (?:de )?(?:sessoes|energia)\b|"
    r"\bsessoes (?:realizadas|totais)\b|\bdemanda (?:contratada|horaria|da operacao)\b"
)
PADRAO_DOCUMENTAL = re.compile(
    r"\bmanual\b|\bficha\b|\bgw\d+k\b|\bhca\b|\brfid\b|\bip\d{2}\b|"
    r"\bgarantia\b|\bfila\b|\bvagas?\b|\bregulamento\b|\bregras?\b|"
    r"\btarifas?\b|\burgente\b|\beconomico\b|\bprotocolo\b|\bconector\b|"
    r"\bcontrole dinamico\b|\bpotencia nominal\b|\bfotovoltaic[oa]\b"
)


def eh_continuacao(pergunta: str) -> bool:
    return bool(
        re.match(
            r"^(?:e (?:o|a|os|as|qual|quais|quanto|como)\b|esse\b|essa\b|"
            r"explique\b|detalhe\b|continue\b|por que\b)",
            normalizar_texto(pergunta),
        )
    )


def resolver_pergunta(pergunta: str, anterior: str | None) -> str:
    if not anterior or not eh_continuacao(pergunta):
        return pergunta
    marcador = "\nTema anterior do usuário: "
    limite = 2000 - len(pergunta) - len(marcador)
    return pergunta + marcador + anterior[:limite] if limite > 0 else pergunta


def classificar_consulta(pergunta: str) -> TipoConsulta:
    texto = normalizar_texto(pergunta)
    if re.search(
        r"\bled\b|\bluz\b|\b(?:verde|azul|vermelho)\b", texto
    ) and not re.search(r"\bev-\d+\b", texto):
        return TipoConsulta.DOCUMENTAL
    operacional = bool(PADRAO_OPERACIONAL.search(texto))
    documental = bool(PADRAO_DOCUMENTAL.search(texto))
    if operacional:
        return TipoConsulta.MISTA if documental else TipoConsulta.OPERACIONAL
    return TipoConsulta.DOCUMENTAL
