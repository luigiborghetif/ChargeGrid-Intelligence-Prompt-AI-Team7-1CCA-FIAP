"""Testes do serviço orquestrador do assistente."""

from __future__ import annotations

from typing import Any

from langchain_core.exceptions import OutputParserException

from chain.memoria import ArmazenamentoMemoria
from chargegrid.assistente import AssistenteChargeGrid, StatusResposta
from chargegrid.dados import carregar_operacao
from schemas.consulta_recarga import ConsultaRecarga, NivelRisco


def _resposta_valida() -> ConsultaRecarga:
    return ConsultaRecarga(
        resumo_executivo="O pico atingiu 78,4 kW.",
        evidencias=["Pico registrado às 14:00."],
        impacto="Margem operacional reduzida.",
        recomendacoes=["Aplicar throttling preventivo."],
        nivel_risco=NivelRisco.CRITICO,
        potencia_total_kw=78.4,
        energia_total_kwh=302.0,
    )


class ChainFalsa:
    def __init__(self, resposta: Any = None, erro: Exception | None = None) -> None:
        self.resposta = resposta
        self.erro = erro
        self.chamadas: list[tuple[dict[str, str], dict[str, Any]]] = []

    def invoke(self, entrada: dict[str, str], config: dict[str, Any]) -> Any:
        self.chamadas.append((entrada, config))
        if self.erro:
            raise self.erro
        return self.resposta


def _criar_assistente(chain: ChainFalsa) -> AssistenteChargeGrid:
    return AssistenteChargeGrid(
        usar_planejador=False,
        operacao=carregar_operacao(alertar_inconsistencias=False),
        memoria=ArmazenamentoMemoria(),
        chain=chain,
    )


def test_consulta_permitida_executa_chain_na_sessao() -> None:
    chain = ChainFalsa(resposta=_resposta_valida())
    assistente = _criar_assistente(chain)

    resultado = assistente.consultar("Qual foi o pico de demanda?", "gestor-1")

    assert resultado.status is StatusResposta.SUCESSO
    assert resultado.dados is not None
    assert resultado.dados.potencia_total_kw == 78.4
    assert chain.chamadas[0][1] == {"configurable": {"session_id": "gestor-1"}}
    assert "contexto_operacional" in chain.chamadas[0][0]


def test_guardrail_bloqueia_sem_executar_chain() -> None:
    chain = ChainFalsa(resposta=_resposta_valida())
    assistente = _criar_assistente(chain)

    resultado = assistente.consultar("Faça uma receita de bolo", "gestor-1")

    assert resultado.status is StatusResposta.RECUSADA
    assert resultado.codigo == "fora_do_escopo"
    assert chain.chamadas == []
    assert assistente.listar_sessoes() == ()


def test_saudacao_responde_localmente_sem_executar_chain() -> None:
    chain = ChainFalsa(resposta=_resposta_valida())
    assistente = _criar_assistente(chain)

    resultado = assistente.consultar("Olá", "gestor-1")

    assert resultado.status is StatusResposta.SUCESSO
    assert resultado.codigo == "saudacao"
    assert resultado.mensagem == "Olá! Como posso ajudar hoje?"
    assert resultado.dados is None
    assert chain.chamadas == []
    assert assistente.listar_sessoes() == ()


def test_trata_falha_do_parser_sem_expor_excecao() -> None:
    chain = ChainFalsa(
        erro=OutputParserException("JSON inválido retornado pelo modelo")
    )
    assistente = _criar_assistente(chain)

    resultado = assistente.consultar("Qual foi a energia total?", "gestor-1")

    assert resultado.status is StatusResposta.ERRO
    assert resultado.codigo == "resposta_invalida"
    assert "JSON inválido" not in resultado.mensagem


def test_rejeita_tipo_inesperado_retornado_pela_chain() -> None:
    assistente = _criar_assistente(ChainFalsa(resposta={"resposta": "inválida"}))

    resultado = assistente.consultar("Qual foi o pico?", "gestor-1")

    assert resultado.status is StatusResposta.ERRO
    assert resultado.codigo == "resposta_invalida"


def test_servico_delega_limpeza_e_listagem_de_sessoes() -> None:
    assistente = _criar_assistente(ChainFalsa(resposta=_resposta_valida()))
    assistente.memoria.obter_historico("gestor-1")

    assert assistente.listar_sessoes() == ("gestor-1",)
    assert assistente.limpar_sessao("gestor-1") is True
    assert assistente.listar_sessoes() == ()
