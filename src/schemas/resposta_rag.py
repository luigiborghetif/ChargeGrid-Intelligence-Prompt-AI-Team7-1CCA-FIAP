"""Contrato interno de geração documental e mista, independente da apresentação."""

from pydantic import Field

from schemas.consulta_recarga import ModeloResposta


class ApoioDocumental(ModeloResposta):
    fonte_id: str = Field(min_length=1)
    trecho: str = Field(min_length=12, max_length=1200)


class RespostaFundamentada(ModeloResposta):
    resposta: str = Field(min_length=1)
    insuficiente: bool
    apoios: list[ApoioDocumental] = Field(default_factory=list)
    limitacoes: list[str] = Field(default_factory=list)
