"""Interface web local do ChargeGrid construída com Gradio."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from chargegrid.assistente import AssistenteChargeGrid, RespostaAssistente
from chargegrid.dashboards import criar_dashboard

SAUDACAO_CHAT = [{"role": "assistant", "content": "Olá! Como posso ajudar hoje?"}]


def formatar_resposta_markdown(resposta: RespostaAssistente) -> str:
    """Formata uma resposta do serviço para o componente de chat."""
    if not resposta.sucesso or resposta.dados is None:
        return resposta.mensagem

    dados = resposta.dados
    evidencias = "\n".join(f"- {item}" for item in dados.evidencias)
    recomendacoes = "\n".join(f"- {item}" for item in dados.recomendacoes)
    secoes = [
        dados.resumo_executivo,
        f"**Nível de risco:** {dados.nivel_risco.value}",
        f"**Evidências**\n{evidencias}",
        f"**Impacto**\n{dados.impacto}",
        f"**Recomendações**\n{recomendacoes}",
    ]
    if dados.limitacoes:
        limitacoes = "\n".join(f"- {item}" for item in dados.limitacoes)
        secoes.append(f"**Limitações**\n{limitacoes}")
    return "\n\n".join(secoes)


def processar_mensagem(
    mensagem: str,
    historico: list[dict[str, Any]] | None,
    session_id: str,
    assistente: AssistenteChargeGrid,
) -> tuple[str, list[dict[str, Any]]]:
    """Processa uma mensagem e atualiza o histórico visual do Gradio."""
    historico_atual = list(historico or SAUDACAO_CHAT)
    resposta = assistente.consultar(mensagem, session_id)
    historico_atual.extend(
        [
            {"role": "user", "content": mensagem},
            {
                "role": "assistant",
                "content": formatar_resposta_markdown(resposta),
            },
        ]
    )
    return "", historico_atual


def nova_conversa(
    session_id: str,
    assistente: AssistenteChargeGrid,
) -> tuple[list[dict[str, str]], str]:
    """Limpa a memória atual e cria um identificador para a nova conversa."""
    assistente.limpar_sessao(session_id)
    return list(SAUDACAO_CHAT), uuid4().hex


def construir_interface(assistente: AssistenteChargeGrid | None = None):
    """Cria a interface sem iniciar o servidor, permitindo testes e reuso."""
    import gradio as gr

    servico = assistente or AssistenteChargeGrid()
    dashboard = criar_dashboard(servico.operacao)

    with gr.Blocks(title="ChargeGrid Intelligence") as interface:
        session_id = gr.State(value=lambda: uuid4().hex)

        gr.Markdown(
            "# ChargeGrid Intelligence\n"
            "Assistente gerencial para análise da operação de recarga GoodWe."
        )

        with gr.Tab("Assistente"):
            chatbot = gr.Chatbot(
                value=list(SAUDACAO_CHAT),
                height=520,
                label="Conversa",
            )
            mensagem = gr.Textbox(
                placeholder="Pergunte sobre demanda, energia ou carregadores...",
                label="Sua pergunta",
                max_lines=4,
            )
            with gr.Row():
                enviar = gr.Button("Enviar", variant="primary")
                limpar = gr.Button("Nova conversa")

        with gr.Tab("Dashboard operacional"):
            gr.Plot(value=dashboard, label="Operação do dia anterior")

        def responder(texto, historico, sessao):
            return processar_mensagem(texto, historico, sessao, servico)

        def limpar_conversa(sessao):
            return nova_conversa(sessao, servico)

        enviar.click(
            responder,
            inputs=[mensagem, chatbot, session_id],
            outputs=[mensagem, chatbot],
        )
        mensagem.submit(
            responder,
            inputs=[mensagem, chatbot, session_id],
            outputs=[mensagem, chatbot],
        )
        limpar.click(
            limpar_conversa,
            inputs=[session_id],
            outputs=[chatbot, session_id],
            queue=False,
        )

    return interface


def main() -> None:
    """Inicia a interface web apenas na máquina local."""
    construir_interface().queue().launch(inbrowser=True, share=False)


if __name__ == "__main__":
    main()
