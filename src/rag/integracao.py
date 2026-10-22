"""LCEL de geração e conferência mínima dos apoios contra as fontes fornecidas."""

from __future__ import annotations

import json
import re
import unicodedata

from langchain_core.documents import Document
from langchain_core.output_parsers import PydanticOutputParser

from chain.builder import criar_llm, criar_parser
from chargegrid.config import Settings
from rag.config import RAGSettings
from rag.errors import ErroRAG
from rag.prompt_rag import criar_prompt_integrado
from schemas.resposta_rag import RespostaFundamentada


class ErroFundamentacao(ErroRAG):
    """A referência ou o trecho não pertence às fontes da consulta."""


def construir_chain_integrada(config: Settings, rag: RAGSettings, *, operacional: bool):
    parser = (
        criar_parser()
        if operacional
        else PydanticOutputParser(pydantic_object=RespostaFundamentada)
    )
    prompt = criar_prompt_integrado(rag.prompt_path, parser.get_format_instructions())
    return prompt | criar_llm(config) | parser


def normalizar_trecho(texto: str) -> str:
    texto = re.sub(r"<br\s*/?>", " ", texto, flags=re.IGNORECASE)
    texto = unicodedata.normalize("NFKC", texto).casefold()
    return re.sub(r"\s+", "", texto)


def conferir_apoios(
    resposta: RespostaFundamentada,
    documentos: list[Document],
    contexto_operacional: str | None,
    origem_operacional: str,
) -> tuple[list[str], set[str]]:
    fontes = {
        doc.metadata["chunk_id"]: (
            doc.page_content,
            f"{doc.metadata['source']} — página PDF {doc.metadata['pagina_pdf']}",
        )
        for doc in documentos
    }
    if contexto_operacional:
        fontes["operacao_atual"] = (contexto_operacional, origem_operacional)
    referencias, usados = [], set()
    for apoio in resposta.apoios:
        fonte = fontes.get(apoio.fonte_id)
        if fonte is None or normalizar_trecho(apoio.trecho) not in normalizar_trecho(
            fonte[0]
        ):
            raise ErroFundamentacao("Referência ou trecho não encontrado no contexto.")
        usados.add(apoio.fonte_id)
        referencia = f"{fonte[1]} — {apoio.trecho}"
        if referencia not in referencias:
            referencias.append(referencia)
    return referencias, usados


def contexto_operacional_com_origem(contexto: str, origem: str) -> str:
    return json.dumps(
        {
            "fonte_id": "operacao_atual",
            "arquivo": origem,
            "procedencia": "JSON validado e indicadores calculados em Python",
            "dados": json.loads(contexto),
        },
        ensure_ascii=False,
    )
