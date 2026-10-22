"""Contratos de geração e de resposta pública com citações verificadas."""

from typing import Literal, Self

from pydantic import Field, model_validator

from schemas.consulta_recarga import ModeloResposta


class ApoioDocumental(ModeloResposta):
    fonte_id: str = Field(min_length=1)
    trecho: str = Field(min_length=12, max_length=1200)


class RespostaFundamentada(ModeloResposta):
    resposta: str = Field(min_length=1)
    insuficiente: bool
    apoios: list[ApoioDocumental] = Field(default_factory=list)
    limitacoes: list[str] = Field(default_factory=list)


class CitacaoFonte(ModeloResposta):
    """Referência resolvida pela aplicação, nunca por metadados gerados pelo LLM."""

    fonte_id: str = Field(min_length=1)
    tipo: Literal["documental", "operacional"]
    arquivo: str = Field(min_length=1)
    pagina_pdf: int | None = Field(default=None, ge=1)
    secao: str | None = Field(default=None, min_length=1)
    trecho: str = Field(min_length=1)

    @model_validator(mode="after")
    def validar_localizacao(self) -> Self:
        if self.tipo == "documental" and self.pagina_pdf is None:
            raise ValueError("Uma citação documental precisa de página PDF")
        if self.tipo == "operacional" and self.pagina_pdf is not None:
            raise ValueError("Uma fonte operacional não possui página PDF")
        return self

    @property
    def referencia(self) -> str:
        local = (
            f"página PDF {self.pagina_pdf}"
            if self.tipo == "documental"
            else "JSON validado e indicadores calculados em Python"
        )
        if self.secao:
            local += f" — {self.secao}"
        return f"{self.arquivo} — {local} — {self.trecho}"


class RespostaDocumental(ModeloResposta):
    """Resposta pública documental ou mista com referências já verificadas."""

    resposta: str = Field(min_length=1)
    insuficiente: bool
    citacoes: list[CitacaoFonte] = Field(default_factory=list)
    limitacoes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def exigir_apoios_para_resposta_completa(self) -> Self:
        if not self.insuficiente and not self.citacoes:
            raise ValueError("Uma resposta completa precisa de citações verificadas")
        return self
