"""Complemento lexical BM25 sobre os chunks já existentes no Chroma."""

import math
import re
from collections import Counter

from langchain_core.documents import Document

from guardrails.moderation import normalizar_texto

STOPWORDS = frozenset(
    [
        "a",
        "o",
        "as",
        "os",
        "de",
        "da",
        "do",
        "das",
        "dos",
        "em",
        "no",
        "na",
        "nos",
        "nas",
        "um",
        "uma",
        "uns",
        "umas",
        "e",
        "ou",
        "que",
        "qual",
        "quais",
        "como",
        "para",
        "por",
        "se",
        "ao",
        "aos",
        "com",
        "sem",
        "sobre",
        "este",
        "esta",
        "esse",
        "essa",
        "isso",
        "sao",
        "ser",
        "tem",
        "tenho",
        "posso",
        "fazer",
        "houver",
        "quanto",
        "quando",
        "meu",
        "minha",
    ]
)


def tokens(texto: str) -> list[str]:
    return [
        t
        for t in re.findall(r"[a-z0-9]+", normalizar_texto(texto))
        if t not in STOPWORDS
    ]


def combinar_resultados(
    pergunta: str, semanticos: list[Document], corpus: list[Document], k: int
) -> list[Document]:
    """Reserva até duas posições lexicais e completa por fusão de rankings.

    Não usa gabaritos, IDs de documentos ou regras específicas por pergunta.
    Os mesmos chunks e metadados são preservados; k continua sendo o limite total.
    """
    if not corpus:
        return semanticos[:k]
    frequencias = [Counter(tokens(d.page_content)) for d in corpus]
    comprimentos = [sum(c.values()) for c in frequencias]
    media = sum(comprimentos) / len(corpus) or 1
    termos = set(tokens(pergunta))
    df = {t: sum(t in f for f in frequencias) for t in termos}
    pontuados = []
    for documento, freq, tamanho in zip(corpus, frequencias, comprimentos, strict=True):
        score = 0.0
        for termo in termos:
            tf = freq[termo]
            if tf:
                idf = math.log(1 + (len(corpus) - df[termo] + 0.5) / (df[termo] + 0.5))
                score += idf * (tf * 2.5) / (tf + 1.5 * (0.25 + 0.75 * tamanho / media))
        if score > 0:
            pontuados.append((score, documento))
    pontuados.sort(key=lambda p: (-p[0], p[1].metadata["chunk_id"]))
    lexicais = [d for _, d in pontuados[:k]]
    fusao, documentos = {}, {}
    for ranking in [semanticos, lexicais]:
        for posicao, documento in enumerate(ranking, start=1):
            id_chunk = documento.metadata["chunk_id"]
            documentos[id_chunk] = documento
            fusao[id_chunk] = fusao.get(id_chunk, 0.0) + 1 / (60 + posicao)
    ordem = [d.metadata["chunk_id"] for d in lexicais[: min(2, k)]]
    ordem.extend(
        id_chunk
        for id_chunk in sorted(fusao, key=lambda i: (-fusao[i], i))
        if id_chunk not in ordem
    )
    return [documentos[id_chunk] for id_chunk in ordem[:k]]
