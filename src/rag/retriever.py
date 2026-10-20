"""Busca semântica com texto e fonte, sem chamar um modelo de geração."""

from __future__ import annotations

from langchain_core.documents import Document
from langchain_core.vectorstores import VectorStoreRetriever

from rag.config import RAGSettings
from rag.errors import ErroRAG
from rag.vector_store import abrir_indice_pronto, bloquear_indice


def criar_retriever(store, config: RAGSettings) -> VectorStoreRetriever:
    """Cria o retriever LCEL para um store já aberto e validado."""
    return store.as_retriever(
        search_type="similarity", search_kwargs={"k": config.top_k}
    )


def buscar_documentos(pergunta: str, config: RAGSettings) -> list[Document]:
    pergunta = pergunta.strip()
    if not pergunta:
        raise ErroRAG("A pergunta não pode ser vazia.")
    if len(pergunta) > 2000:
        raise ErroRAG("A pergunta deve ter no máximo 2000 caracteres.")
    with bloquear_indice(config):
        store, _ = abrir_indice_pronto(config)
        return criar_retriever(store, config).invoke(pergunta)
