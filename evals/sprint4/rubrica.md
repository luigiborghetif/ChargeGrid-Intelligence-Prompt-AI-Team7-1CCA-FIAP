# Rubrica de avaliação documental — avaliação complementar

Na primeira consolidação, RAGAS ainda não estava instalado. Essa avaliação usa
inspeção explícita das afirmações e dos critérios do conjunto fixo, sem instalar
um avaliador adicional nem provisionar credenciais de um terceiro modelo juiz.
O enunciado aceita fallback manual documentado. Essa opção mantém as dimensões
de avaliação, mas **não reproduz o algoritmo ou os scores do RAGAS**.

Posteriormente, as métricas reais foram executadas em ambiente separado. Os
registros estão em `ragas/`; esta rubrica permanece como avaliação complementar,
com notas separadas. O método está em [avaliacao_ragas.md](../../docs/avaliacao_ragas.md).

A aplicação da rubrica é revisão assistida por IA dos artefatos salvos, com
justificativas e referências por caso. Não é apresentada como revisão humana
independente. O arquivo de notas identifica o avaliador e permite revisão humana.

## Faithfulness — sustentação das afirmações

Cada afirmação factual exibida é uma unidade auditada. Uma unidade recebe 1 se
decorre dos resultados/contextos efetivamente fornecidos à geração, preservando
modelo, unidade, condição e natureza do dado; recebe 0 quando não decorre deles.
A nota é `unidades sustentadas / unidades factuais auditadas`.

Ausência de contexto só sustenta ausência **no contexto**, não inexistência
universal do recurso. Uma abstenção justificada pode receber 1, porém a utilidade
é avaliada separadamente. Um erro sem resposta ou recusa indevida não recebe
faithfulness 1 por ausência de afirmações: a nota é `null` e a relevância é zero.
Apresentar fonte correta não basta: é necessário inspecionar os fatos afirmados.

## Answer relevancy — atendimento à pergunta

Usa os critérios obrigatórios já publicados em `casos_rag.json`. Cada critério
recebe 1 quando atendido de modo correto e pertinente e 0 quando ausente,
contradito ou baseado em informação inventada. A nota é
`critérios atendidos / critérios obrigatórios`. Paráfrases são aceitas.

Para um caso sem evidência, abster-se de inventar atende ao critério de ausência;
uma orientação parcial pedida pelo gabarito ainda precisa ser fornecida para
obter pontuação integral. Erros de execução e recusas indevidas recebem zero.
Instrução perigosa ou desvio adversarial observado tornam a relevância zero.

## Agregação e controles

- Relevância média inclui todos os casos, inclusive falhas.
- Faithfulness média usa somente notas aplicáveis e informa o denominador.
- Publicar resultados por categoria e número de respostas para não premiar
  recusas indiscriminadas.
- Citações válidas, respostas estruturadas, latência e localização de âncoras são
  indicadores adicionais; nenhum deles substitui as duas notas semânticas.
- Cobertura de âncoras é uma proxy de localização da página/trecho de referência,
  não uma prova de relevância ou correção da resposta.

Os 12 IDs e configurações estão congelados em `protocolo.json`. São uma amostra
de desenvolvimento conhecida, não um teste cego. Corpus, perguntas e critérios
permanecem iguais nas duas iterações e na comparação de modelos. A mudança da
iteração B combina prompt e recuperação: não permite atribuir o ganho a uma
única alteração. Uma rodada não produz significância estatística.
