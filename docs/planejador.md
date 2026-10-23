# Planejamento semântico e ferramentas

O ChargeGrid interpreta a intenção da pergunta com um planejador LCEL, executa
consultas e cálculos autorizados em Python e gera a resposta a partir dos
resultados e fontes. A seleção por palavras-chave permanece disponível no modo
anterior para comparação, mas não decide o encaminhamento no fluxo padrão.

## Arquitetura

1. Moderação determinística bloqueia entradas inválidas, padrões conhecidos de
   injection e intervenções elétricas perigosas antes de chamar o modelo.
2. O planejador recebe a pergunta, perguntas anteriores da sessão e descrições
   das ferramentas. Classifica consulta, esclarecimento, ajuda, fora do domínio
   ou recusa de segurança. A falta de uma palavra-chave não bloqueia a entrada.
3. `PlanoConsulta` valida etapas e argumentos por união discriminada Pydantic.
   IDs são únicos, há no máximo quatro etapas e dependências precisam apontar
   para etapas anteriores do tipo correto. Campos extras são rejeitados.
4. Um executor exclusivo da consulta invoca ferramentas `StructuredTool` do
   LangChain. Não aceita código, SQL, caminhos arbitrários ou ações físicas.
5. Outra chain LCEL recebe os resultados e fontes. Respostas anteriores da IA
   não entram como evidência. O modelo não substitui os cálculos das ferramentas.
6. A aplicação verifica segurança da resposta, IDs e presença dos trechos nas
   fontes e apresenta as citações pelo contrato já utilizado no Gradio e CLI.

As duas chains usam `prompt | ChatOllama(format="json") | PydanticOutputParser`.
Não dependem de tool calling nativo do provedor: o modelo produz o plano JSON e
o executor chama as ferramentas. O mesmo modelo configurado é usado com
temperatura zero, sem subagentes ou ciclos automáticos de replanejamento.
Uma consulta factual usa normalmente duas chamadas de geração; saudações são
locais, e esclarecimentos ou classificação fora do domínio dispensam a segunda.

## Contratos e implementação

| Arquivo | Responsabilidade |
|---|---|
| `src/schemas/plano_consulta.py` | Plano, argumentos específicos e `ResultadoFerramenta` |
| `src/chain/planejador.py` | Chains de planejamento e resposta |
| `src/tools/executor.py` | Ferramentas, dependências, procedência e cálculos |
| `src/chargegrid/assistente.py` | Guardrails, memória, execução e resposta às interfaces |
| `prompts/planejador_v2.md` | Interpretação e seleção das ferramentas |
| `prompts/resposta_tools_v2.md` | Grounding, limitações e apoios da resposta |

O envelope expõe `plano` e `resultados_ferramentas` para inspeção e avaliação.
As respostas do fluxo planejado usam `documental` (`RespostaDocumental`) como
contrato fundamentado comum, inclusive para fatos operacionais, preservando o
campo existente da fase 4. Não forçam risco ou recomendações quando não pedidos.
`dados` (`ConsultaRecarga`) continua disponível no fluxo operacional anterior.

## Ferramentas

| Ferramenta | Argumentos e resultado |
|---|---|
| `consultar_operacao` | Resumo, demanda horária, carregadores com filtro, ordenação e limite, ou disponibilidade de sessões individuais |
| `calcular_indicadores` | Pico, energia total, sessões totais, throttling, ociosidade, faturamento ou todos os indicadores existentes |
| `buscar_documentos` | Pergunta de busca; retorna chunks e preserva seus metadados para citações |
| `estimar_custo` | Modalidade, referência à busca tarifária e energia explícita do usuário ou referência à consulta operacional anterior |

Os resultados distinguem `sucesso`, `parcial`, `ausente` e `erro`. Uma falha
técnica não é ausência de conhecimento. Resultados parciais/ausentes/erros
impedem que a resposta seja apresentada como inteiramente sustentada, mesmo
quando o modelo marcar o contrário. Uma parte disponível pode ser apresentada.

O cálculo financeiro usa `Decimal`, arredonda centavos e mantém a fórmula e as
premissas. A energia literal precisa constar de uma pergunta do usuário em kWh.
A energia derivada precisa vir de um resultado anterior bem-sucedido, com total
de energia ou um único carregador. A tarifa é extraída dos chunks daquela busca,
com formato `Urgente: R$.../kWh` ou `Econômico: R$.../kWh`. Valores conflitantes
ou outros formatos não geram estimativa. Não há tarifa fixa escondida no código.
Uma estimativa completa precisa citar o cálculo e as fontes dos valores usados.

### Granularidade dos dados

O JSON atual contém energia acumulada e contagem de sessões por carregador,
potência no snapshot e demanda horária. Não contém registros individuais de
sessão, datas de recargas ou preços efetivamente cobrados por sessão.

Assim, a pergunta sobre a maior recarga individual produz uma limitação
explícita e pode apresentar o maior acumulado disponível: EV-01, 38 kWh em seis
sessões. Não se trata de uma única recarga de 38 kWh. Uma estimativa sobre esse
acumulado precisa ser solicitada e identificada como cenário, não cobrança real.

## Configuração e execução

Não há novas dependências ou necessidade de alterar o índice existente.
O Gradio e a CLI usam o planejador por padrão:

```bash
python -m app.main
```

As opções possuem valores padrão e estão em `.env.example`:

```dotenv
CHARGEGRID_USAR_PLANEJADOR=true
PLANNER_PROMPT_PATH=prompts/planejador_v2.md
PLANNER_RESPONSE_PROMPT_PATH=prompts/resposta_tools_v2.md
```

O `.env` original não precisa receber essas opções para ativar a feature.
`CHARGEGRID_USAR_PLANEJADOR=false` restaura a integração anterior com
`RAG_PROMPT_PATH`. Os executores históricos de avaliações preservam explicitamente
o fluxo anterior para que seus resultados não mudem de significado.

## Validação principal — 22/10/2026

- Regressão geral de **182 testes aprovada**, seguida de **26 testes direcionados
  do planejador aprovados**, incluindo um caso adicional de recusa semântica de
  segurança. Naquela execução, a suíte continha 183 casos. Ruff e formatação aprovados.
  Permanecem avisos de descontinuação de dependências.
- Verificação funcional com Gemma e Chroma reais: maior recarga individual com
  limitação e acumulado correto, tarifas, pico com controle dinâmico, estimativa
  de 20 kWh no Econômico, continuação no Urgente e prazo de estorno sem evidência.
- Os seis cenários têm resultado final aprovado. A primeira continuação foi
  recusada pela conferência de citações e não se reproduziu na repetição
  direcionada. A tentativa anterior está preservada no relatório, sem atribuição
  de causa não confirmada. Temperatura zero não é uma garantia de determinismo.
- R$ 21,00 no Econômico e R$ 37,80 no Urgente foram calculados em Python.
  Não foram executados novos testes de navegador nesta feature.

O relatório [`planejador_validacao.json`](../evals/planejador_validacao.json)
registra planos, ferramentas, evidências, respostas, parâmetros e hashes dos
prompts. A versão inicial do executor ainda não capturava as saídas intermediárias
do modelo; a repetição registra também essas saídas. A avaliação é funcional e
restrita; não é um score de faithfulness nem demonstra ganho geral de qualidade.

```bash
python -m pytest tests/test_planejador.py -q
python evals/validar_planejador.py
```

O segundo comando chama o modelo e atualiza o relatório. Para repetir somente a
sequência de custo com seu contexto e preservar os outros casos:

```bash
python evals/validar_planejador.py --casos custo continuacao --atualizar
```

## Limitações

O planejador pode escolher uma consulta inadequada ou pedir esclarecimento
desnecessário. O contrato valida a estrutura, não a interpretação semântica.
A seleção dos trechos ainda depende da recuperação; conferir um trecho não
comprova que toda afirmação decorre dele. As verificações por padrões não cobrem
todos os ataques. Avaliações semânticas, comparação controlada com o baseline e
testes adversariais amplos permanecem nas etapas de avaliação e segurança.

A fase 5 acrescentou triagem documental e integridade de fontes. A regressão
atual contém 215 testes aprovados. Os achados e a limitação funcional do caso
de fumaça estão em [seguranca_rag.md](seguranca_rag.md).
