"""Configuração do pipeline documental, independente do serviço conversacional."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

from chargegrid.config import ENV_FILE, PROJECT_ROOT
from rag.errors import ErroRAG


def _caminho(nome: str, padrao: str) -> Path:
    caminho = Path(os.getenv(nome, padrao)).expanduser()
    return (caminho if caminho.is_absolute() else PROJECT_ROOT / caminho).resolve()


def _inteiro(nome: str, padrao: int) -> int:
    try:
        return int(os.getenv(nome, str(padrao)))
    except ValueError as exc:
        raise ErroRAG(f"{nome} deve ser um número inteiro.") from exc


@dataclass(frozen=True, slots=True)
class RAGSettings:
    """Parâmetros de leitura, embeddings, persistência e busca."""

    knowledge_base_path: Path
    chroma_path: Path
    embedding_base_url: str = "http://localhost:11434"
    embedding_model: str = "nomic-embed-text"
    embedding_timeout: int = 120
    collection_name: str = "chargegrid_knowledge_v2"
    chunk_size: int = 600
    chunk_overlap: int = 200
    top_k: int = 8
    batch_size: int = 16

    @classmethod
    def from_env(cls) -> RAGSettings:
        load_dotenv(ENV_FILE, override=False)
        config = cls(
            knowledge_base_path=_caminho(
                "RAG_KNOWLEDGE_BASE_PATH", "data/knowledge_base"
            ),
            chroma_path=_caminho("RAG_CHROMA_PATH", "data/chroma"),
            embedding_base_url=os.getenv(
                "RAG_EMBEDDING_BASE_URL", "http://localhost:11434"
            ).rstrip("/"),
            embedding_model=os.getenv(
                "RAG_EMBEDDING_MODEL", "nomic-embed-text"
            ).strip(),
            embedding_timeout=_inteiro("RAG_EMBEDDING_TIMEOUT", 120),
            collection_name=os.getenv(
                "RAG_COLLECTION_NAME", "chargegrid_knowledge_v2"
            ).strip(),
            chunk_size=_inteiro("RAG_CHUNK_SIZE", 600),
            chunk_overlap=_inteiro("RAG_CHUNK_OVERLAP", 200),
            top_k=_inteiro("RAG_TOP_K", 8),
            batch_size=_inteiro("RAG_BATCH_SIZE", 16),
        )
        config.validate()
        return config

    def validate(self) -> None:
        url = urlsplit(self.embedding_base_url)
        if url.scheme not in {"http", "https"} or not url.hostname:
            raise ErroRAG("RAG_EMBEDDING_BASE_URL deve ser uma URL HTTP(S) válida.")
        if url.username or url.password or url.query or url.fragment:
            raise ErroRAG("Use um endereço de embeddings sem credenciais ou query.")
        if not self.embedding_model:
            raise ErroRAG("RAG_EMBEDDING_MODEL não pode ser vazio.")
        if not re.fullmatch(
            r"[a-zA-Z0-9][a-zA-Z0-9_-]{1,60}[a-zA-Z0-9]", self.collection_name
        ):
            raise ErroRAG(
                "RAG_COLLECTION_NAME deve ter 3 a 63 letras, números, _ ou -."
            )
        if self.chunk_size < 200:
            raise ErroRAG("RAG_CHUNK_SIZE deve ser pelo menos 200 caracteres.")
        if not 0 <= self.chunk_overlap < self.chunk_size:
            raise ErroRAG("RAG_CHUNK_OVERLAP deve estar entre zero e chunk_size - 1.")
        if min(self.top_k, self.batch_size, self.embedding_timeout) <= 0:
            raise ErroRAG("TOP_K, BATCH_SIZE e EMBEDDING_TIMEOUT devem ser positivos.")
        if (
            self.chroma_path == self.knowledge_base_path
            or self.chroma_path in self.knowledge_base_path.parents
            or self.knowledge_base_path in self.chroma_path.parents
        ):
            raise ErroRAG(
                "Use diretórios separados para a base de PDFs e para o Chroma."
            )
