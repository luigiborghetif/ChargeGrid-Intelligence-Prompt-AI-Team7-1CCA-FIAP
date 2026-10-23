"""Integridade da revisão: não atribuir nota a outra resposta ou a erro ocultado."""

import importlib.util
from pathlib import Path

import pytest

CAMINHO = Path(__file__).resolve().parents[1] / "evals/metricas_sprint4.py"
SPEC = importlib.util.spec_from_file_location("metricas_sprint4", CAMINHO)
modulo = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(modulo)


def test_rejeita_nota_apos_alteracao_da_resposta():
    registro = {"resposta": "texto original"}
    nota = {"registro_sha256": modulo.assinatura(registro)}
    registro["resposta"] = "texto alterado"
    with pytest.raises(ValueError, match="não corresponde"):
        modulo.pontuar(registro, nota, {})


def test_erro_nao_pode_ser_pontuado_como_resposta_correta():
    registro = {"status": "erro"}
    nota = {
        "registro_sha256": modulo.assinatura(registro),
        "criterios_atendidos": [True],
        "afirmacoes": [],
    }
    caso = {"esperado": {"criterios_obrigatorios": ["Responder com evidência"]}}
    with pytest.raises(ValueError, match="Erro de execução"):
        modulo.pontuar(registro, nota, caso)
