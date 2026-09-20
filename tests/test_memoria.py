"""Testes da memória volátil e isolada por sessão."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables.history import RunnableWithMessageHistory

from chain.memoria import (
    ArmazenamentoMemoria,
    ErroMemoria,
    HistoricoLimitado,
    configuracao_sessao,
    construir_chain_com_memoria,
)


def test_isola_historicos_por_sessao() -> None:
    memoria = ArmazenamentoMemoria(limite_tokens=100)

    memoria.obter_historico("sessao-a").add_messages(
        [HumanMessage(content="Pergunta A"), AIMessage(content="Resposta A")]
    )

    assert len(memoria.obter_historico("sessao-a").messages) == 2
    assert memoria.obter_historico("sessao-b").messages == []
    assert memoria.listar_sessoes() == ("sessao-a", "sessao-b")


def test_descarta_turnos_antigos_ao_exceder_limite() -> None:
    historico = HistoricoLimitado(limite_tokens=25)
    historico.add_messages(
        [HumanMessage(content="antiga " * 20), AIMessage(content="resposta antiga")]
    )
    historico.add_messages(
        [HumanMessage(content="recente"), AIMessage(content="resposta recente")]
    )

    conteudos = [str(mensagem.content) for mensagem in historico.messages]
    assert conteudos == ["recente", "resposta recente"]
    assert historico.total_tokens <= historico.limite_tokens


def test_limpa_uma_sessao_sem_afetar_as_demais() -> None:
    memoria = ArmazenamentoMemoria(limite_tokens=100)
    memoria.obter_historico("a")
    memoria.obter_historico("b")

    assert memoria.limpar_sessao("a") is True
    assert memoria.limpar_sessao("a") is False
    assert memoria.listar_sessoes() == ("b",)


def test_rejeita_identificador_vazio() -> None:
    memoria = ArmazenamentoMemoria(limite_tokens=100)

    with pytest.raises(ErroMemoria, match="não pode estar vazio"):
        memoria.obter_historico("   ")


def test_rejeita_limite_de_tokens_invalido() -> None:
    with pytest.raises(ErroMemoria, match="maior que zero"):
        ArmazenamentoMemoria(limite_tokens=0)


def test_monta_configuracao_da_sessao() -> None:
    assert configuracao_sessao(" usuario-1 ") == {
        "configurable": {"session_id": "usuario-1"}
    }


def test_constroi_chain_com_runnable_de_historico() -> None:
    chain = construir_chain_com_memoria(ArmazenamentoMemoria())

    assert len(chain.steps) == 2
    assert isinstance(chain.steps[0], RunnableWithMessageHistory)
