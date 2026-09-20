"""Moderação determinística das mensagens enviadas ao assistente."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

LIMITE_CARACTERES = 2_000


class CategoriaModeracao(StrEnum):
    """Categorias reconhecidas antes de qualquer chamada ao modelo."""

    PERMITIDA = "permitida"
    VAZIA = "vazia"
    MUITO_LONGA = "muito_longa"
    INJECAO_PROMPT = "injecao_prompt"
    INTERVENCAO_PERIGOSA = "intervencao_perigosa"


@dataclass(frozen=True, slots=True)
class ResultadoModeracao:
    """Resultado explicável da análise de segurança da entrada."""

    permitida: bool
    categoria: CategoriaModeracao
    mensagem: str | None = None


PADROES_INJECAO = tuple(
    re.compile(padrao)
    for padrao in (
        r"\bignore\s+(?:todas?\s+)?(?:as\s+)?instrucoes\b",
        r"\bignore\s+(?:all\s+|previous\s+)?instructions\b",
        r"\b(?:revele|mostre|exiba|imprima)\b.{0,40}\b(?:system prompt|prompt do sistema|instrucoes internas|regras ocultas)\b",
        r"\b(?:reveal|show|print)\b.{0,40}\b(?:system prompt|hidden instructions)\b",
        r"\b(?:finja|aja)\s+que\s+(?:nao|voce nao)\b.{0,40}\b(?:tem|possui|existem)\s+regras\b",
        r"\b(?:jailbreak|developer mode|modo desenvolvedor)\b",
        r"\b(?:system|assistant|developer)\s*:\s*",
        r"<\/?(?:system|assistant|developer|seguranca|formato_saida)>",
    )
)

PADROES_INTERVENCAO_PERIGOSA = tuple(
    re.compile(padrao)
    for padrao in (
        r"\b(?:desativar|burlar|remover|ignorar)\b.{0,45}\b(?:disjuntor|protecao|aterramento|intertravamento)\b",
        r"\b(?:ligar|conectar|jumpear)\b.{0,45}\b(?:direto|rede energizada|alta tensao)\b",
        r"\bcomo\b.{0,30}\b(?:abrir|desmontar|reparar)\b.{0,30}\bcarregador\b",
    )
)


def normalizar_texto(texto: str) -> str:
    """Normaliza caixa, acentos e espaços para comparações previsíveis."""
    sem_acentos = "".join(
        caractere
        for caractere in unicodedata.normalize("NFKD", texto)
        if not unicodedata.combining(caractere)
    )
    return " ".join(sem_acentos.casefold().split())


def moderar_entrada(texto: str) -> ResultadoModeracao:
    """Bloqueia entradas inválidas, injeções e intervenções elétricas perigosas."""
    texto_limpo = texto.strip()
    if not texto_limpo:
        return ResultadoModeracao(
            permitida=False,
            categoria=CategoriaModeracao.VAZIA,
            mensagem="Digite uma pergunta sobre a operação do eletroposto.",
        )

    if len(texto_limpo) > LIMITE_CARACTERES:
        return ResultadoModeracao(
            permitida=False,
            categoria=CategoriaModeracao.MUITO_LONGA,
            mensagem=(
                f"A pergunta excede o limite de {LIMITE_CARACTERES} caracteres. "
                "Resuma a solicitação e tente novamente."
            ),
        )

    normalizado = normalizar_texto(texto_limpo)
    if any(padrao.search(normalizado) for padrao in PADROES_INJECAO):
        return ResultadoModeracao(
            permitida=False,
            categoria=CategoriaModeracao.INJECAO_PROMPT,
            mensagem=(
                "Não posso alterar ou revelar minhas instruções internas. "
                "Posso ajudar com a operação do eletroposto."
            ),
        )

    if any(padrao.search(normalizado) for padrao in PADROES_INTERVENCAO_PERIGOSA):
        return ResultadoModeracao(
            permitida=False,
            categoria=CategoriaModeracao.INTERVENCAO_PERIGOSA,
            mensagem=(
                "Não posso orientar intervenções que removam proteções elétricas. "
                "Procure um eletricista habilitado."
            ),
        )

    return ResultadoModeracao(
        permitida=True,
        categoria=CategoriaModeracao.PERMITIDA,
    )
