"""Audita páginas e âncoras recuperadas, sem geração de respostas ou RAGAS."""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from langchain_core.documents import Document

from rag.config import RAGSettings
from rag.retriever import buscar_documentos
from rag.vector_store import consultar_status


def normalizar(texto: str) -> str:
    texto = re.sub(r"<br\s*/?>", " ", texto, flags=re.IGNORECASE)
    return "".join(
        caractere
        for caractere in unicodedata.normalize("NFKD", texto).casefold()
        if caractere.isalnum()
    )


def avaliar(
    config: RAGSettings,
    *,
    recuperar: Callable[[str, RAGSettings], list[Document]] = buscar_documentos,
    exibir_progresso: bool = True,
) -> dict:
    conjunto = json.loads((ROOT / "evals/casos_rag.json").read_text(encoding="utf-8"))
    manifesto = consultar_status(config)
    casos = [c for c in conjunto["casos"] if c["categoria"] == "respondiveis"]
    resultados = []
    for caso in casos:
        documentos = recuperar(caso["pergunta"], config)
        paginas = {
            (d.metadata["documento_id"], d.metadata["pagina_pdf"]) for d in documentos
        }
        esperadas = {(e["documento_id"], e["pagina_pdf"]) for e in caso["evidencias"]}
        ancoras = [
            any(
                doc.metadata["documento_id"] == evidencia["documento_id"]
                and doc.metadata["pagina_pdf"] == evidencia["pagina_pdf"]
                and normalizar(evidencia["trecho"]) in normalizar(doc.page_content)
                for doc in documentos
            )
            for evidencia in caso["evidencias"]
        ]
        fontes = set(caso["esperado"]["fontes_obrigatorias"])
        resultado = {
            "id": caso["id"],
            "pergunta": caso["pergunta"],
            "alguma_pagina_esperada": bool(paginas & esperadas),
            "todas_paginas_esperadas": esperadas <= paginas,
            "todas_fontes_obrigatorias": fontes
            <= {d.metadata["documento_id"] for d in documentos},
            "cobertura_paginas": len(paginas & esperadas) / len(esperadas),
            "ancoras_encontradas": sum(ancoras),
            "ancoras_esperadas": len(ancoras),
            "recuperados": [
                {
                    chave: d.metadata[chave]
                    for chave in (
                        "chunk_id",
                        "documento_id",
                        "source",
                        "pagina_pdf",
                        "tipo_conteudo",
                    )
                }
                for d in documentos
            ],
        }
        resultados.append(resultado)
        if exibir_progresso:
            print(
                f"{caso['id']}: páginas {len(paginas & esperadas)}/{len(esperadas)}, "
                f"âncoras {sum(ancoras)}/{len(ancoras)}",
                file=sys.stderr,
            )
    return {
        "schema_version": 1,
        "executado_em": datetime.now(UTC).isoformat(),
        "dataset_version": conjunto["dataset_version"],
        "escopo": "Recuperação dos 24 casos respondíveis; sem avaliação de respostas, recusas ou injection.",
        "limite": "Páginas e âncoras são indicadores de localização, não comprovação de contexto suficiente nem scores RAGAS.",
        "configuracao": {
            "colecao": config.collection_name,
            "k": config.top_k,
            "chunk_size": config.chunk_size,
            "chunk_overlap": config.chunk_overlap,
            "chunks": manifesto.get("chunks"),
            "ids_sha256": manifesto.get("ids_sha256"),
            "embedding_model": config.embedding_model,
            "embedding_digest": manifesto.get("perfil", {}).get("embedding_digest"),
            "loader_version": manifesto.get("perfil", {}).get("loader_version"),
        },
        "resumo": {
            "casos": len(resultados),
            "com_alguma_pagina_esperada": sum(
                r["alguma_pagina_esperada"] for r in resultados
            ),
            "com_todas_paginas_esperadas": sum(
                r["todas_paginas_esperadas"] for r in resultados
            ),
            "com_todas_fontes_obrigatorias": sum(
                r["todas_fontes_obrigatorias"] for r in resultados
            ),
            "cobertura_media_paginas": round(
                sum(r["cobertura_paginas"] for r in resultados) / len(resultados), 4
            ),
            "ancoras_encontradas": sum(r["ancoras_encontradas"] for r in resultados),
            "ancoras_esperadas": sum(r["ancoras_esperadas"] for r in resultados),
        },
        "resultados": resultados,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--saida", type=Path, default=ROOT / "evals/fase2_recuperacao.json"
    )
    parser.add_argument("--k", type=int, help="Compara outro k sem alterar o .env")
    args = parser.parse_args()
    config = RAGSettings.from_env()
    if args.k is not None:
        config = replace(config, top_k=args.k)
        config.validate()
    relatorio = avaliar(config)
    args.saida.write_text(
        json.dumps(relatorio, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(relatorio["resumo"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
