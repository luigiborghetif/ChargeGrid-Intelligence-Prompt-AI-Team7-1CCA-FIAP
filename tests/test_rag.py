"""Contratos de ingestão e persistência com Chroma real e embeddings isolados."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import replace
from pathlib import Path

import pymupdf
import pytest
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from rag import vector_store
from rag.chunking import dividir_documentos
from rag.config import RAGSettings
from rag.errors import ErroRAG
from rag.loader import carregar_pdfs
from rag.retriever import buscar_documentos


class EmbeddingsTeste(Embeddings):
    """Vetores determinísticos apenas para testar persistência, não relevância."""

    def __init__(self) -> None:
        self.documentos = 0
        self.falhar = False
        self.falhar_apos: int | None = None

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if self.falhar or (
            self.falhar_apos is not None and self.documentos >= self.falhar_apos
        ):
            raise ErroRAG("Indisponibilidade simulada de embeddings")
        self.documentos += len(texts)
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return [valor / 255 for valor in hashlib.sha256(text.encode()).digest()]


def _pdf(arquivo: Path, textos: list[str]) -> None:
    with pymupdf.open() as pdf:
        for texto in textos:
            pagina = pdf.new_page()
            assert pagina.insert_textbox((40, 40, 550, 790), texto, fontsize=11) >= 0
        pdf.save(arquivo)


@pytest.fixture
def indice(tmp_path, monkeypatch):
    base = tmp_path / "pdfs"
    base.mkdir()
    _pdf(base / "regras.pdf", ["Fila de recarga: aguarde sua vez."])
    config = RAGSettings(knowledge_base_path=base, chroma_path=tmp_path / "chroma")
    embeddings = EmbeddingsTeste()
    monkeypatch.setattr(vector_store, "identificar_modelo", lambda _: "digest-teste")
    monkeypatch.setattr(vector_store, "criar_embeddings", lambda _: embeddings)
    return config, embeddings


def test_indexacao_e_idempotencia_sem_regerar_embeddings(indice) -> None:
    config, embeddings = indice
    primeira = vector_store.indexar_base(config)
    chamadas = embeddings.documentos
    segunda = vector_store.indexar_base(config)
    assert primeira["estado"] == segunda["estado"] == "pronto"
    assert primeira["novos"] == segunda["chunks"] > 0
    assert segunda["novos"] == segunda["removidos"] == 0
    assert segunda["reutilizados"] == primeira["chunks"]
    assert embeddings.documentos == chamadas
    assert primeira["ids_sha256"] == segunda["ids_sha256"]


def test_sincroniza_alteracao_adicao_e_remocao_de_pdf(indice) -> None:
    config, _ = indice
    anterior = vector_store.indexar_base(config)
    _pdf(
        config.knowledge_base_path / "novo.pdf",
        ["Tarifa de energia do novo documento."],
    )
    acrescido = vector_store.indexar_base(config)
    assert acrescido["novos"] > 0
    assert acrescido["reutilizados"] == anterior["chunks"]

    arquivo = config.knowledge_base_path / "regras.pdf"
    arquivo.unlink()
    _pdf(arquivo, ["Fila atualizada: prazo de dez minutos para iniciar."])
    alterado = vector_store.indexar_base(config)
    assert alterado["novos"] > 0 and alterado["removidos"] > 0

    (config.knowledge_base_path / "novo.pdf").unlink()
    removido = vector_store.indexar_base(config)
    assert removido["removidos"] > 0
    assert set(removido["arquivos"]) == {"regras.pdf"}
    with vector_store.bloquear_indice(config):
        store, _ = vector_store.abrir_indice_pronto(config)
        conteudo = " ".join(store.get()["documents"])
        assert "Fila atualizada" in conteudo
        assert "novo documento" not in conteudo
        assert "aguarde sua vez" not in conteudo


def test_falha_bloqueia_consulta_e_reindexacao_recupera(indice) -> None:
    config, embeddings = indice
    vector_store.indexar_base(config)
    config = replace(config, batch_size=1)
    _pdf(
        config.knowledge_base_path / "novo.pdf",
        [
            "Primeira página que exige novos embeddings.",
            "Segunda página que exige novos embeddings.",
        ],
    )
    embeddings.falhar_apos = embeddings.documentos + 1
    with pytest.raises(ErroRAG, match="Indisponibilidade simulada"):
        vector_store.indexar_base(config)
    assert vector_store.consultar_status(config)["estado"] == "indexando"
    with pytest.raises(ErroRAG, match="não foi concluída"):
        buscar_documentos("Qual é a regra?", config)
    embeddings.falhar_apos = None
    reparado = vector_store.indexar_base(config)
    assert reparado["estado"] == "pronto"
    assert reparado["reutilizados"] == 2
    assert reparado["novos"] == 1
    assert buscar_documentos("Qual é a regra?", config)


def test_base_vazia_nao_apaga_indice_pronto(indice) -> None:
    config, _ = indice
    anterior = vector_store.indexar_base(config)
    (config.knowledge_base_path / "regras.pdf").unlink()
    with pytest.raises(ErroRAG, match="Nenhum PDF"):
        vector_store.indexar_base(config)
    assert vector_store.consultar_status(config)["ids_sha256"] == anterior["ids_sha256"]


def test_rejeita_modelo_ou_chunking_incompativel(indice, monkeypatch) -> None:
    config, _ = indice
    vector_store.indexar_base(config)
    for alterado in (
        replace(config, chunk_size=800),
        replace(config, chunk_overlap=100),
    ):
        with pytest.raises(ErroRAG, match="incompatíveis"):
            vector_store.indexar_base(alterado)
    monkeypatch.setattr(vector_store, "identificar_modelo", lambda _: "outro-digest")
    with pytest.raises(ErroRAG, match="incompatíveis"):
        buscar_documentos("Qual é a regra?", config)


def test_indice_incompleto_e_detectado_e_reparado(indice) -> None:
    config, _ = indice
    vector_store.indexar_base(config)
    with vector_store.bloquear_indice(config):
        store, _ = vector_store.abrir_indice_pronto(config)
        store.delete(ids=store.get(include=[])["ids"][:1])
    with pytest.raises(ErroRAG, match="incompleta"):
        buscar_documentos("Qual é a regra?", config)
    assert vector_store.indexar_base(config)["novos"] == 1


def test_bloqueio_impede_acesso_simultaneo(indice) -> None:
    config, _ = indice
    with vector_store.bloquear_indice(config), pytest.raises(ErroRAG, match="em uso"):
        vector_store.consultar_status(config)


def test_metadados_por_pagina_e_catalogo(tmp_path) -> None:
    _pdf(
        tmp_path / "base.pdf",
        ["Primeira página de regras.", "Segunda página de tarifas."],
    )
    (tmp_path / "catalogo.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "documentos": [
                    {
                        "arquivo": "base.pdf",
                        "id": "base",
                        "versao": "v1",
                        "natureza": "cenario_simulado_do_projeto",
                    }
                ],
            }
        )
    )
    base = carregar_pdfs(tmp_path)
    assert [pagina.metadata["pagina_pdf"] for pagina in base.paginas] == [1, 2]
    assert [pagina.metadata["page"] for pagina in base.paginas] == [0, 1]
    assert all(p.metadata["documento_id"] == "base" for p in base.paginas)
    assert all(
        p.metadata["documento_sha256"] == base.arquivos["base.pdf"]
        for p in base.paginas
    )


def test_rejeita_pdf_corrompido_ou_sem_texto(tmp_path) -> None:
    arquivo = tmp_path / "base.pdf"
    arquivo.write_bytes(b"isto nao e um PDF")
    with pytest.raises(ErroRAG, match="extrair"):
        carregar_pdfs(tmp_path)
    arquivo.unlink()
    _pdf(arquivo, [""])
    with pytest.raises(ErroRAG, match="OCR"):
        carregar_pdfs(tmp_path)


def test_tabela_preserva_cabecalho_linhas_notas_e_ids(tmp_path) -> None:
    config = RAGSettings(
        knowledge_base_path=tmp_path / "pdfs",
        chroma_path=tmp_path / "chroma",
        chunk_size=250,
        chunk_overlap=30,
    )
    linhas = [f"|Campo {n}|{n} kW|{n + 1} kW|" for n in range(20)]
    pagina = Document(
        page_content="*1: O limite depende da configuração.\n\n"
        "|Dado|Modelo A|Modelo B|\n|---|---|---|\n" + "\n".join(linhas),
        metadata={"source": "base.pdf", "pagina_pdf": 1},
    )
    chunks = dividir_documentos([pagina], config)
    tabelas = [c for c in chunks if c.metadata["tipo_conteudo"] == "tabela"]
    assert len(tabelas) > 1
    assert all(c.page_content.startswith("|Dado|Modelo A|Modelo B|") for c in tabelas)
    assert all("*1: O limite" in c.page_content for c in tabelas)
    assert all(any(linha in c.page_content for c in tabelas) for linha in linhas)
    assert [c.id for c in chunks] == [
        c.id for c in dividir_documentos([pagina], config)
    ]


def test_avisos_do_leitor_nao_contaminam_stdout(tmp_path, monkeypatch, capsys) -> None:
    from langchain_community.document_loaders import PyMuPDFLoader

    _pdf(tmp_path / "base.pdf", ["Documento de teste."])
    original = PyMuPDFLoader.load

    def carregar_com_aviso(self):
        print("Aviso simulado do leitor PDF")
        return original(self)

    monkeypatch.setattr(PyMuPDFLoader, "load", carregar_com_aviso)
    carregar_pdfs(tmp_path)
    captura = capsys.readouterr()
    assert captura.out == ""
    assert "Aviso simulado do leitor PDF" in captura.err


def test_extracao_real_preserva_ancoras_modelos_potencias_e_notas(tmp_path) -> None:
    raiz = Path(__file__).resolve().parents[1]
    config = RAGSettings(
        knowledge_base_path=raiz / "data/knowledge_base",
        chroma_path=tmp_path / "chroma",
    )
    base = carregar_pdfs(config.knowledge_base_path)
    paginas = {
        (p.metadata["documento_id"], p.metadata["pagina_pdf"]): p for p in base.paginas
    }
    conjunto = json.loads((raiz / "evals/casos_rag.json").read_text(encoding="utf-8"))

    def normalizar(texto):
        texto = re.sub(r"<br\s*/?>", " ", texto, flags=re.IGNORECASE)
        return "".join(
            c for c in unicodedata.normalize("NFKD", texto).casefold() if c.isalnum()
        )

    for caso in conjunto["casos"]:
        if caso["categoria"] != "respondiveis":
            continue
        for evidencia in caso["evidencias"]:
            pagina = paginas[(evidencia["documento_id"], evidencia["pagina_pdf"])]
            assert normalizar(evidencia["trecho"]) in normalizar(pagina.page_content), (
                caso["id"]
            )

    ficha = paginas[("goodwe_hca_g2_datasheet", 2)]
    tabelas = [
        c
        for c in dividir_documentos([ficha], config)
        if c.metadata["tipo_conteudo"] == "tabela"
    ]
    assert all(
        "|GW7K-HCA-20|GW11K-HCA-20|GW22K-HCA-20|" in c.page_content for c in tabelas
    )
    assert any(
        "|Potência nominal de saída (W)|7000|11000|22000|" in c.page_content
        for c in tabelas
    )
    assert any("IP66" in c.page_content and "IP55" in c.page_content for c in tabelas)
