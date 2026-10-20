"""Embeddings Nomic via Ollama, com prefixos distintos para texto e consulta."""

from __future__ import annotations

import httpx
from langchain_core.embeddings import Embeddings
from langchain_ollama import OllamaEmbeddings
from ollama import ResponseError

from rag.config import RAGSettings
from rag.errors import ErroRAG

EMBEDDING_STRATEGY = "nomic-search-prefixes-v1"


class EmbeddingsNomic(Embeddings):
    """Aplica os prefixos de recuperação do Nomic de forma consistente."""

    def __init__(self, config: RAGSettings) -> None:
        self.backend = OllamaEmbeddings(
            model=config.embedding_model,
            base_url=config.embedding_base_url,
            client_kwargs={"timeout": config.embedding_timeout},
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        try:
            return self.backend.embed_documents(
                [f"search_document: {text}" for text in texts]
            )
        except (ResponseError, httpx.HTTPError, ConnectionError) as exc:
            raise ErroRAG(
                "Falha ao gerar embeddings. Verifique o Ollama, o endereço "
                "RAG_EMBEDDING_BASE_URL e o modelo RAG_EMBEDDING_MODEL."
            ) from exc

    def embed_query(self, text: str) -> list[float]:
        try:
            return self.backend.embed_query(f"search_query: {text}")
        except (ResponseError, httpx.HTTPError, ConnectionError) as exc:
            raise ErroRAG(
                "Não foi possível gerar o embedding da pergunta no Ollama."
            ) from exc


def criar_embeddings(config: RAGSettings) -> EmbeddingsNomic:
    config.validate()
    return EmbeddingsNomic(config)


def identificar_modelo(config: RAGSettings) -> str:
    """Consulta o digest sem inferência e impede misturar versões de embeddings."""
    try:
        response = httpx.get(
            f"{config.embedding_base_url}/api/tags", timeout=config.embedding_timeout
        )
        response.raise_for_status()
        model_name = config.embedding_model
        if ":" not in model_name.rsplit("/", 1)[-1]:
            model_name += ":latest"
        for model in response.json().get("models", []):
            if model.get("name") == model_name or model.get("model") == model_name:
                digest = model.get("digest")
                if isinstance(digest, str) and digest:
                    return digest
    except (httpx.HTTPError, ValueError) as exc:
        raise ErroRAG(
            "Não foi possível consultar os modelos do Ollama. Verifique se o "
            "servidor está ativo e RAG_EMBEDDING_BASE_URL está correto."
        ) from exc
    raise ErroRAG(
        f"Modelo {config.embedding_model!r} não encontrado no Ollama. "
        f"Prepare-o com: ollama pull {config.embedding_model}"
    )
