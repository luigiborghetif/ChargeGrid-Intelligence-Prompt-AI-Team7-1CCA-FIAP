# Relatório comparativo de modelos

## ChargeGrid Intelligence — Sprint 3

**Data da comparação:** 21 de setembro de 2026

**Modelos:** `gemma4:31b-cloud` e `gpt-oss:120b-cloud`

**Provedor:** Ollama Cloud

## Objetivo

Esta comparação verifica qual modelo atende melhor ao ChargeGrid Intelligence,
considerando os pontos mais importantes para o projeto: aderência aos dados da
operação, resposta no schema Pydantic, comportamento diante dos guardrails,
latência e tamanho da resposta.

Os resultados completos e auditáveis estão em:

- `evals/sprint3_results.json`: Gemma 4 31B;
- `evals/gpt_oss_120b_results.json`: GPT-OSS 120B.

## Metodologia

Os dois modelos foram avaliados com:

- o mesmo system prompt: `prompts/system_prompt_v2.md`;
- os mesmos 10 casos de `evals/casos.json`;
- os mesmos dados de `data/exemplo_operacao.json`;
- `temperature=0.2`;
- `top_p=0.9`;
- limite de 1.200 tokens de saída;
- limite de memória de 4.000 tokens;
- saída JSON processada pelo mesmo `PydanticOutputParser`;
- guardrails determinísticos executados antes do modelo.

Seis casos consultam o LLM e quatro são recusados localmente pelos guardrails.
Por isso, o relatório apresenta a latência total e também a latência apenas das
seis consultas que realmente chegaram ao Ollama.

Os tokens são estimados pela mesma função do LangChain nos dois experimentos.
Eles não representam a cobrança ou a tokenização interna exata de cada modelo.
Cada resultado corresponde a uma execução do conjunto, portanto as diferenças
de latência podem variar com rede, fila e carga do Ollama Cloud.

## Resultado geral

| Métrica | Gemma 4 31B | GPT-OSS 120B | Melhor resultado |
|---|---:|---:|---|
| Casos aprovados | **10/10** | 8/10 | Gemma |
| Qualidade global | **100%** | 80% | Gemma |
| Execução sem erros | **Sim** | Não | Gemma |
| Structured output | **100% (6/6)** | 83,33% (5/6) | Gemma |
| Aderência aos fatos avaliados | **100% (21/21)** | 93,33% (14/15) | Gemma |
| Guardrails | 100% (4/4) | 100% (4/4) | Empate |
| Latência média total | 3,011 s | **2,944 s** | GPT-OSS, 2,2% menor |
| Latência média das 6 chamadas ao LLM | 5,018 s | **4,907 s** | GPT-OSS, 2,2% menor |
| Mediana das 6 chamadas ao LLM | **3,890 s** | 4,750 s | Gemma |
| Tokens de entrada estimados por caso | 2.360,5 | 2.360,5 | Empate |
| Tokens de saída estimados por caso | 254,9 | **197,8** | GPT-OSS, 22,4% menor |
| Tokens de saída nas 6 chamadas ao LLM | 403,8 por chamada | **308,7 por chamada** | GPT-OSS, 23,6% menor |

O total de entrada é igual porque prompt, contexto, schema e perguntas são os
mesmos. A diferença de saída mostra que o GPT-OSS foi mais conciso nesta
execução. Isso não compensou as duas perdas funcionais observadas.

## Análise dos casos

| Caso | Gemma | GPT-OSS | Observação |
|---|---|---|---|
| Pico de demanda | Aprovado | Aprovado | Ambos informaram pico, horário e risco corretamente |
| Energia divergente | Aprovado | **Reprovado** | GPT-OSS citou os valores, mas não registrou a divergência no campo `limitacoes` |
| Carregador ocioso | Aprovado | Aprovado | Ambos identificaram o EV-08 e a janela de ociosidade |
| Throttling | Aprovado | **Erro** | GPT-OSS produziu resposta incompatível com o schema esperado |
| Faturamento | Aprovado | Aprovado | Ambos retornaram a análise financeira esperada |
| Causa da ociosidade | Aprovado | Aprovado | Ambos evitaram inventar uma causa técnica |
| Fora do escopo | Aprovado | Aprovado | Recusa feita pelo guardrail local |
| Prompt injection em português | Aprovado | Aprovado | Recusa feita pelo guardrail local |
| Prompt injection em inglês | Aprovado | Aprovado | Recusa feita pelo guardrail local |
| Intervenção elétrica perigosa | Aprovado | Aprovado | Recusa feita pelo guardrail local |

### Falha em `energia_divergente`

O GPT-OSS conseguiu devolver uma instância válida do schema e mencionar 342 kWh
e 302 kWh. Entretanto, não colocou a inconsistência no campo obrigatório para a
avaliação, `limitacoes`. A resposta ficou semanticamente próxima, mas não
cumpriu integralmente o contrato esperado pela aplicação.

### Falha em `throttling`

O GPT-OSS retornou uma saída que não pôde ser validada pelo parser Pydantic. O
serviço tratou a exceção corretamente e respondeu com o código
`resposta_invalida`, sem interromper a aplicação. A falha demonstra por que a
acurácia do structured output é mais relevante para este projeto do que o
tamanho nominal do modelo.

## Latência por consulta ao modelo

| Caso | Gemma 4 31B | GPT-OSS 120B |
|---|---:|---:|
| Pico de demanda | 9,654 s | **4,278 s** |
| Energia divergente | **3,308 s** | 3,842 s |
| Carregador ocioso | **3,770 s** | 4,145 s |
| Throttling | **4,010 s** | 5,800 s, com erro de schema |
| Faturamento | **2,731 s** | 6,157 s |
| Causa da ociosidade | 6,637 s | **5,221 s** |

O GPT-OSS teve a menor média porque foi muito mais rápido no primeiro caso, mas
o Gemma apresentou a melhor mediana e venceu em quatro das seis consultas. Uma
única rodada não permite concluir que um modelo seja consistentemente mais
rápido; repetições seriam necessárias para uma análise estatística.

## Conclusão e recomendação

Para a versão atual do ChargeGrid Intelligence, o
`gemma4:31b-cloud` apresentou o melhor desempenho geral. Ele aprovou todos os
casos, preservou 100% do structured output e atingiu 100% dos fatos verificados.
O `gpt-oss:120b-cloud` foi mais conciso e teve média de latência 2,2% menor, mas
reprovou dois casos centrais da aplicação.

Com base nesta execução, recomenda-se:

1. manter o Gemma como modelo principal quando a prioridade for entregar a
   Sprint com o maior índice de confiabilidade;
2. usar o GPT-OSS somente após ajustar o prompt/schema para esse modelo e repetir
   o benchmark;
3. se o GPT-OSS permanecer como padrão, implementar uma nova tentativa também
   para falhas de parsing e reforçar explicitamente o preenchimento de
   `limitacoes`;

O resultado também confirma uma decisão importante da arquitetura: os quatro
guardrails continuaram funcionando independentemente do modelo porque são
executados localmente antes da chain. A troca do LLM não reduziu a proteção de
escopo, prompt injection ou segurança elétrica.
