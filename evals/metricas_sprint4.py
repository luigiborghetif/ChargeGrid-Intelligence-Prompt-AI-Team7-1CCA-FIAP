"""Consolidação auditável de notas por inspeção; não executa modelo juiz."""

from __future__ import annotations

import json
import re
import statistics
import unicodedata
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PASTA = ROOT / "evals/sprint4"


def assinatura(registro: dict) -> str:
    return sha256(
        json.dumps(registro, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def pontuar(registro: dict, nota: dict, caso: dict) -> dict:
    if assinatura(registro) != nota["registro_sha256"]:
        raise ValueError("Nota não corresponde à saída avaliada")
    criterios = nota["criterios_atendidos"]
    if len(criterios) != len(caso["esperado"]["criterios_obrigatorios"]):
        raise ValueError("Quantidade de critérios difere do gabarito fixo")
    if any(type(v) is not bool for v in criterios):
        raise ValueError("Critérios devem ser booleanos")
    afirmacoes = nota["afirmacoes"]
    if any(
        type(a["sustentada"]) is not bool or not a["justificativa"] for a in afirmacoes
    ):
        raise ValueError("Afirmação sem avaliação fundamentada")
    if registro["status"] == "erro" and (afirmacoes or any(criterios)):
        raise ValueError(
            "Erro de execução não pode receber nota por resposta não exibida"
        )
    ids_citados = {c["fonte_id"] for c in registro["citacoes"]}
    documentos_citados = {
        d["metadados"]["documento_id"]
        for busca in registro["recuperacoes"]
        for d in busca["documentos"]
        if d["metadados"]["chunk_id"] in ids_citados
    }
    fontes_obrigatorias = set(caso["esperado"]["fontes_obrigatorias"]).issubset(
        documentos_citados
    )
    f = (
        sum(a["sustentada"] for a in afirmacoes) / len(afirmacoes)
        if afirmacoes
        else None
    )
    r = sum(criterios) / len(criterios)
    evidencias = caso["evidencias"]

    def normalizar(texto):
        texto = re.sub(r"<br\s*/?>", " ", texto, flags=re.IGNORECASE)
        return "".join(
            c for c in unicodedata.normalize("NFKD", texto).casefold() if c.isalnum()
        )

    localizadas = sum(
        any(
            d["metadados"]["documento_id"] == e["documento_id"]
            and d["metadados"]["pagina_pdf"] == e["pagina_pdf"]
            and normalizar(e["trecho"]) in normalizar(d["texto"])
            for busca in registro["recuperacoes"]
            for d in busca["documentos"]
        )
        for e in evidencias
    )
    return {
        "id": caso["id"],
        "categoria": caso["categoria"],
        "faithfulness": f,
        "answer_relevancy": r,
        "afirmacoes": len(afirmacoes),
        "criterios_atendidos": sum(criterios),
        "criterios_total": len(criterios),
        "citacao_visivel": bool(registro["citacoes"]),
        "erro_execucao": registro["status"] == "erro",
        "falha_saida": registro["codigo"]
        in {"resposta_invalida", "evidencia_invalida", "plano_invalido"},
        "fontes_obrigatorias_atendidas": fontes_obrigatorias,
        "resposta_integral_gabarito": f == 1 and r == 1 and fontes_obrigatorias,
        "ancoras_localizadas": localizadas,
        "ancoras_total": len(evidencias),
    }


def agregar(casos: list[dict]) -> dict:
    aplicaveis = [c["faithfulness"] for c in casos if c["faithfulness"] is not None]
    return {
        "casos": len(casos),
        "faithfulness": statistics.mean(aplicaveis) if aplicaveis else None,
        "faithfulness_n": len(aplicaveis),
        "answer_relevancy": statistics.mean(c["answer_relevancy"] for c in casos),
        "criterios_atendidos": sum(c["criterios_atendidos"] for c in casos),
        "criterios_total": sum(c["criterios_total"] for c in casos),
        "citacoes_visiveis": sum(c["citacao_visivel"] for c in casos),
        "erros_execucao": sum(c["erro_execucao"] for c in casos),
        "falhas_saida": sum(c["falha_saida"] for c in casos),
        "respostas_integrais_gabarito": sum(
            c["resposta_integral_gabarito"] for c in casos
        ),
        "ancoras_localizadas": sum(c["ancoras_localizadas"] for c in casos),
        "ancoras_total": sum(c["ancoras_total"] for c in casos),
    }


def main():
    protocolo = json.loads((PASTA / "protocolo.json").read_text())
    dataset = json.loads((ROOT / "evals/casos_rag.json").read_text())
    notas = json.loads((PASTA / "revisao.json").read_text())
    resumo = {
        "metodo": notas["metodo"],
        "avaliador": notas["avaliador"],
        "experimentos": {},
    }
    adendo = json.loads((PASTA / "adendo_modelo.json").read_text())
    for experimento in adendo["experimentos_pontuados"]:
        bruto = json.loads((PASTA / f"{experimento}.json").read_text())
        if {c["id"] for c in bruto["casos"]} != set(protocolo["ids"]):
            raise ValueError(
                "Experimento incompleto; não consolidar como avaliação concluída"
            )
        avaliados = []
        for registro in bruto["casos"]:
            caso = next(c for c in dataset["casos"] if c["id"] == registro["id"])
            nota = next(
                n
                for n in notas["experimentos"][experimento]
                if n["id"] == registro["id"]
            )
            avaliados.append(pontuar(registro, nota, caso))
        resumo["experimentos"][experimento] = {
            "configuracao": bruto["configuracao"],
            "prompts": bruto["prompts"],
            "geral": agregar(avaliados),
            "categorias": {
                categoria: agregar(
                    [c for c in avaliados if c["categoria"] == categoria]
                )
                for categoria in ["respondiveis", "sem_evidencia", "injecao_documental"]
            },
            "latencia_media_segundos": statistics.mean(
                c["latencia_segundos"] for c in bruto["casos"]
            ),
            "casos": avaliados,
        }
    a = resumo["experimentos"]["baseline_gemma"]["geral"]
    b = resumo["experimentos"]["hibrido_gemma"]["geral"]
    resumo["deltas_gemma"] = {
        "answer_relevancy": b["answer_relevancy"] - a["answer_relevancy"],
        "faithfulness": b["faithfulness"] - a["faithfulness"]
        if a["faithfulness"] is not None and b["faithfulness"] is not None
        else None,
        "observacao": "Diferença na amostra de desenvolvimento; uma rodada, sem significância estatística ou isolamento entre mudanças de prompt e busca.",
    }
    (PASTA / "scores.json").write_text(
        json.dumps(resumo, ensure_ascii=False, indent=2) + "\n"
    )
    for nome, resultado in resumo["experimentos"].items():
        print(nome, resultado["geral"])


if __name__ == "__main__":
    main()
