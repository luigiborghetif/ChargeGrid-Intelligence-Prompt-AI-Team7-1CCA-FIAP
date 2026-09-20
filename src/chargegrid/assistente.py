"""Serviço de aplicação que coordena o assistente ChargeGrid."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import httpx
from langchain_core.exceptions import OutputParserException
from langchain_core.runnables import Runnable
from ollama import ResponseError

from chain.builder import criar_entrada_chain
from chain.memoria import (
    ArmazenamentoMemoria,
    ErroMemoria,
    configuracao_sessao,
    construir_chain_com_memoria,
)
from chargegrid.config import Settings, settings
from chargegrid.dados import Operacao, carregar_operacao
from guardrails import avaliar_entrada
from schemas.consulta_recarga import ConsultaRecarga


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

    @property
    def sucesso(self) -> bool:
        return self.status is StatusResposta.SUCESSO


class AssistenteChargeGrid:
    """Executa o fluxo guardrails → memória → Ollama → schema."""

    def __init__(
        self,
        operacao: Operacao | None = None,
        memoria: ArmazenamentoMemoria | None = None,
        chain: Runnable[dict[str, Any], ConsultaRecarga] | None = None,
        configuracao: Settings | None = None,
    ) -> None:
        self.configuracao = configuracao or settings
        self.operacao = operacao or carregar_operacao(
            self.configuracao.data_path,
            alertar_inconsistencias=False,
        )
        self.memoria = memoria or ArmazenamentoMemoria(
            self.configuracao.memory_token_limit
        )
        self.chain = chain or construir_chain_com_memoria(
            armazenamento=self.memoria,
            configuracao=self.configuracao,
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
            resposta = self.chain.invoke(
                criar_entrada_chain(pergunta, self.operacao),
                config=configuracao_sessao(session_id),
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

    def limpar_sessao(self, session_id: str) -> bool:
        """Apaga o histórico de uma sessão."""
        return self.memoria.limpar_sessao(session_id)

    def listar_sessoes(self) -> tuple[str, ...]:
        """Retorna as sessões criadas durante a execução atual."""
        return self.memoria.listar_sessoes()
