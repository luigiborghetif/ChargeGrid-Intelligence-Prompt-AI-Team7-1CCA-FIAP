"""Testes do carregamento e da validação dos dados operacionais."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chargegrid.config import settings
from chargegrid.dados import (
    ErroDados,
    InconsistenciaDadosWarning,
    carregar_operacao,
    validar_totais,
)


def _dados_exemplo() -> dict:
    return json.loads(settings.data_path.read_text(encoding="utf-8"))


def _salvar_json(tmp_path: Path, dados: dict) -> Path:
    caminho = tmp_path / "operacao.json"
    caminho.write_text(
        json.dumps(dados, ensure_ascii=False),
        encoding="utf-8",
    )
    return caminho


def test_carrega_exemplo_e_reporta_divergencia_de_energia() -> None:
    with pytest.warns(InconsistenciaDadosWarning, match="energia_total_kwh"):
        operacao = carregar_operacao()

    inconsistencias = validar_totais(operacao)

    assert len(operacao.snapshot_carregadores.carregadores) == 10
    assert len(inconsistencias) == 1
    assert inconsistencias[0].informado == 342.0
    assert inconsistencias[0].calculado == 302.0


def test_rejeita_ids_de_carregadores_duplicados(tmp_path: Path) -> None:
    dados = _dados_exemplo()
    carregadores = dados["snapshot_carregadores"]["carregadores"]
    carregadores[-1]["id"] = carregadores[0]["id"]
    caminho = _salvar_json(tmp_path, dados)

    with pytest.raises(ErroDados, match="IDs dos carregadores devem ser únicos"):
        carregar_operacao(caminho, alertar_inconsistencias=False)


def test_rejeita_valor_operacional_negativo(tmp_path: Path) -> None:
    dados = _dados_exemplo()
    dados["demanda_horaria"][0]["potencia_media_kw"] = -1
    caminho = _salvar_json(tmp_path, dados)

    with pytest.raises(ErroDados, match="potencia_media_kw"):
        carregar_operacao(caminho, alertar_inconsistencias=False)


def test_informa_linha_e_coluna_quando_json_e_invalido(tmp_path: Path) -> None:
    caminho = tmp_path / "invalido.json"
    caminho.write_text('{"site":', encoding="utf-8")

    with pytest.raises(ErroDados, match=r"linha 1, coluna \d+"):
        carregar_operacao(caminho)


def test_informa_caminho_quando_arquivo_nao_existe(tmp_path: Path) -> None:
    caminho = tmp_path / "inexistente.json"

    with pytest.raises(ErroDados, match=str(caminho)):
        carregar_operacao(caminho)
