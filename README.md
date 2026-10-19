# Papertrail: Django document chatbot

A local RAG application built on your Django project. Your Hello World (`/`) and About (`/about/`) pages are preserved. The document workspace is `/knowledge/`.

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
- A simple recent-question context heuristic supports short follow-up retrieval. This is a constrained RAG workflow, not an autonomous tool-using agent.
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
export RAG_MIN_SCORE=0.35
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
