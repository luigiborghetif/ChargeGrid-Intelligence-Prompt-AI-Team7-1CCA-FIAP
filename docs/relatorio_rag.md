# Relatório RAG — Sprint 4

## Protocolo e interpretação

Execução em 23/10/2026. O conjunto completo contém 38 casos. Esta avaliação usa
**12 IDs fixados antes da execução**: seis respondíveis, três sem evidência
completa e três ataques documentais. É uma amostra de desenvolvimento conhecida,
sem teste cego, repetição estatística ou alegação de cobertura integral dos 38.
Cada configuração executou os mesmos 12 casos uma vez, com sessão nova por caso.
Os casos adversariais adicionam a fixture apenas em memória, antes das fontes
legítimas; não contaminam o índice.

Foi aplicada inicialmente uma **rubrica por inspeção assistida por
IA (Codex)** dos registros, com unidades factuais e critérios explícitos. Não é
avaliação humana independente nem resultado produzido pelo RAGAS. A equivalência
é das dimensões, não dos algoritmos ou valores numéricos. Faithfulness é a fração
de afirmações auditadas sustentadas pelo contexto efetivamente fornecido;
answer relevancy é a fração de critérios obrigatórios do gabarito atendidos.
As notas são médias por caso. Erros de saída entram na relevância com zero;
faithfulness sem afirmações é não aplicável, com denominador informado. Uma
abstenção fiel pode ter relevância zero se havia resposta na base completa.

Resposta integral exige simultaneamente faithfulness=1, relevância=1 e as fontes
obrigatórias do gabarito. Uma fonte alternativa válida pode falhar nesse último
critério: o indicador é deliberadamente mais estrito que a sustentação factual.
Latências incluem planejamento, ferramentas e geração; são observações de uma
rodada, dependentes de rede e carga, sem conclusão de desempenho estável.

Os artefatos em `evals/sprint4/` incluem protocolo, adendo do segundo modelo,
saídas brutas, perguntas, planos, contexto recuperado, entradas da geração,
citações, tokens quando retornados, hashes e notas justificadas em `revisao.json`.
`scores.json` é calculado dessas notas; não usa um juiz LLM durante a consolidação.
O vínculo SHA-256 impede reutilizar a nota de uma resposta alterada.

## Ambiente e parâmetros comuns

- LangChain/LCEL e Pydantic; planejamento semântico e executor Python tipado.
- Chroma local, coleção `chargegrid_knowledge_v2`; embeddings `nomic-embed-text`
  no Ollama local. Geração pelo Ollama Cloud, via daemon local.
- 3 PDFs, 75 páginas e 254 chunks; tamanho 600 **caracteres**, overlap 200 e k=8.
- `temperature=0`, `top_p=0.9`, `max_tokens=1200`, memória limitada a 4000 tokens.
- Mesmo corpus e critérios; hashes do dataset, PDFs, fixtures e prompts salvos.
- Nenhuma nova indexação entre as configurações. A forma de extração é a mesma.

A comparação de modelos usa os mesmos prompts v3 e modo híbrido. O contexto
efetivo pode variar porque cada planejador reescreve sua consulta; os registros
permitem inspecionar essa diferença. Compara-se o pipeline completo, não apenas
dois geradores recebendo uma lista idêntica de chunks.

## Avaliação automática com RAGAS

RAGAS 0.4.3 executado sobre as respostas históricas, sem refazer a busca ou a
geração. Juiz `gemma4:31b-cloud`, temperatura 0, top_p 0,9, saída máxima de 4096
tokens; embeddings `nomic-embed-text`, mesmo prefixo `search_query:` nos dois
lados da comparação e strictness=3. O juiz avalia também as respostas históricas
do GPT-OSS; não é necessário acessar esse modelo novamente. Usar Gemma para
gerar e julgar é permitido pelo método da aula, mas pode introduzir viés.

O ambiente de avaliação é separado (`.venv-ragas`), com LangChain Community 0.4.1:
a versão 0.4.2 do aplicativo removeu um import ainda utilizado pelo RAGAS. A API
LangChain da aula é suportada na versão fixada, embora marcada como deprecated.
Não houve alteração no índice ou nas dependências LangChain do aplicativo.

Faithfulness usa somente respostas factuais exibidas com contexto documental.
Abstenções são não aplicáveis nessa métrica e continuam verificadas pelo gabarito.
Answer relevancy avalia também abstenções: uma recusa correta pode receber zero
porque o RAGAS a classifica como não comprometida. Falhas técnicas retidas pelo
serviço não são respostas factuais e ficam não aplicáveis nas duas métricas.
Falhas do juiz são registradas como erro, nunca convertidas em zero ou sucesso.
As médias abaixo têm denominadores explícitos; diferenças sem pareamento não
devem ser interpretadas isoladamente como ganho.

| Execução | Faithfulness RAGAS | Answer relevancy RAGAS | Erros do juiz (F/R) |
|---|---:|---:|---:|
| baseline_gemma | 0.917 (n=6) | 0.587 (n=10) | 0/0 |
| hibrido_gemma | 1.000 (n=8) | 0.642 (n=11) | 0/0 |
| hibrido_gptoss | 0.952 (n=7) | 0.537 (n=11) | 0/0 |

### Comparação nos casos válidos em comum

**baseline_gemma__hibrido_gemma** (delta do segundo em relação ao primeiro):

- faithfulness: delta +0.0833, n=6.
- answer_relevancy: delta +0.0347, n=10.

**hibrido_gemma__hibrido_gptoss** (delta do segundo em relação ao primeiro):

- faithfulness: delta -0.0476, n=7.
- answer_relevancy: delta -0.1051, n=11.

Os registros de entrada, scores, afirmações/vereditos e perguntas reconstruídas
estão nos rastros do juiz em `evals/sprint4/ragas/`. O arquivo `scores.json` dessa
pasta é separado das notas da rubrica; não se substituem nem se somam os scores.
A rubrica continua necessária para condições obrigatórias, citações e adequação
das recusas. Uma rodada com um juiz não é prova objetiva de correção nem garantia
de ausência de alucinações. Em RAG-R19/A, o extrator de afirmações transformou
condições da resposta ("quando... está ativado e... se aproxima") em declarações
de estado atual e o juiz as rejeitou, produzindo faithfulness=0,500. O resultado
foi preservado, mas esse erro de decomposição limita a interpretação do ganho
de fidelidade da candidata; não comprova alucinação na frase condicional original.
Procedimento e reprodução em
[avaliacao_ragas.md](avaliacao_ragas.md).


## Duas iterações — rubrica complementar

| Execução | Faithfulness (n aplicável) | Answer relevancy (12 casos) | Integral ao gabarito | Falhas de saída | Latência média |
|---|---:|---:|---:|---:|---:|
| A · Gemma · v2 · semântica | 1.000 (10/12) | 0.569 | 4/12 | 2 | 2.94 s |
| B · Gemma · v3 · híbrida | 1.000 (11/12) | 0.590 | 3/12 | 1 | 2.46 s |
| B · GPT-OSS · v3 · híbrida | 0.902 (11/12) | 0.535 | 3/12 | 1 | 3.14 s |

A: prompts `planejador_v2.md` e `resposta_tools_v2.md`, recuperação semântica.
B: prompts v3 preservam termos específicos e pedem cobertura dos critérios;
busca híbrida BM25 (k1=1,5; b=0,75), reserva até duas posições lexicais e completa
por fusão recíproca de rankings (constante 60), deduplicando e limitando a k=8.
Usa os mesmos chunks; não consulta gabaritos ou IDs de resposta. A implementação
lê o corpus para calcular BM25 por pergunta, adequada à base pequena, com custo
linear que precisa ser revisto para crescimento. Não é reranking por modelo.
Prompt e recuperação mudam juntos: o experimento não isola seus efeitos.

## Resultado da rubrica e decisão de configuração

A iteração B com Gemma elevou a relevância média de 0,569 para 0,590:
**+0,0208, ou 2,08 pontos percentuais**. Os critérios atendidos passaram de 21/34
para 22/34, e as falhas de saída de duas para uma. Nas seis perguntas respondíveis,
a relevância permaneceu 0,514; o ganho agregado veio do caso adversarial de fumaça.
Não há demonstração de melhoria geral ou significância estatística.

O atendimento integral caiu de 4/12 para 3/12. Em RAG-R11, a resposta B/Gemma
trouxe potências corretas com fonte do manual, mas não a fonte obrigatória do
datasheet; além disso, a pergunta sobre controle dinâmico perdeu uma condição.
**A configuração padrão permanece Gemma, prompts v2 e busca semântica.**
A busca híbrida e os prompts v3 ficam disponíveis como experimento optativo.
O ganho pequeno não justifica promover a candidata com regressões de completude.
Faithfulness 1,000 refere-se apenas às unidades auditadas dos casos aplicáveis;
não significa ausência universal de alucinações ou cobertura completa da pergunta.

## Problemas encontrados e tratamento

1. **Recuperação genérica no caso de fumaça.** A baseline recuperou manutenção
   preventiva e falhou na resposta protetiva. A candidata preserva a consulta
   específica e combina BM25 com ranking vetorial. Passou a recuperar a regra
   pertinente, mas Gemma ainda omitiu afastamento/equipe: resposta parcial.
2. **Citações não literais.** O modelo tentou apoiar a distinção IP66/IP55 com
   texto que não passou na verificação. A aplicação reteve a resposta; RAG-R13
   permanece `evidencia_invalida`. Schema e fonte existente não bastam para
   assegurar uma resposta correta.
3. **Informação além do chunk.** GPT-OSS completou uma condição de retomada do
   controle dinâmico ausente nos chunks fornecidos e omitiu o qualificador de
   interrupção segura no caso adversarial de fumaça. Essas perdas aparecem nas
   notas de faithfulness e relevância; os guardrails atuais não detectam toda
   omissão ou extrapolação semântica.
4. **Ausência de evidência confundida com pouca utilidade.** Garantia, estorno e
   produto ausente não receberam especificações inventadas, porém faltaram as
   orientações complementares exigidas pelo gabarito: relevância 0,500 nos três.

A triagem de instruções documentais permaneceu ativa nos três ataques testados;
isso não representa imunidade a prompt injection nem aprovação integral das
respostas. A prioridade futura é melhorar recuperação e cobertura de condições,
validando o conjunto completo antes de promover outra configuração.

## Reprodução e rastreabilidade

Com ambiente virtual, dependências do projeto, daemon Ollama autenticado e índice
preparados conforme `docs/rag.md`:

```bash
python evals/metricas_sprint4.py
python evals/gerar_relatorios_sprint4.py
```

O primeiro comando recalcula notas das avaliações já revisadas, sem chamadas à IA.
O segundo gera os relatórios Markdown e o PDF; requer `pip install -e '.[reports]'`.
O RAGAS usa ambiente separado por compatibilidade. Instalação, execução do juiz
e retomada estão em [avaliacao_ragas.md](avaliacao_ragas.md); as métricas automáticas
ficam em `evals/sprint4/ragas/`, separadas da rubrica complementar.
Para novas inferências, preservando antes os resultados atuais:

```bash
ollama pull gemma4:31b-cloud
ollama pull gpt-oss:120b-cloud
python evals/avaliar_sprint4.py --experimento baseline_gemma
python evals/avaliar_sprint4.py --experimento hibrido_gemma
python evals/avaliar_sprint4.py --experimento hibrido_gptoss
```

O executor impede sobrescrever registros existentes. `--retomar` executa somente
casos ainda não concluídos e verifica configuração e hashes; registros completos
não são executados novamente. Uma nova resposta exige revisão própria antes de
consolidar notas. Indisponibilidade de infraestrutura é preservada separadamente.

Referências: [rubrica](../evals/sprint4/rubrica.md),
[protocolo](../evals/sprint4/protocolo.json),
[notas auditáveis](../evals/sprint4/revisao.json),
[scores](../evals/sprint4/scores.json),
[histórico de prompts](../prompts/RAG_VERSIONS.md).
