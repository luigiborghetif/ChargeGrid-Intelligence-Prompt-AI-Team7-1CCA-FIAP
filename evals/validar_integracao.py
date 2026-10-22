"""Verificação funcional da fase 3 com Ollama, documentos reais e sessões isoladas."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from langchain_core.runnables import RunnableLambda

from chargegrid.assistente import AssistenteChargeGrid
from rag.integracao import construir_chain_integrada
from rag.retriever import buscar_documentos


def main() -> None:
    capturados = []
    saidas_modelo = []
    assistente = AssistenteChargeGrid()

    def registrar_saida(saida):
        saidas_modelo.append(saida.model_dump(mode="json"))
        return saida

    assistente.chain_rag = construir_chain_integrada(
        assistente.configuracao, assistente.configuracao_rag, operacional=False
    ) | RunnableLambda(registrar_saida)

    def recuperar(pergunta):
        docs = buscar_documentos(pergunta, assistente.configuracao_rag)
        capturados.extend(
            {"texto": d.page_content, "metadados": d.metadata} for d in docs
        )
        return docs

    assistente.recuperador = recuperar
    casos = [
        ("tarifas", "doc", "Quais são as tarifas Urgente e Econômico?", "documental"),
        (
            "continuacao",
            "doc",
            "E quanto custa somente a energia de 20 kWh no Econômico?",
            "documental",
        ),
        ("pico", "op", "Qual foi o pico de demanda e qual o risco?", "operacional"),
        (
            "mista",
            "mista",
            "Qual foi o pico de demanda e como o controle dinâmico de carga pode ajudar?",
            "mista",
        ),
        (
            "sem_evidencia",
            "ausencia",
            "Qual é o prazo de estorno se a recarga falhar?",
            "documental",
        ),
        (
            "modelo_ausente",
            "modelo",
            "Qual a potência do modelo GW150K-HCA-20?",
            "documental",
        ),
        ("outra_sessao", "nova", "E o preço?", None),
    ]
    relatorio = {
        "executado_em": datetime.now(UTC).isoformat(),
        "escopo": "Verificação funcional da integração; não substitui avaliação RAGAS ou testes adversariais completos.",
        "modelo": assistente.configuracao.ollama_model,
        "parametros": {
            k: v
            for k, v in asdict(assistente.configuracao).items()
            if k in {"temperature", "top_p", "max_tokens", "memory_token_limit"}
        },
        "rag": {
            k: v
            for k, v in asdict(assistente.configuracao_rag).items()
            if k
            in {
                "collection_name",
                "chunk_size",
                "chunk_overlap",
                "top_k",
                "embedding_model",
            }
        },
        "prompt": {
            "arquivo": "prompts/rag_v2.md",
            "sha256": sha256(
                assistente.configuracao_rag.prompt_path.read_bytes()
            ).hexdigest(),
        },
        "casos": [],
    }
    for id_caso, sessao, pergunta, tipo in casos:
        capturados.clear()
        saidas_modelo.clear()
        resposta = assistente.consultar(pergunta, f"fase3-{sessao}")
        verificacoes = {"tipo": resposta.tipo_consulta == tipo}
        if id_caso in {"tarifas", "continuacao", "pico", "mista"}:
            verificacoes["sucesso"] = resposta.sucesso
            verificacoes["fontes"] = bool(resposta.fontes)
        if id_caso == "tarifas":
            texto = resposta.mensagem.replace(" ", "")
            verificacoes["precos"] = "1,89" in texto and "1,05" in texto
        elif id_caso == "continuacao":
            verificacoes["valor_20_kwh"] = "21" in resposta.mensagem
        elif id_caso == "pico":
            verificacoes["valor_deterministico"] = (
                resposta.dados is not None and resposta.dados.potencia_total_kw == 78.4
            )
        elif id_caso == "mista":
            verificacoes["ambas_fontes"] = any(
                "exemplo_operacao.json" in f for f in resposta.fontes
            ) and any(".pdf" in f for f in resposta.fontes)
        elif id_caso in {"sem_evidencia", "modelo_ausente"}:
            verificacoes["insuficiencia"] = resposta.codigo == "contexto_insuficiente"
        else:
            verificacoes["isolamento"] = resposta.codigo == "contexto_ausente"
        relatorio["casos"].append(
            {
                "id": id_caso,
                "pergunta": pergunta,
                "status": resposta.status.value,
                "codigo": resposta.codigo,
                "tipo_consulta": resposta.tipo_consulta,
                "mensagem": resposta.mensagem,
                "dados": resposta.dados.model_dump(mode="json")
                if resposta.dados
                else None,
                "fontes": resposta.fontes,
                "contexto_recuperado": list(capturados),
                "saida_estruturada_modelo": list(saidas_modelo),
                "verificacoes": verificacoes,
                "aprovado": all(verificacoes.values()),
            }
        )
        (ROOT / "evals/fase3_integracao.json").write_text(
            json.dumps(relatorio, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(id_caso, resposta.codigo, verificacoes, flush=True)
    relatorio["resumo"] = {
        "aprovados": sum(c["aprovado"] for c in relatorio["casos"]),
        "total": len(casos),
    }
    (ROOT / "evals/fase3_integracao.json").write_text(
        json.dumps(relatorio, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if relatorio["resumo"]["aprovados"] != len(casos):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
