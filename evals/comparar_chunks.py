"""Compara tamanhos de chunk com consultas reais e vetores de pergunta reutilizados."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from itertools import product
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from validar_recuperacao import avaliar

from rag.config import RAGSettings
from rag.embeddings import criar_embeddings, identificar_modelo
from rag.vector_store import (
    abrir_indice_pronto,
    bloquear_indice,
    consultar_status,
    indexar_base,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tamanhos", type=int, nargs="+", default=[600, 900, 1200, 1800]
    )
    parser.add_argument("--ks", type=int, nargs="+", default=[4, 8])
    parser.add_argument(
        "--overlaps",
        type=int,
        nargs="+",
        help="Overlaps em caracteres; padrão: configuração atual",
    )
    parser.add_argument(
        "--saida", type=Path, default=ROOT / "evals/comparacao_chunks.json"
    )
    args = parser.parse_args()
    base = RAGSettings.from_env()
    overlaps = list(dict.fromkeys(args.overlaps or [base.chunk_overlap]))
    pares = list(product(dict.fromkeys(args.tamanhos), overlaps))
    for tamanho, overlap in pares:
        replace(base, chunk_size=tamanho, chunk_overlap=overlap).validate()
    for k in args.ks:
        replace(base, top_k=k).validate()
    original = consultar_status(base)
    if original.get("estado") != "pronto":
        parser.error("Indexe a coleção principal antes da comparação.")
    digest = identificar_modelo(base)
    conjunto_path = ROOT / "evals/casos_rag.json"
    conjunto = json.loads(conjunto_path.read_text(encoding="utf-8"))
    casos = [c for c in conjunto["casos"] if c["categoria"] == "respondiveis"]
    embeddings = criar_embeddings(base)
    print(
        f"Gerando embeddings de {len(casos)} perguntas uma única vez...",
        file=sys.stderr,
        flush=True,
    )
    vetores = {c["pergunta"]: embeddings.embed_query(c["pergunta"]) for c in casos}
    relatorio = {
        "schema_version": 1,
        "iniciado_em": datetime.now(UTC).isoformat(),
        "dataset_sha256": hashlib.sha256(conjunto_path.read_bytes()).hexdigest(),
        "dataset_version": conjunto["dataset_version"],
        "controle": {
            "casos": len(casos),
            "embedding_model": base.embedding_model,
            "embedding_digest": digest,
            "chunk_overlap": base.chunk_overlap,
            "overlaps_testados": overlaps,
            "fontes_sha256": original["arquivos"],
            "comparacao": "Combinações de tamanho e overlap avaliadas com o mesmo corpus, perguntas e vetores, separadamente para cada k.",
            "vetores_perguntas": "Reais, calculados uma vez no Ollama e reutilizados entre configurações.",
            "limite": "Indicadores de páginas e âncoras; não são scores RAGAS nem medem qualidade de respostas.",
        },
        "experimentos": [],
    }
    for tamanho, overlap in pares:
        config = replace(
            base,
            chunk_size=tamanho,
            chunk_overlap=overlap,
            chroma_path=base.chroma_path / "experimentos_chunks",
            collection_name=f"chunks_{tamanho}_overlap_{overlap}",
        )
        config.validate()
        if tamanho == base.chunk_size and overlap == base.chunk_overlap:
            # Reutiliza o baseline já persistido, sem reindexá-lo.
            config = base
            manifesto = original
        else:
            print(
                f"Indexando chunks de {tamanho} caracteres, overlap {overlap}...",
                file=sys.stderr,
                flush=True,
            )
            manifesto = indexar_base(config)
        if manifesto["arquivos"] != original["arquivos"]:
            raise RuntimeError("O corpus mudou durante o experimento.")
        with bloquear_indice(config):
            store, _ = abrir_indice_pronto(config)
        for k in dict.fromkeys(args.ks):
            consulta = replace(config, top_k=k)
            consulta.validate()
            comprimentos = []

            def recuperar(
                pergunta, configuracao, *, indice=store, contagens=comprimentos
            ):
                with bloquear_indice(configuracao):
                    documentos = indice.similarity_search_by_vector(
                        vetores[pergunta], k=configuracao.top_k
                    )
                contagens.append(sum(len(d.page_content) for d in documentos))
                return documentos

            resultado = avaliar(consulta, recuperar=recuperar, exibir_progresso=False)
            resultado["resumo"]["casos_com_todas_ancoras"] = sum(
                r["ancoras_encontradas"] == r["ancoras_esperadas"]
                for r in resultado["resultados"]
            )
            resultado["resumo"]["caracteres_contexto_medio"] = round(mean(comprimentos))
            resultado["resumo"]["caracteres_contexto_maximo"] = max(comprimentos)
            relatorio["experimentos"].append(resultado)
            args.saida.write_text(
                json.dumps(relatorio, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(
                f"chunk={tamanho}, overlap={overlap}, k={k}: {resultado['resumo']}",
                file=sys.stderr,
                flush=True,
            )
    if identificar_modelo(base) != digest:
        raise RuntimeError("O modelo mudou durante o experimento.")
    if consultar_status(base) != original:
        raise RuntimeError(
            "O manifesto do índice principal mudou durante o experimento."
        )
    relatorio["concluido_em"] = datetime.now(UTC).isoformat()
    relatorio["indice_principal_preservado"] = True
    args.saida.write_text(
        json.dumps(relatorio, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Comparação salva em {args.saida}")


if __name__ == "__main__":
    main()
