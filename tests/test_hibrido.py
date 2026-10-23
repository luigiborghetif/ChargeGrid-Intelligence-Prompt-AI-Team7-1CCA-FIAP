"""Invariantes do complemento lexical sem rede ou modelo de embeddings."""

from langchain_core.documents import Document

from rag.hibrido import combinar_resultados


def doc(id, texto):
    return Document(
        page_content=texto,
        metadata={"chunk_id": id, "source": "manual.pdf", "pagina_pdf": 2},
    )


def test_termos_especificos_complementam_resultado_semantico_generico():
    generico = doc("a", "Orientações gerais para uso do carregador.")
    especifico = doc("b", "Fumaça: interrompa com segurança e comunique atendimento.")
    resultado = combinar_resultados(
        "O que fazer diante de fumaça?", [generico], [generico, especifico], 2
    )
    assert resultado[0] == especifico
    assert resultado[0].metadata["pagina_pdf"] == 2


def test_limite_e_deduplicacao_sao_preservados():
    docs = [doc(str(i), f"Tarifa modalidade {i}") for i in range(10)]
    resultado = combinar_resultados("tarifa", docs[:8], docs, 4)
    assert len(resultado) == 4
    assert len({d.metadata["chunk_id"] for d in resultado}) == 4


def test_sem_correspondencia_lexical_preserva_resultados_semanticos():
    documentos = [doc("a", "Manual técnico.")]
    assert combinar_resultados("xyz", documentos, documentos, 8) == documentos
    assert combinar_resultados("xyz", documentos, [], 8) == documentos
