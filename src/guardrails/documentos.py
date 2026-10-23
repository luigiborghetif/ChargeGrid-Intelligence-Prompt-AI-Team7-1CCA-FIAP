"""Triagem de contexto documental; regras locais não substituem grounding semântico."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from langchain_core.documents import Document

from guardrails.moderation import PADROES_INJECAO, normalizar_texto
from rag.errors import ErroRAG

PADROES_INSTRUCAO_DOCUMENTAL = (
    re.compile(
        r"\binstru(?:cao|coes)\s+(?:(?:obrigatoria|prioritaria|especial|direta|administrativa)s?\s+){0,2}"
        r"(?:ao|aos|para\s+o|para\s+os)\s+(?:modelo|assistentes?|chatbot)\b"
    ),
    re.compile(
        r"\b(?:nota|regra|atualizacao)\b.{0,60}\b(?:para|ao)\s+(?:(?:o|a)\s+)?(?:assistentes?|chatbot|modelo)\b"
    ),
    re.compile(
        r"\b(?:ignore|desconsidere)\b.{0,55}\b(?:pergunta|instrucoes|regras|fontes)\b"
    ),
)


@dataclass(frozen=True)
class TriagemDocumental:
    documentos: list[Document]
    bloqueados: list[dict[str, str]]


def triar_documentos(documentos: list[Document]) -> TriagemDocumental:
    """Quarentena em memória, sem alterar PDFs ou o índice persistente.

    Instruções ao usuário do produto continuam permitidas. A triagem procura
    padrões de tomada de controle do assistente, também nos metadados.
    """
    aceitos, bloqueados, vistos = [], [], {}
    for documento in documentos:
        meta = documento.metadata
        for campo in ("chunk_id", "source", "documento_id", "versao", "natureza"):
            if not isinstance(meta.get(campo), str) or not meta[campo].strip():
                raise ErroRAG("Documento recuperado com metadados inválidos.")
        pagina = meta.get("pagina_pdf")
        if type(pagina) is not int or pagina < 1:
            raise ErroRAG("Documento recuperado sem página PDF válida.")
        identificador = meta["chunk_id"]
        if identificador == "operacao_atual" or identificador.startswith("resultado_"):
            raise ErroRAG(
                "Identificador documental invade o espaço de fontes operacionais."
            )
        assinatura = (
            documento.page_content,
            json.dumps(meta, sort_keys=True, ensure_ascii=False),
        )
        if identificador in vistos:
            if vistos[identificador] != assinatura:
                raise ErroRAG("Fontes diferentes possuem o mesmo identificador.")
            continue
        vistos[identificador] = assinatura
        texto = normalizar_texto(
            documento.page_content + "\n" + json.dumps(meta, ensure_ascii=False)
        )
        if any(
            p.search(texto) for p in (*PADROES_INJECAO, *PADROES_INSTRUCAO_DOCUMENTAL)
        ):
            bloqueados.append(
                {
                    "chunk_id": identificador,
                    "arquivo": meta["source"],
                    "motivo": "instrucoes_ao_assistente",
                }
            )
        else:
            aceitos.append(documento)
    return TriagemDocumental(aceitos, bloqueados)


def modelos_sem_evidencia(pergunta: str, documentos: list[Document]) -> list[str]:
    """Não transfere especificações de um código de produto para outro."""
    modelos = set(
        re.findall(r"\bGW\d+K(?:-HCA-\d+)?\b", normalizar_texto(pergunta).upper())
    )
    conteudo = "\n".join(d.page_content.upper() for d in documentos)
    return sorted(
        modelo
        for modelo in modelos
        if not re.search(
            rf"(?<![\w-]){re.escape(modelo)}(?![\w-])"
            if "-HCA-" in modelo
            else rf"(?<![\w-]){re.escape(modelo)}(?!\w)",
            conteudo,
        )
    )
