"""Executa a amostra fixa da Sprint 4, com checkpoint e rastreabilidade."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from langchain_core.documents import Document
from langchain_core.runnables import RunnableLambda
from ollama import ResponseError

from chain.planejador import construir_planejador, construir_resposta_planejada
from chargegrid.assistente import AssistenteChargeGrid
from chargegrid.config import settings
from rag.config import RAGSettings
from rag.retriever import buscar_documentos
from rag.vector_store import consultar_status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--experimento",
        required=True,
        choices=["baseline_gemma", "hibrido_gemma", "hibrido_qwen", "hibrido_gptoss"],
    )
    parser.add_argument("--retomar", action="store_true")
    parser.add_argument("--casos", nargs="+")
    args = parser.parse_args()
    pasta = ROOT / "evals/sprint4"
    protocolo = json.loads((pasta / "protocolo.json").read_text())
    dataset = json.loads((ROOT / "evals/casos_rag.json").read_text())
    registro_experimentos = dict(protocolo["experimentos"])
    adendo = pasta / "adendo_modelo.json"
    if adendo.exists():
        registro_experimentos.update(
            json.loads(adendo.read_text())["experimentos_adicionais"]
        )
    experimento = registro_experimentos[args.experimento]
    config = replace(
        settings,
        ollama_model=experimento["modelo"],
        temperature=0,
        top_p=protocolo["top_p"],
        max_tokens=protocolo["max_tokens"],
        planner_prompt_path=ROOT / "prompts" / experimento["planejador"],
        planner_response_prompt_path=ROOT / "prompts" / experimento["resposta"],
    )
    rag = replace(
        RAGSettings.from_env(), search_mode=experimento["busca"], top_k=protocolo["k"]
    )
    if (rag.chunk_size, rag.chunk_overlap) != (
        protocolo["chunk_size"],
        protocolo["chunk_overlap"],
    ):
        parser.error("O índice/configuração difere do protocolo")
    manifesto = consultar_status(rag)
    controle = {
        "experimento": args.experimento,
        "configuracao": {
            **experimento,
            "temperature": 0,
            "top_p": config.top_p,
            "max_tokens": config.max_tokens,
            "k": rag.top_k,
            "chunk_size": rag.chunk_size,
            "chunk_overlap": rag.chunk_overlap,
            "colecao": rag.collection_name,
            "embedding_model": rag.embedding_model,
            "memoria_tokens": config.memory_token_limit,
        },
        "protocolo_sha256": sha256((pasta / "protocolo.json").read_bytes()).hexdigest(),
        "dataset_sha256": sha256(
            (ROOT / "evals/casos_rag.json").read_bytes()
        ).hexdigest(),
        "prompts": [
            {
                "arquivo": str(p.relative_to(ROOT)),
                "sha256": sha256(p.read_bytes()).hexdigest(),
            }
            for p in [config.planner_prompt_path, config.planner_response_prompt_path]
        ],
        "corpus": dataset["documentos"],
        "indice": manifesto,
    }
    for documento in dataset["documentos"]:
        if (
            sha256((ROOT / documento["arquivo"]).read_bytes()).hexdigest()
            != documento["sha256"]
        ):
            parser.error("Corpus mudou desde a preparação do gabarito")
    arquivo = pasta / f"{args.experimento}.json"
    relatorio = {**controle, "iniciado_em": datetime.now(UTC).isoformat(), "casos": []}
    if arquivo.exists():
        if not args.retomar:
            parser.error(
                "Relatório existe; use --retomar ou preserve-o antes de outra execução"
            )
        anterior = json.loads(arquivo.read_text())
        if any(
            anterior[c] != controle[c]
            for c in ["configuracao", "protocolo_sha256", "dataset_sha256", "prompts"]
        ):
            parser.error(
                "Configuração mudou; não é possível juntar execuções diferentes"
            )
        relatorio = anterior
    selecionados = args.casos or protocolo["ids"]
    if set(selecionados) - set(protocolo["ids"]):
        parser.error("ID fora do protocolo")
    for id_caso in protocolo["ids"]:
        if id_caso not in selecionados or any(
            c["id"] == id_caso for c in relatorio["casos"]
        ):
            continue
        caso = next(c for c in dataset["casos"] if c["id"] == id_caso)
        capturados, geracoes, entradas_geracao = [], [], []

        def instrumentar(
            chain, nome, entradas_geracao=entradas_geracao, geracoes=geracoes
        ):
            def entrada(valor):
                entradas_geracao.append({"etapa": nome, "entrada": valor})
                return valor

            def saida(mensagem):
                geracoes.append(
                    {
                        "etapa": nome,
                        "conteudo": mensagem.content,
                        "tokens": {
                            k: mensagem.response_metadata.get(k)
                            for k in ["prompt_eval_count", "eval_count", "done_reason"]
                        },
                    }
                )
                return mensagem

            def chamar_modelo(valor):
                try:
                    return chain.steps[1].invoke(valor)
                except ResponseError as exc:
                    geracoes.append({"etapa": nome, "erro_servico": str(exc)})
                    raise

            return (
                RunnableLambda(entrada)
                | chain.steps[0]
                | RunnableLambda(chamar_modelo)
                | RunnableLambda(saida)
                | chain.steps[-1]
            )

        def recuperar(pergunta, caso=caso, id_caso=id_caso, capturados=capturados):
            docs = buscar_documentos(pergunta, rag)
            if "ataque" in caso:
                ataque = caso["ataque"]
                caminho = ROOT / ataque["arquivo"]
                if sha256(caminho.read_bytes()).hexdigest() != ataque["sha256"]:
                    raise ValueError("Fixture mudou")
                docs = [
                    Document(
                        page_content=caminho.read_text(),
                        metadata={
                            "chunk_id": f"ataque_{id_caso}",
                            "source": caminho.name,
                            "pagina_pdf": 1,
                            "documento_id": "fixture",
                            "versao": "teste",
                            "natureza": "sintetico_adversarial",
                        },
                    ),
                    *docs,
                ]
            capturados.append(
                {
                    "consulta": pergunta,
                    "documentos": [
                        {"texto": d.page_content, "metadados": d.metadata} for d in docs
                    ],
                }
            )
            return docs

        servico = AssistenteChargeGrid(
            configuracao=config,
            configuracao_rag=rag,
            recuperador=recuperar,
            usar_planejador=True,
        )
        servico.planejador = instrumentar(construir_planejador(config), "planejador")
        servico.chain_resposta = instrumentar(
            construir_resposta_planejada(config), "resposta"
        )
        inicio = perf_counter()
        resposta = servico.consultar(caso["pergunta"], f"sprint4-{id_caso}")
        registro = {
            "id": id_caso,
            "categoria": caso["categoria"],
            "pergunta": caso["pergunta"],
            "executado_em": datetime.now(UTC).isoformat(),
            "latencia_segundos": round(perf_counter() - inicio, 3),
            "status": resposta.status.value,
            "codigo": resposta.codigo,
            "resposta": resposta.mensagem,
            "texto_resposta": resposta.documental.resposta
            if resposta.documental
            else resposta.mensagem,
            "plano": resposta.plano.model_dump(mode="json") if resposta.plano else None,
            "resultados": [
                r.model_dump(mode="json") for r in resposta.resultados_ferramentas
            ],
            "citacoes": [c.model_dump(mode="json") for c in resposta.citacoes],
            "recuperacoes": capturados,
            "entradas_geracao": entradas_geracao,
            "geracoes": geracoes,
        }
        if resposta.codigo in {"ollama_indisponivel", "ferramenta_indisponivel"}:
            relatorio.setdefault("falhas_infraestrutura", []).append(registro)
            arquivo.write_text(
                json.dumps(relatorio, ensure_ascii=False, indent=2, default=str) + "\n"
            )
            print(
                id_caso,
                resposta.codigo,
                "infraestrutura indisponível; execução interrompida",
                flush=True,
            )
            raise SystemExit(2)
        relatorio["casos"].append(registro)
        relatorio["concluido"] = len(relatorio["casos"]) == len(protocolo["ids"])
        arquivo.write_text(
            json.dumps(relatorio, ensure_ascii=False, indent=2, default=str) + "\n"
        )
        print(
            args.experimento,
            id_caso,
            resposta.codigo,
            f"{registro['latencia_segundos']}s",
            flush=True,
        )


if __name__ == "__main__":
    main()
