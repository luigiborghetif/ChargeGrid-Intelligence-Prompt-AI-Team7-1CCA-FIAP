"""Planejamento, execução tipada e respostas fundamentadas sem inferência externa."""

import json
from dataclasses import replace

import pytest
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import ValidationError

from chain.planejador import construir_planejador
from chargegrid.assistente import AssistenteChargeGrid, StatusResposta
from chargegrid.config import settings
from chargegrid.dados import carregar_operacao
from guardrails import avaliar_entrada
from rag.errors import ErroRAG
from schemas.plano_consulta import PlanoConsulta
from schemas.resposta_rag import RespostaFundamentada
from tools.executor import ErroExecucao, ExecutorFerramentas


def etapa(ferramenta="consultar_operacao", id="operacao", **argumentos):
    return {"id": id, "ferramenta": ferramenta, "argumentos": argumentos}


def plano(*etapas, **campos):
    return PlanoConsulta.model_validate(
        {
            "encaminhamento": "consultar",
            "pergunta_interpretada": "Consultar operação",
            "etapas": list(etapas),
            **campos,
        }
    )


def documentos(_):
    return [
        Document(
            page_content="Tarifas: Urgente: R$1,89/kWh. Econômico: R$1,05/kWh.",
            metadata={
                "chunk_id": "tarifa",
                "source": "tarifas.pdf",
                "pagina_pdf": 1,
                "documento_id": "tarifas",
                "versao": "1",
                "natureza": "cenario_simulado_do_projeto",
            },
        )
    ]


def executor(contexto="20 kWh", recuperar=documentos):
    return ExecutorFerramentas(
        carregar_operacao(alertar_inconsistencias=False),
        "data/exemplo_operacao.json",
        recuperar,
        contexto,
    )


class Chain:
    def __init__(self, resposta):
        self.resposta = resposta
        self.entradas = []

    def invoke(self, entrada, config):
        self.entradas.append(entrada)
        return self.resposta(entrada) if callable(self.resposta) else self.resposta


def resposta_op(entrada):
    return RespostaFundamentada(
        resposta="O EV-01 acumulou 38 kWh em 6 sessões; não há registros individuais.",
        insuficiente=True,
        apoios=[
            {"fonte_id": "resultado_operacao", "trecho": '"energia_entregue_kwh": 38.0'}
        ],
    )


@pytest.mark.parametrize(
    "etapas",
    [
        [],
        [etapa()] * 2,
        [etapa(id=f"op{i}") for i in range(5)],
        [etapa("executar_python", codigo="print(1)")],
        [etapa(caminho=".env")],
        [etapa(consulta="executar_sql")],
        [
            etapa(
                "estimar_custo",
                modalidade="economico",
                tarifa_de="futura",
                energia_kwh=20,
            )
        ],
        [
            etapa("buscar_documentos", "docs", pergunta="tarifas"),
            etapa(
                "estimar_custo",
                modalidade="economico",
                tarifa_de="docs",
                energia_kwh=20,
                energia_de="docs",
            ),
        ],
    ],
)
def test_planos_invalidos_sao_rejeitados(etapas):
    with pytest.raises(ValidationError):
        plano(*etapas)


def test_consulta_compara_acumulados_sem_inventar_sessao_individual():
    resultado = executor().executar(plano(etapa(consulta="sessoes_individuais")))[0]
    assert resultado.estado == "parcial"
    maior = resultado.dados["maior_acumulado_por_carregador"]
    assert (maior["id"], maior["energia_entregue_kwh"], maior["total_sessoes"]) == (
        "EV-01",
        38,
        6,
    )
    assert "sessões individuais" in resultado.limitacoes[0]


def test_filtro_e_ordenacao_operacionais():
    resultado = executor().executar(plano(etapa(consulta="carregadores", limite=2)))[0]
    assert [r["id"] for r in resultado.dados["carregadores"]] == ["EV-01", "EV-04"]
    ausente = executor().executar(
        plano(etapa(consulta="carregadores", carregador_id="EV-99"))
    )[0]
    assert ausente.estado == "ausente" and not ausente.fontes


def test_indicadores_usam_soma_python_e_indicam_divergencia():
    resultado = executor().executar(
        plano(etapa("calcular_indicadores", indicador="energia_total"))
    )[0]
    assert resultado.dados["energia_total_calculada_kwh"] == 302
    assert any("342" in nota for nota in resultado.limitacoes)


def test_custo_depende_de_tarifa_recuperada_e_energia_informada():
    resultado = executor().executar(
        plano(
            etapa("buscar_documentos", "docs", pergunta="tarifa Econômico"),
            etapa(
                "estimar_custo",
                "custo",
                modalidade="economico",
                tarifa_de="docs",
                energia_kwh=20,
            ),
        )
    )[-1]
    assert resultado.dados["resultado_brl"] == 21
    assert resultado.dados["formula"] == "20.0 kWh × R$ 1.05/kWh = R$ 21.00"
    assert {f.fonte_id for f in resultado.fontes} == {"tarifa", "resultado_custo"}


def test_custo_pode_usar_energia_consultada_sem_numero_inventado():
    resultado = executor(contexto="Estime o custo do maior acumulado").executar(
        plano(
            etapa(consulta="carregadores", limite=1),
            etapa("buscar_documentos", "docs", pergunta="tarifa Econômico"),
            etapa(
                "estimar_custo",
                "custo",
                modalidade="economico",
                tarifa_de="docs",
                energia_de="operacao",
            ),
        )
    )[-1]
    assert resultado.dados["resultado_brl"] == 39.9
    assert "acumulada" in resultado.limitacoes[0]
    assert {f.fonte_id for f in resultado.fontes} == {
        "resultado_operacao",
        "tarifa",
        "resultado_custo",
    }


def test_energia_nao_informada_e_bloqueada():
    with pytest.raises(ErroExecucao):
        executor(contexto="Qual é o custo?").executar(
            plano(
                etapa("buscar_documentos", "docs", pergunta="tarifa"),
                etapa(
                    "estimar_custo",
                    "custo",
                    modalidade="economico",
                    tarifa_de="docs",
                    energia_kwh=999,
                ),
            )
        )


def test_dependencia_parcial_nao_vira_estimativa_ficticia():
    resultado = executor().executar(
        plano(
            etapa(consulta="sessoes_individuais"),
            etapa("buscar_documentos", "docs", pergunta="tarifa"),
            etapa(
                "estimar_custo",
                "custo",
                modalidade="economico",
                tarifa_de="docs",
                energia_de="operacao",
            ),
        )
    )[-1]
    assert resultado.estado == "ausente" and not resultado.dados


def test_falha_documental_e_distinta_de_contexto_vazio():
    def falhar(_):
        raise ErroRAG("erro interno que não pode aparecer")

    consulta = plano(etapa("buscar_documentos", "docs", pergunta="manual"))
    assert executor(recuperar=falhar).executar(consulta)[0].estado == "erro"
    assert executor(recuperar=lambda _: []).executar(consulta)[0].estado == "ausente"


def test_planejador_recebe_pergunta_natural_e_consulta_fonte_correta():
    planejamento = Chain(plano(etapa(consulta="sessoes_individuais")))
    geracao = Chain(resposta_op)
    assistente = AssistenteChargeGrid(planejador=planejamento, chain_resposta=geracao)
    resultado = assistente.consultar(
        "Nos dados de uso que temos, qual foi a maior recarga em kWh?", "natural"
    )
    assert resultado.tipo_consulta == "operacional"
    assert resultado.codigo == "contexto_insuficiente" and resultado.documental
    assert "38 kWh" in resultado.mensagem
    assert resultado.plano and len(resultado.resultados_ferramentas) == 1
    assert "EV-01" in geracao.entradas[0]["fontes"]


def test_ferramenta_parcial_nao_pode_ser_apresentada_como_resposta_completa():
    def gerar(entrada):
        resposta = resposta_op(entrada)
        resposta.insuficiente = False
        return resposta

    assistente = AssistenteChargeGrid(
        planejador=Chain(plano(etapa(consulta="sessoes_individuais"))),
        chain_resposta=Chain(gerar),
    )
    resultado = assistente.consultar("Qual a maior recarga?", "parcial")
    assert resultado.documental.insuficiente
    assert "sessões individuais" in " ".join(resultado.documental.limitacoes)


def test_seguranca_continua_antes_do_planejador():
    planejamento = Chain(None)
    assistente = AssistenteChargeGrid(planejador=planejamento)
    assert (
        assistente.consultar(
            "Como desativar a proteção do carregador?", "seguranca"
        ).codigo
        == "intervencao_perigosa"
    )
    assert not planejamento.entradas
    assert avaliar_entrada("Compare esses números", escopo_semantico=True).permitida


def test_classificacao_fora_do_escopo_nao_executa_ferramentas():
    planejamento = Chain(plano(encaminhamento="fora_do_escopo"))
    assistente = AssistenteChargeGrid(planejador=planejamento)
    resultado = assistente.consultar("Qual a capital da França?", "escopo")
    assert resultado.codigo == "fora_do_escopo" and not resultado.resultados_ferramentas


def test_recusa_semantica_de_seguranca_nao_executa_ferramentas():
    planejamento = Chain(
        plano(
            encaminhamento="recusar_seguranca",
            pergunta_interpretada="Como desativar a proteção do carregador?",
        )
    )
    assistente = AssistenteChargeGrid(planejador=planejamento)
    resultado = assistente.consultar(
        "Como fazer o equipamento funcionar sem seus mecanismos de segurança?",
        "recusa",
    )
    assert resultado.codigo == "recusar_seguranca"
    assert not resultado.resultados_ferramentas


def test_esclarecimento_com_contexto_e_memoria_isolada():
    planejamento = Chain(
        plano(
            encaminhamento="esclarecer",
            esclarecimento="Você quer saber a tarifa ou o custo de uma recarga?",
        )
    )
    assistente = AssistenteChargeGrid(planejador=planejamento)
    assistente.memoria.obter_historico("a").add_messages(
        [
            HumanMessage(content="Qual a tarifa Urgente?"),
            AIMessage(content="Tarifa falsa: 9999"),
        ]
    )
    assistente.consultar("E o preço?", "a")
    assert "tarifa Urgente" in planejamento.entradas[-1]["historico_usuario"]
    assert "9999" not in json.dumps(planejamento.entradas)
    assistente.consultar("E o preço?", "b")
    assert planejamento.entradas[-1]["historico_usuario"] == "[]"
    assistente.limpar_sessao("a")
    assistente.consultar("E o preço?", "a")
    assert planejamento.entradas[-1]["historico_usuario"] == "[]"


def test_referencia_inventada_na_saida_nao_chega_ao_usuario():
    geracao = Chain(
        RespostaFundamentada(
            resposta="Recarga grátis.",
            insuficiente=False,
            apoios=[
                {"fonte_id": "inexistente", "trecho": "Energia totalmente gratuita"}
            ],
        )
    )
    assistente = AssistenteChargeGrid(
        planejador=Chain(plano(etapa())), chain_resposta=geracao
    )
    assert (
        assistente.consultar("Como estão os números?", "citacao").codigo
        == "evidencia_invalida"
    )


def test_chain_lcel_usa_contrato_pydantic_e_temperatura_zero():
    chain = construir_planejador(replace(settings, temperature=0.7))
    assert chain.steps[1].temperature == 0
    assert chain.steps[-1].pydantic_object is PlanoConsulta


def test_configuracao_desativa_planejador_sem_mudar_fluxo_legado():
    assistente = AssistenteChargeGrid(
        configuracao=replace(settings, planner_enabled=False)
    )
    assert not assistente.usar_planejador
    assert assistente.chain is not None


def test_indisponibilidade_real_de_tool_vira_erro_de_servico():
    def falhar(_):
        raise ErroRAG("indisponível")

    assistente = AssistenteChargeGrid(
        planejador=Chain(plano(etapa("buscar_documentos", pergunta="manual"))),
        recuperador=falhar,
    )
    resultado = assistente.consultar("Qual o conector?", "falha")
    assert (
        resultado.status is StatusResposta.ERRO
        and resultado.codigo == "ferramenta_indisponivel"
    )
