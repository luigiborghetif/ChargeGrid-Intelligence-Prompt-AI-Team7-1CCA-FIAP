"""Contratos tipados do planejador e das ferramentas permitidas."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from schemas.consulta_recarga import ModeloResposta
from schemas.resposta_rag import CitacaoFonte

IdEtapa = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")]
IdCarregador = Annotated[str, Field(pattern=r"^EV-\d{2}$")]


class ArgumentosOperacao(ModeloResposta):
    consulta: Literal[
        "resumo", "carregadores", "demanda_horaria", "sessoes_individuais"
    ] = "resumo"
    carregador_id: IdCarregador | None = None
    ordenar_por: Literal["energia_entregue_kwh", "potencia_kw", "total_sessoes"] = (
        "energia_entregue_kwh"
    )
    ordem: Literal["asc", "desc"] = "desc"
    limite: int = Field(default=10, ge=1, le=10)


class ArgumentosIndicadores(ModeloResposta):
    indicador: Literal[
        "todos",
        "pico",
        "energia_total",
        "sessoes_total",
        "throttling",
        "ociosidade",
        "faturamento",
    ] = "todos"


class ArgumentosDocumentos(ModeloResposta):
    pergunta: str = Field(min_length=3, max_length=2000)


class ArgumentosCusto(ModeloResposta):
    modalidade: Literal["urgente", "economico"]
    tarifa_de: IdEtapa
    energia_de: IdEtapa | None = None
    energia_kwh: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def uma_origem_de_energia(self) -> Self:
        if (self.energia_de is None) == (self.energia_kwh is None):
            raise ValueError("Informe energia_de OU energia_kwh")
        return self


class ConsultaOperacao(ModeloResposta):
    id: IdEtapa
    ferramenta: Literal["consultar_operacao"]
    argumentos: ArgumentosOperacao


class ConsultaIndicadores(ModeloResposta):
    id: IdEtapa
    ferramenta: Literal["calcular_indicadores"]
    argumentos: ArgumentosIndicadores


class ConsultaDocumentos(ModeloResposta):
    id: IdEtapa
    ferramenta: Literal["buscar_documentos"]
    argumentos: ArgumentosDocumentos


class EstimativaCusto(ModeloResposta):
    id: IdEtapa
    ferramenta: Literal["estimar_custo"]
    argumentos: ArgumentosCusto


EtapaConsulta = Annotated[
    ConsultaOperacao | ConsultaIndicadores | ConsultaDocumentos | EstimativaCusto,
    Field(discriminator="ferramenta"),
]


class PlanoConsulta(ModeloResposta):
    encaminhamento: Literal[
        "consultar", "esclarecer", "fora_do_escopo", "ajuda", "recusar_seguranca"
    ]
    pergunta_interpretada: str = Field(min_length=1, max_length=2000)
    esclarecimento: str | None = Field(default=None, min_length=1, max_length=500)
    etapas: list[EtapaConsulta] = Field(default_factory=list, max_length=4)

    @model_validator(mode="after")
    def validar_plano(self) -> Self:
        if (self.encaminhamento == "consultar") != bool(self.etapas):
            raise ValueError("Somente consultas precisam de uma a quatro etapas")
        if self.encaminhamento == "esclarecer" and not self.esclarecimento:
            raise ValueError("Esclarecimento precisa de uma pergunta ao usuário")
        anteriores = {}
        for etapa in self.etapas:
            if etapa.id in anteriores:
                raise ValueError("IDs de etapas devem ser únicos")
            if isinstance(etapa, EstimativaCusto):
                args = etapa.argumentos
                tarifa = anteriores.get(args.tarifa_de)
                if tarifa is None or tarifa.ferramenta != "buscar_documentos":
                    raise ValueError(
                        "tarifa_de deve apontar para busca documental anterior"
                    )
                if args.energia_de is not None and not isinstance(
                    anteriores.get(args.energia_de),
                    (ConsultaOperacao, ConsultaIndicadores),
                ):
                    raise ValueError(
                        "energia_de deve apontar para consulta operacional anterior"
                    )
            anteriores[etapa.id] = etapa
        return self


class ResultadoFerramenta(ModeloResposta):
    etapa_id: IdEtapa
    ferramenta: Literal[
        "consultar_operacao",
        "calcular_indicadores",
        "buscar_documentos",
        "estimar_custo",
    ]
    estado: Literal["sucesso", "parcial", "ausente", "erro"]
    dados: dict = Field(default_factory=dict)
    limitacoes: list[str] = Field(default_factory=list)
    fontes: list[CitacaoFonte] = Field(default_factory=list)
