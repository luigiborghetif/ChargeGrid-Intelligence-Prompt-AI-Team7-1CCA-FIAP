# Segurança documental — fase 5

A fase 5 acrescenta controles na fronteira entre contexto recuperado, ferramentas
e geração. Documentos não possuem autoridade para alterar instruções, liberar
ferramentas ou solicitar dados internos. Os PDFs e o índice Chroma são preservados.

## Controles implementados

- Triagem em memória antes da geração e da extração de tarifas. Padrões conhecidos
  de instrução ao assistente, falsificação de papel e desvio da pergunta colocam
  o chunk inteiro em quarentena. A triagem inspeciona conteúdo e metadados, sem
  rejeitar instruções legítimas de uso do produto apenas por serem imperativas.
- Metadados obrigatórios, página válida, separação entre IDs documentais e IDs
  operacionais e rejeição de conteúdo diferente com o mesmo identificador,
  inclusive entre buscas do mesmo plano. Repetições idênticas são deduplicadas.
- Nova conferência na montagem das citações: uma referência não pode usar um
  documento em quarentena, fonte inexistente ou trecho que não esteja na fonte.
- Tratamento de caracteres invisíveis na identificação de padrões e modelos.
- Especificações de um código de produto não são transferidas para outro quando
  o código consultado não aparece no contexto disponível. A verificação considera
  a pergunta atual e sua interpretação pelo planejador, incluindo continuações.
- Memória continua isolada por sessão; respostas anteriores não entram como
  evidência. Perguntas atuais continuam passando pela moderação antes do modelo.

O executor registra os IDs descartados e o motivo em
`resultados_ferramentas[].dados.documentos_bloqueados`. Esse registro permite
inspeção técnica sem transformar instruções adversariais em texto da resposta.
Sem fontes utilizáveis, a resposta informa insuficiência. Problemas de integridade
ou indisponibilidade são erros de consulta, não prova de ausência de conhecimento.

## Validação — 23/10/2026

| Verificação | Resultado |
|---|---|
| Regressão geral | 215 testes aprovados, com três avisos de descontinuação de dependências |
| Novos testes de segurança | 32 casos: seis ataques em duas ordens, integridade de fontes, cálculos, memória, modelo ausente, contexto e apresentação de recusas |
| Amostra real inicial | 8/9 cenários funcionais aprovados com Ollama e Chroma |
| Ataques reais I01–I05 | Quarentena aplicada; respostas com fontes legítimas e valores/regras esperados |
| Modelo ausente, recuperação irrelevante e fora do domínio | Recusas de evidência ou escopo apropriadas |
| Fumaça/dano aparente, I06 | Limitação funcional identificada; tentativas e resultado parcial preservados |

As duas ordens de inserção dos seis ataques foram cobertas nos testes locais.
Na amostra com o modelo real, cada ataque foi inserido uma vez, alternando a
posição antes/depois. Os ataques ficaram somente em memória; nenhuma fixture
foi adicionada à base vetorial. Os testes locais usam saídas controladas para
verificar os controles, não para atribuir qualidade semântica ao modelo.

Os prompts `planejador-v2` e `resposta-tools-v2` separam orientações protetivas
de intervenção elétrica e pedem citações literais curtas. As versões anteriores
foram mantidas. Os padrões do código e `.env.example` apontam para as versões v2.
Uma configuração explícita com caminhos v1 continua sendo respeitada.

Registros principais:

- [`fase5_seguranca.json`](../evals/fase5_seguranca.json): nove cenários iniciais,
  configuração, hashes, contextos antes da triagem, fontes e verificações.
- [`fase5_seguranca_fumaca.json`](../evals/fase5_seguranca_fumaca.json): repetições
  somente do caso afetado, incluindo saídas intermediárias e tentativas anteriores.
  A captura intermediária foi acrescentada durante o diagnóstico, portanto não
  aparece nas primeiras execuções.

Não foram repetidos testes de navegador. A camada de apresentação existente foi
exercitada pela função utilizada pelo Gradio, inclusive para recusa sem exposição
do ataque. A conferência visual anterior permanece válida para o layout existente.

## Reprodução

```bash
python -m pytest -q
python evals/validar_seguranca.py
```

O segundo comando chama o modelo e o retriever configurados e preserva o relatório
anterior. Para investigar apenas um caso em relatório separado:

```bash
python evals/validar_seguranca.py --casos RAG-I06 --saida evals/fase5_seguranca_fumaca.json
```

## Limites das conclusões

A triagem detecta padrões conhecidos; ataques reformulados podem passar e trechos
legítimos podem ser descartados indevidamente. Descartar um chunk inteiro também
remove fatos legítimos nele presentes. As instruções de grounding continuam
necessárias após a triagem. A amostra não mede resistência isolada do LLM aos
ataques descartados antes da geração e não constitui garantia geral de segurança.

Presença de um trecho e validade da referência não comprovam que toda afirmação
decorra dele. Os resultados não são scores RAGAS nem substituem a rubrica manual
equivalente, comparação de modelos e iterações da fase 6. O conjunto fixo de
avaliação não foi alterado para remover os casos que falharam.
