# Histórico dos prompts RAG

| Versão | Uso | Mudança e validação |
|---|---|---|
| `rag-v1` | Protótipo em `src/rag/prompt_rag.py` | Serialização das evidências documentais para preparar a integração. |
| `rag-v2` | Aplicação integrada; arquivo `prompts/rag_v2.md` | Separa fontes operacionais, documentais e histórico do usuário; exige apoios e insuficiência explícita. Passou em 7 cenários funcionais com o modelo real. |

O arquivo ativo é configurável por `RAG_PROMPT_PATH`. A versão `rag-v2` mantém
os indicadores calculados em Python, delimita os documentos como dados sem
autoridade para alterar instruções e não usa respostas anteriores como evidência.
Perguntas documentais não exigem avaliação de risco ou recomendações operacionais.

O relatório [`fase3_integracao.json`](../evals/fase3_integracao.json) contém o
hash do arquivo, parâmetros, evidências e resultados da execução registrada.
Os sete cenários verificam a integração; não constituem comparação controlada
entre versões nem medição RAGAS. Não há ganho percentual de qualidade medido
entre `rag-v1` e `rag-v2`.
