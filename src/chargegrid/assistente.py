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

from chain.builder import criar_entrada_chain
from chain.memoria import (
    ArmazenamentoMemoria,
    ErroMemoria,
    configuracao_sessao,
    construir_chain_com_memoria,
)
from chargegrid.config import PROJECT_ROOT, Settings, settings
from chargegrid.dados import Operacao, carregar_operacao
from guardrails import avaliar_entrada
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
from schemas.resposta_rag import RespostaFundamentada


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
        self.configuracao_rag = configuracao_rag or RAGSettings.from_env()
        self.chain = chain or (
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
        decisao = avaliar_entrada(pergunta)
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
        referencias, usados = conferir_apoios(
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
            ),
        )

    def limpar_sessao(self, session_id: str) -> bool:
        """Apaga o histórico de uma sessão."""
        return self.memoria.limpar_sessao(session_id)

    def listar_sessoes(self) -> tuple[str, ...]:
        """Retorna as sessões criadas durante a execução atual."""
        return self.memoria.listar_sessoes()
