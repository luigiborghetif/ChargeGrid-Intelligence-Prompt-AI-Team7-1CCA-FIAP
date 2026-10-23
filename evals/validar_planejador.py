"""Verificação funcional curta do planejador com modelo e índice configurados."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from langchain_core.runnables import RunnableLambda

from chain.planejador import construir_planejador, construir_resposta_planejada
from chargegrid.assistente import AssistenteChargeGrid
from rag.retriever import buscar_documentos


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--casos",
        nargs="+",
        help="Executa apenas os IDs selecionados, na ordem original.",
    )
    parser.add_argument(
        "--atualizar",
        action="store_true",
        help="Atualiza os casos selecionados no relatório existente.",
    )
    args = parser.parse_args()
    assistente = AssistenteChargeGrid(usar_planejador=True)
    recuperados = []
    planos = []
    saidas = []

    def capturar_plano(saida):
        planos.append(saida.model_dump(mode="json"))
        return saida

    def capturar_saida(saida):
        saidas.append(saida.model_dump(mode="json"))
        return saida

    assistente.planejador = construir_planejador(
        assistente.configuracao
    ) | RunnableLambda(capturar_plano)
    assistente.chain_resposta = construir_resposta_planejada(
        assistente.configuracao
    ) | RunnableLambda(capturar_saida)

    def recuperar(pergunta):
        docs = buscar_documentos(pergunta, assistente.configuracao_rag)
        recuperados.extend(
            {"texto": d.page_content, "metadados": d.metadata} for d in docs
        )
        return docs

    assistente.recuperador = recuperar
    config = assistente.configuracao
    casos = [
        (
            "maior_recarga",
            "natural",
            "Nos dados de uso que temos, qual foi a maior recarga em kWh?",
            "operacional",
        ),
        ("tarifas", "doc", "Quais são as tarifas Urgente e Econômico?", "documental"),
        (
            "mista",
            "mista",
            "Qual foi o pico de demanda e como o controle dinâmico de carga pode ajudar?",
            "mista",
        ),
        (
            "custo",
            "custo",
            "Quanto custa somente a energia de 20 kWh no Econômico?",
            "mista",
        ),
        ("continuacao", "custo", "E no Urgente?", "mista"),
        (
            "sem_evidencia",
            "ausente",
            "Qual é o prazo de estorno se a recarga falhar?",
            "documental",
        ),
    ]
    relatorio = {
        "executado_em": datetime.now(UTC).isoformat(),
        "escopo": "Verificação funcional direcionada; não substitui RAGAS, rubrica semântica ou avaliação adversarial da Sprint.",
        "modelo": config.ollama_model,
        "temperature_planejamento_e_resposta": 0,
        "top_p": config.top_p,
        "max_tokens": config.max_tokens,
        "limite_chamadas_ferramentas": 4,
        "top_k": assistente.configuracao_rag.top_k,
        "prompts": [
            {
                "arquivo": str(p.relative_to(ROOT))
                if p.is_relative_to(ROOT)
                else p.name,
                "sha256": sha256(p.read_bytes()).hexdigest(),
            }
            for p in [config.planner_prompt_path, config.planner_response_prompt_path]
        ],
        "casos": [],
    }
    selecionados = set(args.casos or [c[0] for c in casos])
    if selecionados - {c[0] for c in casos}:
        parser.error("ID de caso desconhecido")
    arquivo = ROOT / "evals/planejador_validacao.json"
    if args.atualizar:
        anterior = json.loads(arquivo.read_text(encoding="utf-8"))
        if anterior["prompts"] != relatorio["prompts"]:
            parser.error(
                "Prompts mudaram; execute o conjunto completo para comparar a mesma configuração"
            )
        relatorio["casos"] = anterior["casos"]
    for id_caso, sessao, pergunta, tipo in casos:
        if id_caso not in selecionados:
            continue
        recuperados.clear()
        planos.clear()
        saidas.clear()
        inicio = perf_counter()
        resposta = assistente.consultar(pergunta, f"planejador-{sessao}")
        verificacoes = {
            "tipo": resposta.tipo_consulta == tipo,
            "limite_ferramentas": 0 < len(resposta.resultados_ferramentas) <= 4,
        }
        if id_caso == "maior_recarga":
            verificacoes["limita_sessao_individual"] = (
                resposta.documental is not None
                and resposta.documental.insuficiente
                and "38" in resposta.mensagem
                and "EV-01" in resposta.mensagem
                and "acumulad" in resposta.mensagem.casefold()
            )
        elif id_caso == "tarifas":
            verificacoes["valores_tarifas"] = (
                resposta.sucesso
                and "1,89" in resposta.mensagem
                and "1,05" in resposta.mensagem
            )
        elif id_caso == "mista":
            verificacoes["fontes_mistas"] = resposta.sucesso and {
                c.tipo for c in resposta.citacoes
            } == {"operacional", "documental"}
            verificacoes["pico"] = (
                "78,4" in resposta.mensagem or "78.4" in resposta.mensagem
            )
        elif id_caso in {"custo", "continuacao"}:
            esperado = 21.0 if id_caso == "custo" else 37.8
            verificacoes["custo_calculado_python"] = resposta.sucesso and any(
                r.ferramenta == "estimar_custo"
                and r.dados.get("resultado_brl") == esperado
                for r in resposta.resultados_ferramentas
            )
            verificacoes["valor_exibido"] = (
                "21" in resposta.mensagem
                if id_caso == "custo"
                else "37,80" in resposta.mensagem or "37.80" in resposta.mensagem
            )
        else:
            verificacoes["insuficiencia"] = resposta.codigo == "contexto_insuficiente"
        registro = {
            "id": id_caso,
            "executado_em": datetime.now(UTC).isoformat(),
            "pergunta": pergunta,
            "latencia_segundos": round(perf_counter() - inicio, 3),
            "status": resposta.status.value,
            "codigo": resposta.codigo,
            "mensagem": resposta.mensagem,
            "plano": resposta.plano.model_dump(mode="json") if resposta.plano else None,
            "resultados": [
                r.model_dump(mode="json") for r in resposta.resultados_ferramentas
            ],
            "citacoes": [c.model_dump(mode="json") for c in resposta.citacoes],
            "contexto_recuperado": list(recuperados),
            "planos_modelo": list(planos),
            "saidas_modelo": list(saidas),
            "verificacoes": verificacoes,
            "aprovado": all(verificacoes.values()),
        }
        antigo = next((c for c in relatorio["casos"] if c["id"] == id_caso), None)
        if antigo:
            registro["tentativas_anteriores"] = [
                *antigo.get("tentativas_anteriores", []),
                {k: v for k, v in antigo.items() if k != "tentativas_anteriores"},
            ]
            relatorio["casos"][relatorio["casos"].index(antigo)] = registro
        else:
            relatorio["casos"].append(registro)
        print(id_caso, resposta.codigo, verificacoes, flush=True)
    relatorio["resumo"] = {
        "aprovados": sum(c["aprovado"] for c in relatorio["casos"]),
        "total": len(relatorio["casos"]),
    }
    arquivo.write_text(
        json.dumps(relatorio, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if relatorio["resumo"]["aprovados"] != relatorio["resumo"]["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
