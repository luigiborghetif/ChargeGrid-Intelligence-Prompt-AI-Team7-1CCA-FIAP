"""Ponto único de avaliação dos guardrails de entrada."""

from __future__ import annotations

from dataclasses import dataclass

from guardrails.moderation import CategoriaModeracao, moderar_entrada
from guardrails.scope_validator import CategoriaEscopo, validar_escopo


@dataclass(frozen=True, slots=True)
class DecisaoGuardrail:
    """Decisão final usada pela camada de aplicação."""

    permitida: bool
    codigo: str
    mensagem: str | None = None


def avaliar_entrada(texto: str, *, escopo_semantico: bool = False) -> DecisaoGuardrail:
    """Executa moderação antes da validação de escopo."""
    moderacao = moderar_entrada(texto)
    if not moderacao.permitida:
        return DecisaoGuardrail(
            permitida=False,
            codigo=moderacao.categoria.value,
            mensagem=moderacao.mensagem,
        )

    escopo = validar_escopo(texto)
    if not escopo.dentro_escopo:
        if escopo_semantico:
            return DecisaoGuardrail(permitida=True, codigo="escopo_a_classificar")
        return DecisaoGuardrail(
            permitida=False,
            codigo=escopo.categoria.value,
            mensagem=escopo.mensagem,
        )

    codigo = (
        CategoriaModeracao.PERMITIDA.value
        if escopo.categoria is CategoriaEscopo.OPERACIONAL
        else escopo.categoria.value
    )
    return DecisaoGuardrail(permitida=True, codigo=codigo)


__all__ = ["DecisaoGuardrail", "avaliar_entrada"]
