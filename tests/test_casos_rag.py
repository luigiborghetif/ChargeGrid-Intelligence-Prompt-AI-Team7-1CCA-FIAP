"""Integridade do conjunto documental, das evidências e dos ataques isolados."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATASET = json.loads((ROOT / "evals/casos_rag.json").read_text(encoding="utf-8"))
DOCUMENTOS = {item["id"]: item for item in DATASET["documentos"]}
CASOS = DATASET["casos"]


def _arquivo_interno(caminho: str) -> Path:
    arquivo = (ROOT / caminho).resolve()
    assert arquivo.is_relative_to(ROOT)
    assert arquivo.is_file()
    return arquivo


def _normalizar(texto: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", texto)).casefold()


def test_conjunto_fixo_cobre_as_tres_categorias() -> None:
    assert len({caso["id"] for caso in CASOS}) == len(CASOS)
    assert Counter(caso["categoria"] for caso in CASOS) == {
        "respondiveis": 24,
        "sem_evidencia": 8,
        "injecao_documental": 6,
    }


@pytest.mark.parametrize("documento", DATASET["documentos"], ids=DOCUMENTOS)
def test_fontes_correspondem_aos_pdfs_analisados(documento: dict) -> None:
    arquivo = _arquivo_interno(documento["arquivo"])
    assert arquivo.is_relative_to(ROOT / "data/knowledge_base")
    assert arquivo.suffix == ".pdf"
    assert arquivo.read_bytes().startswith(b"%PDF-")
    assert hashlib.sha256(arquivo.read_bytes()).hexdigest() == documento["sha256"]


@pytest.mark.parametrize("caso", CASOS, ids=lambda caso: caso["id"])
def test_gabaritos_tem_criterios_e_referencias_coerentes(caso: dict) -> None:
    assert caso["pergunta"].strip()
    esperado = caso["esperado"]
    assert esperado["resposta_referencia"].strip()
    assert esperado["criterios_obrigatorios"]
    assert all(item.strip() for item in esperado["criterios_obrigatorios"])
    assert esperado["citacao_obrigatoria"] == bool(caso["evidencias"])
    assert set(esperado["fontes_obrigatorias"]) == {
        evidencia["documento_id"] for evidencia in caso["evidencias"]
    }
    for evidencia in caso["evidencias"]:
        documento = DOCUMENTOS[evidencia["documento_id"]]
        assert 1 <= evidencia["pagina_pdf"] <= documento["paginas"]
        assert evidencia["trecho"].strip()
        assert evidencia["secao"].strip()

    if caso["categoria"] == "sem_evidencia":
        assert esperado["comportamento"] == "abster_total_ou_parcial"
        assert caso["escopo_da_ausencia"].strip()
        assert esperado["erros_a_evitar"]
        assert all(item["papel"] == "limite_contextual" for item in caso["evidencias"])
    else:
        assert esperado["comportamento"] == "responder"
        assert caso["evidencias"]
        assert all(item["papel"] == "suporte" for item in caso["evidencias"])


def test_documentos_adversariais_estao_isolados_e_integros() -> None:
    arquivos = set()
    for caso in CASOS:
        if caso["categoria"] != "injecao_documental":
            assert "ataque" not in caso
            continue
        ataque = caso["ataque"]
        arquivo = _arquivo_interno(ataque["arquivo"])
        assert arquivo.is_relative_to(ROOT / "evals/fixtures/prompt_injection")
        assert not arquivo.is_relative_to(ROOT / "data/knowledge_base")
        assert hashlib.sha256(arquivo.read_bytes()).hexdigest() == ataque["sha256"]
        assert ataque["objetivo"].strip()
        assert ataque["aplicacao"].strip()
        assert set(ataque["variantes_ordem"]) == {
            "antes_das_evidencias_legitimas",
            "depois_das_evidencias_legitimas",
        }
        arquivos.add(arquivo)
    assert len(arquivos) == 6
    assert arquivos == set((ROOT / "evals/fixtures/prompt_injection").glob("*.md"))


def test_trechos_de_evidencia_existem_nas_paginas_dos_pdfs() -> None:
    # A suíte estrutural continua disponível sem dependências de leitura de PDF.
    pymupdf = pytest.importorskip("pymupdf", reason="Auditoria textual requer PyMuPDF")
    textos = {}
    for identificador, documento in DOCUMENTOS.items():
        with pymupdf.open(_arquivo_interno(documento["arquivo"])) as pdf:
            assert len(pdf) == documento["paginas"]
            textos[identificador] = [
                _normalizar(pagina.get_text(sort=True)) for pagina in pdf
            ]
    for caso in CASOS:
        for evidencia in caso["evidencias"]:
            pagina = textos[evidencia["documento_id"]][evidencia["pagina_pdf"] - 1]
            assert _normalizar(evidencia["trecho"]) in pagina, (
                caso["id"],
                evidencia,
            )
