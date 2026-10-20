"""Leitura de PDFs por página, com tabelas Markdown e metadados de origem."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import warnings
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path

from langchain_core.documents import Document

from rag.errors import ErroRAG

LOADER_VERSION = "pymupdf-page-tables-v1"


def _carregar_catalogo(raiz: Path) -> dict[str, dict[str, str]]:
    arquivo = raiz / "catalogo.json"
    if not arquivo.exists():
        return {}
    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
        if dados["schema_version"] != 1:
            raise ValueError("Versão de catálogo inválida")
        catalogo = {}
        ids = set()
        for registro in dados["documentos"]:
            if not all(
                isinstance(registro[chave], str) and registro[chave].strip()
                for chave in ("arquivo", "id", "versao", "natureza")
            ):
                raise ValueError("Campos vazios no catálogo")
            if registro["arquivo"] in catalogo or registro["id"] in ids:
                raise ValueError("Arquivo ou ID duplicado no catálogo")
            ids.add(registro["id"])
            catalogo[registro["arquivo"]] = registro
        return catalogo
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ErroRAG("Catálogo documental inválido: revise catalogo.json.") from exc


def _tabelas_pagina(pagina):
    """Detecta grades e tabelas técnicas com três cabeçalhos de modelos."""
    tabelas = list(pagina.find_tables())
    if tabelas:
        return tabelas
    modelos = [
        palavra
        for palavra in pagina.get_text("words")
        if re.fullmatch(r"GW\d+K-HCA-20", palavra[4])
    ]
    if len(modelos) != 3:
        return []
    modelos.sort(key=lambda palavra: palavra[0])
    if max(p[1] for p in modelos) - min(p[1] for p in modelos) > 5:
        return []
    centros = [(p[0] + p[2]) / 2 for p in modelos]
    passo = (centros[-1] - centros[0]) / 2
    bordas = [
        desenho["rect"].x0
        for desenho in pagina.get_drawings()
        if desenho["rect"].width > pagina.rect.width * 0.6
    ]
    limites = [
        min(bordas) if bordas else max(0, centros[0] - 2.5 * passo),
        centros[0] - passo / 2,
        (centros[0] + centros[1]) / 2,
        (centros[1] + centros[2]) / 2,
        min(pagina.rect.width, centros[-1] + passo / 2),
    ]
    tabelas = list(
        pagina.find_tables(
            clip=(
                limites[0],
                min(p[1] for p in modelos) - 4,
                limites[-1],
                pagina.rect.height,
            ),
            vertical_strategy="explicit",
            vertical_lines=limites,
            horizontal_strategy="lines",
        )
    )
    for tabela in tabelas:
        if tabela.col_count == 4:
            tabela.header.names = ["Dados técnicos", *(p[4] for p in modelos)]
            tabela.header.external = True
    return tabelas


def _pagina_com_tabelas(pagina, original: str) -> tuple[str, int]:
    """Substitui o texto achatado de cada tabela por sua representação Markdown."""
    tabelas = _tabelas_pagina(pagina)
    if not tabelas:
        return original, 0
    linhas = {}
    for x0, y0, x1, y1, palavra, bloco, linha, _ in pagina.get_text("words", sort=True):
        centro_x, centro_y = (x0 + x1) / 2, (y0 + y1) / 2
        if any(
            t.bbox[0] <= centro_x <= t.bbox[2] and t.bbox[1] <= centro_y <= t.bbox[3]
            for t in tabelas
        ):
            continue
        linhas.setdefault((bloco, linha), []).append(palavra)
    texto = "\n".join(" ".join(palavras) for palavras in linhas.values())
    # Não propagar automaticamente valores de células vizinhas/linhas anteriores.
    markdown = "\n\n".join(t.to_markdown(fill_empty=False) for t in tabelas)
    return f"{texto}\n\n{markdown}", len(tabelas)


@dataclass(frozen=True, slots=True)
class BaseDocumental:
    paginas: list[Document]
    arquivos: dict[str, str]
    paginas_vazias: tuple[str, ...]


def carregar_pdfs(diretorio: Path) -> BaseDocumental:
    """Carrega apenas PDFs sob a raiz escolhida, sem seguir links externos."""
    import pymupdf
    from langchain_community.document_loaders import PyMuPDFLoader

    raiz = diretorio.resolve()
    if not raiz.is_dir():
        raise ErroRAG(f"Diretório de conhecimento não encontrado: {raiz}")
    arquivos = sorted(
        path
        for path in raiz.rglob("*")
        if path.is_file() and path.suffix.lower() == ".pdf"
    )
    if not arquivos:
        raise ErroRAG("Nenhum PDF encontrado na base; o índice não será modificado.")
    catalogo = _carregar_catalogo(raiz)
    paginas, hashes, vazias = [], {}, []
    for arquivo in arquivos:
        if not arquivo.resolve().is_relative_to(raiz):
            raise ErroRAG(f"PDF aponta para fora da base: {arquivo.name}")
        relativo = arquivo.relative_to(raiz).as_posix()
        registro = catalogo.get(relativo, {})
        digest = hashlib.sha256(arquivo.read_bytes()).hexdigest()
        try:
            # Bibliotecas de PDF podem imprimir avisos; stdout da CLI é JSON.
            with redirect_stdout(sys.stderr):
                docs = PyMuPDFLoader(arquivo, mode="page", extract_images=False).load()
            with redirect_stdout(sys.stderr), pymupdf.open(arquivo) as pdf:
                for doc in docs:
                    conteudo, quantidade = _pagina_com_tabelas(
                        pdf[doc.metadata["page"]], doc.page_content
                    )
                    doc.page_content = conteudo
                    doc.metadata["tabelas_extraidas"] = quantidade
        except Exception as exc:
            raise ErroRAG(f"Não foi possível extrair o PDF {relativo}.") from exc
        if not docs:
            raise ErroRAG(f"PDF sem páginas: {relativo}")
        hashes[relativo] = digest
        paginas_legiveis = 0
        for doc in docs:
            numero = int(doc.metadata["page"]) + 1
            if not doc.page_content.strip():
                vazias.append(f"{relativo}: página PDF {numero}")
                continue
            paginas_legiveis += 1
            # Chroma requer metadados escalares; não conservar valores opcionais None.
            paginas.append(
                Document(
                    page_content=doc.page_content,
                    metadata={
                        "source": relativo,
                        "documento_id": registro.get(
                            "id", hashlib.sha256(relativo.encode()).hexdigest()
                        ),
                        "versao": registro.get("versao", "nao_declarada"),
                        "natureza": registro.get("natureza", "nao_classificada"),
                        "documento_sha256": digest,
                        "pagina_pdf": numero,
                        "page": numero - 1,
                        "total_pages": len(docs),
                        "title": str(doc.metadata.get("title") or arquivo.stem),
                        "loader_version": LOADER_VERSION,
                        "tabelas_extraidas": doc.metadata["tabelas_extraidas"],
                    },
                )
            )
        if not paginas_legiveis:
            raise ErroRAG(
                f"{relativo} não contém texto extraível; forneça PDF pesquisável ou OCR."
            )
    if vazias:
        warnings.warn(
            f"{len(vazias)} página(s) sem texto foram ignoradas. "
            "Consulte paginas_vazias no relatório de indexação.",
            UserWarning,
            stacklevel=2,
        )
    return BaseDocumental(paginas, hashes, tuple(vazias))
