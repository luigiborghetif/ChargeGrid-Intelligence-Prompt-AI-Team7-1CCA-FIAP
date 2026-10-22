"""Fluxos híbridos com fontes, abstenção e memória isolada, sem inferência real."""

import json

import pytest
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage

from chargegrid.app import formatar_resposta_markdown
from chargegrid.assistente import AssistenteChargeGrid, StatusResposta
from guardrails import avaliar_entrada
from rag.errors import ErroRAG
from rag.roteamento import TipoConsulta, classificar_consulta
from schemas.consulta_recarga import ConsultaRecarga, NivelRisco
from schemas.resposta_rag import ApoioDocumental, RespostaFundamentada


class ChainTeste:
    def __init__(self, resposta):
        self.resposta = resposta
        self.entradas = []

    def invoke(self, entrada, config):
        self.entradas.append(entrada)
        return self.resposta(entrada) if callable(self.resposta) else self.resposta


@pytest.fixture
def documento():
    return Document(
        page_content="Urgente: R$1,89/kWh. Econômico: R$1,05/kWh.",
        metadata={
            "chunk_id": "chunk-tarifas",
            "source": "tarifas.pdf",
            "pagina_pdf": 1,
            "documento_id": "tarifas",
            "versao": "v1",
            "natureza": "cenario_simulado_do_projeto",
        },
    )


def _resposta_doc():
    return RespostaFundamentada(
        resposta="O modo Urgente custa R$ 1,89/kWh.",
        insuficiente=False,
        apoios=[
            ApoioDocumental(fonte_id="chunk-tarifas", trecho="Urgente: R$1,89/kWh")
        ],
    )


@pytest.mark.parametrize(
    ("pergunta", "tipo"),
    [
        ("Qual foi o pico de demanda?", TipoConsulta.OPERACIONAL),
        ("Qual foi o total de energia?", TipoConsulta.OPERACIONAL),
        ("Qual foi o faturamento estimado?", TipoConsulta.OPERACIONAL),
        ("Quais são as tarifas Urgente e Econômico?", TipoConsulta.DOCUMENTAL),
        ("Qual o limite da fila?", TipoConsulta.DOCUMENTAL),
        ("Qual a potência nominal do GW22K-HCA-20?", TipoConsulta.DOCUMENTAL),
        ("O que significa o indicador LED vermelho?", TipoConsulta.DOCUMENTAL),
        ("Qual o pico e como o controle dinâmico ajuda?", TipoConsulta.MISTA),
        ("Recalcule o faturamento usando a tarifa Econômico.", TipoConsulta.MISTA),
    ],
)
def test_escolhe_fontes_por_tipo_de_consulta(pergunta, tipo):
    assert classificar_consulta(pergunta) is tipo


@pytest.mark.parametrize(
    "pergunta",
    [
        "Quais são as regras da fila?",
        "Qual o prazo de estorno?",
        "O plugue tem grau IP55?",
        "O que significa o indicador LED?",
    ],
)
def test_escopo_aceita_base_expandida(pergunta):
    assert avaliar_entrada(pergunta).permitida


def test_documental_nao_injeta_telemetria_nem_exige_risco(documento):
    chain = ChainTeste(_resposta_doc())
    assistente = AssistenteChargeGrid(
        chain_rag=chain, recuperador=lambda _: [documento]
    )
    resultado = assistente.consultar("Qual a tarifa Urgente?", "a")
    assert resultado.sucesso and resultado.tipo_consulta == "documental"
    assert resultado.dados is None
    assert "tarifas.pdf" in resultado.mensagem and "página PDF 1" in resultado.mensagem
    assert "R$ 1,89" in formatar_resposta_markdown(resultado)
    assert "resumo_calculado" not in chain.entradas[0]["contexto_operacional"]
    assert assistente.listar_sessoes() == ("a",)


def test_operacional_independe_do_indice_documental():
    dados = ConsultaRecarga(
        resumo_executivo="Pico de 78,4 kW.",
        evidencias=["98% do limite."],
        impacto="Margem reduzida.",
        recomendacoes=["Avaliar demanda."],
        nivel_risco=NivelRisco.CRITICO,
        potencia_total_kw=78.4,
    )
    chain = ChainTeste(dados)

    def nao_deve_buscar(_):
        raise AssertionError("Consulta operacional não deve acessar o Chroma")

    resultado = AssistenteChargeGrid(
        chain=chain, recuperador=nao_deve_buscar
    ).consultar("Qual o pico de demanda?", "a")
    assert resultado.sucesso
    assert resultado.dados.potencia_total_kw == 78.4
    assert "data/exemplo_operacao.json" in resultado.fontes[0]
    contexto = json.loads(chain.entradas[0]["contexto_operacional"])
    assert contexto["dados"]["resumo_calculado"]["energia_total_calculada_kwh"] == 302


def test_mista_recebe_e_cita_ambas_as_fontes(documento):
    def gerar(entrada):
        op = entrada["contexto_operacional"]
        assert "resumo_calculado" in op
        return RespostaFundamentada(
            resposta="Pico registrado; tarifa conforme documento.",
            insuficiente=False,
            apoios=[
                ApoioDocumental(
                    fonte_id="operacao_atual", trecho='"fonte_id": "operacao_atual"'
                ),
                ApoioDocumental(fonte_id="chunk-tarifas", trecho="Urgente: R$1,89/kWh"),
            ],
        )

    resultado = AssistenteChargeGrid(
        chain_rag=ChainTeste(gerar), recuperador=lambda _: [documento]
    ).consultar("Qual o pico e a tarifa Urgente?", "a")
    assert resultado.sucesso and resultado.tipo_consulta == "mista"
    assert len(resultado.fontes) == 2


def test_mista_sem_apoio_documental_nao_afirma_resposta_completa(documento):
    resposta = RespostaFundamentada(
        resposta="Tarifa X e pico Y.",
        insuficiente=False,
        apoios=[
            ApoioDocumental(
                fonte_id="operacao_atual", trecho='"fonte_id": "operacao_atual"'
            )
        ],
    )
    resultado = AssistenteChargeGrid(
        chain_rag=ChainTeste(resposta), recuperador=lambda _: [documento]
    ).consultar("Qual o pico e a tarifa Urgente?", "a")
    assert resultado.codigo == "contexto_insuficiente"


def test_contexto_vazio_nao_chama_llm():
    chain = ChainTeste(_resposta_doc())
    resultado = AssistenteChargeGrid(
        chain_rag=chain, recuperador=lambda _: []
    ).consultar("Qual a garantia do HCA?", "a")
    assert resultado.codigo == "contexto_insuficiente" and not chain.entradas


@pytest.mark.parametrize(
    ("fonte", "trecho"),
    [
        ("arquivo-inexistente", "Urgente: R$1,89/kWh"),
        ("chunk-tarifas", "Urgente: R$0,00/kWh"),
    ],
)
def test_rejeita_fontes_ou_trechos_inventados(documento, fonte, trecho):
    resposta = RespostaFundamentada(
        resposta="Recarga gratuita.",
        insuficiente=False,
        apoios=[ApoioDocumental(fonte_id=fonte, trecho=trecho)],
    )
    assistente = AssistenteChargeGrid(
        chain_rag=ChainTeste(resposta), recuperador=lambda _: [documento]
    )
    resultado = assistente.consultar("Qual a tarifa?", "a")
    assert resultado.codigo == "evidencia_invalida"
    assert assistente.memoria.obter_historico("a").messages == []


def test_indisponibilidade_nao_e_confundida_com_ausencia_de_evidencia():
    def indisponivel(_):
        raise ErroRAG("Falha de conexão")

    resultado = AssistenteChargeGrid(recuperador=indisponivel).consultar(
        "Qual a tarifa?", "a"
    )
    assert resultado.status is StatusResposta.ERRO
    assert resultado.codigo == "rag_indisponivel"


def test_memoria_reformula_continuacao_sem_reusar_resposta_como_fato(documento):
    perguntas = []
    chain = ChainTeste(_resposta_doc())
    assistente = AssistenteChargeGrid(
        chain_rag=chain, recuperador=lambda p: perguntas.append(p) or [documento]
    )
    assistente.memoria.obter_historico("a").add_messages(
        [
            HumanMessage(content="Qual a tarifa Urgente?"),
            AIMessage(content="Tarifa falsa de R$ 9999."),
        ]
    )
    assert assistente.consultar("E o preço no Econômico?", "a").sucesso
    assert "tarifa Urgente" in perguntas[-1]
    assert "9999" not in json.dumps(chain.entradas[-1])
    assert assistente.consultar("E o preço?", "b").codigo == "contexto_ausente"
    assistente.limpar_sessao("a")
    assert assistente.consultar("E o preço?", "a").codigo == "contexto_ausente"


def test_modelo_indica_insuficiencia_sem_inventar_detalhes(documento):
    resposta = RespostaFundamentada(resposta="Garantia de dez anos.", insuficiente=True)
    resultado = AssistenteChargeGrid(
        chain_rag=ChainTeste(resposta), recuperador=lambda _: [documento]
    ).consultar("Qual a garantia?", "a")
    assert resultado.codigo == "contexto_insuficiente"
    assert "dez anos" not in resultado.mensagem
