"""Comandos para indexar a base, inspecionar o índice e recuperar evidências."""

from __future__ import annotations

import argparse
import json
import sys

from rag.config import RAGSettings
from rag.errors import ErroRAG


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingestão e busca documental ChargeGrid"
    )
    parser.add_argument(
        "--debug", action="store_true", help="Mostra o traceback em falhas"
    )
    comandos = parser.add_subparsers(dest="comando", required=True)
    comandos.add_parser("indexar", help="Sincroniza os PDFs com a coleção local")
    comandos.add_parser("status", help="Mostra o manifesto local, sem inferência")
    buscar = comandos.add_parser("buscar", help="Recupera trechos com arquivo e página")
    buscar.add_argument("pergunta")
    argumentos = parser.parse_args()
    try:
        config = RAGSettings.from_env()
        if argumentos.comando == "indexar":
            from rag.vector_store import indexar_base

            print("Indexando a base documental...", file=sys.stderr)
            resultado = indexar_base(config)
        elif argumentos.comando == "status":
            from rag.vector_store import consultar_status

            resultado = consultar_status(config)
        else:
            from rag.retriever import buscar_documentos

            documentos = buscar_documentos(argumentos.pergunta, config)
            resultado = {
                "pergunta": argumentos.pergunta,
                "trechos": [
                    {"conteudo": doc.page_content, "metadados": doc.metadata}
                    for doc in documentos
                ],
            }
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
    except (ErroRAG, OSError) as exc:
        if argumentos.debug:
            raise
        print(f"Erro: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except Exception as exc:
        if argumentos.debug:
            raise
        print(
            f"Falha no pipeline ({type(exc).__name__}). A indexação pode ser repetida "
            "após corrigir a causa. Use --debug antes do subcomando para diagnóstico.",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
