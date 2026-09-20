"""Memória de conversa isolada por sessão para a chain do ChargeGrid."""

from __future__ import annotations

from collections.abc import Sequence
from threading import RLock
from typing import Any

from langchain_core.chat_history import InMemoryChatMessageHistory
from langchain_core.messages import BaseMessage
from langchain_core.messages.utils import count_tokens_approximately, trim_messages
from langchain_core.runnables import Runnable
from langchain_core.runnables.history import RunnableWithMessageHistory

from chain.builder import criar_llm, criar_parser, criar_prompt
from chargegrid.config import Settings, settings
from schemas.consulta_recarga import ConsultaRecarga


class ErroMemoria(ValueError):
    """Indica um identificador ou limite inválido para a memória."""


class HistoricoLimitado(InMemoryChatMessageHistory):
    """Histórico volátil que mantém apenas as mensagens mais recentes."""

    limite_tokens: int

    def model_post_init(self, __context: Any, /) -> None:
        if self.limite_tokens <= 0:
            raise ErroMemoria("O limite de tokens da memória deve ser maior que zero.")

    @property
    def total_tokens(self) -> int:
        """Retorna uma estimativa local do tamanho atual do histórico."""
        return count_tokens_approximately(self.messages)

    def _aplicar_limite(self) -> None:
        self.messages = trim_messages(
            self.messages,
            max_tokens=self.limite_tokens,
            token_counter=count_tokens_approximately,
            strategy="last",
            start_on="human",
            allow_partial=False,
        )

    def add_message(self, message: BaseMessage) -> None:
        """Adiciona uma mensagem e aplica o limite configurado."""
        self.messages.append(message)
        self._aplicar_limite()

    def add_messages(self, messages: Sequence[BaseMessage]) -> None:
        """Adiciona mensagens e descarta turnos antigos quando necessário."""
        self.messages.extend(messages)
        self._aplicar_limite()


class ArmazenamentoMemoria:
    """Registro em memória dos históricos, indexados por sessão."""

    def __init__(self, limite_tokens: int | None = None) -> None:
        self.limite_tokens = (
            settings.memory_token_limit if limite_tokens is None else limite_tokens
        )
        if self.limite_tokens <= 0:
            raise ErroMemoria("O limite de tokens da memória deve ser maior que zero.")

        self._sessoes: dict[str, HistoricoLimitado] = {}
        self._lock = RLock()

    @staticmethod
    def _validar_id_sessao(session_id: str) -> str:
        session_id = session_id.strip()
        if not session_id:
            raise ErroMemoria("O identificador da sessão não pode estar vazio.")
        return session_id

    def obter_historico(self, session_id: str) -> HistoricoLimitado:
        """Obtém o histórico existente ou cria uma sessão vazia."""
        session_id = self._validar_id_sessao(session_id)
        with self._lock:
            return self._sessoes.setdefault(
                session_id,
                HistoricoLimitado(limite_tokens=self.limite_tokens),
            )

    def limpar_sessao(self, session_id: str) -> bool:
        """Remove uma sessão e informa se ela existia."""
        session_id = self._validar_id_sessao(session_id)
        with self._lock:
            return self._sessoes.pop(session_id, None) is not None

    def limpar_todas(self) -> None:
        """Remove todos os históricos armazenados."""
        with self._lock:
            self._sessoes.clear()

    def listar_sessoes(self) -> tuple[str, ...]:
        """Lista os identificadores ativos em ordem alfabética."""
        with self._lock:
            return tuple(sorted(self._sessoes))


def construir_chain_com_memoria(
    armazenamento: ArmazenamentoMemoria | None = None,
    configuracao: Settings | None = None,
) -> Runnable[dict[str, Any], ConsultaRecarga]:
    """Monta prompt | Ollama com histórico por sessão | parser Pydantic."""
    config = configuracao or settings
    memoria = armazenamento or ArmazenamentoMemoria(config.memory_token_limit)
    parser = criar_parser()
    prompt = criar_prompt(parser, config.prompt_path)
    llm = criar_llm(config)

    chain_com_historico = RunnableWithMessageHistory(
        prompt | llm,
        memoria.obter_historico,
        input_messages_key="pergunta",
        history_messages_key="history",
    )
    return chain_com_historico | parser


def configuracao_sessao(session_id: str) -> dict[str, dict[str, str]]:
    """Cria a configuração exigida pelo RunnableWithMessageHistory."""
    session_id = ArmazenamentoMemoria._validar_id_sessao(session_id)
    return {"configurable": {"session_id": session_id}}
