"""Coleção Chroma persistente, sincronização por IDs e manifesto de integridade."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings
from filelock import FileLock, Timeout
from langchain_chroma import Chroma

from rag.chunking import CHUNKING_VERSION, dividir_documentos
from rag.config import RAGSettings
from rag.embeddings import EMBEDDING_STRATEGY, criar_embeddings, identificar_modelo
from rag.errors import ErroRAG
from rag.loader import LOADER_VERSION, carregar_pdfs


def _manifesto_path(config: RAGSettings) -> Path:
    return config.chroma_path / "chargegrid" / f"{config.collection_name}.json"


@contextmanager
def bloquear_indice(config: RAGSettings) -> Iterator[None]:
    """Serializa ingestão e consultas desta coleção, inclusive entre processos."""
    config.validate()
    pasta = _manifesto_path(config).parent
    pasta.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(pasta / f"{config.collection_name}.lock"))
    try:
        lock.acquire(timeout=0)
    except Timeout as exc:
        raise ErroRAG(
            "A coleção está em uso. Aguarde a operação atual terminar."
        ) from exc
    try:
        yield
    finally:
        lock.release()


def _ler_manifesto(config: RAGSettings) -> dict | None:
    arquivo = _manifesto_path(config)
    if not arquivo.exists():
        return None
    try:
        manifesto = json.loads(arquivo.read_text(encoding="utf-8"))
        if not isinstance(manifesto, dict) or manifesto.get("schema_version") != 1:
            raise ValueError("Versão de manifesto inválida")
        if not isinstance(manifesto.get("perfil"), dict):
            raise TypeError("Perfil ausente")
        return manifesto
    except (OSError, ValueError, TypeError) as exc:
        raise ErroRAG(
            "Manifesto do índice inválido. Preserve os arquivos para diagnóstico "
            "e use outra RAG_COLLECTION_NAME para uma nova indexação."
        ) from exc


def _salvar_manifesto(config: RAGSettings, manifesto: dict) -> None:
    destino = _manifesto_path(config)
    temporario = destino.with_suffix(".json.tmp")
    temporario.write_text(
        json.dumps(manifesto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporario.replace(destino)


def _perfil(config: RAGSettings, digest: str) -> dict:
    return {
        "knowledge_base_path": str(config.knowledge_base_path),
        "embedding_model": config.embedding_model,
        "embedding_digest": digest,
        "embedding_strategy": EMBEDDING_STRATEGY,
        "loader_version": LOADER_VERSION,
        "chunking_version": CHUNKING_VERSION,
        "chunk_size": config.chunk_size,
        "chunk_overlap": config.chunk_overlap,
        "libraries": {
            nome: version(nome)
            for nome in (
                "pymupdf",
                "langchain-community",
                "langchain-text-splitters",
                "langchain-ollama",
            )
        },
    }


def _conferir_perfil(manifesto: dict, perfil: dict) -> None:
    if manifesto["perfil"] != perfil:
        raise ErroRAG(
            "A configuração, versão do extrator ou modelo de embeddings difere "
            "do índice salvo. Defina outra RAG_COLLECTION_NAME e indexe novamente; "
            "vetores incompatíveis não serão misturados."
        )


def _cliente(config: RAGSettings):
    return chromadb.PersistentClient(
        path=str(config.chroma_path),
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def _abrir_store(config: RAGSettings, *, criar: bool) -> Chroma:
    return Chroma(
        client=_cliente(config),
        collection_name=config.collection_name,
        embedding_function=criar_embeddings(config),
        create_collection_if_not_exists=criar,
        collection_configuration={"hnsw": {"space": "cosine"}} if criar else None,
    )


def _hash_ids(ids: list[str] | set[str]) -> str:
    return hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest()


def abrir_indice_pronto(config: RAGSettings) -> tuple[Chroma, dict]:
    """Abre índice existente; o chamador deve manter bloquear_indice ativo."""
    manifesto = _ler_manifesto(config)
    if manifesto is None:
        raise ErroRAG("Índice não encontrado. Execute chargegrid-rag indexar.")
    if manifesto.get("estado") != "pronto":
        raise ErroRAG(
            "A indexação anterior não foi concluída. Execute chargegrid-rag indexar "
            "novamente antes de consultar."
        )
    _conferir_perfil(manifesto, _perfil(config, identificar_modelo(config)))
    store = _abrir_store(config, criar=False)
    ids = store.get(include=[])["ids"]
    if not ids or _hash_ids(ids) != manifesto.get("ids_sha256"):
        raise ErroRAG(
            "Coleção incompleta. Execute chargegrid-rag indexar para sincronizar."
        )
    return store, manifesto


def indexar_base(config: RAGSettings) -> dict:
    """Sincroniza o corpus completo; elimina obsoletos só após gravar os novos."""
    config.validate()
    with bloquear_indice(config):
        digest = identificar_modelo(config)
        perfil = _perfil(config, digest)
        anterior = _ler_manifesto(config)
        if anterior is not None:
            _conferir_perfil(anterior, perfil)
        base = carregar_pdfs(config.knowledge_base_path)
        chunks = dividir_documentos(base.paginas, config)
        if not chunks:
            raise ErroRAG("Nenhum chunk extraído; o índice não será modificado.")
        desejados = {chunk.metadata["chunk_id"]: chunk for chunk in chunks}
        if len(desejados) != len(chunks):
            raise ErroRAG(
                "IDs de chunks duplicados; revise a extração antes de indexar."
            )
        store = _abrir_store(config, criar=True)
        existentes = set(store.get(include=[])["ids"])
        if anterior is None and existentes:
            raise ErroRAG(
                "A coleção já contém dados sem manifesto ChargeGrid. "
                "Escolha outra RAG_COLLECTION_NAME."
            )
        novos = sorted(set(desejados) - existentes)
        obsoletos = sorted(existentes - set(desejados))
        manifesto = {
            "schema_version": 1,
            "estado": "indexando",
            "colecao": config.collection_name,
            "perfil": perfil,
        }
        # Se uma operação falhar, o estado persistido bloqueia consultas parciais.
        _salvar_manifesto(config, manifesto)
        for inicio in range(0, len(novos), config.batch_size):
            lote = novos[inicio : inicio + config.batch_size]
            store.add_documents(
                [desejados[identificador] for identificador in lote], ids=lote
            )
        # Confere o corpus antes de remover trechos da versão anterior.
        atuais = {
            arquivo.relative_to(config.knowledge_base_path).as_posix(): hashlib.sha256(
                arquivo.read_bytes()
            ).hexdigest()
            for arquivo in config.knowledge_base_path.rglob("*")
            if arquivo.is_file() and arquivo.suffix.lower() == ".pdf"
        }
        if atuais != base.arquivos:
            raise ErroRAG(
                "A base mudou durante a ingestão. Execute a indexação novamente."
            )
        if identificar_modelo(config) != digest:
            raise ErroRAG("O modelo de embeddings mudou durante a ingestão.")
        for inicio in range(0, len(obsoletos), config.batch_size):
            store.delete(ids=obsoletos[inicio : inicio + config.batch_size])
        ids_finais = set(store.get(include=[])["ids"])
        if ids_finais != set(desejados):
            raise ErroRAG("A coleção não corresponde ao corpus. Repita a indexação.")
        manifesto.update(
            estado="pronto",
            atualizado_em=datetime.now(UTC).isoformat(),
            arquivos=base.arquivos,
            paginas_extraidas=len(base.paginas),
            paginas_vazias=list(base.paginas_vazias),
            chunks=len(chunks),
            chunks_acima_tamanho_alvo=sum(
                chunk.metadata["acima_tamanho_alvo"] for chunk in chunks
            ),
            ids_sha256=_hash_ids(ids_finais),
        )
        _salvar_manifesto(config, manifesto)
        return {
            **manifesto,
            "novos": len(novos),
            "reutilizados": len(desejados) - len(novos),
            "removidos": len(obsoletos),
        }


def consultar_status(config: RAGSettings) -> dict:
    """Exibe o manifesto sem chamar Ollama ou criar uma coleção vazia."""
    with bloquear_indice(config):
        manifesto = _ler_manifesto(config)
        return manifesto or {
            "estado": "nao_indexado",
            "colecao": config.collection_name,
            "configuracao": {
                chave: str(valor) if isinstance(valor, Path) else valor
                for chave, valor in asdict(config).items()
            },
        }
