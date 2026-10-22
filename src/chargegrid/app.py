"""Interface web local do ChargeGrid construída com Gradio."""

from __future__ import annotations

import html
import re
from typing import Any
from uuid import uuid4

from chargegrid.assistente import AssistenteChargeGrid, RespostaAssistente
from chargegrid.dashboards import criar_dashboard

SAUDACAO_CHAT = [{"role": "assistant", "content": "Olá! Como posso ajudar hoje?"}]


def _texto_literal(texto: str) -> str:
    """Exibe trechos e metadados como texto, sem links ou HTML dos documentos."""
    texto = re.sub(r"<br\s*/?>", " ", texto, flags=re.IGNORECASE)
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", html.escape(texto))


def _formatar_citacoes(resposta: RespostaAssistente) -> str:
    if not resposta.citacoes:
        return ""
    blocos = ["**Fontes utilizadas**"]
    for indice, citacao in enumerate(resposta.citacoes, start=1):
        local = (
            f"página PDF {citacao.pagina_pdf}"
            if citacao.tipo == "documental"
            else "dados operacionais — indicadores calculados em Python"
        )
        if citacao.secao:
            local += f" — {citacao.secao}"
        trecho = "\n".join(
            f"> {_texto_literal(linha)}" for linha in citacao.trecho.splitlines()
        )
        blocos.append(
            f"**[{indice}] {_texto_literal(citacao.arquivo)}** — {_texto_literal(local)}"
            f"\n\n{trecho}"
        )
    return "\n\n".join(blocos)


def formatar_resposta_markdown(resposta: RespostaAssistente) -> str:
    """Formata uma resposta do serviço para o componente de chat."""
    if resposta.documental is not None:
        documental = resposta.documental
        secoes = []
        if documental.insuficiente:
            secoes.append("**Resposta parcial — evidência insuficiente**")
        secoes.append(documental.resposta)
        if documental.limitacoes:
            secoes.append(
                "**Limitações**\n\n"
                + "\n".join(f"- {item}" for item in documental.limitacoes)
            )
        secoes.append(_formatar_citacoes(resposta))
        return "\n\n".join(secao for secao in secoes if secao)
    if not resposta.sucesso or resposta.dados is None:
        return resposta.mensagem

    dados = resposta.dados
    evidencias = "\n".join(f"- {item}" for item in dados.evidencias)
    recomendacoes = "\n".join(f"- {item}" for item in dados.recomendacoes)
    secoes = [
        dados.resumo_executivo,
        f"**Nível de risco:** {dados.nivel_risco.value}",
        f"**Evidências**\n\n{evidencias}",
        f"**Impacto**\n{dados.impacto}",
        f"**Recomendações**\n\n{recomendacoes}",
    ]
    if dados.limitacoes:
        limitacoes = "\n".join(f"- {item}" for item in dados.limitacoes)
        secoes.append(f"**Limitações**\n\n{limitacoes}")
    if resposta.citacoes:
        secoes.append(_formatar_citacoes(resposta))
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
            "Consulte indicadores de recarga, manuais e regras da estação."
        )

        with gr.Tab("Assistente"):
            chatbot = gr.Chatbot(
                value=list(SAUDACAO_CHAT),
                height=520,
                label="Conversa",
            )
            mensagem = gr.Textbox(
                placeholder="Pergunte sobre demanda, tarifas, regras ou manuais...",
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
