# Conjunto de avaliação documental — Sprint 4

O arquivo `casos_rag.json` contém 38 casos fixos fundamentados nos três PDFs de
`data/knowledge_base/`. O conjunto é independente dos dez casos operacionais de
`casos.json` e não utiliza o JSON de operação nem fontes externas como evidência.

| Categoria | Casos | Objetivo |
|---|---:|---|
| Respondíveis | 24 | Verificar recuperação, precisão, unidades, condições e citações. |
| Sem evidência suficiente | 8 | Verificar abstenção total ou parcial sem invenção de fatos. |
| Prompt injection documental | 6 | Verificar se instruções maliciosas nos documentos não alteram a resposta legítima. |

## Fontes e rastreabilidade

O catálogo `documentos` registra arquivo, identificador estável, versão, quantidade
de páginas, natureza do conteúdo e SHA-256. O hash identifica o arquivo analisado;
não certifica a autenticidade da publicação. URLs de download não foram fornecidas
e não são presumidas.

| Identificador | Documento | Versão | Páginas PDF |
|---|---|---|---:|
| `goodwe_hca_g2_datasheet` | GW_HCA-G2_Datasheet-PT.pdf | 20241121-PT-V2.1 | 2 |
| `goodwe_hca_g2_manual` | GW_HCA-G2_User-Manual-PT.pdf | V1.5-2025-11-11 | 70 |
| `wecharge_tarifas_regras` | Tarifas e Regras WeCharge.pdf | Não declarada no PDF | 3 |

O documento WeCharge representa o cenário comercial simulado do projeto. Essa
classificação decorre do contexto de criação das regras; o PDF não a declara
explicitamente. Seus preços e regras não representam política oficial da GoodWe.

`pagina_pdf` começa em 1 e representa a posição física no arquivo. No manual, a
página PDF 5 corresponde à página impressa 1. Metadados de loaders que começam
em zero precisam ser convertidos antes da comparação.

## Gabaritos

Cada caso apresenta uma pergunta, uma resposta de referência, critérios
obrigatórios, erros a evitar e evidências com documento, página, seção e trecho.
A resposta de referência admite paráfrases; a avaliação deve considerar o
significado e as condições, sem exigir igualdade literal de texto.

As evidências são âncoras para localizar o conteúdo na página, e não uma reprodução
integral da tabela ou seção. O contexto utilizado na avaliação precisa incluir os
valores, cabeçalhos, condições e notas necessários para sustentar toda a resposta.

`fontes_obrigatorias` contém os documentos que devem ser citados para sustentar
os critérios daquele caso. Referências adicionais são aceitas se forem relevantes
e pertencerem ao contexto efetivamente recuperado. Citar uma fonte correta sem
apoio para a afirmação não satisfaz o critério de grounding.

Nos casos sem evidência, `escopo_da_ausencia` delimita o que não está documentado.
Uma evidência com papel `limite_contextual` sustenta apenas a explicação parcial
disponível, como a menção condicional à cobrança de permanência. Ela não comprova
um valor ausente. A ausência é relativa ao corpus analisado, não uma afirmação
universal sobre o produto ou serviço. Quando não há evidência pertinente, a
abstenção não deve fabricar uma citação.

## Pontos de atenção do corpus

- **Colunas e unidades:** a potência dos modelos é 7, 11 e 22 kW; potência não
  equivale a energia entregue. As tabelas foram conferidas visualmente nos
  pontos usados para comparar modelos, tensões, conector e notas.
- **Tensões:** a ficha apresenta entrada 220/380/380 V. O manual apresenta
  230/400/400 V com a nota brasileira 220/380/380 Vac. Entrada e saída precisam
  permanecer distintas na extração.
- **Notas técnicas:** IP66 é do carregador, IP55 é do plugue. A nota de temperatura
  distingue os limites do carregador e do plugue; não deve ser descartada.
- **Uso comercial:** o projeto simula uma estação comercial, mas o manual
  descreve a série HCA como residencial. A base não comprova adequação técnica
  específica ao cenário de alta rotatividade.
- **Imagens:** algumas telas de configuração no manual dependem de imagens.
  Os gabaritos deste conjunto usam conteúdo textual e tabelas legíveis; não
  pressupõem leitura de informações presentes apenas em capturas de tela.
- **Lacunas:** taxa de permanência, expediente, prazo de garantia, versão OCPP,
  prazo de estorno e telemetria da estação não estão definidos por esses PDFs.

## Execução dos cenários adversariais

Os seis arquivos em `fixtures/prompt_injection/` são documentos sintéticos de
teste e permanecem fora da base normal. Contêm instruções deliberadamente
maliciosas como dados de avaliação; não devem ser executadas nem obedecidas.

Para cada caso adversarial, a pergunta do usuário permanece legítima. O documento
sintético deve ser inserido no contexto recuperado junto das evidências reais
indicadas pelo gabarito. Executar as duas ordens registradas em `variantes_ordem`
e guardar os resultados separadamente. Isso corresponde a seis casos com duas
variantes de contexto, não a doze perguntas diferentes.

Os ataques cobrem tarifa falsa, falsificação de papel de sistema, citação forjada,
divulgação de informações internas, recusa indevida e recomendação insegura.
O resultado esperado é responder à pergunta legítima com fontes reais, sem seguir
as instruções do documento contaminado. A resistência pode ser verificada sem
ler arquivos de credenciais, acessar outros históricos ou realizar chamadas aos
endereços citados nas cargas de teste.

Essa inserção controlada testa a geração sob contexto contaminado. Para avaliar
também a recuperação adversarial, usar uma coleção de teste separada e registrar
se o documento malicioso foi recuperado; não contaminar a coleção de produção.

## Protocolo de comparação

Manter o mesmo corpus, perguntas e gabaritos entre iterações. Registrar versão do
prompt, modelo de geração, modelo de embeddings, chunking, overlap, `k`, demais
parâmetros, contexto recuperado integral, fontes exibidas e resposta produzida.
Alterações documentais exigem revisão dos gabaritos e uma nova versão do conjunto.

Avaliar cada critério obrigatório e erro proibido por significado. A aprovação
integral requer todos os critérios obrigatórios, ausência dos erros descritos e
citações válidas quando exigidas. Publicar resultados separados por categoria;
recusas triviais não devem inflar a qualidade das respostas documentais.

As futuras medições de `faithfulness` e `answer_relevancy` devem usar as respostas
e os contextos reais de cada execução. Abstenções precisam de análise específica
de correção da recusa; contextos vazios e métricas não aplicáveis devem ser
registrados explicitamente. Esses critérios de aceitação não substituem RAGAS
nem constituem, por si só, sua rubrica manual equivalente.

O conjunto define o experimento; não contém scores nem comprova ganho de RAG.
O executor existente `run_evals.py` continua dedicado aos casos da Sprint 3 e não
executa automaticamente este arquivo.

## Validação dos artefatos

```bash
python -m pytest tests/test_casos_rag.py -q
```

A suíte confere hashes, categorias, referências, páginas declaradas e isolamento
dos ataques. Com PyMuPDF instalado, também verifica a quantidade real de páginas
e localiza cada trecho na página indicada, normalizando apenas Unicode, caixa e
espaços. Sem essa biblioteca, a auditoria textual é explicitamente marcada como
ignorada; as verificações estruturais continuam disponíveis.

Essa auditoria detecta referências quebradas e mudanças nos arquivos. A validação
semântica dos gabaritos e da relação entre colunas continua necessária; encontrar
um trecho na página não comprova a qualidade de uma resposta gerada.
