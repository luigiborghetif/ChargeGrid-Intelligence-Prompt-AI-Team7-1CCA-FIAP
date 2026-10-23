"""Serviço de aplicação que coordena o assistente ChargeGrid."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import httpx
from langchain_core.documents import Document
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import Runnable
from ollama import ResponseError
from pydantic import ValidationError

from chain.builder import ErroChain, criar_entrada_chain
from chain.memoria import (
    ArmazenamentoMemoria,
    ErroMemoria,
    configuracao_sessao,
    construir_chain_com_memoria,
)
from chain.planejador import construir_planejador, construir_resposta_planejada
from chargegrid.config import PROJECT_ROOT, Settings, settings
from chargegrid.dados import Operacao, carregar_operacao
from guardrails import avaliar_entrada
from guardrails.documentos import modelos_sem_evidencia, triar_documentos
from guardrails.moderation import CategoriaModeracao, moderar_entrada
from rag.config import RAGSettings
from rag.errors import ErroRAG
from rag.integracao import (
    ErroFundamentacao,
    conferir_apoios,
    construir_chain_integrada,
    contexto_operacional_com_origem,
)
from rag.prompt_rag import formatar_contexto
from rag.retriever import buscar_documentos
from rag.roteamento import (
    TipoConsulta,
    classificar_consulta,
    eh_continuacao,
    resolver_pergunta,
)
from schemas.consulta_recarga import ConsultaRecarga
from schemas.plano_consulta import PlanoConsulta, ResultadoFerramenta
from schemas.resposta_rag import CitacaoFonte, RespostaDocumental, RespostaFundamentada
from tools.executor import DESCRICOES, ErroExecucao, ExecutorFerramentas


class StatusResposta(StrEnum):
    """Estados possíveis de uma consulta ao serviço."""

    SUCESSO = "sucesso"
    RECUSADA = "recusada"
    ERRO = "erro"


@dataclass(frozen=True, slots=True)
class RespostaAssistente:
    """Envelope estável retornado à CLI ou a outra interface."""

    status: StatusResposta
    codigo: str
    mensagem: str
    dados: ConsultaRecarga | None = None
    tipo_consulta: str | None = None
    fontes: tuple[str, ...] = ()
    citacoes: tuple[CitacaoFonte, ...] = ()
    documental: RespostaDocumental | None = None
    plano: PlanoConsulta | None = None
    resultados_ferramentas: tuple[ResultadoFerramenta, ...] = ()

    @property
    def sucesso(self) -> bool:
        return self.status is StatusResposta.SUCESSO


class AssistenteChargeGrid:
    """Coordena guardrails, fontes operacionais/documentais e memória por sessão."""

    def __init__(
        self,
        operacao: Operacao | None = None,
        memoria: ArmazenamentoMemoria | None = None,
        chain: Runnable[dict[str, Any], ConsultaRecarga] | None = None,
        configuracao: Settings | None = None,
        configuracao_rag: RAGSettings | None = None,
        chain_rag: Runnable | None = None,
        recuperador: Callable[[str], list[Document]] | None = None,
        usar_rag: bool = True,
        usar_planejador: bool | None = None,
        planejador: Runnable | None = None,
        chain_resposta: Runnable | None = None,
    ) -> None:
        self.configuracao = configuracao or settings
        origem = self.configuracao.data_path
        self.origem_operacao = (
            (
                str(origem.relative_to(PROJECT_ROOT))
                if origem.is_relative_to(PROJECT_ROOT)
                else origem.name
            )
            if operacao is None
            else "operacao_fornecida_em_memoria"
        )
        self.operacao = operacao or carregar_operacao(
            self.configuracao.data_path,
            alertar_inconsistencias=False,
        )
        self.memoria = memoria or ArmazenamentoMemoria(
            self.configuracao.memory_token_limit
        )
        self.usar_rag = usar_rag
        self.usar_planejador = usar_rag and (
            self.configuracao.planner_enabled
            if usar_planejador is None
            else usar_planejador
        )
        self.planejador = planejador
        self.chain_resposta = chain_resposta
        self.configuracao_rag = configuracao_rag or RAGSettings.from_env()
        self.chain = chain
        if self.chain is None and not self.usar_planejador:
            self.chain = (
                construir_chain_integrada(
                    self.configuracao, self.configuracao_rag, operacional=True
                )
                if usar_rag
                else construir_chain_com_memoria(
                    armazenamento=self.memoria,
                    configuracao=self.configuracao,
                )
            )
        self.chain_rag = chain_rag
        self.recuperador = recuperador or (
            lambda pergunta: buscar_documentos(pergunta, self.configuracao_rag)
        )

    def consultar(self, pergunta: str, session_id: str) -> RespostaAssistente:
        """Processa uma pergunta sem chamar o modelo quando ela for bloqueada."""
        decisao = avaliar_entrada(pergunta, escopo_semantico=self.usar_planejador)
        if not decisao.permitida:
            return RespostaAssistente(
                status=StatusResposta.RECUSADA,
                codigo=decisao.codigo,
                mensagem=decisao.mensagem or "Solicitação recusada pelos guardrails.",
            )

        if decisao.codigo == "saudacao":
            return RespostaAssistente(
                status=StatusResposta.SUCESSO,
                codigo="saudacao",
                mensagem="Olá! Como posso ajudar hoje?",
            )

        try:
            sessao = configuracao_sessao(session_id)
            if self.usar_planejador:
                return self._consultar_planejado(pergunta.strip(), session_id, sessao)
            if self.usar_rag:
                return self._consultar_integrado(
                    pergunta.strip(), session_id, sessao, decisao.codigo
                )
            resposta = self.chain.invoke(
                criar_entrada_chain(pergunta, self.operacao), config=sessao
            )
        except ErroMemoria:
            return RespostaAssistente(
                status=StatusResposta.ERRO,
                codigo="sessao_invalida",
                mensagem="Não foi possível identificar a sessão da conversa.",
            )
        except (ErroExecucao, ErroChain, ValidationError):
            return RespostaAssistente(
                StatusResposta.ERRO,
                "plano_invalido",
                "Não foi possível executar um plano válido para esta consulta. Reformule a pergunta ou confira a configuração dos prompts.",
            )
        except OutputParserException:
            return RespostaAssistente(
                status=StatusResposta.ERRO,
                codigo="resposta_invalida",
                mensagem=(
                    "O modelo retornou uma resposta fora do formato esperado. "
                    "Tente formular a pergunta novamente."
                ),
            )
        except ErroFundamentacao:
            return RespostaAssistente(
                status=StatusResposta.RECUSADA,
                codigo="evidencia_invalida",
                mensagem="Não foi possível confirmar os apoios da resposta nas fontes fornecidas. Reformule a pergunta.",
            )
        except ErroRAG:
            return RespostaAssistente(
                status=StatusResposta.ERRO,
                codigo="rag_indisponivel",
                mensagem="Não foi possível recuperar os documentos. Verifique o Ollama e o índice documental configurado.",
            )
        except (ResponseError, httpx.HTTPError, ConnectionError):
            return RespostaAssistente(
                status=StatusResposta.ERRO,
                codigo="ollama_indisponivel",
                mensagem=(
                    "Não foi possível consultar o modelo agora. Verifique se o "
                    "Ollama está em execução e tente novamente."
                ),
            )

        if not isinstance(resposta, ConsultaRecarga):
            return RespostaAssistente(
                status=StatusResposta.ERRO,
                codigo="resposta_invalida",
                mensagem="O modelo retornou um tipo de resposta inesperado.",
            )

        return RespostaAssistente(
            status=StatusResposta.SUCESSO,
            codigo="consulta_concluida",
            mensagem=resposta.resumo_executivo,
            dados=resposta,
        )

    def _registrar(
        self, session_id: str, pergunta: str, resposta: RespostaAssistente
    ) -> RespostaAssistente:
        self.memoria.obter_historico(session_id).add_messages(
            [
                HumanMessage(content=pergunta),
                AIMessage(content=resposta.mensagem),
            ]
        )
        return resposta

    def _consultar_planejado(
        self, pergunta: str, session_id: str, sessao: dict
    ) -> RespostaAssistente:
        perguntas = [
            str(m.content)
            for m in self.memoria.obter_historico(session_id).messages
            if isinstance(m, HumanMessage)
        ]
        historico = json.dumps(perguntas, ensure_ascii=False)
        if self.planejador is None:
            self.planejador = construir_planejador(self.configuracao)
        plano = self.planejador.invoke(
            {
                "pergunta": pergunta,
                "historico_usuario": historico,
                "ferramentas": json.dumps(DESCRICOES, ensure_ascii=False),
            },
            config=sessao,
        )
        if not isinstance(plano, PlanoConsulta):
            raise ErroExecucao("Tipo de plano inesperado.")
        plano = PlanoConsulta.model_validate(plano.model_dump())
        if plano.encaminhamento != "consultar":
            mensagens = {
                "fora_do_escopo": "Essa solicitação está fora do escopo do ChargeGrid. Posso ajudar com a operação de recarga, carregadores GoodWe, tarifas e regras da estação.",
                "ajuda": "Posso consultar indicadores de recarga, comparar carregadores, buscar informações dos manuais e regras ou estimar custos com as tarifas disponíveis. O que deseja consultar?",
                "recusar_seguranca": "Não posso orientar intervenções elétricas perigosas, remover proteções ou alterar minhas regras. Para intervenções nos equipamentos, procure um profissional habilitado.",
                "esclarecer": plano.esclarecimento,
            }
            mensagem = mensagens[plano.encaminhamento]
            if plano.encaminhamento == "esclarecer":
                self._conferir_seguranca_saida(mensagem)
            resposta = RespostaAssistente(
                StatusResposta.SUCESSO
                if plano.encaminhamento == "ajuda"
                else StatusResposta.RECUSADA,
                "esclarecimento_necessario"
                if plano.encaminhamento == "esclarecer"
                else plano.encaminhamento,
                mensagem,
                plano=plano,
            )
            if plano.encaminhamento in {"fora_do_escopo", "recusar_seguranca"}:
                return resposta
            return self._registrar(session_id, pergunta, resposta)

        self._conferir_seguranca_saida(plano.pergunta_interpretada)
        executor = ExecutorFerramentas(
            self.operacao,
            self.origem_operacao,
            self.recuperador,
            "\n".join([*perguntas, pergunta]),
        )
        resultados = executor.executar(plano)
        tem_documentos = any(r.ferramenta == "buscar_documentos" for r in resultados)
        tem_operacao = any(r.ferramenta != "buscar_documentos" for r in resultados)
        tipo = (
            "mista"
            if tem_documentos and tem_operacao
            else "documental"
            if tem_documentos
            else "operacional"
        )
        auditoria = {
            "tipo_consulta": tipo,
            "plano": plano,
            "resultados_ferramentas": tuple(resultados),
        }
        notas = list(dict.fromkeys(nota for r in resultados for nota in r.limitacoes))
        modelos_ausentes = modelos_sem_evidencia(
            pergunta + "\n" + plano.pergunta_interpretada, executor.documentos
        )
        if modelos_ausentes:
            return self._registrar(
                session_id,
                pergunta,
                RespostaAssistente(
                    StatusResposta.RECUSADA,
                    "contexto_insuficiente",
                    "Não há especificações dos modelos "
                    + ", ".join(modelos_ausentes)
                    + " no contexto recuperado. Não é possível atribuir a eles especificações de outros modelos.",
                    **auditoria,
                ),
            )
        if not executor.documentos and not executor.fontes_adicionais:
            falhou = any(r.estado == "erro" for r in resultados)
            return self._registrar(
                session_id,
                pergunta,
                RespostaAssistente(
                    StatusResposta.ERRO if falhou else StatusResposta.RECUSADA,
                    "ferramenta_indisponivel" if falhou else "contexto_insuficiente",
                    " ".join(notas)
                    or "Não há evidências suficientes para essa consulta.",
                    **auditoria,
                ),
            )
        if self.chain_resposta is None:
            self.chain_resposta = construir_resposta_planejada(self.configuracao)
        fontes = {
            "documentos": json.loads(formatar_contexto(executor.documentos)),
            "resultados": [
                {"fonte_id": id_fonte, "conteudo": texto, **meta}
                for id_fonte, (texto, meta) in executor.fontes_adicionais.items()
            ],
        }
        resposta = self.chain_resposta.invoke(
            {
                "pergunta": pergunta,
                "historico_usuario": historico,
                "plano": plano.model_dump_json(),
                "resultados": json.dumps(
                    [r.model_dump(mode="json") for r in resultados], ensure_ascii=False
                ),
                "fontes": json.dumps(fontes, ensure_ascii=False),
            },
            config=sessao,
        )
        if not isinstance(resposta, RespostaFundamentada):
            raise ErroExecucao("Tipo de resposta inesperado.")
        self._conferir_seguranca_saida(resposta.resposta)
        for nota in resposta.limitacoes:
            self._conferir_seguranca_saida(nota)
        citacoes, usados = conferir_apoios(
            resposta,
            executor.documentos,
            None,
            self.origem_operacao,
            fontes_adicionais=executor.fontes_adicionais,
        )
        incompleta = resposta.insuficiente or any(
            r.estado != "sucesso" for r in resultados
        )
        if not usados:
            return self._registrar(
                session_id,
                pergunta,
                RespostaAssistente(
                    StatusResposta.RECUSADA,
                    "contexto_insuficiente",
                    " ".join(notas)
                    if notas
                    else f"O contexto recuperado não fornece evidências suficientes para responder à pergunta: {pergunta}",
                    **auditoria,
                ),
            )
        if not incompleta:
            tipos_citados = {c.tipo for c in citacoes}
            if (tem_operacao and "operacional" not in tipos_citados) or (
                tem_documentos and "documental" not in tipos_citados
            ):
                raise ErroFundamentacao(
                    "Resposta completa sem os tipos de fonte necessários."
                )
            for resultado in resultados:
                if resultado.ferramenta == "estimar_custo" and not {
                    f.fonte_id for f in resultado.fontes
                }.issubset(usados):
                    raise ErroFundamentacao(
                        "Estimativa sem as fontes dos valores de entrada e do cálculo."
                    )
        documental = RespostaDocumental(
            resposta=resposta.resposta,
            insuficiente=incompleta,
            citacoes=citacoes,
            limitacoes=list(dict.fromkeys([*resposta.limitacoes, *notas])),
        )
        referencias = tuple(c.referencia for c in citacoes)
        mensagem = documental.resposta
        if documental.limitacoes:
            mensagem += "\n\nLimitações:\n" + "\n".join(
                f"- {n}" for n in documental.limitacoes
            )
        mensagem += "\n\nFontes utilizadas:\n" + "\n".join(
            f"- {r}" for r in referencias
        )
        return self._registrar(
            session_id,
            pergunta,
            RespostaAssistente(
                StatusResposta.RECUSADA if incompleta else StatusResposta.SUCESSO,
                "contexto_insuficiente" if incompleta else f"consulta_{tipo}_concluida",
                mensagem,
                documental=documental,
                citacoes=tuple(citacoes),
                fontes=referencias,
                **auditoria,
            ),
        )

    @staticmethod
    def _conferir_seguranca_saida(texto: str) -> None:
        moderacao = moderar_entrada(texto)
        if moderacao.categoria in {
            CategoriaModeracao.INJECAO_PROMPT,
            CategoriaModeracao.INTERVENCAO_PERIGOSA,
        }:
            raise ErroFundamentacao(
                "Saída não permitida pelas verificações de segurança."
            )

    def _consultar_integrado(
        self, pergunta: str, session_id: str, sessao: dict, codigo: str
    ) -> RespostaAssistente:
        historico = self.memoria.obter_historico(session_id)
        perguntas = [
            str(m.content) for m in historico.messages if isinstance(m, HumanMessage)
        ]
        if not perguntas and (
            codigo == "continuacao"
            or (eh_continuacao(pergunta) and pergunta.casefold().startswith("e "))
        ):
            return RespostaAssistente(
                StatusResposta.RECUSADA,
                "contexto_ausente",
                "Informe qual carregador, regra ou dado você deseja consultar para iniciar a conversa.",
            )
        pergunta_busca = resolver_pergunta(
            pergunta, perguntas[-1] if perguntas else None
        )
        tipo = classificar_consulta(pergunta_busca)
        documentos = (
            self.recuperador(pergunta_busca) if tipo != TipoConsulta.OPERACIONAL else []
        )
        documentos = triar_documentos(documentos).documentos
        modelos_ausentes = modelos_sem_evidencia(pergunta_busca, documentos)
        if modelos_ausentes and tipo != TipoConsulta.OPERACIONAL:
            return self._registrar(
                session_id,
                pergunta,
                RespostaAssistente(
                    StatusResposta.RECUSADA,
                    "contexto_insuficiente",
                    "Não há especificações dos modelos "
                    + ", ".join(modelos_ausentes)
                    + " no contexto recuperado.",
                    tipo_consulta=tipo.value,
                ),
            )
        if tipo == TipoConsulta.DOCUMENTAL and not documentos:
            return self._registrar(
                session_id,
                pergunta,
                RespostaAssistente(
                    StatusResposta.RECUSADA,
                    "contexto_insuficiente",
                    "Não há evidências suficientes no contexto recuperado para responder à pergunta.",
                    tipo_consulta=tipo.value,
                ),
            )
        contexto_op = None
        origem_texto = self.origem_operacao
        if tipo != TipoConsulta.DOCUMENTAL:
            bruto = criar_entrada_chain(pergunta, self.operacao)["contexto_operacional"]
            contexto_op = contexto_operacional_com_origem(bruto, origem_texto)
        entrada = {
            "pergunta": pergunta,
            "tipo_consulta": tipo.value,
            "contexto_operacional": contexto_op
            or "Nenhum registro operacional fornecido para esta consulta.",
            "contexto_documental": formatar_contexto(documentos),
            "historico_usuario": json.dumps(perguntas, ensure_ascii=False),
        }
        if tipo == TipoConsulta.OPERACIONAL:
            dados = self.chain.invoke(entrada, config=sessao)
            if not isinstance(dados, ConsultaRecarga):
                return RespostaAssistente(
                    StatusResposta.ERRO,
                    "resposta_invalida",
                    "O modelo retornou um tipo de resposta inesperado.",
                )
            referencia = f"Fonte operacional: {origem_texto} — JSON validado e indicadores calculados em Python."
            dados = dados.model_copy(
                update={"evidencias": [*dados.evidencias, referencia]}
            )
            return self._registrar(
                session_id,
                pergunta,
                RespostaAssistente(
                    StatusResposta.SUCESSO,
                    "consulta_concluida",
                    dados.resumo_executivo,
                    dados=dados,
                    tipo_consulta=tipo.value,
                    fontes=(referencia,),
                    citacoes=(
                        CitacaoFonte(
                            fonte_id="operacao_atual",
                            tipo="operacional",
                            arquivo=origem_texto,
                            secao="resumo_calculado",
                            trecho=json.dumps(
                                json.loads(bruto)["resumo_calculado"],
                                ensure_ascii=False,
                            ),
                        ),
                    ),
                ),
            )
        if self.chain_rag is None:
            self.chain_rag = construir_chain_integrada(
                self.configuracao, self.configuracao_rag, operacional=False
            )
        resposta = self.chain_rag.invoke(entrada, config=sessao)
        if not isinstance(resposta, RespostaFundamentada):
            return RespostaAssistente(
                StatusResposta.ERRO,
                "resposta_invalida",
                "O modelo retornou um tipo de resposta inesperado.",
            )
        citacoes, usados = conferir_apoios(
            resposta, documentos, contexto_op, origem_texto
        )
        if not usados or (
            tipo == TipoConsulta.MISTA
            and not resposta.insuficiente
            and ("operacao_atual" not in usados or not (usados - {"operacao_atual"}))
        ):
            return self._registrar(
                session_id,
                pergunta,
                RespostaAssistente(
                    StatusResposta.RECUSADA,
                    "contexto_insuficiente",
                    "Não há evidências suficientes para sustentar todas as partes da pergunta.",
                    tipo_consulta=tipo.value,
                ),
            )
        documental = RespostaDocumental(
            resposta=resposta.resposta,
            insuficiente=resposta.insuficiente,
            citacoes=citacoes,
            limitacoes=resposta.limitacoes,
        )
        referencias = [citacao.referencia for citacao in citacoes]
        mensagem = resposta.resposta
        if resposta.limitacoes:
            mensagem += "\n\nLimitações:\n" + "\n".join(
                f"- {item}" for item in resposta.limitacoes
            )
        mensagem += "\n\nFontes utilizadas:\n" + "\n".join(
            f"- {item}" for item in referencias
        )
        return self._registrar(
            session_id,
            pergunta,
            RespostaAssistente(
                StatusResposta.RECUSADA
                if resposta.insuficiente
                else StatusResposta.SUCESSO,
                "contexto_insuficiente"
                if resposta.insuficiente
                else f"consulta_{tipo.value}_concluida",
                mensagem,
                tipo_consulta=tipo.value,
                fontes=tuple(referencias),
                citacoes=tuple(citacoes),
                documental=documental,
            ),
        )

    def limpar_sessao(self, session_id: str) -> bool:
        """Apaga o histórico de uma sessão."""
        return self.memoria.limpar_sessao(session_id)

    def listar_sessoes(self) -> tuple[str, ...]:
        """Retorna as sessões criadas durante a execução atual."""
        return self.memoria.listar_sessoes()
