"""Chunking recursivo de texto e divisão de tabelas por linhas completas."""

from __future__ import annotations

import hashlib
import json
import re

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from rag.config import RAGSettings

CHUNKING_VERSION = "recursive-table-rows-v1"


def _partes(conteudo: str) -> list[tuple[bool, str]]:
    """Separa blocos Markdown de tabela dos parágrafos ao redor."""
    partes: list[tuple[bool, str]] = []
    linhas: list[str] = []
    tabela_anterior = False
    for linha in conteudo.splitlines():
        tabela = linha.lstrip().startswith("|")
        if linhas and tabela != tabela_anterior:
            partes.append((tabela_anterior, "\n".join(linhas)))
            linhas = []
        linhas.append(linha)
        tabela_anterior = tabela
    if linhas:
        partes.append((tabela_anterior, "\n".join(linhas)))
    return partes


def _tabela_chunks(tabela: str, tamanho: int, notas: str) -> list[str]:
    linhas = tabela.splitlines()
    if len(linhas) < 2 or not re.fullmatch(r"[\s|:\-]+", linhas[1]):
        return [tabela]
    cabecalho = "\n".join(linhas[:2])
    sufixo = f"\n\nNotas da página:\n{notas}" if notas else ""
    resultado, grupo = [], []
    for linha in linhas[2:]:
        candidato = "\n".join([cabecalho, *grupo, linha]) + sufixo
        if grupo and len(candidato) > tamanho:
            resultado.append("\n".join([cabecalho, *grupo]) + sufixo)
            grupo = []
        grupo.append(linha)
    if grupo:
        resultado.append("\n".join([cabecalho, *grupo]) + sufixo)
    return resultado or [tabela + sufixo]


def dividir_documentos(paginas: list[Document], config: RAGSettings) -> list[Document]:
    """Preserva página, cabeçalhos e notas; IDs são determinísticos."""
    config.validate()
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    resultado = []
    for pagina in paginas:
        # Notas com *1, *2 e *3 qualificam os valores das tabelas técnicas.
        notas = "\n".join(
            re.findall(
                r"(?m)^\s*\*\d[^\n]*(?:\n(?!\s*\*|\s*$)[^\n]+)*", pagina.page_content
            )
        ).strip()
        indice = 0
        for tabela, bloco in _partes(pagina.page_content):
            textos = (
                _tabela_chunks(bloco, config.chunk_size, notas)
                if tabela
                else splitter.split_text(bloco)
            )
            for texto in textos:
                if not texto.strip():
                    continue
                metadados = {
                    **pagina.metadata,
                    "chunk_index": indice,
                    "tipo_conteudo": "tabela" if tabela else "texto",
                    "chunking_version": CHUNKING_VERSION,
                    "acima_tamanho_alvo": len(texto) > config.chunk_size,
                }
                identidade = json.dumps(
                    [metadados, config.chunk_size, config.chunk_overlap, texto],
                    sort_keys=True,
                    ensure_ascii=False,
                )
                chunk_id = hashlib.sha256(identidade.encode()).hexdigest()
                metadados["chunk_id"] = chunk_id
                resultado.append(
                    Document(id=chunk_id, page_content=texto, metadata=metadados)
                )
                indice += 1
    return resultado
