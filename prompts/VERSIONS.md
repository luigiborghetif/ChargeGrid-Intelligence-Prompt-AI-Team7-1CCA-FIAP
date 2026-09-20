# Histórico de versões dos prompts

Os prompts são avaliados com o mesmo conjunto de casos, dados operacionais,
parâmetros de geração e modelo. As métricas serão preenchidas pelo executor em
`evals/run_evals.py` para evitar conclusões subjetivas sobre qualidade.

| Versão | Principais mudanças | Motivo | Ganho medido |
|---|---|---|---|
| `v1` | Migração do prompt monolítico das Sprints 1 e 2; dados retirados do texto; formato Pydantic adicionado. | Criar um baseline compatível com a aplicação local e manter o comportamento original. | 10/10 casos; 100% de schema, fatos e guardrails. |
| `v2` | XML tagging; separação entre identidade, escopo, contexto, raciocínio, domínio, linguagem, segurança e formato. | Reduzir ambiguidades, melhorar aderência ao contexto e tornar recusas e limitações explícitas. | 10/10 casos; manteve 100% com regras mais explícitas. |

## Hipóteses da versão 2

- Maior percentual de respostas válidas no schema Pydantic.
- Menor ocorrência de afirmações sem evidência.
- Maior precisão na distinção entre kW e kWh.
- Maior taxa de recusa em jailbreak, prompt injection e perguntas fora do escopo.
- Respostas mais consistentes entre execuções com os mesmos parâmetros.

## Métricas planejadas

| Métrica | Como será calculada |
|---|---|
| Qualidade da resposta | Pontuação dos fatos e comportamentos esperados em cada caso. |
| Structured output válido | Respostas aceitas pelo schema ÷ total de respostas. |
| Aderência aos fatos | Fatos esperados encontrados sem afirmações contraditórias. |
| Guardrails | Recusas corretas ÷ casos que exigem recusa. |
| Tokens de entrada e saída | Contagem registrada durante cada execução. |
| Latência | Tempo entre a chamada e a resposta completa do modelo. |

## Controle do experimento

Ao comparar versões, devem permanecer iguais:

- modelo;
- dados operacionais;
- conjunto de perguntas;
- `temperature`;
- `top_p`;
- limite de saída;
- limite de memória;
- máquina ou serviço cloud utilizado.

## Resultado da execução

A comparação foi executada com `gemma4:31b-cloud`, temperatura `0.2`, `top_p`
`0.9` e limite de saída de `1200` tokens. Os dez casos incluem seis consultas ao
modelo e quatro bloqueios determinísticos pelos guardrails.

| Métrica | v1 | v2 |
|---|---:|---:|
| Casos aprovados | 10/10 | 10/10 |
| Structured output válido | 100% | 100% |
| Aderência aos fatos | 100% | 100% |
| Guardrails | 100% | 100% |
| Latência média | 1,273 s | 3,011 s |
| Tokens de entrada estimados | 19.515 | 23.605 |
| Tokens de saída estimados | 2.376 | 2.549 |

Neste conjunto, a v2 não produziu ganho percentual de qualidade porque a v1 já
atingiu o teto das métricas. A v2 mantém as mesmas taxas com instruções de
segurança, escopo e domínio mais explícitas, mas usa um prompt maior. Os valores
de tokens são estimativas locais; a latência pode variar conforme o Ollama Cloud.
