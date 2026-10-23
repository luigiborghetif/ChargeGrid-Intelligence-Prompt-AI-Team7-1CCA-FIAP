"""Gera relatórios públicos da Sprint 4 a partir das notas auditáveis salvas."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PASTA = ROOT / "evals/sprint4"


def formatar_ragas(metrica):
    valor = metrica["media"]
    return f"{valor:.3f} (n={metrica['n']})" if valor is not None else "N/A (n=0)"


def secao_ragas(ragas):
    texto = """## Avaliação automática com RAGAS

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
"""
    for nome, e in ragas["experimentos"].items():
        m = e["metricas"]
        texto += f"| {nome} | {formatar_ragas(m['faithfulness'])} | {formatar_ragas(m['answer_relevancy'])} | {m['faithfulness']['erros_avaliador']}/{m['answer_relevancy']['erros_avaliador']} |\n"
    texto += "\n### Comparação nos casos válidos em comum\n\n"
    for nome, comparacao in ragas["comparacoes_pareadas"].items():
        texto += f"**{nome}** (delta do segundo em relação ao primeiro):\n\n"
        for metrica, valores in comparacao.items():
            d = valores["delta_segundo_menos_primeiro"]
            delta = f"{d:+.4f}" if d is not None else "N/A"
            texto += f"- {metrica}: delta {delta}, n={valores['n']}.\n"
        texto += "\n"
    texto += """Os registros de entrada, scores, afirmações/vereditos e perguntas reconstruídas
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

"""
    return texto


def main():
    scores = json.loads((PASTA / "scores.json").read_text())
    experimentos = scores["experimentos"]
    arquivo_ragas = PASTA / "ragas/scores.json"
    ragas = json.loads(arquivo_ragas.read_text()) if arquivo_ragas.exists() else None
    if ragas:
        for nome in experimentos:
            bruto = json.loads((PASTA / f"ragas/{nome}.json").read_text())
            if len(bruto["casos"]) != 12 or any(
                len(c["metricas"]) != 2 for c in bruto["casos"]
            ):
                raise ValueError(
                    "Avaliação RAGAS incompleta; não publicar como concluída"
                )
    nomes = {
        "baseline_gemma": "A · Gemma · v2 · semântica",
        "hibrido_gemma": "B · Gemma · v3 · híbrida",
        "hibrido_gptoss": "B · GPT-OSS · v3 · híbrida",
    }
    tabela = (
        "| Execução | Faithfulness (n aplicável) | Answer relevancy (12 casos) | "
        "Integral ao gabarito | Falhas de saída | Latência média |\n"
        "|---|---:|---:|---:|---:|---:|\n"
    )
    for nome, e in experimentos.items():
        g = e["geral"]
        tabela += (
            f"| {nomes[nome]} | {g['faithfulness']:.3f} ({g['faithfulness_n']}/12) | "
            f"{g['answer_relevancy']:.3f} | {g['respostas_integrais_gabarito']}/12 | "
            f"{g['falhas_saida']} | {e['latencia_media_segundos']:.2f} s |\n"
        )
    metodo = """## Protocolo e interpretação

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
"""
    parametros = """## Ambiente e parâmetros comuns

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
"""
    decisao = """## Resultado da rubrica e decisão de configuração

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
"""
    achados = """## Problemas encontrados e tratamento

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
"""
    reproducao = """## Reprodução e rastreabilidade

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
"""
    rag = "# Relatório RAG — Sprint 4\n\n" + metodo + "\n" + parametros
    if ragas:
        rag += "\n" + secao_ragas(ragas)
    rag += "\n## Duas iterações — rubrica complementar\n\n" + tabela
    rag += """
A: prompts `planejador_v2.md` e `resposta_tools_v2.md`, recuperação semântica.
B: prompts v3 preservam termos específicos e pedem cobertura dos critérios;
busca híbrida BM25 (k1=1,5; b=0,75), reserva até duas posições lexicais e completa
por fusão recíproca de rankings (constante 60), deduplicando e limitando a k=8.
Usa os mesmos chunks; não consulta gabaritos ou IDs de resposta. A implementação
lê o corpus para calcular BM25 por pergunta, adequada à base pequena, com custo
linear que precisa ser revisto para crescimento. Não é reranking por modelo.
Prompt e recuperação mudam juntos: o experimento não isola seus efeitos.
"""
    rag += "\n" + decisao + "\n" + achados + "\n" + reproducao
    (ROOT / "docs/relatorio_rag.md").write_text(rag)
    modelos = "# Comparação de modelos — Sprint 4\n\n"
    modelos += """Gemma `gemma4:31b-cloud` e GPT-OSS `gpt-oss:120b-cloud`, ambos via
Ollama Cloud. A alternativa GPT-OSS foi definida antes da execução após
indisponibilidade do Qwen, registrada em `hibrido_qwen.json` e
`adendo_modelo.json`. Qwen não recebeu nota de qualidade: nenhum caso concluído.
A tentativa local inicialmente bloqueada da baseline também está preservada
em `falhas_infraestrutura`, sem ser contada como resposta do modelo.
Dois modelos no mesmo provedor **não constituem comparação multi-provider**.
\n"""
    modelos += parametros
    if ragas:
        modelos += "\n" + secao_ragas(ragas)
    modelos += "\n## Resultados da rubrica complementar\n\n" + tabela
    modelos += """
Na comparação B com as mesmas configurações, Gemma apresentou relevância 0,590
e faithfulness 1,000 (11 casos aplicáveis); GPT-OSS apresentou 0,535 e 0,902
(11 casos aplicáveis). Ambos tiveram uma resposta retida por evidência inválida.
GPT-OSS cobriu mais aspectos da pergunta de fumaça, mas perdeu condições de
segurança e completou uma informação ausente no contexto do controle dinâmico.
Os limites semânticos justificam manter Gemma nesta entrega, sem concluir que
um modelo é superior em qualquer tarefa ou ambiente.
\n"""
    modelos += decisao + "\n" + metodo + "\n" + reproducao
    modelos += "\nA comparação operacional anterior permanece em [relatorio_modelos_sprint3.md](relatorio_modelos_sprint3.md); suas notas não foram reutilizadas como avaliação RAG.\n"
    (ROOT / "docs/relatorio_modelos.md").write_text(modelos)
    gerar_pdf(experimentos, ragas)


def gerar_pdf(experimentos, ragas=None):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    estilos = getSampleStyleSheet()
    corpo = ParagraphStyle(
        "Corpo", parent=estilos["BodyText"], fontSize=10, leading=14, spaceAfter=10
    )
    pequeno = ParagraphStyle("Pequeno", parent=corpo, fontSize=9, leading=12)
    titulo = ParagraphStyle(
        "Titulo", parent=estilos["Heading1"], fontSize=19, leading=23, spaceAfter=16
    )
    subtitulo = estilos["Heading2"]
    elementos = []
    paginas_md = []

    def p(texto):
        elementos.append(Paragraph(escape(texto), corpo))
        paginas_md.append(texto + "\n")

    def h(texto):
        elementos.append(Paragraph(escape(texto), titulo))
        paginas_md.append("## " + texto + "\n")

    def tabela(linhas, larguras):
        t = Table(
            [[Paragraph(escape(str(x)), pequeno) for x in linha] for linha in linhas],
            colWidths=larguras,
            hAlign="LEFT",
        )
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e4edf4")),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#a3b2bd")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("PADDING", (0, 0), (-1, -1), 7),
                ]
            )
        )
        elementos.extend([t, Spacer(1, 12)])
        paginas_md.extend(
            ["| " + " | ".join(map(str, linha)) + " |" for linha in linhas[:1]]
            + ["|" + "---|" * len(linhas[0])]
            + ["| " + " | ".join(map(str, linha)) + " |" for linha in linhas[1:]]
            + [""]
        )

    def pagina():
        elementos.append(PageBreak())
        paginas_md.append("\n---\n")

    h("ChargeGrid Intelligence | Sprint 4")
    p("Relatório técnico de evolução · 23 de outubro de 2026")
    p(
        "O projeto evolui o assistente gerencial de recarga para consultar dados operacionais e PDFs com fontes verificáveis. O planejamento usa LCEL e contratos Pydantic; os cálculos continuam em Python. A entrega inclui avaliação rastreável e registra limitações de recuperação e completude."
    )
    tabela(
        [
            ["Dimensão", "Sprints 1/2 (versão original)", "Sprint 04 (RAG avaliado)"],
            [
                "Evidências",
                "JSON da operação simulada",
                "JSON e 3 PDFs com origem e página",
            ],
            [
                "Consulta",
                "Análise operacional com prompt",
                "Plano tipado; até 4 ferramentas",
            ],
            ["Recuperação", "Sem índice documental", "Chroma persistente e Nomic"],
            [
                "Resposta",
                "Schema operacional",
                "Resposta documental/mista com apoios validados",
            ],
            [
                "Segurança",
                "Guardrails de entrada e saída",
                "Triagem documental e integridade de fontes",
            ],
            ["Avaliação RAG", "Não medida", "12 casos fixos; 2 iterações e 2 modelos"],
            [
                "Scores por iteração",
                "Não medidos",
                (
                    "RAGAS Gemma A: F="
                    + formatar_ragas(
                        ragas["experimentos"]["baseline_gemma"]["metricas"][
                            "faithfulness"
                        ]
                    )
                    + ", R="
                    + formatar_ragas(
                        ragas["experimentos"]["baseline_gemma"]["metricas"][
                            "answer_relevancy"
                        ]
                    )
                    + "; B: F="
                    + formatar_ragas(
                        ragas["experimentos"]["hibrido_gemma"]["metricas"][
                            "faithfulness"
                        ]
                    )
                    + ", R="
                    + formatar_ragas(
                        ragas["experimentos"]["hibrido_gemma"]["metricas"][
                            "answer_relevancy"
                        ]
                    )
                )
                if ragas
                else "Rubrica Gemma A: F=1,000 (n=10), R=0,569; B: F=1,000 (n=11), R=0,590",
            ],
            [
                "Qualidade do contexto",
                "Sem avaliação documental",
                "Proxy: âncoras recuperadas A 11/18; B 12/18; ainda há lacunas",
            ],
            [
                "Citação de fonte",
                "Sem citação documental estruturada",
                "Arquivo, página e trecho; visível em A 7/12 e B 8/12 casos",
            ],
        ],
        [3.0 * cm, 6.0 * cm, 7.3 * cm],
    )
    p(
        "O fluxo operacional anterior permanece disponível. As métricas antigas de classificação não são tratadas como faithfulness ou relevância RAG. Os dados comerciais e as regras WeCharge são simulados e não representam políticas da GoodWe."
    )
    pagina()
    h("Arquitetura e evidências")
    p(
        "Fluxo: pergunta → guardrails e histórico da sessão → planejador LCEL → plano Pydantic → executor Python → fontes documentais/operacionais → geração estruturada → conferência de citações e segurança → CLI ou Gradio."
    )
    p(
        "Ingestão: PyMuPDFLoader → RecursiveCharacterTextSplitter → OllamaEmbeddings → Chroma local persistente. Base de 3 PDFs, 75 páginas e 254 chunks, com 600 caracteres, overlap de 200 e top-k 8. Identificadores, arquivo e página acompanham os trechos; reindexação evita duplicação."
    )
    p(
        "As ferramentas consultam a operação, calculam indicadores, buscam documentos e estimam custos em Python. O histórico da sessão ajuda a interpretar a pergunta, mas respostas anteriores não viram evidência. Dados agregados não permitem descobrir valores de sessões individuais inexistentes na base."
    )
    p(
        "Documentos são dados sem autoridade sobre o sistema. Conteúdo e metadados passam por triagem; identificadores reservados ou conflitantes são rejeitados. As citações precisam existir no contexto e preservar trechos literais. A proteção não garante detectar toda omissão ou conclusão semanticamente indevida."
    )
    p(
        "Iteração A: busca semântica e prompts v2. Iteração B: prompts v3 preservam termos específicos; BM25 com k1=1,5 e b=0,75 reserva até duas posições lexicais e completa por fusão recíproca de rankings (constante 60), mantendo o limite total de oito chunks. Não usa gabarito para selecionar evidências."
    )
    p(
        "O BM25 recalcula estatísticas do pequeno corpus por pergunta. O custo linear e a ausência de reconstrução de tabelas complexas são limitações para bases maiores. A extração não usa imagens e pode fragmentar relações entre linhas e colunas."
    )
    pagina()
    h("Avaliação comparável")
    p(
        "Amostra pré-fixada de desenvolvimento: 6 perguntas respondíveis, 3 sem evidência completa e 3 ataques documentais, retirada do conjunto de 38. Uma execução por caso/configuração, sessão nova, mesmo corpus e gabarito; fixtures adversariais apenas em memória. Não é teste cego nem avaliação dos 38 casos completos."
    )
    p(
        "Geração cloud: Gemma 4 31B e GPT-OSS 120B via Ollama. Temperature 0; top_p 0,9; limite de saída 1200 tokens; k=8; memória de 4000 tokens. Modelos B usam os mesmos prompts e busca, porém seus planejadores podem recuperar contextos distintos. Qwen ficou indisponível e foi substituído antes da rodada alternativa; não recebeu nota."
    )
    p(
        "RAGAS 0.4.3 avalia os registros salvos com Gemma como juiz (temperatura 0, top_p 0,9, limite 4096 tokens) e Nomic para relevância (strictness 3). Usa o contexto pós-triagem efetivamente enviado à geração. Ambiente separado, com LangChain Community 0.4.1 para compatibilidade; API da aula marcada como deprecated, sem alterar o aplicativo."
        if ragas
        else "Rubrica por inspeção contextual assistida por IA, com notas justificadas e vínculo SHA-256 por resposta; não é score calculado pelo RAGAS."
    )
    linhas = [
        [
            "Execução",
            "Faithfulness RAGAS" if ragas else "F / rubrica",
            "Relevância RAGAS" if ragas else "R / rubrica",
            "Integral*",
            "Falhas",
        ]
    ]
    for nome, curto in [
        ("baseline_gemma", "A / Gemma"),
        ("hibrido_gemma", "B / Gemma"),
        ("hibrido_gptoss", "B / GPT-OSS"),
    ]:
        g = experimentos[nome]["geral"]
        linhas.append(
            [
                curto,
                formatar_ragas(ragas["experimentos"][nome]["metricas"]["faithfulness"])
                if ragas
                else f"{g['faithfulness']:.3f} (n={g['faithfulness_n']})",
                formatar_ragas(
                    ragas["experimentos"][nome]["metricas"]["answer_relevancy"]
                )
                if ragas
                else f"{g['answer_relevancy']:.3f} (n=12)",
                f"{g['respostas_integrais_gabarito']}/12",
                str(g["falhas_saida"]),
            ]
        )
    tabela(linhas, [3.5 * cm, 4 * cm, 4 * cm, 2.4 * cm, 2.4 * cm])
    if ragas:
        p(
            "Falhas técnicas são não aplicáveis nas duas métricas. Abstenções não recebem faithfulness por ausência de fatos; relevância pode ser zero mesmo numa recusa correta. Erros do juiz não viram zeros. Denominadores diferentes exigem examinar também o pareamento de casos válidos."
        )
        par = ragas["comparacoes_pareadas"]["baseline_gemma__hibrido_gemma"]
        frases = []
        for metrica, dados in par.items():
            delta = dados["delta_segundo_menos_primeiro"]
            frases.append(
                f"{metrica}: delta B-A {delta:+.4f} (n={dados['n']})"
                if delta is not None
                else f"{metrica}: sem par válido"
            )
        p(
            "Comparação pareada Gemma: "
            + "; ".join(frases)
            + ". Os IDs e os rastros do juiz estão em evals/sprint4/ragas. Usar o mesmo modelo para gerar e julgar pode introduzir viés; não há garantia de correção automática."
        )
        p(
            "Em RAG-R19/A, o juiz transformou condições em afirmações de estado ao decompor a resposta, contribuindo para faithfulness=0,500. A nota foi preservada; o ganho observado não comprova melhoria factual geral."
        )
    p(
        "*Rubrica complementar: relevância Gemma 0,569 → 0,590 (+2,08 p.p.); critérios atendidos 21/34 → 22/34. Atendimento integral exige todos os critérios e fontes obrigatórias: 4/12 → 3/12. Esses números não são scores RAGAS. Prompt e busca mudam juntos; uma rodada não isola causas nem produz significância estatística."
    )
    pagina()
    h("Achados, decisão e reprodução")
    for assunto, texto in [
        (
            "Recuperação e fumaça",
            "A baseline recuperou manutenção em lugar da regra protetiva. A candidata recuperou o trecho pertinente, mas Gemma ainda omitiu afastamento e equipe. A melhoria é parcial.",
        ),
        (
            "Apoios inválidos",
            "A resposta sobre IP66/IP55 permaneceu retida por trecho não confirmado. O controle evita exibir uma resposta com citação inválida, mas causa perda de utilidade.",
        ),
        (
            "Extrapolações",
            "GPT-OSS completou uma condição de retomada ausente nos chunks e perdeu uma condição de interrupção segura. As notas penalizam esses casos. Fonte válida não assegura fidelidade de toda a resposta.",
        ),
    ]:
        elementos.append(Paragraph(escape(assunto), subtitulo))
        paginas_md.append("### " + assunto + "\n")
        p(texto)
    p(
        "Decisão: manter Gemma, busca semântica e prompts v2 como padrão. A candidata híbrida/v3 fica optativa, pois o pequeno ganho agregado veio do caso adversarial e o atendimento integral caiu. Os três ataques testados não comandaram a execução; isso não prova imunidade nem aprovação integral das respostas."
    )
    p(
        "Rastreabilidade: evals/sprint4 contém protocolo, adendo, perguntas, contextos, gerações brutas, citações, notas e scores. docs/relatorio_rag.md e docs/relatorio_modelos.md detalham a metodologia. A regressão e as instruções de execução estão no README; a interface permanece Gradio, sem alteração visual nesta etapa."
    )
    p(
        "Reprodução: evals/avaliar_ragas.py executa o juiz em ambiente separado, com versões fixadas em evals/requirements-ragas.txt e lock da rodada. evals/gerar_relatorios_sprint4.py gera os documentos dos scores salvos sem inferência. O procedimento está em docs/avaliacao_ragas.md; o índice e a aplicação em docs/rag.md."
    )

    def rodape(canvas, doc):
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#536775"))
        canvas.drawString(
            1.8 * cm, 1.1 * cm, "ChargeGrid Intelligence | Relatório técnico Sprint 4"
        )
        canvas.drawRightString(A4[0] - 1.8 * cm, 1.1 * cm, str(doc.page))

    documento = SimpleDocTemplate(
        str(ROOT / "docs/relatorio_evolucao_sprint4.pdf"),
        pagesize=A4,
        rightMargin=1.8 * cm,
        leftMargin=1.8 * cm,
        topMargin=1.7 * cm,
        bottomMargin=1.7 * cm,
        title="ChargeGrid Intelligence — Evolução Sprint 4",
        author="ChargeGrid Intelligence",
    )
    corpo.alignment = TA_LEFT
    documento.build(elementos, onFirstPage=rodape, onLaterPages=rodape)
    (ROOT / "docs/relatorio_evolucao_sprint4.md").write_text(
        "# Relatório técnico de evolução — Sprint 4\n\n" + "\n".join(paginas_md)
    )
    print("Relatórios Markdown e PDF gerados a partir dos scores salvos.")


if __name__ == "__main__":
    main()
