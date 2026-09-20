"""Carregamento e validação dos dados operacionais do ChargeGrid."""

from __future__ import annotations

import json
import math
import re
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from chargegrid.config import PROJECT_ROOT, settings


class ErroDados(ValueError):
    """Indica que a fonte de dados não pode ser utilizada pela aplicação."""


class InconsistenciaDadosWarning(UserWarning):
    """Alerta sobre totais divergentes sem impedir o uso dos dados."""


class ModeloDados(BaseModel):
    """Configuração comum para os modelos dos dados operacionais."""

    model_config = ConfigDict(extra="forbid")


def _validar_hora(valor: str) -> str:
    if re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", valor) is None:
        raise ValueError("o horário deve seguir o formato HH:MM")
    return valor


class Infraestrutura(ModeloDados):
    quantidade_carregadores: int = Field(gt=0)
    fabricante: str = Field(min_length=1)
    modelo: str = Field(min_length=1)
    potencia_unitaria_maxima_kw: float = Field(gt=0)
    capacidade_teorica_total_kw: float = Field(gt=0)
    limite_demanda_contratada_kw: float = Field(gt=0)


class Site(ModeloDados):
    tipo_estabelecimento: str = Field(min_length=1)
    localizacao_carregadores: str = Field(min_length=1)
    infraestrutura: Infraestrutura


class PicoDemanda(ModeloDados):
    potencia_kw: float = Field(ge=0)
    hora: str
    percentual_limite_contratado: float = Field(ge=0)

    _hora_valida = field_validator("hora")(_validar_hora)


class JanelaCritica(ModeloDados):
    inicio: str
    fim: str

    _inicio_valido = field_validator("inicio")(_validar_hora)
    _fim_valido = field_validator("fim")(_validar_hora)


class ResumoOperacionalInformado(ModeloDados):
    total_sessoes: int = Field(ge=0)
    energia_total_kwh: float = Field(ge=0)
    faturamento_estimado_brl: float = Field(ge=0)
    pico_demanda: PicoDemanda
    janela_critica: JanelaCritica


class RegistroDemanda(ModeloDados):
    hora: str
    potencia_media_kw: float = Field(ge=0)

    _hora_valida = field_validator("hora")(_validar_hora)


class PeriodoOciosidade(ModeloDados):
    inicio: str
    fim: str
    duracao_horas: float = Field(gt=0)
    durante_janela_pico: bool

    _inicio_valido = field_validator("inicio")(_validar_hora)
    _fim_valido = field_validator("fim")(_validar_hora)


class Carregador(ModeloDados):
    id: str = Field(pattern=r"^EV-\d{2}$")
    potencia_kw: float = Field(ge=0)
    total_sessoes: int = Field(ge=0)
    energia_entregue_kwh: float = Field(ge=0)
    status: Literal["normal", "atencao", "pico_critico", "ocioso"]
    periodo_ociosidade: PeriodoOciosidade | None = None


class SnapshotCarregadores(ModeloDados):
    hora_referencia: str
    carregadores: list[Carregador] = Field(min_length=1)

    _hora_valida = field_validator("hora_referencia")(_validar_hora)


class Operacao(ModeloDados):
    """Representa um conjunto completo e estruturalmente válido de operação."""

    schema_version: str = Field(min_length=1)
    origem: str = Field(min_length=1)
    site: Site
    resumo_operacional_informado: ResumoOperacionalInformado
    demanda_horaria: list[RegistroDemanda] = Field(min_length=1)
    snapshot_carregadores: SnapshotCarregadores

    @model_validator(mode="after")
    def validar_relacionamentos(self) -> Self:
        infraestrutura = self.site.infraestrutura
        carregadores = self.snapshot_carregadores.carregadores

        if len(carregadores) != infraestrutura.quantidade_carregadores:
            raise ValueError(
                "a quantidade de carregadores detalhados difere da infraestrutura"
            )

        ids = [carregador.id for carregador in carregadores]
        if len(ids) != len(set(ids)):
            raise ValueError("os IDs dos carregadores devem ser únicos")

        horas = [registro.hora for registro in self.demanda_horaria]
        if len(horas) != len(set(horas)):
            raise ValueError("os horários de demanda devem ser únicos")

        limite_unitario = infraestrutura.potencia_unitaria_maxima_kw
        acima_do_limite = [
            carregador.id
            for carregador in carregadores
            if carregador.potencia_kw > limite_unitario
        ]
        if acima_do_limite:
            raise ValueError(
                "carregadores acima da potência máxima unitária: "
                + ", ".join(acima_do_limite)
            )

        return self


@dataclass(frozen=True, slots=True)
class InconsistenciaDados:
    """Descreve a diferença entre um valor informado e o calculado."""

    campo: str
    informado: int | float | str
    calculado: int | float | str

    @property
    def mensagem(self) -> str:
        return (
            f"{self.campo}: informado={self.informado!r}, calculado={self.calculado!r}"
        )


def _numeros_iguais(valor_a: float, valor_b: float) -> bool:
    return math.isclose(valor_a, valor_b, rel_tol=1e-9, abs_tol=1e-9)


def validar_totais(operacao: Operacao) -> list[InconsistenciaDados]:
    """Compara totais informados com valores calculáveis a partir dos detalhes."""
    inconsistencias: list[InconsistenciaDados] = []
    infraestrutura = operacao.site.infraestrutura
    resumo = operacao.resumo_operacional_informado
    carregadores = operacao.snapshot_carregadores.carregadores

    total_sessoes = sum(item.total_sessoes for item in carregadores)
    if resumo.total_sessoes != total_sessoes:
        inconsistencias.append(
            InconsistenciaDados(
                campo="resumo_operacional_informado.total_sessoes",
                informado=resumo.total_sessoes,
                calculado=total_sessoes,
            )
        )

    energia_total = sum(item.energia_entregue_kwh for item in carregadores)
    if not _numeros_iguais(resumo.energia_total_kwh, energia_total):
        inconsistencias.append(
            InconsistenciaDados(
                campo="resumo_operacional_informado.energia_total_kwh",
                informado=resumo.energia_total_kwh,
                calculado=energia_total,
            )
        )

    capacidade_teorica = (
        infraestrutura.quantidade_carregadores
        * infraestrutura.potencia_unitaria_maxima_kw
    )
    if not _numeros_iguais(
        infraestrutura.capacidade_teorica_total_kw, capacidade_teorica
    ):
        inconsistencias.append(
            InconsistenciaDados(
                campo="site.infraestrutura.capacidade_teorica_total_kw",
                informado=infraestrutura.capacidade_teorica_total_kw,
                calculado=capacidade_teorica,
            )
        )

    registro_pico = max(
        operacao.demanda_horaria,
        key=lambda registro: registro.potencia_media_kw,
    )
    if not _numeros_iguais(
        resumo.pico_demanda.potencia_kw, registro_pico.potencia_media_kw
    ):
        inconsistencias.append(
            InconsistenciaDados(
                campo="resumo_operacional_informado.pico_demanda.potencia_kw",
                informado=resumo.pico_demanda.potencia_kw,
                calculado=registro_pico.potencia_media_kw,
            )
        )
    if resumo.pico_demanda.hora != registro_pico.hora:
        inconsistencias.append(
            InconsistenciaDados(
                campo="resumo_operacional_informado.pico_demanda.hora",
                informado=resumo.pico_demanda.hora,
                calculado=registro_pico.hora,
            )
        )

    percentual_limite = (
        registro_pico.potencia_media_kw
        / infraestrutura.limite_demanda_contratada_kw
        * 100
    )
    if not _numeros_iguais(
        resumo.pico_demanda.percentual_limite_contratado,
        percentual_limite,
    ):
        inconsistencias.append(
            InconsistenciaDados(
                campo=(
                    "resumo_operacional_informado.pico_demanda."
                    "percentual_limite_contratado"
                ),
                informado=resumo.pico_demanda.percentual_limite_contratado,
                calculado=percentual_limite,
            )
        )

    return inconsistencias


def _resolver_caminho(caminho: str | Path | None) -> Path:
    if caminho is None:
        return settings.data_path

    resolved = Path(caminho).expanduser()
    if not resolved.is_absolute():
        resolved = PROJECT_ROOT / resolved
    return resolved.resolve()


def carregar_operacao(
    caminho: str | Path | None = None,
    *,
    alertar_inconsistencias: bool = True,
) -> Operacao:
    """Carrega o JSON, valida sua estrutura e retorna dados tipados."""
    arquivo = _resolver_caminho(caminho)

    try:
        conteudo = arquivo.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ErroDados(f"Arquivo de operação não encontrado: {arquivo}") from exc
    except OSError as exc:
        raise ErroDados(
            f"Não foi possível ler o arquivo de operação: {arquivo}"
        ) from exc

    try:
        dados_brutos = json.loads(conteudo)
    except json.JSONDecodeError as exc:
        raise ErroDados(
            f"JSON inválido em {arquivo}, linha {exc.lineno}, coluna {exc.colno}."
        ) from exc

    try:
        operacao = Operacao.model_validate(dados_brutos)
    except ValidationError as exc:
        raise ErroDados(f"Dados operacionais inválidos em {arquivo}:\n{exc}") from exc

    inconsistencias = validar_totais(operacao)
    if alertar_inconsistencias and inconsistencias:
        detalhes = "; ".join(item.mensagem for item in inconsistencias)
        warnings.warn(
            f"Foram encontradas inconsistências nos dados: {detalhes}",
            InconsistenciaDadosWarning,
            stacklevel=2,
        )

    return operacao
