"""Contrato público e apresentação de citações verificadas na interface."""

import json
from pathlib import Path
from runpy import run_path
from unittest.mock import patch

import pytest
from langchain_core.documents import Document
from pydantic import ValidationError

from chargegrid.app import formatar_resposta_markdown, processar_mensagem
from chargegrid.assistente import (
    AssistenteChargeGrid,
    RespostaAssistente,
    StatusResposta,
)
from rag.integracao import ErroFundamentacao, conferir_apoios
from schemas.resposta_rag import (
    ApoioDocumental,
    CitacaoFonte,
    RespostaDocumental,
    RespostaFundamentada,
)


def fonte():
    return Document(
        page_content="Urgente: R$1,89/kWh. Econômico: R$1,05/kWh.",
        metadata={
            "chunk_id": "tarifas-1",
            "source": "Tarifas.pdf",
            "pagina_pdf": 2,
            "secao": "Tarifas comerciais",
            "documento_id": "tarifas",
            "versao": "1",
            "natureza": "cenario_simulado_do_projeto",
        },
    )


def geracao(insuficiente=False):
    return RespostaFundamentada(
        resposta="O Econômico custa R$1,05/kWh.",
        insuficiente=insuficiente,
        apoios=[ApoioDocumental(fonte_id="tarifas-1", trecho="Econômico: R$1,05/kWh")],
        limitacoes=["O prazo de estorno não está informado."] if insuficiente else [],
    )


def servico(insuficiente=False):
    class Chain:
        def invoke(self, entrada, config):
            return geracao(insuficiente)

    return AssistenteChargeGrid(chain_rag=Chain(), recuperador=lambda _: [fonte()])


def test_contrato_publico_usa_localizacao_da_fonte_e_serializa():
    resposta = servico().consultar("Qual a tarifa Econômico?", "contrato")
    assert resposta.sucesso and resposta.dados is None
    dados = json.loads(resposta.documental.model_dump_json())
    citacao = dados["citacoes"][0]
    assert citacao == {
        "fonte_id": "tarifas-1",
        "tipo": "documental",
        "arquivo": "Tarifas.pdf",
        "pagina_pdf": 2,
        "secao": "Tarifas comerciais",
        "trecho": "Econômico: R$1,05/kWh",
    }
    assert resposta.citacoes[0].arquivo == "Tarifas.pdf"
    assert resposta.documental.citacoes == list(resposta.citacoes)


@pytest.mark.parametrize(
    "alteracao",
    [
        {"fonte_id": "fonte-fora-do-contexto"},
        {"trecho": "Econômico: R$0,00/kWh"},
    ],
)
def test_citacoes_fora_do_contexto_nao_sao_publicadas(alteracao):
    resposta = geracao()
    resposta.apoios[0] = ApoioDocumental(
        **(resposta.apoios[0].model_dump() | alteracao)
    )
    with pytest.raises(ErroFundamentacao):
        conferir_apoios(resposta, [fonte()], None, "operacao.json")


def test_modelo_nao_pode_forjar_metadados_da_citacao():
    with pytest.raises(ValidationError):
        ApoioDocumental(
            fonte_id="tarifas-1",
            trecho="Econômico: R$1,05/kWh",
            arquivo="manual-oficial.pdf",
            pagina_pdf=99,
        )


@pytest.mark.parametrize(
    "campos",
    [
        {"tipo": "documental"},
        {"tipo": "documental", "pagina_pdf": 0},
        {"tipo": "operacional", "pagina_pdf": 2},
    ],
)
def test_contrato_rejeita_localizacao_inconsistente(campos):
    with pytest.raises(ValidationError):
        CitacaoFonte(fonte_id="a", arquivo="fonte", trecho="apoio", **campos)


def test_resposta_completa_sem_citacoes_e_rejeitada():
    with pytest.raises(ValidationError):
        RespostaDocumental(resposta="Uma afirmação sem apoio.", insuficiente=False)


@pytest.mark.parametrize("parcial", [False, True])
def test_chat_apresenta_fontes_sem_campos_operacionais_inventados(parcial):
    _, historico = processar_mensagem(
        "Qual a tarifa Econômico e o prazo de estorno?",
        [],
        "chat",
        servico(parcial),
    )
    texto = historico[-1]["content"]
    assert "Tarifas" in texto and "página PDF 2" in texto
    assert "Tarifas comerciais" in texto and "R$1,05/kWh" in texto
    assert "Nível de risco" not in texto and "Recomendações" not in texto
    assert ("Resposta parcial" in texto) is parcial
    assert ("prazo de estorno não está informado" in texto) is parcial
    assert texto.count("Fontes utilizadas") == 1


def test_chat_preserva_recusa_sem_apresentar_citacoes():
    resposta = RespostaAssistente(
        StatusResposta.RECUSADA,
        "contexto_insuficiente",
        "Não há evidência suficiente para informar o prazo de estorno.",
    )
    assert formatar_resposta_markdown(resposta) == resposta.mensagem


def test_citacoes_sao_texto_sem_html_ou_links_ativos():
    citacao = CitacaoFonte(
        fonte_id="a",
        tipo="documental",
        arquivo="[Fonte](https://example.com).pdf",
        pagina_pdf=1,
        trecho='<img src=x onerror="alert(1)"> [abrir](https://example.com)',
    )
    resposta = RespostaAssistente(
        StatusResposta.SUCESSO,
        "consulta_documental_concluida",
        "Resposta.",
        citacoes=(citacao,),
        documental=RespostaDocumental(
            resposta="Resposta.", insuficiente=False, citacoes=[citacao]
        ),
    )
    texto = formatar_resposta_markdown(resposta)
    assert "<img" not in texto and "&lt;img" in texto
    assert "[abrir](https://example.com)" not in texto


def test_ponto_de_entrada_reutiliza_interface_existente():
    caminho = Path(__file__).resolve().parents[1] / "app/main.py"
    with patch("chargegrid.app.main") as iniciar:
        run_path(str(caminho), run_name="__main__")
    iniciar.assert_called_once_with()
