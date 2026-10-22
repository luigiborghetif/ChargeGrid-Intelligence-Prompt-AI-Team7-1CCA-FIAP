"""Executa avaliações reproduzíveis dos prompts do ChargeGrid."""

from __future__ import annotations

import argparse
import json
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain_core.messages.utils import count_tokens_approximately

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from chain.builder import criar_entrada_chain, criar_parser
from chargegrid.assistente import (
    AssistenteChargeGrid,
    RespostaAssistente,
    StatusResposta,
)
from chargegrid.config import Settings, settings
from schemas.consulta_recarga import ConsultaRecarga

ARQUIVO_CASOS = PROJECT_ROOT / "evals/casos.json"
VERSOES = {
    "v1": {
        "prompt": PROJECT_ROOT / "prompts/system_prompt_v1.md",
        "resultado": PROJECT_ROOT / "evals/baseline_results.json",
    },
    "v2": {
        "prompt": PROJECT_ROOT / "prompts/system_prompt_v2.md",
        "resultado": PROJECT_ROOT / "evals/sprint3_results.json",
    },
}


@dataclass(frozen=True, slots=True)
class Verificacao:
    nome: str
    passou: bool
    esperado: Any
    obtido: Any
    tipo: str


def _normalizar(texto: str) -> str:
    return "".join(
        caractere
        for caractere in unicodedata.normalize("NFKD", texto.casefold())
        if not unicodedata.combining(caractere)
    )


def carregar_casos(caminho: Path = ARQUIVO_CASOS) -> list[dict[str, Any]]:
    """Carrega e valida minimamente o conjunto versionado de avaliações."""
    conteudo = json.loads(caminho.read_text(encoding="utf-8"))
    casos = conteudo.get("casos")
    if not isinstance(casos, list) or not casos:
        raise ValueError("O arquivo de avaliações deve conter uma lista de casos.")

    ids = [caso.get("id") for caso in casos]
    if any(not identificador for identificador in ids) or len(ids) != len(set(ids)):
        raise ValueError("Todos os casos devem possuir IDs únicos e não vazios.")
    return casos


def _adicionar(
    verificacoes: list[Verificacao],
    nome: str,
    esperado: Any,
    obtido: Any,
    passou: bool,
    tipo: str = "qualidade",
) -> None:
    verificacoes.append(Verificacao(nome, passou, esperado, obtido, tipo))


def avaliar_resposta(
    caso: dict[str, Any],
    resposta: RespostaAssistente,
) -> list[Verificacao]:
    """Compara uma resposta estruturada às expectativas declaradas no caso."""
    esperado = caso["esperado"]
    verificacoes: list[Verificacao] = []
    _adicionar(
        verificacoes,
        "status",
        esperado["status"],
        resposta.status.value,
        resposta.status.value == esperado["status"],
        "guardrail" if esperado["status"] == "recusada" else "qualidade",
    )

    if esperado["status"] == "recusada":
        codigo = esperado.get("codigo")
        if codigo:
            _adicionar(
                verificacoes,
                "codigo_recusa",
                codigo,
                resposta.codigo,
                resposta.codigo == codigo,
                "qualidade",
            )
        return verificacoes

    dados = resposta.dados
    _adicionar(
        verificacoes,
        "schema_valido",
        True,
        dados is not None,
        dados is not None,
        "schema",
    )
    if dados is None:
        return verificacoes

    if "nivel_risco" in esperado:
        _adicionar(
            verificacoes,
            "nivel_risco",
            esperado["nivel_risco"],
            dados.nivel_risco.value,
            dados.nivel_risco.value == esperado["nivel_risco"],
            "fato",
        )

    for campo in ("potencia_total_kw", "energia_total_kwh"):
        if campo in esperado:
            obtido = getattr(dados, campo)
            passou = obtido is not None and abs(obtido - esperado[campo]) <= 0.1
            _adicionar(verificacoes, campo, esperado[campo], obtido, passou, "fato")

    texto_json = _normalizar(dados.model_dump_json())
    for trecho in esperado.get("texto_contem", []):
        _adicionar(
            verificacoes,
            f"texto_contem:{trecho}",
            trecho,
            trecho if _normalizar(trecho) in texto_json else None,
            _normalizar(trecho) in texto_json,
            "fato",
        )

    alternativas = esperado.get("texto_contem_um_de", [])
    if alternativas:
        encontrada = next(
            (
                alternativa
                for alternativa in alternativas
                if _normalizar(alternativa) in texto_json
            ),
            None,
        )
        _adicionar(
            verificacoes,
            "texto_contem_um_de",
            alternativas,
            encontrada,
            encontrada is not None,
            "fato",
        )

    ids = {carregador.id for carregador in dados.carregadores_relacionados}
    for identificador in esperado.get("carregadores_contem", []):
        _adicionar(
            verificacoes,
            f"carregador:{identificador}",
            identificador,
            identificador if identificador in ids else None,
            identificador in ids,
            "fato",
        )

    texto_limitacoes = _normalizar(" ".join(dados.limitacoes))
    for trecho in esperado.get("limitacoes_contem", []):
        _adicionar(
            verificacoes,
            f"limitacao:{trecho}",
            trecho,
            trecho if _normalizar(trecho) in texto_limitacoes else None,
            _normalizar(trecho) in texto_limitacoes,
            "fato",
        )

    if "analise_financeira" in esperado:
        presente = dados.analise_financeira is not None
        _adicionar(
            verificacoes,
            "analise_financeira",
            esperado["analise_financeira"],
            presente,
            presente is esperado["analise_financeira"],
            "fato",
        )

    return verificacoes


def _percentual(parte: int, total: int) -> float:
    return round(100 * parte / total, 2) if total else 0.0


def consolidar_metricas(resultados: list[dict[str, Any]]) -> dict[str, Any]:
    """Calcula métricas agregadas, mantendo numeradores auditáveis."""
    verificacoes = [
        verificacao
        for resultado in resultados
        for verificacao in resultado["verificacoes"]
    ]
    por_tipo = {
        tipo: [item for item in verificacoes if item["tipo"] == tipo]
        for tipo in ("schema", "fato", "guardrail")
    }
    casos_aprovados = sum(
        all(item["passou"] for item in resultado["verificacoes"])
        for resultado in resultados
    )
    erros_execucao = sum(item["status"] == "erro" for item in resultados)

    def metrica(tipo: str) -> dict[str, Any]:
        itens = por_tipo[tipo]
        aprovados = sum(item["passou"] for item in itens)
        return {
            "aprovados": aprovados,
            "total": len(itens),
            "percentual": _percentual(aprovados, len(itens)),
        }

    return {
        "casos_aprovados": casos_aprovados,
        "total_casos": len(resultados),
        "qualidade_percentual": _percentual(casos_aprovados, len(resultados)),
        "execucao_valida": erros_execucao == 0,
        "erros_execucao": erros_execucao,
        "structured_output": metrica("schema"),
        "aderencia_fatos": metrica("fato"),
        "guardrails": metrica("guardrail"),
        "latencia_media_segundos": round(
            sum(item["latencia_segundos"] for item in resultados) / len(resultados),
            3,
        ),
        "tokens_entrada_estimados": sum(
            item["tokens_entrada_estimados"] for item in resultados
        ),
        "tokens_saida_estimados": sum(
            item["tokens_saida_estimados"] for item in resultados
        ),
    }


def consultar_com_tentativas(
    assistente: AssistenteChargeGrid,
    pergunta: str,
    session_id: str,
    max_tentativas: int = 3,
) -> tuple[RespostaAssistente, int]:
    """Repete apenas falhas transitórias de comunicação com o Ollama."""
    resposta: RespostaAssistente | None = None
    for tentativa in range(1, max_tentativas + 1):
        resposta = assistente.consultar(pergunta, session_id)
        if resposta.codigo != "ollama_indisponivel" or tentativa == max_tentativas:
            return resposta, tentativa
        time.sleep(2 ** (tentativa - 1))
    raise RuntimeError("A execução das tentativas terminou sem uma resposta.")


def executar_versao(
    versao: str,
    casos: list[dict[str, Any]],
    configuracao_base: Settings = settings,
) -> dict[str, Any]:
    """Executa todos os casos com uma versão de prompt e retorna o relatório."""
    definicao = VERSOES[versao]
    configuracao = replace(configuracao_base, prompt_path=definicao["prompt"])
    assistente = AssistenteChargeGrid(configuracao=configuracao, usar_rag=False)
    prompt = definicao["prompt"].read_text(encoding="utf-8")
    contexto = criar_entrada_chain("avaliação", assistente.operacao)[
        "contexto_operacional"
    ]
    instrucoes_schema = criar_parser().get_format_instructions()
    resultados: list[dict[str, Any]] = []

    for indice, caso in enumerate(casos, start=1):
        print(f"[{versao} {indice}/{len(casos)}] {caso['id']}", flush=True)
        inicio = time.perf_counter()
        resposta, tentativas = consultar_com_tentativas(
            assistente,
            caso["pergunta"],
            f"eval-{versao}-{caso['id']}",
        )
        latencia = time.perf_counter() - inicio
        verificacoes = avaliar_resposta(caso, resposta)
        saida = (
            resposta.dados.model_dump_json() if resposta.dados else resposta.mensagem
        )
        resultados.append(
            {
                "id": caso["id"],
                "categoria": caso["categoria"],
                "pergunta": caso["pergunta"],
                "status": resposta.status.value,
                "codigo": resposta.codigo,
                "tentativas": tentativas,
                "latencia_segundos": round(latencia, 3),
                "tokens_entrada_estimados": count_tokens_approximately(
                    [prompt, contexto, instrucoes_schema, caso["pergunta"]]
                ),
                "tokens_saida_estimados": count_tokens_approximately([saida]),
                "verificacoes": [asdict(item) for item in verificacoes],
                "aprovado": all(item.passou for item in verificacoes),
                "resposta": (
                    resposta.dados.model_dump(mode="json")
                    if resposta.dados
                    else {"mensagem": resposta.mensagem}
                ),
            }
        )

    return {
        "executado_em": datetime.now(UTC).isoformat(),
        "versao_prompt": versao,
        "prompt": str(definicao["prompt"].relative_to(PROJECT_ROOT)),
        "modelo": configuracao.ollama_model,
        "parametros": {
            "temperature": configuracao.temperature,
            "top_p": configuracao.top_p,
            "max_tokens": configuracao.max_tokens,
            "memory_token_limit": configuracao.memory_token_limit,
        },
        "metricas": consolidar_metricas(resultados),
        "resultados": resultados,
    }


def salvar_relatorio(relatorio: dict[str, Any], caminho: Path) -> None:
    caminho.write_text(
        json.dumps(relatorio, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def recalcular_relatorio(
    relatorio: dict[str, Any],
    casos: list[dict[str, Any]],
) -> dict[str, Any]:
    """Reaplica critérios locais às respostas salvas, sem nova inferência."""
    casos_por_id = {caso["id"]: caso for caso in casos}
    for resultado in relatorio["resultados"]:
        status = StatusResposta(resultado["status"])
        dados = (
            ConsultaRecarga.model_validate(resultado["resposta"])
            if status is StatusResposta.SUCESSO
            else None
        )
        resposta = RespostaAssistente(
            status=status,
            codigo=resultado["codigo"],
            mensagem=(
                dados.resumo_executivo
                if dados
                else resultado["resposta"].get("mensagem", "")
            ),
            dados=dados,
        )
        verificacoes = avaliar_resposta(casos_por_id[resultado["id"]], resposta)
        resultado["verificacoes"] = [asdict(item) for item in verificacoes]
        resultado["aprovado"] = all(item.passou for item in verificacoes)

    relatorio["recalculado_em"] = datetime.now(UTC).isoformat()
    relatorio["metricas"] = consolidar_metricas(relatorio["resultados"])
    return relatorio


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prompt",
        choices=("v1", "v2", "all"),
        default="all",
        help="Versão a avaliar; por padrão executa a comparação completa.",
    )
    parser.add_argument(
        "--recalcular",
        action="store_true",
        help="Recalcula critérios sobre respostas salvas, sem chamar o modelo.",
    )
    args = parser.parse_args()

    casos = carregar_casos()
    versoes = tuple(VERSOES) if args.prompt == "all" else (args.prompt,)
    for versao in versoes:
        destino = VERSOES[versao]["resultado"]
        if args.recalcular:
            relatorio = recalcular_relatorio(
                json.loads(destino.read_text(encoding="utf-8")),
                casos,
            )
        else:
            relatorio = executar_versao(versao, casos)
        salvar_relatorio(relatorio, destino)
        metricas = relatorio["metricas"]
        print(
            f"{versao}: {metricas['casos_aprovados']}/"
            f"{metricas['total_casos']} casos aprovados → {destino}",
            flush=True,
        )


if __name__ == "__main__":
    main()
