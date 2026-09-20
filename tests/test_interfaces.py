"""Testes das interfaces sem iniciar servidor ou consultar o Ollama."""

from __future__ import annotations

from chargegrid.app import SAUDACAO_CHAT, nova_conversa, processar_mensagem
from chargegrid.assistente import RespostaAssistente, StatusResposta
from chargegrid.cli import executar_cli
from schemas.consulta_recarga import ConsultaRecarga, NivelRisco


def _resposta() -> RespostaAssistente:
    dados = ConsultaRecarga(
        resumo_executivo="Pico de 78,4 kW às 14:00.",
        evidencias=["O pico corresponde a 98% do limite."],
        impacto="Margem reduzida.",
        recomendacoes=["Aplicar throttling."],
        nivel_risco=NivelRisco.CRITICO,
        limitacoes=["Energia informada diverge da calculada."],
    )
    return RespostaAssistente(
        status=StatusResposta.SUCESSO,
        codigo="consulta_concluida",
        mensagem=dados.resumo_executivo,
        dados=dados,
    )


class AssistenteFalso:
    def __init__(self) -> None:
        self.consultas: list[tuple[str, str]] = []
        self.sessoes_limpas: list[str] = []

    def consultar(self, pergunta: str, session_id: str) -> RespostaAssistente:
        self.consultas.append((pergunta, session_id))
        return _resposta()

    def limpar_sessao(self, session_id: str) -> bool:
        self.sessoes_limpas.append(session_id)
        return True


def test_cli_consulta_limpa_e_encerra() -> None:
    assistente = AssistenteFalso()
    entradas = iter(["Qual foi o pico?", "/limpar", "/sair"])
    saidas: list[str] = []

    executar_cli(
        assistente,  # type: ignore[arg-type]
        session_id="cli-1",
        input_fn=lambda _: next(entradas),
        output_fn=saidas.append,
    )

    assert assistente.consultas == [("Qual foi o pico?", "cli-1")]
    assert assistente.sessoes_limpas == ["cli-1"]
    assert any("78,4 kW" in saida for saida in saidas)
    assert saidas[-1] == "Até logo!"


def test_gradio_processa_mensagem_na_sessao() -> None:
    assistente = AssistenteFalso()

    campo, historico = processar_mensagem(
        "Qual foi o pico?",
        list(SAUDACAO_CHAT),
        "web-1",
        assistente,  # type: ignore[arg-type]
    )

    assert campo == ""
    assert assistente.consultas == [("Qual foi o pico?", "web-1")]
    assert [mensagem["role"] for mensagem in historico] == [
        "assistant",
        "user",
        "assistant",
    ]
    assert "**Nível de risco:** critico" in historico[-1]["content"]


def test_gradio_nova_conversa_limpa_memoria_e_troca_id() -> None:
    assistente = AssistenteFalso()

    historico, novo_id = nova_conversa(
        "web-1",
        assistente,  # type: ignore[arg-type]
    )

    assert assistente.sessoes_limpas == ["web-1"]
    assert historico == SAUDACAO_CHAT
    assert novo_id != "web-1"
