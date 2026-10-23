"""Busca semântica com texto e fonte, sem chamar um modelo de geração."""

from __future__ import annotations

from langchain_core.documents import Document
from langchain_core.vectorstores import VectorStoreRetriever

from rag.config import RAGSettings
from rag.errors import ErroRAG
from rag.hibrido import combinar_resultados
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
        semanticos = criar_retriever(store, config).invoke(pergunta)
        if config.search_mode == "similarity":
            return semanticos
        registros = store.get(include=["documents", "metadatas"])
        corpus = [
            Document(page_content=texto, metadata=meta)
            for texto, meta in zip(
                registros["documents"], registros["metadatas"], strict=True
            )
        ]
        return combinar_resultados(pergunta, semanticos, corpus, config.top_k)
