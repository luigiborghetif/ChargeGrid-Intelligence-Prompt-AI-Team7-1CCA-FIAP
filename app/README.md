# Aplicação ChargeGrid

Interface Gradio para consultas operacionais, documentais e mistas, com
dashboard e memória por sessão. As respostas documentais exibem arquivo,
página PDF e trecho de apoio conferido contra o contexto recuperado.

Na raiz do repositório, ative o ambiente virtual e instale o projeto:

```bash
python -m pip install -e ".[dev]"
```

Configure `.env` a partir de `.env.example`. Prepare os modelos no Ollama e o
índice documental, caso ainda não estejam disponíveis:

```bash
ollama signin
ollama pull gemma4:31b-cloud
ollama pull nomic-embed-text
chargegrid-rag indexar
```

Com o Ollama ativo, execute a partir da raiz:

```bash
python -m app.main
```

Também é possível usar `python app/main.py` ou `chargegrid-web`.
Abra `http://127.0.0.1:7860`. Encerre com `Ctrl+C` no terminal.
O ponto de entrada reutiliza `src/chargegrid/app.py`, sem duplicar a interface.

Exemplos de consulta:

- Quais são as tarifas Urgente e Econômico?
- Qual foi o pico de demanda?
- Qual foi o pico e como o controle dinâmico de carga pode ajudar?
- Qual é o prazo de estorno se a recarga falhar?

Consultas documentais apresentam resposta e fontes, sem exigir risco ou
recomendações operacionais. Uma resposta parcial é identificada explicitamente;
sem evidência suficiente, o assistente informa a limitação. **Nova conversa**
limpa a memória da sessão e inicia outra conversa.

A numeração apresentada é a página do arquivo PDF, que pode diferir da página
impressa. A conferência de identificadores e trechos não constitui verificação
semântica automática de todas as afirmações. Consulte
[a documentação RAG](../docs/rag.md) para configuração, validação e limitações.
