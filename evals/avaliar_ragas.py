"""Avalia respostas salvas com RAGAS/Ollama, sem refazer busca ou geração."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import statistics
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

os.environ.setdefault("RAGAS_DO_NOT_TRACK", "true")
ROOT = Path(__file__).resolve().parents[1]
PASTA = ROOT / "evals/sprint4"
EXPERIMENTOS = ("baseline_gemma", "hibrido_gemma", "hibrido_gptoss")
FALHAS_TECNICAS = {"resposta_invalida", "evidencia_invalida", "plano_invalido"}


def digest(valor: bytes) -> str:
    return hashlib.sha256(valor).hexdigest()


def preparar_amostra(caso: dict) -> dict:
    """Usa o conteúdo pós-triagem enviado ao gerador, nunca a busca bruta."""
    etapas = [e for e in caso["entradas_geracao"] if e["etapa"] == "resposta"]
    documentos = []
    if etapas:
        fontes = json.loads(etapas[-1]["entrada"]["fontes"])
        documentos = fontes.get("documentos", [])
    return {
        "user_input": caso["pergunta"],
        "response": caso["texto_resposta"],
        "retrieved_contexts": [d["conteudo"] for d in documentos],
        "fontes_ids": [d["fonte_id"] for d in documentos],
    }


def elegibilidade(caso: dict, amostra: dict, metrica: str) -> str | None:
    if caso["status"] == "erro" or caso["codigo"] in FALHAS_TECNICAS:
        return "Falha técnica retida pelo serviço; não é resposta factual do RAG."
    if not amostra["response"].strip():
        return "Resposta vazia."
    if metrica == "faithfulness":
        if caso["status"] != "sucesso":
            return "Abstenção/recusa: avaliar adequação pelo gabarito, sem premiar ausência de fatos."
        if not amostra["retrieved_contexts"]:
            return "Sem contexto documental fornecido ao gerador."
    return None


def resumir(registros: list[dict]) -> dict:
    resumo = {"casos": len(registros), "metricas": {}}
    for nome in ["faithfulness", "answer_relevancy"]:
        validos = [
            r["metricas"][nome]["score"]
            for r in registros
            if r["metricas"].get(nome, {}).get("estado") == "sucesso"
        ]
        resumo["metricas"][nome] = {
            "media": statistics.mean(validos) if validos else None,
            "n": len(validos),
            "nao_aplicaveis": sum(
                r["metricas"].get(nome, {}).get("estado") == "nao_aplicavel"
                for r in registros
            ),
            "erros_avaliador": sum(
                r["metricas"].get(nome, {}).get("estado") == "erro" for r in registros
            ),
        }
    return resumo


def consolidar(pasta: Path) -> dict:
    arquivos = [pasta / f"{nome}.json" for nome in EXPERIMENTOS]
    dados = {p.stem: json.loads(p.read_text()) for p in arquivos if p.exists()}
    saida = {
        "metodo": "RAGAS real; médias por métrica somente nos casos aplicáveis e válidos; falhas não são zeros artificiais.",
        "experimentos": {
            nome: {"configuracao": d["configuracao"], **resumir(d["casos"])}
            for nome, d in dados.items()
        },
        "comparacoes_pareadas": {},
    }
    for a, b in [
        ("baseline_gemma", "hibrido_gemma"),
        ("hibrido_gemma", "hibrido_gptoss"),
    ]:
        if a not in dados or b not in dados:
            continue
        par = {}
        for metrica in ["faithfulness", "answer_relevancy"]:
            mapas = [
                {
                    c["id"]: c["metricas"][metrica]["score"]
                    for c in dados[nome]["casos"]
                    if c["metricas"].get(metrica, {}).get("estado") == "sucesso"
                }
                for nome in [a, b]
            ]
            ids = sorted(mapas[0].keys() & mapas[1].keys())
            medias = [
                statistics.mean(m[i] for i in ids) if ids else None for m in mapas
            ]
            par[metrica] = {
                "ids": ids,
                "n": len(ids),
                a: medias[0],
                b: medias[1],
                "delta_segundo_menos_primeiro": medias[1] - medias[0] if ids else None,
            }
        saida["comparacoes_pareadas"][f"{a}__{b}"] = par
    salvar(pasta / "scores.json", saida)
    return saida


def salvar(arquivo: Path, dados: dict):
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    temporario = arquivo.with_suffix(".tmp")
    temporario.write_text(
        json.dumps(dados, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    )
    temporario.replace(arquivo)


async def executar(args):
    import httpx
    from dotenv import load_dotenv
    from langchain_core.callbacks import BaseCallbackHandler
    from langchain_ollama import ChatOllama, OllamaEmbeddings
    from ragas import SingleTurnSample
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import Faithfulness, ResponseRelevancy
    from ragas.run_config import RunConfig

    load_dotenv(ROOT / ".env", override=False)
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    embedding_url = os.getenv("RAG_EMBEDDING_BASE_URL", "http://localhost:11434")
    modelo = "gemma4:31b-cloud"
    embedding = "nomic-embed-text"
    # Diagnóstico antes de criar registros: erro de acesso não vira nota de qualidade.
    with httpx.Client(timeout=10) as cliente:
        modelos = cliente.get(base_url.rstrip("/") + "/api/tags")
        modelos.raise_for_status()
        tags = modelos.json()["models"]
        if modelo not in {m["name"] for m in tags}:
            raise ValueError(f"Modelo juiz indisponível: {modelo}")
        emb_response = cliente.get(embedding_url.rstrip("/") + "/api/tags")
        emb_response.raise_for_status()
        emb_tags = emb_response.json()["models"]
        emb_digest = next(
            (m["digest"] for m in emb_tags if m["name"].split(":")[0] == embedding),
            None,
        )
        if not emb_digest:
            raise ValueError("nomic-embed-text indisponível no Ollama de embeddings")
    versoes = {
        n: importlib.metadata.version(n)
        for n in [
            "ragas",
            "langchain-core",
            "langchain-community",
            "langchain-ollama",
            "pydantic",
            "ollama",
        ]
    }
    configuracao = {
        "juiz": modelo,
        "temperature": 0,
        "top_p": 0.9,
        "max_tokens_juiz": 4096,
        "embeddings": embedding,
        "embedding_digest": emb_digest,
        "embedding_prefixo": "search_query: (igual para pergunta original e reconstruídas)",
        "strictness": 3,
        "timeout_metrica_segundos": 180,
        "max_retries_transporte": 1,
        "api": "RAGAS SingleTurnSample + Faithfulness/ResponseRelevancy + Langchain wrappers (API da aula)",
        "versoes": versoes,
        "python": platform.python_version(),
        "politica": "Uma avaliação por resposta/métrica; sem refazer respostas, sem substituir falha por zero; retomada não repete métricas registradas.",
        "idioma": "Entradas originais em português; prompts oficiais RAGAS em inglês, sem adaptação.",
    }
    llm = ChatOllama(
        model=modelo,
        base_url=base_url,
        temperature=0,
        top_p=0.9,
        num_predict=4096,
        client_kwargs={"timeout": 90},
    )
    juiz = LangchainLLMWrapper(
        llm,
        run_config=RunConfig(timeout=180, max_retries=1, max_workers=1),
        bypass_temperature=True,
    )

    class EmbeddingsPerguntas(OllamaEmbeddings):
        # Relevância compara perguntas entre si: aplicar o mesmo prefixo nos dois lados.
        async def aembed_query(self, text):
            return (await super().aembed_documents(["search_query: " + text]))[0]

        async def aembed_documents(self, texts):
            return await super().aembed_documents(["search_query: " + t for t in texts])

    embs = LangchainEmbeddingsWrapper(
        EmbeddingsPerguntas(
            model=embedding, base_url=embedding_url, client_kwargs={"timeout": 90}
        )
    )
    metricas = {
        "faithfulness": Faithfulness(llm=juiz),
        "answer_relevancy": ResponseRelevancy(llm=juiz, embeddings=embs, strictness=3),
    }
    pasta = PASTA / "ragas"
    for experimento in args.experimentos:
        origem = PASTA / f"{experimento}.json"
        bruto = json.loads(origem.read_text())
        arquivo = pasta / f"{experimento}.json"
        controle = {
            "experimento": experimento,
            "configuracao": configuracao,
            "origem_sha256": digest(origem.read_bytes()),
            "executor_sha256": digest(Path(__file__).read_bytes()),
        }
        if arquivo.exists():
            if not args.retomar:
                raise ValueError(
                    "Resultado existe; use --retomar. Não sobrescrever avaliações."
                )
            relatorio = json.loads(arquivo.read_text())
            if any(relatorio[k] != v for k, v in controle.items()):
                raise ValueError(
                    "Origem, executor ou configuração mudaram; preservar a rodada anterior."
                )
        else:
            relatorio = {
                **controle,
                "iniciado_em": datetime.now(UTC).isoformat(),
                "casos": [],
            }
        if args.casos and set(args.casos) - {c["id"] for c in bruto["casos"]}:
            raise ValueError("Caso ausente no registro de origem")
        for caso in bruto["casos"]:
            if args.casos and caso["id"] not in args.casos:
                continue
            registro = next(
                (c for c in relatorio["casos"] if c["id"] == caso["id"]), None
            )
            amostra = preparar_amostra(caso)
            if registro is None:
                registro = {
                    "id": caso["id"],
                    "categoria": caso["categoria"],
                    "status_assistente": caso["status"],
                    "codigo_assistente": caso["codigo"],
                    "amostra": amostra,
                    "metricas": {},
                }
                relatorio["casos"].append(registro)
            for nome, metrica in metricas.items():
                if nome in registro["metricas"]:
                    continue
                motivo = elegibilidade(caso, amostra, nome)
                if motivo:
                    registro["metricas"][nome] = {
                        "estado": "nao_aplicavel",
                        "score": None,
                        "motivo": motivo,
                    }
                    salvar(arquivo, relatorio)
                    continue
                rastros = []

                class Rastro(BaseCallbackHandler):
                    def __init__(self, destino):
                        self.destino = destino

                    def on_chat_model_start(self, serialized, messages, **kwargs):
                        self.destino.append(
                            {
                                "evento": "entrada_juiz",
                                "mensagens": [
                                    [
                                        {"papel": m.type, "texto": m.content}
                                        for m in lote
                                    ]
                                    for lote in messages
                                ],
                            }
                        )

                    def on_llm_end(self, response, **kwargs):
                        self.destino.append(
                            {
                                "evento": "saida_juiz",
                                "geracoes": [
                                    [
                                        {
                                            "texto": g.text,
                                            "metadados": g.generation_info,
                                        }
                                        for g in lote
                                    ]
                                    for lote in response.generations
                                ],
                            }
                        )

                inicio = perf_counter()
                print(f"{experimento} {caso['id']} {nome}...", flush=True)
                try:
                    sample = SingleTurnSample(
                        user_input=amostra["user_input"],
                        response=amostra["response"],
                        retrieved_contexts=amostra["retrieved_contexts"],
                    )
                    score = float(
                        await asyncio.wait_for(
                            metrica.single_turn_ascore(
                                sample, callbacks=[Rastro(rastros)]
                            ),
                            timeout=180,
                        )
                    )
                    if not math.isfinite(score):
                        raise ValueError(
                            "Métrica retornou NaN/infinito; não é uma nota válida"
                        )
                    resultado = {"estado": "sucesso", "score": score}
                except Exception as exc:  # noqa: BLE001 - preservar falhas do avaliador externo
                    resultado = {
                        "estado": "erro",
                        "score": None,
                        "tipo_erro": type(exc).__name__,
                        "erro": str(exc),
                    }
                resultado.update(
                    {
                        "latencia_segundos": round(perf_counter() - inicio, 3),
                        "rastro_juiz": rastros,
                    }
                )
                registro["metricas"][nome] = resultado
                salvar(arquivo, relatorio)
                consolidar(pasta)
                print(f"  {resultado['estado']}: {resultado['score']}", flush=True)
                if resultado["estado"] == "erro" and not rastros:
                    raise RuntimeError(
                        "Juiz não respondeu; rodada interrompida para diagnóstico."
                    )
        salvar(arquivo, relatorio)
    consolidar(pasta)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--experimentos", nargs="+", choices=EXPERIMENTOS, default=list(EXPERIMENTOS)
    )
    parser.add_argument("--casos", nargs="+")
    parser.add_argument("--retomar", action="store_true")
    args = parser.parse_args()
    asyncio.run(executar(args))


if __name__ == "__main__":
    main()
