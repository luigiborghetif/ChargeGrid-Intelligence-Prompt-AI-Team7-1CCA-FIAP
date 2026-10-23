# Histórico dos prompts RAG

| Versão | Uso | Mudança e validação |
|---|---|---|
| `rag-v1` | Protótipo em `src/rag/prompt_rag.py` | Serialização das evidências documentais para preparar a integração. |
| `rag-v2` | Integração anterior; arquivo `prompts/rag_v2.md` | Separa fontes operacionais, documentais e histórico do usuário; exige apoios e insuficiência explícita. Passou em 7 cenários funcionais com o modelo real. |
| `planejador-v1` | Baseline; `prompts/planejador_v1.md` | Interpreta intenção e produz plano tipado de até quatro chamadas, sem resposta factual direta. |
| `resposta-tools-v1` | Baseline; `prompts/resposta_tools_v1.md` | Responde com resultados de ferramentas e chunks; preserva citações, limitações e cálculos Python. Validação funcional registrada em seis cenários, com uma repetição direcionada da continuação. |
| `planejador-v2` | Padrão; `prompts/planejador_v2.md` | Distingue orientação protetiva de intervenção elétrica. O caso de fumaça passou de recusa de segurança para consulta documental na repetição direcionada. |
| `resposta-tools-v2` | Padrão; `prompts/resposta_tools_v2.md` | Solicita citações curtas e literais e restringe orientações de risco ao uso protetivo. A última resposta de fumaça foi parcial por recuperação insuficiente; não há ganho RAGAS medido. |
| `planejador-v3` | Candidata; `prompts/planejador_v3.md` | Preserva termos específicos da consulta documental e evita acrescentar temas genéricos. Avaliada junto com resposta v3 e busca híbrida. |
| `resposta-tools-v3` | Candidata; `prompts/resposta_tools_v3.md` | Pede cobertura das partes da pergunta e trechos literais curtos. Não promovida ao padrão por regressões de completude. |

## RAGAS — duas iterações e comparação de modelos

Mesmo conjunto fixo de 12 casos, respostas históricas e contexto pós-triagem.
Juiz Gemma, temperatura 0; Nomic para relevância. Apenas casos aplicáveis entram
nas médias; cobertura e erros do serviço permanecem explícitos.

| Planejador / resposta | Busca | Modelo avaliado | Faithfulness RAGAS | Answer relevancy RAGAS |
|---|---|---|---:|---:|
| v2 / v2 | Semântica | Gemma | 0,917 (n=6) | 0,587 (n=10) |
| v3 / v3 | Híbrida | Gemma | 1,000 (n=8) | 0,642 (n=11) |
| v3 / v3 | Híbrida | GPT-OSS | 0,952 (n=7) | 0,537 (n=11) |

Nos mesmos IDs válidos entre Gemma A/B: fidelidade +0,0833 (n=6) e relevância
+0,0347 (n=10). O juiz transformou condições da resposta RAG-R19/A em afirmações
de estado, contribuindo para a nota 0,500 nesse caso. A nota original é preservada;
o ganho não demonstra melhoria factual geral. A mudança conjunta de busca e prompt,
a amostra conhecida e o uso de Gemma como juiz limitam a interpretação.
Procedimento em [avaliacao_ragas.md](../docs/avaliacao_ragas.md) e
[scores com IDs pareados](../evals/sprint4/ragas/scores.json).

## Rubrica complementar da fase 6

Rubrica por inspeção assistida por IA, não RAGAS nem revisão humana independente.
Mesmos 12 casos pré-fixados de desenvolvimento; uma rodada por configuração.

| Planejador / resposta | Busca | Modelo | Faithfulness (casos aplicáveis) | Answer relevancy (12 casos) | Integral ao gabarito |
|---|---|---|---:|---:|---:|
| v2 / v2 | Semântica | Gemma | 1,000 (10) | 0,569 | 4/12 |
| v3 / v3 | Híbrida | Gemma | 1,000 (11) | 0,590 | 3/12 |
| v3 / v3 | Híbrida | GPT-OSS | 0,902 (11) | 0,535 | 3/12 |

O ganho agregado Gemma é 2,08 pontos percentuais de relevância, com uma falha de
saída a menos. Nas seis perguntas respondíveis, a relevância permaneceu 0,514.
A mudança conjunta de prompt e busca impede isolar seus efeitos. O atendimento
integral caiu; por isso v2 e busca semântica permanecem padrão. Notas 1,000 não
significam completude nem garantia universal de factualidade. Consulte o
[relatório RAG](../docs/relatorio_rag.md) e as
[notas por resposta](../evals/sprint4/revisao.json).

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

A fase 5 está registrada em [`seguranca_rag.md`](../docs/seguranca_rag.md).
A amostra inicial teve 8/9 cenários funcionais aprovados; as repetições do caso
de fumaça mantêm os erros anteriores e a última resposta parcial. A alteração de
encaminhamento não representa aprovação integral do caso ou ganho semântico
quantificado. Os prompts anteriores permanecem disponíveis para comparação.
