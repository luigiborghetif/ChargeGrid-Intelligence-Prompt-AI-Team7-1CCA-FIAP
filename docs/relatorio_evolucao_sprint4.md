# Relatório técnico de evolução — Sprint 4

## ChargeGrid Intelligence | Sprint 4

Relatório técnico de evolução · 23 de outubro de 2026

O projeto evolui o assistente gerencial de recarga para consultar dados operacionais e PDFs com fontes verificáveis. O planejamento usa LCEL e contratos Pydantic; os cálculos continuam em Python. A entrega inclui avaliação rastreável e registra limitações de recuperação e completude.

| Dimensão | Sprints 1/2 (versão original) | Sprint 04 (RAG avaliado) |
|---|---|---|
| Evidências | JSON da operação simulada | JSON e 3 PDFs com origem e página |
| Consulta | Análise operacional com prompt | Plano tipado; até 4 ferramentas |
| Recuperação | Sem índice documental | Chroma persistente e Nomic |
| Resposta | Schema operacional | Resposta documental/mista com apoios validados |
| Segurança | Guardrails de entrada e saída | Triagem documental e integridade de fontes |
| Avaliação RAG | Não medida | 12 casos fixos; 2 iterações e 2 modelos |
| Scores por iteração | Não medidos | RAGAS Gemma A: F=0.917 (n=6), R=0.587 (n=10); B: F=1.000 (n=8), R=0.642 (n=11) |
| Qualidade do contexto | Sem avaliação documental | Proxy: âncoras recuperadas A 11/18; B 12/18; ainda há lacunas |
| Citação de fonte | Sem citação documental estruturada | Arquivo, página e trecho; visível em A 7/12 e B 8/12 casos |

O fluxo operacional anterior permanece disponível. As métricas antigas de classificação não são tratadas como faithfulness ou relevância RAG. Os dados comerciais e as regras WeCharge são simulados e não representam políticas da GoodWe.


---

## Arquitetura e evidências

Fluxo: pergunta → guardrails e histórico da sessão → planejador LCEL → plano Pydantic → executor Python → fontes documentais/operacionais → geração estruturada → conferência de citações e segurança → CLI ou Gradio.

Ingestão: PyMuPDFLoader → RecursiveCharacterTextSplitter → OllamaEmbeddings → Chroma local persistente. Base de 3 PDFs, 75 páginas e 254 chunks, com 600 caracteres, overlap de 200 e top-k 8. Identificadores, arquivo e página acompanham os trechos; reindexação evita duplicação.

As ferramentas consultam a operação, calculam indicadores, buscam documentos e estimam custos em Python. O histórico da sessão ajuda a interpretar a pergunta, mas respostas anteriores não viram evidência. Dados agregados não permitem descobrir valores de sessões individuais inexistentes na base.

Documentos são dados sem autoridade sobre o sistema. Conteúdo e metadados passam por triagem; identificadores reservados ou conflitantes são rejeitados. As citações precisam existir no contexto e preservar trechos literais. A proteção não garante detectar toda omissão ou conclusão semanticamente indevida.

Iteração A: busca semântica e prompts v2. Iteração B: prompts v3 preservam termos específicos; BM25 com k1=1,5 e b=0,75 reserva até duas posições lexicais e completa por fusão recíproca de rankings (constante 60), mantendo o limite total de oito chunks. Não usa gabarito para selecionar evidências.

O BM25 recalcula estatísticas do pequeno corpus por pergunta. O custo linear e a ausência de reconstrução de tabelas complexas são limitações para bases maiores. A extração não usa imagens e pode fragmentar relações entre linhas e colunas.


---

## Avaliação comparável

Amostra pré-fixada de desenvolvimento: 6 perguntas respondíveis, 3 sem evidência completa e 3 ataques documentais, retirada do conjunto de 38. Uma execução por caso/configuração, sessão nova, mesmo corpus e gabarito; fixtures adversariais apenas em memória. Não é teste cego nem avaliação dos 38 casos completos.

Geração cloud: Gemma 4 31B e GPT-OSS 120B via Ollama. Temperature 0; top_p 0,9; limite de saída 1200 tokens; k=8; memória de 4000 tokens. Modelos B usam os mesmos prompts e busca, porém seus planejadores podem recuperar contextos distintos. Qwen ficou indisponível e foi substituído antes da rodada alternativa; não recebeu nota.

RAGAS 0.4.3 avalia os registros salvos com Gemma como juiz (temperatura 0, top_p 0,9, limite 4096 tokens) e Nomic para relevância (strictness 3). Usa o contexto pós-triagem efetivamente enviado à geração. Ambiente separado, com LangChain Community 0.4.1 para compatibilidade; API da aula marcada como deprecated, sem alterar o aplicativo.

| Execução | Faithfulness RAGAS | Relevância RAGAS | Integral* | Falhas |
|---|---|---|---|---|
| A / Gemma | 0.917 (n=6) | 0.587 (n=10) | 4/12 | 2 |
| B / Gemma | 1.000 (n=8) | 0.642 (n=11) | 3/12 | 1 |
| B / GPT-OSS | 0.952 (n=7) | 0.537 (n=11) | 3/12 | 1 |

Falhas técnicas são não aplicáveis nas duas métricas. Abstenções não recebem faithfulness por ausência de fatos; relevância pode ser zero mesmo numa recusa correta. Erros do juiz não viram zeros. Denominadores diferentes exigem examinar também o pareamento de casos válidos.

Comparação pareada Gemma: faithfulness: delta B-A +0.0833 (n=6); answer_relevancy: delta B-A +0.0347 (n=10). Os IDs e os rastros do juiz estão em evals/sprint4/ragas. Usar o mesmo modelo para gerar e julgar pode introduzir viés; não há garantia de correção automática.

Em RAG-R19/A, o juiz transformou condições em afirmações de estado ao decompor a resposta, contribuindo para faithfulness=0,500. A nota foi preservada; o ganho observado não comprova melhoria factual geral.

*Rubrica complementar: relevância Gemma 0,569 → 0,590 (+2,08 p.p.); critérios atendidos 21/34 → 22/34. Atendimento integral exige todos os critérios e fontes obrigatórias: 4/12 → 3/12. Esses números não são scores RAGAS. Prompt e busca mudam juntos; uma rodada não isola causas nem produz significância estatística.


---

## Achados, decisão e reprodução

### Recuperação e fumaça

A baseline recuperou manutenção em lugar da regra protetiva. A candidata recuperou o trecho pertinente, mas Gemma ainda omitiu afastamento e equipe. A melhoria é parcial.

### Apoios inválidos

A resposta sobre IP66/IP55 permaneceu retida por trecho não confirmado. O controle evita exibir uma resposta com citação inválida, mas causa perda de utilidade.

### Extrapolações

GPT-OSS completou uma condição de retomada ausente nos chunks e perdeu uma condição de interrupção segura. As notas penalizam esses casos. Fonte válida não assegura fidelidade de toda a resposta.

Decisão: manter Gemma, busca semântica e prompts v2 como padrão. A candidata híbrida/v3 fica optativa, pois o pequeno ganho agregado veio do caso adversarial e o atendimento integral caiu. Os três ataques testados não comandaram a execução; isso não prova imunidade nem aprovação integral das respostas.

Rastreabilidade: evals/sprint4 contém protocolo, adendo, perguntas, contextos, gerações brutas, citações, notas e scores. docs/relatorio_rag.md e docs/relatorio_modelos.md detalham a metodologia. A regressão e as instruções de execução estão no README; a interface permanece Gradio, sem alteração visual nesta etapa.

Reprodução: evals/avaliar_ragas.py executa o juiz em ambiente separado, com versões fixadas em evals/requirements-ragas.txt e lock da rodada. evals/gerar_relatorios_sprint4.py gera os documentos dos scores salvos sem inferência. O procedimento está em docs/avaliacao_ragas.md; o índice e a aplicação em docs/rag.md.
