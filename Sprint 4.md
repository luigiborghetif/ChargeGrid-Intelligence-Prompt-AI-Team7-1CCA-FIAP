# Sprint 4 — Stack e ordem de implementação

Evolução do ChargeGrid Intelligence para um assistente com recuperação de
documentos (RAG), respostas fundamentadas em fontes e avaliação reproduzível.
O desenvolvimento aproveita a aplicação local existente.

## Stack necessária

| Camada | Tecnologia | Aplicação |
|---|---|---|
| Linguagem e projeto | Python e `pyproject.toml` | Manter o pacote local e centralizar as dependências. |
| Orquestração | LangChain e LCEL | Compor recuperação, prompt, modelo, validação e memória. |
| Leitura de PDFs | `PyMuPDFLoader`, de `langchain-community`, com PyMuPDF | Extrair conteúdo e metadados de origem e página. |
| Divisão de documentos | `RecursiveCharacterTextSplitter`, de `langchain-text-splitters` | Produzir chunks com tamanho e overlap configuráveis. |
| Embeddings | `nomic-embed-text` via `OllamaEmbeddings`, de `langchain-ollama` | Vetorizar documentos e perguntas com o mesmo modelo. |
| Banco vetorial | ChromaDB e integração `langchain-chroma` | Persistir embeddings e executar buscas semânticas entre reinicializações. |
| Recuperação | Retriever do Chroma | Selecionar trechos relevantes com `k` configurável. |
| Geração | `ChatOllama`, de `langchain-ollama` | Reaproveitar a integração existente e comparar pelo menos dois modelos no pipeline RAG. |
| Contratos e validação | Pydantic | Validar respostas e referências estruturadas às fontes. |
| Interface | Gradio | Reaproveitar o chat e apresentar citações e trechos de apoio. |
| Indicadores e visualização | Funções Python existentes e Plotly | Preservar os cálculos determinísticos e o dashboard operacional. |
| Avaliação | RAGAS | Medir `faithfulness` e `answer_relevancy` por iteração. |
| Alternativa de avaliação | Rubrica manual documentada, com notas de 0 a 1 | Substituir RAGAS caso o ambiente não o suporte, justificando a equivalência e mantendo o mesmo conjunto de avaliação. |
| Configuração | Variáveis de ambiente e `python-dotenv` | Configurar modelos, persistência, chunking, recuperação e geração. |
| Qualidade | Pytest e Ruff | Verificar comportamento, regressões, lint e formatação. |

A disponibilidade e a forma de execução do modelo de embeddings no ambiente
Ollama devem ser verificadas antes da integração. A infraestrutura utilizada deve
ficar registrada para permitir a reprodução dos resultados.

## Ordem de implementação

### 1. Base documental e conjunto de avaliação

- Criar `data/knowledge_base/` com manuais GoodWe, FAQs de carregamento,
  regras de uso compartilhado e tabelas tarifárias relevantes.
- Registrar origem, versão e identificação de cada documento. Identificar
  explicitamente os materiais simulados.
- Preparar um conjunto fixo de perguntas respondíveis, perguntas sem evidência
  na base e casos de prompt injection em documentos.
- Definir as respostas esperadas e as fontes que as sustentam.

**Validação:** cada pergunta respondível possui evidência identificável; os
casos sem resposta e os casos adversariais possuem comportamento esperado.

### 2. Ingestão, embeddings e recuperação

- Criar `src/rag/` com `loader.py`, `chunking.py`, `embeddings.py`,
  `vector_store.py`, `retriever.py` e `prompt_rag.py`.
- Implementar o fluxo `PyMuPDFLoader → RecursiveCharacterTextSplitter →
  OllamaEmbeddings → ChromaDB persistente → retriever`.
- Preservar documento, página, seção quando disponível e identificador do chunk.
- Configurar tamanho dos chunks, overlap, diretório de persistência e `k`.
- Disponibilizar um comando reproduzível de indexação, evitando duplicação na
  reingestão e tratando alterações na base.

**Validação:** documentos são recuperados após reiniciar o processo, os
metadados permanecem disponíveis e reindexar não duplica os trechos.

### 3. Integração ao assistente existente

- Integrar a recuperação ao `AssistenteChargeGrid` e à chain LCEL.
- Criar e versionar o prompt RAG, delimitando os trechos recuperados e exigindo
  respostas sustentadas pelas evidências fornecidas.
- Manter os indicadores operacionais calculados em Python e identificar sua
  procedência quando usados na resposta.
- Combinar evidências documentais e operacionais quando a pergunta exigir ambas.
- Adaptar o escopo para aceitar os temas da base expandida.
- Preservar a memória por sessão sem tratar respostas anteriores do modelo
  como evidência factual.

**Validação:** consultas documentais, operacionais e mistas utilizam as fontes
apropriadas; ausência de evidência produz uma resposta explícita de insuficiência.

### 4. Citações estruturadas e interface

- Ampliar o contrato Pydantic com referências às fontes utilizadas.
- Validar se os identificadores citados pertencem ao contexto fornecido.
- Exibir documento, página/seção e trecho de apoio no chat Gradio.
- Adaptar a apresentação para perguntas documentais, sem obrigar o modelo a
  inventar risco operacional ou recomendações sem fundamento.
- Criar o ponto de entrada em `app/` e seu README de execução, reutilizando a
  interface existente.

**Validação:** as citações exibidas correspondem a evidências reais e sustentam
as afirmações da resposta; a interface apresenta respostas e recusas corretamente.

### 5. Segurança e testes

- Tratar documentos recuperados como dados não confiáveis, sem autoridade para
  alterar as instruções do sistema.
- Distinguir perguntas dentro do domínio de perguntas com evidência suficiente.
- Testar injection por documentos, recuperação irrelevante, contexto ausente,
  referências inexistentes e especificações de produtos ausentes da base.
- Verificar que memória e documentos não contornam os guardrails existentes.
- Executar testes de regressão, verificações de lint e formatação e validação
  funcional da interface integrada ao RAG.

**Validação:** o sistema mantém as proteções existentes, resiste aos ataques
testados e recusa conclusões sem suporte documental ou operacional.

**Execução registrada:** controles documentais implementados e regressão de
215 testes aprovada. A amostra real inicial aprovou 8/9 cenários funcionais;
o caso de fumaça revelou recusa indevida e limitação de recuperação. O planejador
foi ajustado e a última resposta foi parcial, sem uso do documento adversarial.
O caso não está contabilizado como aprovação funcional integral. Detalhes e
registros estão em [docs/seguranca_rag.md](docs/seguranca_rag.md); a qualidade
da recuperação permanece um ponto de avaliação e melhoria da etapa 6.

### 6. Avaliação, iterações e documentação técnica

- Registrar pergunta, contexto recuperado, resposta, fontes, modelos,
  parâmetros e scores em `evals/`.
- Medir `faithfulness` e `answer_relevancy` com RAGAS ou aplicar a rubrica manual
  equivalente documentada no mesmo conjunto de perguntas a cada iteração.
- Realizar pelo menos duas iterações RAG, registrando as mudanças e os ganhos
  efetivamente medidos; não presumir melhoria pela troca de versão.
- Manter uma tabela de versões dos prompts RAG com alterações e scores.
- Comparar pelo menos dois modelos com os mesmos casos e configurações
  comparáveis. Registrar `temperature`, `top_p`, `max_tokens` e `k` do retriever.
  A Sprint recomenda temperatura zero.
- Atualizar `docs/relatorio_modelos.md` e criar `docs/relatorio_rag.md`,
  documentando chunking, base, recuperação, limitações e resultados.
- Atualizar os READMEs com instruções reproduzíveis e produzir o relatório
  técnico de evolução em PDF, com até cinco páginas e comparação antes/depois.

**Validação:** os resultados permitem inspecionar cada execução e comparar as
iterações; os ganhos declarados possuem evidência e as instruções de execução
correspondem ao comportamento verificado.

**Execução registrada:** duas iterações RAG e comparação entre Gemma e GPT-OSS
concluídas sobre os mesmos 12 casos pré-fixados (6 respondíveis, 3 sem evidência
completa e 3 ataques). Qwen indisponível foi substituído por GPT-OSS, com adendo
preservado. RAGAS 0.4.3 executado em ambiente separado com Gemma como juiz:
nos casos válidos em comum entre A/B, fidelidade 0,917 → 1,000 (n=6) e relevância
0,587 → 0,622 (n=10). Um erro de decomposição de frase condicional pelo juiz foi
registrado; os ganhos não comprovam melhoria factual geral. A rubrica complementar
permanece auditável e mostra atendimento integral de 4/12 para 3/12; a candidata
híbrida/v3 permanece optativa. Regressão: 224 testes
aprovados. Resultados em [relatorio_rag.md](docs/relatorio_rag.md) e
[relatorio_modelos.md](docs/relatorio_modelos.md); relatório técnico em
[PDF de quatro páginas](docs/relatorio_evolucao_sprint4.pdf).

## Prioridade de escopo

A evolução do roteamento usa um planejador semântico LCEL com plano Pydantic
e ferramentas tipadas de consulta, cálculo e busca documental. Ela preserva
o pipeline RAG, memória por sessão, segurança e citações. O fluxo anterior
permanece disponível para comparação. A implementação, configuração e os
resultados funcionais estão em [docs/planejador.md](docs/planejador.md).
Essa evolução não substitui os testes adversariais da etapa 5 nem as avaliações,
comparações e relatórios da etapa 6.

A prioridade é concluir o pipeline RAG persistente, as citações visíveis, o
grounding, a segurança documental e a avaliação com ganhos registrados.
LangGraph, agentes, reranking, chunking avançado e observabilidade são
diferenciais opcionais. O bônus multi-provider é posterior aos requisitos
obrigatórios.
