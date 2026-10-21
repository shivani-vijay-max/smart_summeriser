# Papertrail: Django + Ollama + LangChain document agent

A local RAG application with a LangChain research agent using your existing Ollama models. Your Hello World (`/`) and About (`/about/`) pages are preserved. The document workspace is `/knowledge/`.

## 1. Python setup

Python 3.11+ is recommended. Use the project-local virtual environment at `.venv`. To create it on a fresh checkout, run `python3.11 -m venv .venv`.

```bash
cd /Users/shivanivijay/smart_summeriser
source .venv/bin/activate
python -m pip install -r requirements.txt
python manage.py migrate
```

The PDF dependency has also been installed into this project's ignored `.deps/` folder for the current workspace. Settings make that folder importable. New installations can simply use requirements.txt.

## 2. Install local models

For this workspace, the official Ollama runtime is installed under `.ollama/runtime/`, with model files under `.ollama/models/`. You can use the bundled executable instead of a global installation:

Both configured models have been downloaded in this workspace. A real-model smoke test passed: uploading the fictional leave policy, indexing its text, retrieving a passage, and answering “25 days” with a source citation. You do not need to download the models again unless they are removed or you choose different models.

```bash
OLLAMA_MODELS="$PWD/.ollama/models" .ollama/runtime/ollama serve
# In another terminal, if a model is missing:
.ollama/runtime/ollama pull embeddinggemma
.ollama/runtime/ollama pull llama3.2:3b
```

Install Ollama from https://ollama.com/download and start its application. Then run:

```bash
ollama pull embeddinggemma
ollama pull llama3.2:3b
```

These downloads require internet access and disk space. Models run on your computer; speed and memory needs depend on hardware. If using the CLI without the desktop app, start `ollama serve` in a separate terminal. Do not start a second server if one is already running.

This app calls the documented Ollama endpoints `/api/embed` and `/api/chat` with non-streaming chat responses:
- https://docs.ollama.com/api/embed
- https://docs.ollama.com/api/chat

## 3. Run Django and the worker

The easiest option, once both models are downloaded, is one command in your activated environment:

```bash
python scripts/run_local.py
```

This starts Ollama if needed, migrates the database, and starts the indexing worker and web server. Stop any separate Django/worker processes first to avoid port conflicts. Ctrl+C stops the processes it started. Alternatively, run services separately as follows.

Terminal one, with the environment activated:

```bash
python manage.py runserver
```

Terminal two, in the same project and environment:

```bash
source .venv/bin/activate
python manage.py process_documents
```

Open http://127.0.0.1:8000/knowledge/ and create an account. Upload files, wait for `ready`, select the documents, and ask a question. Expand citations to read the retrieved passages. Conversations are saved and can be reopened in the sidebar. Downloads require the owning user's login.

## Features and limits

- Multiple PDF, TXT, MD, or CSV uploads: up to five files per request, 10 MB per file.
- Text files must use UTF-8. PDFs need selectable text; OCR and password-protected PDFs are unsupported. PDF limit: 200 pages; extracted text limit: one million characters per file. CSV is treated as text, not a spreadsheet calculation engine.
- Private originals in `private_uploads/`; users cannot retrieve another user's files, conversations, or search results.
- Durable SQLite document rows form the indexing queue; a worker claims jobs using a conditional update. Failed files can be retried and ready files re-indexed from the UI.
- Overlapping text chunks, real Ollama embeddings, cosine similarity search, evidence-based model prompts, saved chats, and source references.
- SQLite stores chunk text and vectors as JSON. Search scans authorized chunks exactly; suitable for a small learning project, not a large production corpus. The architectural vector-index role is implemented in SQLite rather than a separate vector database.
- A LangChain tool-calling research agent can refine a document search. An initial search is guaranteed, so a small local model cannot skip retrieval. A separate structured answer step preserves reliable citation formatting.
- Citations are checked against retrieved source IDs. This does not prove every claim is correct. Similarity thresholds and retrieval quality need evaluation on your documents; the chatbot may refuse or miss answers.
- Deletion removes file contents and chunks and replaces historical assistant answers citing that document with a removal notice. User-written questions remain in chat history. Processing files must finish or be recovered before deletion.
- The app uses non-streaming answers. Timeouts/model errors return a retryable message without saving a fabricated answer.

## Model configuration

Environment variables are read by Django and the worker. Set the same values in both terminals. `.env` files are not automatically loaded.

```bash
export OLLAMA_URL=http://127.0.0.1:11434
export EMBED_MODEL=embeddinggemma
export CHAT_MODEL=llama3.2:3b
export MODEL_TIMEOUT=180
# Optional: enable a cutoff only after evaluating it on your documents.
# export RAG_MIN_SCORE=0.35
```

After changing the embedding model, re-index documents before chatting. Keep the Ollama URL local to keep document processing on this computer. A remote URL sends evidence and questions to that server.

## Troubleshooting

- **Queued forever:** start the worker in terminal two.
- **Interrupted processing:** stop all workers, then run `python manage.py process_documents --recover`. This resets processing jobs; do not use recovery while another worker is running.
- **Failed indexing:** check the worker output, start Ollama, pull both models, then click Retry. Model requests can take time on the first load.
- **No supported answer:** check selected sources, read retrieved passages, rephrase, and tune retrieval on representative questions.
- **No module named Django:** activate `.venv`; the system Python on this Mac does not contain Django.

## Verification

```bash
python manage.py check
python manage.py test knowledge
node --check knowledge/static/knowledge/chat.js
```

Tests use controlled model responses and temporary file storage. They check uploads, processing, failure/retry, permissions, CSRF, citations, deletion, and saved chats. They do not download models or demonstrate real-model answer quality. Complete a real-model smoke test after Ollama is installed: upload a text file stating “Employees receive 25 days of annual leave,” ask how much leave employees receive, and verify both answer and citation.

An example is included at `examples/leave-policy.txt`. To verify real models automatically without changing your project database or files:

```bash
python scripts/smoke_ollama.py
```

This is configured for local development. Before exposing it publicly, add deployment settings, HTTPS, rate limits/quotas, sandboxed parsing/resource limits, monitored workers, backups, and a scalable database/index. Django's development server and default development secret are not a production setup.


## Current provider: local Ollama

The hosted OpenAI migration was canceled at the user's request. Embeddings and answers use local Ollama, and a LangChain agent now coordinates document research; no OpenAI API key, API balance, or hosted request is required. The saved private `.env` is not loaded by this implementation. Existing downloaded models, uploads, accounts, and conversation records are retained.

Documents already indexed with `embeddinggemma` can be used immediately. Any document indexed with a different model shows **Re-index required**; click Re-index, or run `python manage.py reindex_documents` with the local worker running. This uses Ollama only.


## Retrieval and citation fix

The default retrieval uses the five best-ranked passages without a hard similarity cutoff. A cosine score is not an answer-confidence percentage: a fixed 0.35 cutoff rejected relevant resume passages before the LLM saw them. `RAG_MIN_SCORE` is now an optional evaluated override, not a default gate. Unset an old exported cutoff to use the new default.

Ollama returns a structured object with answerability, answer text, and supporting source IDs. Django validates those IDs and renders citation markers, so a correct answer is not rejected merely because the model omitted bracket formatting. Unsupported questions still receive an honest refusal. The retrieval and citation fixes are retained under the local LangChain agent described below.


## Local LangChain agent

The user requested LangChain while keeping local Ollama. The application now uses `langchain.agents.create_agent` and `langchain_ollama.ChatOllama` in `knowledge/agent.py`. It does not use OpenAI, load an OpenAI key, or require API credits. Existing vectors are unchanged: no re-upload or re-index is needed for documents already indexed with the configured embedding model.

Each question follows this flow:

1. Django checks the selected documents and conversation ownership.
2. The application invokes a LangChain `search_documents(query)` tool once to guarantee an initial evidence search.
3. A LangChain research agent reads that tool result and may call the same tool with refined queries.
4. After research, `ChatOllama` generates a structured answer with answerability and supporting source IDs.
5. Django validates those IDs, adds visible citations, and saves the final answer using the existing chat models.

The search tool captures the authorized document list on the server. Its schema accepts only a query, so the model cannot pass arbitrary user IDs, document IDs, file paths, or commands. Retrieved passages and history are treated as untrusted data, not instructions. There are no browser, shell, or internet tools.

Limits: at most three search executions including the initial search, eight retained source passages, and a research graph recursion limit of ten. If the agent exhausts its graph steps, the answer step uses the evidence already collected instead of looping. Recent history is capped. Both model stages use the same local chat model. Additional research calls can take longer on a small computer. External LangSmith tracing is explicitly disabled for this workflow.

`knowledge/services.py` still handles file extraction, embedding/indexing, cosine retrieval, schema creation, and citation validation. `knowledge/agent.py` handles LangChain orchestration. The embedding model remains `embeddinggemma`, the chat model remains `llama3.2:3b`, and SQLite remains the local vector store.

Validation commands remain:

```bash
python manage.py test knowledge
python scripts/smoke_ollama.py
```

The tests run the actual LangChain graph with test model responses to check tool refinement, search budgets, document isolation, structured citations, and model errors. The smoke test uses real local models with temporary storage and the fictional policy.

References: [LangChain agents](https://docs.langchain.com/oss/python/langchain/agents), [ChatOllama](https://docs.langchain.com/oss/python/integrations/chat/ollama).


## Recent/current employer questions

For employment recency, `knowledge/chronology.py` validates exact employer/date pairs against retrieved passages and compares calendar dates in Python. The local model supplies structured employment records, but its prose guess and passage order do not determine the result. Date ranges in explicit employment sections are scanned independently so an omitted newer job triggers a bounded extraction retry. Student roles count as employment; education sections are excluded from that date scan. Prior assistant answers are not included in a fresh chronological extraction.

The implementation handles month/year, named-month/year, year-only, and Present-style ranges. Uncertain or contradictory dates produce a limitation message rather than a guessed employer. “Most recent” does not imply “currently employed”: if all roles have ended, the answer states the most recent listed role rather than claiming it is ongoing. This remains a source-grounded local extraction, and unusual resume layouts, unsupported date formats, or incomplete retrieved sections may require clarification.


Employment questions also accept close spelling variations such as “recent employement” and role/job wording. Employment answers include a source-supported job title, employer, and dates. The extractor independently resolves supporting citations from retrieved text and ignores unsupported extra records; a newer unaccounted-for employment date still blocks an older answer. Previous incorrect assistant answers are excluded from this date comparison.
