"""Schema estruturado das respostas gerenciais do ChargeGrid."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)


class ModeloResposta(BaseModel):
    """Configuração comum dos objetos retornados pelo modelo."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )


class NivelRisco(StrEnum):
    """Níveis de risco aceitos na resposta gerencial."""

    NORMAL = "normal"
    ATENCAO = "atencao"
    CRITICO = "critico"
    INCIDENTE = "incidente"
    INDETERMINADO = "indeterminado"


class EstadoCarregador(StrEnum):
    """Estados conhecidos dos carregadores no contexto operacional."""

    NORMAL = "normal"
    ATENCAO = "atencao"
    PICO_CRITICO = "pico_critico"
    OCIOSO = "ocioso"
    DESCONHECIDO = "desconhecido"


class CarregadorRelacionado(ModeloResposta):
    """Carregador citado como evidência ou alvo de uma recomendação."""

    id: str
    estado: EstadoCarregador | None = None
    potencia_kw: float | None = Field(default=None, ge=0)

    @field_validator("id")
    @classmethod
    def validar_id(cls, valor: str) -> str:
        """Normaliza e valida identificadores no formato EV-XX."""
        normalizado = valor.strip().upper()
        if re.fullmatch(r"EV-\d{2}", normalizado) is None:
            raise ValueError("o ID do carregador deve seguir o formato EV-XX")
        return normalizado


class AnaliseFinanceira(ModeloResposta):
    """Estimativa financeira acompanhada das premissas utilizadas."""

    resultado_brl: float = Field(ge=0)
    premissas: list[str] = Field(min_length=1)
    formula: str = Field(min_length=1)

    @field_validator("premissas")
    @classmethod
    def validar_premissas(cls, valores: list[str]) -> list[str]:
        return _normalizar_lista_textual(valores, "premissas")


def _normalizar_lista_textual(valores: list[str], campo: str) -> list[str]:
    normalizados = [valor.strip() for valor in valores]
    if any(not valor for valor in normalizados):
        raise ValueError(f"{campo} não pode conter textos vazios")
    return list(dict.fromkeys(normalizados))


class ConsultaRecarga(ModeloResposta):
    """Resposta validada para consultas operacionais sobre recarga elétrica."""

    resumo_executivo: str = Field(min_length=1)
    evidencias: list[str] = Field(min_length=1)
    impacto: str = Field(min_length=1)
    recomendacoes: list[str] = Field(min_length=1)
    nivel_risco: NivelRisco
    carregadores_relacionados: list[CarregadorRelacionado] = Field(default_factory=list)
    potencia_total_kw: float | None = Field(default=None, ge=0)
    energia_total_kwh: float | None = Field(default=None, ge=0)
    analise_financeira: AnaliseFinanceira | None = None
    limitacoes: list[str] = Field(default_factory=list)

    @field_validator("evidencias", "recomendacoes", "limitacoes")
    @classmethod
    def validar_listas_textuais(
        cls,
        valores: list[str],
        info: ValidationInfo,
    ) -> list[str]:
        """Remove espaços, duplicações e rejeita itens vazios."""
        return _normalizar_lista_textual(valores, info.field_name)

    @model_validator(mode="after")
    def validar_carregadores_unicos(self) -> Self:
        ids = [carregador.id for carregador in self.carregadores_relacionados]
        if len(ids) != len(set(ids)):
            raise ValueError("carregadores_relacionados não pode repetir IDs")
        return self
