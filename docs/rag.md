# Recuperação documental e integração ao assistente

O pipeline documental do ChargeGrid transforma PDFs em trechos com metadados,
gera embeddings com `nomic-embed-text` no Ollama e mantém uma coleção ChromaDB
persistente. O assistente combina essa recuperação com os indicadores calculados
em Python e responde a consultas documentais, operacionais e mistas na CLI e no
chat Gradio.

## Instalação

Na raiz do repositório, com o ambiente virtual ativo:

```bash
python -m pip install -e ".[dev]"
ollama pull nomic-embed-text
ollama list
```

O servidor Ollama precisa estar disponível. Quando não for iniciado pelo serviço
local, execute `ollama serve` em outro terminal. O modelo de embeddings é distinto
do modelo Gemma utilizado para geração de respostas.

Chroma funciona incorporado ao processo Python, com persistência em disco.
Este modo não requer conta, credenciais, Docker nem servidor Chroma separado.

## Configuração

Os valores abaixo têm padrões no código e estão registrados em `.env.example`.
Variáveis exportadas no ambiente têm precedência sobre o `.env`. Caminhos relativos
são resolvidos em relação à raiz do projeto, independentemente do diretório atual.

```dotenv
RAG_KNOWLEDGE_BASE_PATH=data/knowledge_base
RAG_EMBEDDING_BASE_URL=http://localhost:11434
RAG_EMBEDDING_MODEL=nomic-embed-text
RAG_EMBEDDING_TIMEOUT=120
RAG_CHROMA_PATH=data/chroma
RAG_COLLECTION_NAME=chargegrid_knowledge_v2
RAG_CHUNK_SIZE=600
RAG_CHUNK_OVERLAP=200
RAG_TOP_K=8
RAG_BATCH_SIZE=16
RAG_PROMPT_PATH=prompts/rag_v2.md
```

`RAG_CHUNK_SIZE` e `RAG_CHUNK_OVERLAP` são medidos em caracteres, não tokens.
Os padrões atuais adotam a recomendação medida: 600 caracteres, overlap de 200
e oito trechos. A coleção `chargegrid_knowledge_v2` separa esse índice do baseline
anterior de 1.200 caracteres. Um `.env` existente tem precedência sobre esses
padrões e deve utilizar os mesmos valores para adotar a configuração recomendada.
`RAG_TOP_K` determina quantos trechos a busca retorna. O tamanho do lote controla
quantos trechos novos são enviados ao gerador de embeddings por operação.

## Base e extração

Os PDFs ficam em `data/knowledge_base/`, incluindo subdiretórios. O arquivo
`catalogo.json` associa os documentos conhecidos a identificadores, versões e
natureza do conteúdo. Os identificadores são compatíveis com o conjunto de
avaliação documental. PDFs adicionais podem ser indexados sem catálogo; recebem
identificador derivado do caminho e classificação não declarada.

O pipeline utiliza `PyMuPDFLoader` por página e detecção geométrica de tabelas
com PyMuPDF. Para a ficha HCA sem grade vertical, existe detecção complementar
baseada no alinhamento dos três cabeçalhos de modelos. A representação Markdown
substitui a cópia achatada do texto da tabela, evitando indexar as duas versões.

Texto comum é dividido com `RecursiveCharacterTextSplitter`. Tabelas são divididas
por linhas completas, repetindo o cabeçalho e as notas técnicas identificadas na
mesma página. Uma linha extensa pode exceder o tamanho alvo para preservar a
associação dos valores; essa ocorrência é contabilizada no manifesto. O overlap
se aplica aos blocos de texto, não às linhas de tabela.

Cada trecho conserva arquivo, identificador documental, SHA-256 do PDF, página PDF
iniciada em 1, índice de página iniciado em zero, versão, natureza, tipo de conteúdo
e identificador determinístico do chunk. A página PDF não é a numeração impressa.

Imagens não são interpretadas e OCR não é executado automaticamente. PDFs sem
texto extraível interrompem a ingestão; páginas vazias são reportadas. Tabelas com
células mescladas, cabeçalhos desalinhados ou continuação em outra página exigem
inspeção de fidelidade. O extrator não corrige inconsistências do documento nem
infere cabeçalhos ausentes entre páginas. A recuperação desse conteúdo deve ser
avaliada antes de utilizá-lo como evidência de uma resposta.

## Indexação e sincronização

```bash
chargegrid-rag indexar
chargegrid-rag status
```

Alternativa equivalente:

```bash
python -m rag indexar
python -m rag status
```

Na primeira execução, o código cria a coleção e o banco em `data/chroma/`. Essa
pasta está ignorada pelo Git. O relatório JSON registra fontes, páginas, chunks,
versões das bibliotecas e digest do modelo de embeddings.

Executar novamente com os mesmos arquivos e configuração reutiliza os IDs
existentes sem gerar seus embeddings outra vez. Alterar, adicionar ou remover PDFs
sincroniza a coleção: primeiro grava os novos trechos e depois remove os obsoletos.
Um diretório sem PDFs não apaga o índice existente.

A indexação usa bloqueio por coleção. Durante a sincronização, consultas são
recusadas; uma falha deixa o manifesto em `indexando`, impedindo uso de uma coleção
parcial. A mesma indexação pode ser repetida para concluir a sincronização.

Mudanças de modelo/digest, tamanho de chunk, overlap ou versão do extrator exigem
uma nova coleção. Por exemplo, configure `RAG_COLLECTION_NAME=chargegrid_knowledge_v3`
e execute a indexação. Isso preserva a anterior e evita misturar vetores ou
configurações incompatíveis. Alterar apenas `RAG_TOP_K`, timeout ou tamanho do lote
não exige nova coleção. Alterar o prompt de geração também não exige reindexação.

## Busca semântica

```bash
chargegrid-rag buscar "Quais são as tarifas Urgente e Econômico?"
chargegrid-rag buscar "O grau IP66 também vale para o plugue?"
```

O resultado JSON apresenta os trechos e seus metadados de origem. A consulta utiliza
o mesmo modelo e digest de embeddings da indexação, com prefixo `search_query:`;
os documentos utilizam `search_document:`. A similaridade é calculada em espaço
cosseno.

Uma busca retorna os vizinhos mais próximos, mesmo quando eles não respondem à
pergunta. A presença de resultados não comprova evidência suficiente. A geração
integrada deve reconhecer quando os trechos não sustentam a resposta.

## Integração ao assistente — fase 3

O `AssistenteChargeGrid` seleciona as fontes por regras determinísticas:

| Consulta | Contexto fornecido ao modelo | Exemplo |
|---|---|---|
| Operacional | JSON validado e indicadores calculados em Python | Qual foi o pico de demanda? |
| Documental | Trechos recuperados dos PDFs com metadados | Quais são as tarifas Urgente e Econômico? |
| Mista | Indicadores e trechos dos PDFs | Qual foi o pico e como o controle dinâmico de carga pode ajudar? |

O prompt versionado [`rag_v2.md`](../prompts/rag_v2.md) é usado na chain LCEL
ativa. `RAG_PROMPT_PATH` seleciona esse arquivo; `CHARGEGRID_PROMPT_PATH` permanece
destinado ao fluxo legado de comparação dos prompts operacionais v1/v2.
O histórico das versões RAG está em [`RAG_VERSIONS.md`](../prompts/RAG_VERSIONS.md).

Consultas operacionais preservam o contrato `ConsultaRecarga` e identificam a
origem dos indicadores. Consultas documentais e mistas utilizam um contrato
interno com resposta, insuficiência, limitações e trechos de apoio. A aplicação
confere se cada identificador pertence ao contexto da consulta e se o trecho
citado existe na fonte, tolerando diferenças de espaços e quebras de linha.
Arquivo e página são obtidos dos metadados recuperados. Uma resposta mista
completa exige apoios dos dois tipos de fonte.

Sem apoios válidos, o assistente informa insuficiência; referências inexistentes
ou trechos inventados são rejeitados. Falhas de recuperação têm um código de erro
próprio e não são apresentadas como ausência de conhecimento. Perguntas puramente
operacionais dispensam acesso ao Chroma.

A memória permanece isolada por sessão e limitada por tokens. Somente perguntas
anteriores do usuário ajudam a interpretar continuações; respostas anteriores
do modelo não entram como evidência factual. Os guardrails continuam sendo
executados antes da recuperação e da geração.

O roteamento por palavras-chave pode exigir ajustes para formulações novas.
A conferência de trechos comprova sua presença na fonte, mas não verifica
automaticamente se todas as afirmações da resposta decorrem deles. A avaliação
semântica, a bateria adversarial completa e as métricas RAGAS permanecem nas
etapas de segurança e avaliação. O contrato público e a apresentação estruturada
das citações são descritos na seção da fase 4 abaixo.

### Validação principal — 21/10/2026

- 23 novos testes automatizados: seleção de fontes, respostas mistas, ausência
  de evidência, referências inválidas, falha de recuperação e memória isolada.
- Regressão completa: 144 testes aprovados; Ruff e verificação de formatação
  aprovados. Três avisos de descontinuação de dependências não impediram os testes.
- 7/7 cenários funcionais com Ollama e Chroma reais: tarifas, continuação com
  estimativa de energia, pico operacional, consulta mista, prazo sem evidência,
  modelo ausente e continuação em outra sessão.
- Valores conferidos: R$ 1,89/kWh e R$ 1,05/kWh, R$ 21,00 para 20 kWh no
  Econômico e pico de 78,4 kW. A resposta mista citou o JSON operacional e o
  manual, página PDF 49.

O relatório [`fase3_integracao.json`](../evals/fase3_integracao.json) registra
configuração, hash do prompt, contextos recuperados, saídas e verificações.
Essa execução funcional não mede a qualidade de todo o conjunto documental.

```bash
python -m pytest tests/test_integracao_rag.py -q
python evals/validar_integracao.py
```

O segundo comando chama o modelo configurado, requer Ollama e índice disponíveis
e atualiza o relatório. Não é necessário criar outro banco nem reindexar para
ativar a integração sobre a coleção já preparada.

## Citações estruturadas e interface — fase 4

As respostas documentais e mistas expõem `RespostaDocumental`, um contrato
Pydantic independente da análise operacional. Ele contém `resposta`,
`insuficiente`, `citacoes` e `limitacoes`. Cada `CitacaoFonte` inclui:

| Campo | Origem e significado |
|---|---|
| `fonte_id` | Identificador conferido contra o contexto desta consulta |
| `tipo` | Fonte `documental` ou `operacional` |
| `arquivo` | Nome/caminho obtido pela aplicação, sem aceitar nomes inventados pelo modelo |
| `pagina_pdf` | Página do PDF a partir de 1; ausente para fontes operacionais |
| `secao` | Seção, quando disponível nos metadados, ou identificação do resumo operacional |
| `trecho` | Texto de apoio conferido contra a fonte fornecida |

O envelope `RespostaAssistente` expõe `documental` e `citacoes`. Os campos
`mensagem`, `dados` e `fontes` são preservados para os consumidores existentes.
Uma resposta documental completa exige citações; uma resposta parcial pode
apresentar o que foi encontrado e explicar o que falta. As consultas operacionais
também expõem uma citação do resumo calculado, com origem no JSON validado.

O Gradio exibe as fontes numeradas, com arquivo, página/seção e trecho em bloco
de citação. Os trechos e metadados são escapados para apresentação como texto,
sem ativar HTML ou links contidos no documento. Respostas documentais dispensam
campos de risco e recomendação; respostas parciais têm identificação própria.
Recusas sem apoio não exibem fontes artificiais.

Execute a interface a partir da raiz com `python -m app.main`.
O [README da aplicação](../app/README.md) detalha a preparação e as alternativas
`python app/main.py` e `chargegrid-web`. A interface existente é reutilizada.
Não há novas dependências, variáveis obrigatórias ou necessidade de reindexação.

### Validação principal — 22/10/2026

- Suíte completa: **157 testes aprovados**, incluindo 13 novos casos para o
  contrato público, localização das fontes, recusa de referências forjadas,
  apresentação de respostas parciais e ponto de entrada. Ruff e formatação
  aprovados; permanecem três avisos de descontinuação das dependências.
- Validação em Chromium/Playwright com Ollama e Chroma reais: tarifas, consulta
  mista, ausência de evidência, nova sessão, recusa de intervenção elétrica e
  navegação do dashboard. As citações observadas sustentaram os valores
  apresentados: tarifas na página PDF 1 e controle dinâmico na página PDF 49,
  combinado com pico operacional de 78,4 kW do JSON.
- Desktop de 1365×1000 e celular de 390×844: conteúdo e controles disponíveis,
  sem transbordamento horizontal ou erros de console. O chat mantém rolagem
  própria para respostas longas. Playwright foi usado porque o plugin Browser
  não estava disponível nesta sessão.

```bash
python -m pytest -q
ruff check src tests app evals/run_evals.py evals/validar_integracao.py
ruff format --check src tests app evals/run_evals.py evals/validar_integracao.py
```

A conferência estrutural verifica origem e presença dos trechos, não a relação
semântica de todas as afirmações em toda a base. A inspeção funcional acima é
restrita aos cenários testados; a avaliação ampla permanece nas fases 5 e 6.

## Diagnóstico

```bash
chargegrid-rag --debug indexar
chargegrid-rag --debug buscar "Qual é o conector?"
```

O modo de diagnóstico apresenta o traceback. `status` inspeciona o manifesto local
sem consultar o Ollama; ele não comprova disponibilidade do modelo nem relevância
da recuperação. Um erro de modelo ausente requer conferir o endereço do Ollama e
o nome instalado. Uma coleção sem manifesto ChargeGrid não é sobrescrita.

## Validação da fase 2 — 20/10/2026

Os testes principais estão em `tests/test_rag.py`. A execução real utilizou os
três PDFs do catálogo, Ollama com `nomic-embed-text` e Chroma persistente.
Os resultados desta seção registram o baseline de 1.200 caracteres, overlap de
200 e `k=4`, anterior à adoção dos novos padrões.

| Verificação principal | Resultado |
|---|---|
| Regressão geral | 121 testes passaram, incluindo os 12 testes principais da fase 2; lint e formatação aprovados. |
| Ingestão real | 3 PDFs, 75 páginas e 161 chunks persistidos. |
| Consulta em novo processo | Fontes e trechos recuperados após o término do processo de indexação. |
| Reindexação real | 161 chunks reutilizados; zero novos, removidos ou duplicados; hash dos IDs preservado. |
| Fidelidade da extração | As 39 âncoras dos casos respondíveis permanecem nas páginas extraídas; modelos, potências e notas da ficha técnica são preservados nos testes. |
| Sincronização e recuperação | Adição, alteração e remoção de PDFs, falha parcial com retomada, coleção incompleta e bloqueio de acesso simultâneo passaram em base temporária. |
| Saída da CLI | Avisos do leitor de PDF são enviados a stderr, preservando o JSON em stdout. |

Os testes em base temporária usam Chroma real e embeddings determinísticos de
teste para isolar falhas e verificar sincronização sem depender da rede. Eles não
medem relevância semântica. As verificações de ingestão e recuperação sobre os PDFs
do catálogo utilizam o modelo real do Ollama.

A auditoria das 24 perguntas respondíveis encontrou:

| Indicador de localização | `k=4` (baseline anterior) | `k=8` (comparação) |
|---|---:|---:|
| Casos com ao menos uma página esperada | 14/24 | 21/24 |
| Casos com todas as páginas esperadas | 14/24 | 20/24 |
| Casos com todos os documentos exigidos | 20/24 | 22/24 |
| Âncoras textuais localizadas | 21/39 | 27/39 |

Esses números medem a localização das páginas e dos trechos indicados pelo
gabarito. Uma página recuperada pode não conter o trecho necessário no chunk
selecionado; uma página diferente pode conter informação equivalente. Portanto,
os indicadores não representam aprovação de respostas nem scores RAGAS.

A extração preservou as âncoras, mas a recuperação ainda perde evidências com o
contexto limitado. Aumentar `k` ampliou a cobertura, sem eliminar as perdas e sem
garantir contexto suficiente. Durante essa medição, a configuração e o `.env` foram preservados.
Respostas geradas, recusas e resistência a injection documental não foram avaliadas
nesta etapa.

O resumo das verificações está em `evals/fase2_validacao.json`; os resultados por
pergunta do baseline anterior estão em `evals/fase2_recuperacao.json`.
Para executar as verificações com a configuração atual (os números acima
permanecem como registro do baseline anterior):

```bash
python -m pytest tests/test_rag.py -q
python evals/validar_recuperacao.py
python evals/validar_recuperacao.py --k 8 --saida /tmp/recuperacao-k8.json
```

## Comparação de tamanhos de chunk — 20/10/2026

Foram comparados quatro tamanhos alvo em caracteres, mantendo overlap de 200,
os três PDFs, as 24 perguntas e o mesmo modelo/digest de embeddings. Cada tamanho
foi avaliado com `k=4` e `k=8`. Os vetores reais das perguntas foram calculados uma
vez e reutilizados para manter a comparação consistente.

| Tamanho alvo | Âncoras com `k=4` | Âncoras com `k=8` | Casos com todas as âncoras, `k=8` | Contexto médio com `k=8` (caracteres) |
|---:|---:|---:|---:|---:|
| 600 | 26/39 | **32/39** | **18/24** | **3.808** |
| 900 | 22/39 | 25/39 | 14/24 | 5.170 |
| 1.200 | 21/39 | 27/39 | 16/24 | 5.621 |
| 1.800 | 21/39 | 27/39 | 14/24 | 6.513 |

Entre as configurações testadas, **600 caracteres, overlap de 200 e `k=8`**
apresentou a melhor localização de âncoras e menor volume médio de contexto que
1.200 com `k=8`: cinco âncoras adicionais e aproximadamente 32% menos caracteres.
O contexto corresponde à soma dos textos recuperados, sem incluir o prompt e os
metadados de serialização; não é uma contagem de tokens.

O resultado é exploratório: existem perdas e regressões por pergunta, e algumas
fontes podem ter conteúdo equivalente em páginas não previstas pelo gabarito.
A configuração de 600 não recuperou todas as âncoras em seis casos. Esses números
não comprovam qualidade de respostas nem substituem avaliação RAGAS.

Durante a primeira comparação, o `.env`, os padrões do código e a coleção principal
foram preservados. As coleções
experimentais ficam em `data/chroma/experimentos_chunks/`, ignoradas pelo Git.
O relatório com resultados por configuração e pergunta está em
[`evals/comparacao_chunks.json`](../evals/comparacao_chunks.json).

Para reproduzir a comparação:

```bash
python evals/comparar_chunks.py
```

## Equilíbrio entre tamanho, overlap e contexto

Uma segunda comparação avaliou 18 combinações: tamanhos de 400, 600 e 800
caracteres, overlaps de 100 e 200, e `k` de 4, 6 e 8. Foram mantidos os mesmos
PDFs, as 24 perguntas e o modelo de embeddings. A seleção priorizou casos com
todas as âncoras, quantidade total de âncoras e menor volume de texto, nessa ordem.

| Perfil | Tamanho | Overlap | `k` | Âncoras | Casos com todas as âncoras | Contexto médio / máximo (caracteres) |
|---|---:|---:|---:|---:|---:|---:|
| Recomendado | 600 | 200 | 8 | 32/39 | 18/24 | 3.808 / 4.317 |
| Mais enxuto, com perda de cobertura | 600 | 200 | 6 | 30/39 | 17/24 | 2.910 / 3.293 |

**600 caracteres, overlap de 200 e oito trechos** manteve o melhor equilíbrio
entre as opções testadas. Diminuir os chunks para 400 reduziu o contexto, mas
fragmentou mais as evidências; aumentar para 800 trouxe mais texto sem melhorar
a cobertura. Para tamanho 600 com `k=8`, overlap de 100 encontrou 28 âncoras e
completou 16 casos, abaixo das 32 âncoras e 18 casos com overlap de 200.

O máximo observado de 4.317 caracteres não é um limite imposto pelo retriever:
ele depende dos documentos, das perguntas e das linhas de tabela preservadas.
Os valores medem apenas os textos recuperados, sem prompt, memória ou metadados.
As medidas de localização não garantem respostas corretas nem ausência de
alucinação. A geração deve se limitar às fontes citadas e declarar insuficiência
quando o contexto não sustentar uma conclusão.

Essa comparação não alterou o `.env` nem a coleção principal. Posteriormente,
os padrões do código e o `.env.example` foram alinhados à recomendação. A coleção
`chargegrid_knowledge_v2` foi indexada com os novos parâmetros: 3 PDFs, 75 páginas
e 254 chunks. A busca em novo processo retornou oito trechos e localizou as duas
tarifas na fonte correta. O hash dos IDs e o digest do modelo correspondem ao
experimento recomendado. O registro está em `evals/fase2_validacao.json`.
O relatório
completo está em
[`evals/comparacao_chunk_overlap.json`](../evals/comparacao_chunk_overlap.json).

```bash
python evals/comparar_chunks.py --tamanhos 400 600 800 --overlaps 100 200 --ks 4 6 8 --saida evals/comparacao_chunk_overlap.json
```

## Referências técnicas

- [Chroma e persistência com LangChain](https://docs.langchain.com/oss/python/integrations/vectorstores/chroma)
- [OllamaEmbeddings com LangChain](https://docs.langchain.com/oss/python/integrations/embeddings/ollama)
- [Prefixos de recuperação do Nomic](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5)
