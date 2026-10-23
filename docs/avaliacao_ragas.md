# Avaliação automática com RAGAS

O projeto executa as métricas reais `faithfulness` e `answer_relevancy` sobre as
respostas salvas das duas iterações da Sprint 4. A avaliação é separada do chat:
não refaz consultas ao assistente e não reindexa a base.

## Ambiente e compatibilidade

RAGAS 0.4.3 usa um import removido em `langchain-community==0.4.2`, versão do
aplicativo. O erro foi reproduzido; o
[problema está registrado no RAGAS](https://github.com/vibrantlabsai/ragas/issues/2745).
O avaliador utiliza um ambiente próprio com `langchain-community==0.4.1`, sem
alterar essa dependência do aplicativo ou o perfil do índice Chroma.

Preparação, a partir da raiz:

```bash
python -m venv .venv-ragas
.venv-ragas/bin/python -m pip install -r evals/requirements-ragas.txt
```

As versões completas da rodada Python 3.14/Linux estão em
[`ragas_requirements.lock.txt`](../evals/sprint4/ragas_requirements.lock.txt).
O arquivo de dependências diretas serve para outros ambientes. A API LangChain
da aula (`SingleTurnSample`, métricas e wrappers) funciona na versão fixada, mas
está marcada como deprecated; atualizá-la exige validar novamente a integração.

## Modelos e configuração

- Juiz: `gemma4:31b-cloud` via Ollama, temperatura 0, top_p 0,9 e saída máxima
  de 4096 tokens. Não herda o limite de saída do assistente.
- Embeddings: `nomic-embed-text`, com `search_query:` tanto na pergunta original
  quanto nas reconstruídas; a comparação é entre perguntas.
- `answer_relevancy` com `strictness=3`; prompts oficiais do pacote em inglês,
  com entradas originais em português.
- Timeout de 180 segundos por métrica e uma tentativa de transporte. O parser
  pode solicitar correção de JSON; essas chamadas aparecem nos rastros.
- Uma avaliação por resposta/métrica; não se escolhe a melhor de repetições.

Os endpoints são lidos de `OLLAMA_BASE_URL` e `RAG_EMBEDDING_BASE_URL`, no ambiente
ou no `.env`. Não são necessárias novas credenciais de OpenAI ou outro provedor.
Bibliotecas de outros provedores são dependências do pacote, mas as chamadas
desta avaliação usam somente Gemma e Nomic pelo Ollama.

## Insumos e métricas

São usados os mesmos 12 casos salvos em `baseline_gemma.json`, `hibrido_gemma.json`
e `hibrido_gptoss.json`. As respostas históricas do GPT-OSS são julgadas pelo
Gemma, sem acessar o GPT-OSS novamente. Cada arquivo de origem tem hash SHA-256.

| Campo RAGAS | Origem |
|---|---|
| `user_input` | Pergunta original salva |
| `response` | Texto efetivamente entregue pelo serviço |
| `retrieved_contexts` | Conteúdos de `fontes.documentos` da entrada da geração após triagem |

Usar a busca bruta reincluiria documentos em quarentena. Refazer a busca poderia
produzir outros chunks. Os casos atuais são documentais; uma avaliação futura
de respostas operacionais deve incluir também as evidências das ferramentas.

`faithfulness` decompõe a resposta em afirmações e verifica sua sustentação no
contexto. É aplicada aos casos de sucesso com contexto documental. Recusas ficam
não aplicáveis, inclusive quando contêm orientação parcial: a seleção segue o
status do serviço, sem escolha posterior baseada na nota. Sua adequação continua
verificada pelo gabarito complementar.

`answer_relevancy` reconstrói perguntas a partir da resposta e compara embeddings
com a pergunta original. Também avalia abstenções. Uma recusa correta pode receber
zero por ser considerada não comprometida; isso não prova falha de segurança.
Não é a mesma conta de critérios atendidos utilizada na rubrica complementar.

Erros de execução e respostas retidas por citação/schema inválidos são não
aplicáveis nas duas métricas: uma mensagem técnica não é resposta factual.
Timeout, NaN e falhas do avaliador são registrados como erro, com score `null`;
não viram zeros ou sucessos artificiais. As médias mostram denominadores,
cobertura e comparações pareadas nos mesmos IDs válidos. Não há uma nota única
misturando segurança, recusas, fidelidade e relevância.

## Execução e rastreabilidade

```bash
.venv-ragas/bin/python evals/avaliar_ragas.py --experimentos baseline_gemma --casos RAG-R01 RAG-R03
.venv-ragas/bin/python evals/avaliar_ragas.py --retomar
```

O primeiro comando é a validação inicial em dois casos. Com resultados já
existentes, use o segundo: ele ignora métricas registradas, inclusive erros
preservados. Configuração, origem e hash do executor precisam corresponder à
rodada. Uma nova rodada deve ser preservada separadamente; não se sobrescreve
a anterior.

`evals/sprint4/ragas/` contém scores, amostras e mensagens do juiz, permitindo
inspecionar afirmações/vereditos e perguntas reconstruídas. `scores.json` contém
a consolidação e os pareamentos. Sem chamadas ao juiz, é possível testar os
controles e gerar os relatórios a partir dos resultados completos:

```bash
python -m pytest tests/test_ragas_avaliacao.py -q
python evals/gerar_relatorios_sprint4.py
```

A geração de PDF requer as dependências `reports`. Resultados no
[relatório RAG](relatorio_rag.md) e na [comparação de modelos](relatorio_modelos.md).

## Limitações

Gemma também gerou parte das respostas; isso pode introduzir viés no julgamento.
Uma rodada sobre amostra conhecida, com um juiz, não oferece significância
estatística nem garantia de correção. As notas podem divergir da rubrica porque
medem aspectos diferentes; as divergências devem ser inspecionadas por caso.

Em RAG-R19 da baseline, a decomposição converteu duas condições da resposta em
afirmações de estado atual. O juiz rejeitou essas unidades e retornou 0,500.
A nota foi preservada, com o rastro completo, mas esse erro de extração limita a
interpretação do ganho de fidelidade e não comprova alucinação na frase original.

A rubrica inicial permanece como avaliação complementar de completude, fontes
obrigatórias e recusas, sem ser chamada de RAGAS. `context_precision`, novos
chunkings e reranking não foram acrescentados nesta integração.

Referências: [faithfulness](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/faithfulness/)
e [answer relevancy](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/answer_relevance/).
