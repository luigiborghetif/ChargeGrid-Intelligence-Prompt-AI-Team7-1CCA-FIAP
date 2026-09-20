"""Interface de terminal do ChargeGrid Intelligence."""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from chargegrid.assistente import AssistenteChargeGrid, RespostaAssistente

SAUDACAO = "Olá! Como posso ajudar hoje?"
AJUDA = "Comandos disponíveis: /limpar, /ajuda e /sair."


def formatar_resposta_terminal(resposta: RespostaAssistente) -> str:
    """Converte o envelope do serviço em texto legível no terminal."""
    if not resposta.sucesso or resposta.dados is None:
        return resposta.mensagem

    dados = resposta.dados
    linhas = [dados.resumo_executivo, "", f"Risco: {dados.nivel_risco.value}"]

    linhas.extend(("", "Evidências:"))
    linhas.extend(f"- {item}" for item in dados.evidencias)
    linhas.extend(("", f"Impacto: {dados.impacto}", "", "Recomendações:"))
    linhas.extend(f"- {item}" for item in dados.recomendacoes)

    if dados.limitacoes:
        linhas.extend(("", "Limitações:"))
        linhas.extend(f"- {item}" for item in dados.limitacoes)

    return "\n".join(linhas)


def executar_cli(
    assistente: AssistenteChargeGrid,
    session_id: str | None = None,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> None:
    """Executa o loop interativo, com dependências substituíveis em testes."""
    sessao = session_id or uuid4().hex
    output_fn(SAUDACAO)
    output_fn(AJUDA)

    while True:
        try:
            pergunta = input_fn("\nVocê: ").strip()
        except (EOFError, KeyboardInterrupt):
            output_fn("\nAté logo!")
            break

        comando = pergunta.casefold()
        if comando == "/sair":
            output_fn("Até logo!")
            break
        if comando == "/ajuda":
            output_fn(AJUDA)
            continue
        if comando == "/limpar":
            assistente.limpar_sessao(sessao)
            output_fn("Histórico da conversa apagado.")
            continue

        resposta = assistente.consultar(pergunta, sessao)
        output_fn("\nChargeGrid: " + formatar_resposta_terminal(resposta))


def main() -> None:
    """Ponto de entrada do comando `chargegrid`."""
    executar_cli(AssistenteChargeGrid())


if __name__ == "__main__":
    main()
