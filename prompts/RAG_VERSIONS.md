# Histórico dos prompts RAG

| Versão | Uso | Mudança e validação |
|---|---|---|
| `rag-v1` | Protótipo em `src/rag/prompt_rag.py` | Serialização das evidências documentais para preparar a integração. |
| `rag-v2` | Integração anterior; arquivo `prompts/rag_v2.md` | Separa fontes operacionais, documentais e histórico do usuário; exige apoios e insuficiência explícita. Passou em 7 cenários funcionais com o modelo real. |
| `planejador-v1` | Fluxo padrão; `prompts/planejador_v1.md` | Interpreta intenção e produz plano tipado de até quatro chamadas, sem resposta factual direta. |
| `resposta-tools-v1` | Fluxo padrão; `prompts/resposta_tools_v1.md` | Responde com resultados de ferramentas e chunks; preserva citações, limitações e cálculos Python. Validação funcional registrada em seis cenários, com uma repetição direcionada da continuação. |

Os prompts do fluxo padrão são configuráveis por `PLANNER_PROMPT_PATH` e
`PLANNER_RESPONSE_PROMPT_PATH`. O fluxo anterior é selecionado por
`CHARGEGRID_USAR_PLANEJADOR=false` e usa `RAG_PROMPT_PATH`. A versão `rag-v2` mantém
os indicadores calculados em Python, delimita os documentos como dados sem
autoridade para alterar instruções e não usa respostas anteriores como evidência.
Perguntas documentais não exigem avaliação de risco ou recomendações operacionais.

O relatório [`fase3_integracao.json`](../evals/fase3_integracao.json) contém o
hash do arquivo, parâmetros, evidências e resultados da execução registrada.
Os sete cenários verificam a integração; não constituem comparação controlada
entre versões nem medição RAGAS. Não há ganho percentual de qualidade medido
entre `rag-v1` e `rag-v2`.

A execução do planejador está em
[`planejador_validacao.json`](../evals/planejador_validacao.json), com hashes dos
dois prompts, planos, fontes e resultados. Uma continuação inicialmente recusada
por citação passou na repetição direcionada, preservada no registro. Os cenários
não são uma comparação controlada de versões nem medição RAGAS; não há ganho
semântico percentual demonstrado pela mudança arquitetural.
