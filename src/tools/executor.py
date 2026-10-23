"""Execução limitada de ferramentas LangChain sobre dados autorizados do projeto."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import asdict
from decimal import ROUND_HALF_UP, Decimal

import httpx
from langchain_core.documents import Document
from langchain_core.tools import StructuredTool
from ollama import ResponseError

from chain.builder import construir_contexto_operacional
from chargegrid.dados import Operacao, validar_totais
from chargegrid.indicadores import calcular_indicadores
from guardrails.moderation import moderar_entrada, normalizar_texto
from rag.errors import ErroRAG
from schemas.plano_consulta import (
    ArgumentosCusto,
    ArgumentosDocumentos,
    ArgumentosIndicadores,
    ArgumentosOperacao,
    PlanoConsulta,
    ResultadoFerramenta,
)
from schemas.resposta_rag import CitacaoFonte

DESCRICOES = {
    "consultar_operacao": (
        "Consulta JSON validado: resumo, demanda horária, carregadores com filtro, "
        "ordenação e limite. Energia e sessões são ACUMULADOS por carregador; "
        "sessoes_individuais retorna a limitação e o maior acumulado disponível. "
        "Não há data, duração, energia ou valor cobrado por sessão individual."
    ),
    "calcular_indicadores": (
        "Calcula em Python pico, energia_total, sessoes_total, throttling, "
        "ociosidade, faturamento estimado informado ou todos."
    ),
    "buscar_documentos": (
        "Busca evidências nos PDFs GoodWe e tarifas/regras simuladas. "
        "Retorna trechos e metadados, não uma resposta pronta."
    ),
    "estimar_custo": (
        "Calcula energia × tarifa em Python. tarifa_de referencia busca anterior. "
        "energia_de referencia consulta anterior com um carregador ou energia total; "
        "alternativamente energia_kwh deve ter sido explicitamente informada pelo "
        "usuário. Não determina o valor realmente cobrado de uma sessão individual."
    ),
}


class ErroExecucao(ValueError):
    """O plano ou os argumentos não podem ser executados com segurança."""


class ExecutorFerramentas:
    """Estado exclusivo de uma consulta; no máximo quatro chamadas, sem replanejar."""

    def __init__(
        self,
        operacao: Operacao,
        origem: str,
        recuperador: Callable[[str], list[Document]],
        contexto_usuario: str,
    ):
        self.operacao = operacao
        self.origem = origem
        self.recuperador = recuperador
        self.contexto_usuario = contexto_usuario
        self.resultados: list[ResultadoFerramenta] = []
        self.documentos: list[Document] = []
        self.documentos_por_etapa: dict[str, list[Document]] = {}
        self.fontes_adicionais: dict[str, tuple[str, dict]] = {}
        self._etapa = None
        definicoes = (
            ("consultar_operacao", self._operacao, ArgumentosOperacao),
            ("calcular_indicadores", self._indicadores, ArgumentosIndicadores),
            ("buscar_documentos", self._documentos, ArgumentosDocumentos),
            ("estimar_custo", self._custo, ArgumentosCusto),
        )
        self.ferramentas = {
            nome: StructuredTool.from_function(
                func=funcao, name=nome, description=DESCRICOES[nome], args_schema=schema
            )
            for nome, funcao, schema in definicoes
        }

    def executar(self, plano: PlanoConsulta) -> list[ResultadoFerramenta]:
        if self.resultados:
            raise ErroExecucao("Crie um executor por consulta.")
        plano = PlanoConsulta.model_validate(plano.model_dump())
        # Valida todo o plano antes da primeira chamada, inclusive textos gerados.
        for etapa in plano.etapas:
            if (
                etapa.ferramenta == "buscar_documentos"
                and not moderar_entrada(etapa.argumentos.pergunta).permitida
            ):
                raise ErroExecucao("Consulta documental não permitida.")
        for etapa in plano.etapas:
            self._etapa = etapa
            try:
                resultado = self.ferramentas[etapa.ferramenta].invoke(
                    etapa.argumentos.model_dump()
                )
            except (ErroRAG, httpx.HTTPError, ResponseError, ConnectionError):
                resultado = self._resultado(
                    "erro",
                    {},
                    ["A consulta documental está indisponível nesta execução."],
                )
            self._adicionar_fonte(resultado)
            self.resultados.append(resultado)
        return list(self.resultados)

    def _resultado(self, estado, dados, limitacoes=None, fontes=None):
        return ResultadoFerramenta(
            etapa_id=self._etapa.id,
            ferramenta=self._etapa.ferramenta,
            estado=estado,
            dados=dados,
            limitacoes=limitacoes or [],
            fontes=fontes or [],
        )

    def _adicionar_fonte(self, resultado):
        if resultado.ferramenta == "buscar_documentos" or not resultado.dados:
            return
        texto = json.dumps(
            {"dados": resultado.dados, "limitacoes": resultado.limitacoes},
            ensure_ascii=False,
        )
        fonte_id = f"resultado_{resultado.etapa_id}"
        meta = {
            "tipo": "operacional",
            "arquivo": "estimativa_python"
            if resultado.ferramenta == "estimar_custo"
            else self.origem,
            "secao": resultado.ferramenta,
        }
        self.fontes_adicionais[fonte_id] = (texto, meta)
        resultado.fontes.append(CitacaoFonte(fonte_id=fonte_id, trecho=texto, **meta))

    def _operacao(self, **kwargs):
        args = ArgumentosOperacao(**kwargs)
        registros = self.operacao.snapshot_carregadores.carregadores
        if args.carregador_id:
            registros = [r for r in registros if r.id == args.carregador_id]
            if not registros:
                return self._resultado(
                    "ausente",
                    {},
                    [f"O carregador {args.carregador_id} não consta da operação."],
                )
        notas = [i.mensagem for i in validar_totais(self.operacao)]
        if args.consulta == "resumo":
            dados = json.loads(construir_contexto_operacional(self.operacao))
        elif args.consulta == "demanda_horaria":
            dados = {
                "demanda_horaria": [
                    r.model_dump(mode="json") for r in self.operacao.demanda_horaria
                ]
            }
        elif args.consulta == "sessoes_individuais":
            maior = max(registros, key=lambda r: r.energia_entregue_kwh)
            return self._resultado(
                "parcial",
                {"maior_acumulado_por_carregador": maior.model_dump(mode="json")},
                [
                    "Não há registros de sessões individuais: não é possível identificar a maior recarga individual, sua data ou preço efetivamente cobrado. Os valores disponíveis são acumulados por carregador em várias sessões.",
                    *notas,
                ],
            )
        else:
            registros = sorted(
                registros,
                key=lambda r: getattr(r, args.ordenar_por),
                reverse=args.ordem == "desc",
            )
            dados = {
                "carregadores": [
                    r.model_dump(mode="json") for r in registros[: args.limite]
                ],
                "granularidade": "acumulados por carregador; potência instantânea no snapshot",
            }
        return self._resultado("sucesso", dados, notas)

    def _indicadores(self, **kwargs):
        args = ArgumentosIndicadores(**kwargs)
        calculados = json.loads(json.dumps(asdict(calcular_indicadores(self.operacao))))
        campos = {
            "pico": "pico",
            "energia_total": "energia_total_calculada_kwh",
            "sessoes_total": "total_sessoes",
            "throttling": "throttling",
            "ociosidade": "carregadores_ociosos",
            "faturamento": "faturamento_estimado_brl",
        }
        dados = (
            calculados
            if args.indicador == "todos"
            else {campos[args.indicador]: calculados[campos[args.indicador]]}
        )
        notas = [i.mensagem for i in validar_totais(self.operacao)]
        if args.indicador in {"todos", "faturamento"}:
            notas.append(
                "O faturamento é uma estimativa informada no JSON, sem valores cobrados por sessão ou decomposição tarifária."
            )
        return self._resultado("sucesso", dados, notas)

    def _documentos(self, **kwargs):
        args = ArgumentosDocumentos(**kwargs)
        docs = self.recuperador(args.pergunta)
        self.documentos_por_etapa[self._etapa.id] = docs
        conhecidos = {d.metadata["chunk_id"] for d in self.documentos}
        self.documentos.extend(
            d for d in docs if d.metadata["chunk_id"] not in conhecidos
        )
        return self._resultado(
            "sucesso" if docs else "ausente",
            {"chunks": [d.metadata["chunk_id"] for d in docs]},
            []
            if docs
            else ["Não foram recuperados trechos documentais para esta consulta."],
        )

    def _custo(self, **kwargs):
        args = ArgumentosCusto(**kwargs)
        docs = self.documentos_por_etapa.get(args.tarifa_de, [])
        candidatos = []
        for doc in docs:
            for match in re.finditer(
                r"\b(Urgente|Econ[oô]mico)\s*:\s*R\$\s*(\d+(?:[.,]\d+)?)\s*/\s*kWh",
                doc.page_content,
                flags=re.IGNORECASE,
            ):
                if normalizar_texto(match[1]) == args.modalidade:
                    candidatos.append(
                        (Decimal(match[2].replace(",", ".")), doc, match[0])
                    )
        if not candidatos or len({c[0] for c in candidatos}) != 1:
            return self._resultado(
                "ausente",
                {},
                [
                    "A tarifa solicitada não foi encontrada em formato suportado ou possui valores conflitantes nos trechos recuperados."
                ],
            )
        notas = []
        fontes = []
        if args.energia_de:
            anterior = next(r for r in self.resultados if r.etapa_id == args.energia_de)
            if anterior.estado != "sucesso":
                return self._resultado(
                    "ausente",
                    {},
                    [
                        "A consulta anterior não fornece energia suficiente para calcular o custo solicitado."
                    ],
                )
            dados = anterior.dados
            energia = dados.get(
                "energia_total_calculada_kwh",
                dados.get("resumo_calculado", {}).get("energia_total_calculada_kwh"),
            )
            if "carregadores" in dados:
                registros = dados["carregadores"]
                energia = (
                    registros[0]["energia_entregue_kwh"]
                    if len(registros) == 1
                    else None
                )
            if energia is None:
                return self._resultado(
                    "ausente",
                    {},
                    [
                        "Especifique a energia ou selecione um único carregador para a estimativa."
                    ],
                )
            notas.append(
                "Estimativa para energia acumulada, não valor efetivamente cobrado de uma sessão individual."
            )
            fontes.extend(anterior.fontes)
        else:
            energia = args.energia_kwh
            informadas = {
                Decimal(m.replace(",", "."))
                for m in re.findall(
                    r"(?<![\w.,])([0-9]+(?:[.,][0-9]+)?)\s*kWh\b",
                    self.contexto_usuario,
                    flags=re.IGNORECASE,
                )
            }
            if Decimal(str(energia)) not in informadas:
                raise ErroExecucao(
                    "Energia não foi informada pelo usuário nem obtida de uma ferramenta."
                )
            notas.append("Energia fornecida pelo usuário como premissa da estimativa.")
        tarifa, doc, trecho = candidatos[0]
        fontes.append(
            CitacaoFonte(
                fonte_id=doc.metadata["chunk_id"],
                tipo="documental",
                arquivo=doc.metadata["source"],
                pagina_pdf=doc.metadata["pagina_pdf"],
                trecho=trecho,
            )
        )
        total = (Decimal(str(energia)) * tarifa).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        return self._resultado(
            "sucesso",
            {
                "energia_kwh": energia,
                "tarifa_brl_kwh": float(tarifa),
                "modalidade": args.modalidade,
                "resultado_brl": float(total),
                "formula": f"{energia} kWh × R$ {tarifa}/kWh = R$ {total}",
                "natureza_tarifa": doc.metadata.get("natureza", "nao_declarada"),
                "premissas": [
                    "Somente energia; não inclui taxas adicionais não informadas."
                ],
            },
            notas,
            fontes,
        )
