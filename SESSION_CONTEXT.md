# Session handoff: smart_summeriser

## Latest implementation: local LangChain + Ollama agent

After confirming the retrieval fix works, the user explicitly requested a LangChain LLM agent while retaining Ollama. The active answer path now uses knowledge/agent.py: guaranteed initial LangChain search_documents tool invocation, create_agent with ChatOllama for bounded research/refinement, then a structured ChatOllama answer with existing source-ID validation. Embeddings remain the original local embeddinggemma vectors and require no migration. Chat remains llama3.2:3b. The tool scope is fixed to authorized selected documents, maximum three searches/eight source passages/ten research graph steps. External tracing is explicitly disabled. Dependencies are LangChain 1.4.6 and langchain-ollama 1.1.0; no hosted provider, OpenAI key, or API credits are used. Prior paragraphs saying the active app does not use LangChain are historical and superseded. README describes the current runtime.


## Current decision: continue with local Ollama

The user explicitly canceled the OpenAI migration and requested the original working Ollama implementation. The application, requirements, launcher, worker, UI, and smoke test have been restored to the local Ollama RAG pipeline. Defaults: embeddinggemma and llama3.2:3b. No OpenAI API calls or API billing are needed. The saved private .env is left untouched but is not loaded by the active code. Existing files, accounts, and chat history are preserved. The original Ollama embeddings can be reused. A model mismatch is marked for local re-indexing. The OpenAI/LangChain-specific source files were removed. Historical notes below describe earlier decisions and do not override this cancellation.


## Historical update: 21 October 2026 — attempted OpenAI migration (canceled)

The user explicitly requested migrating from Ollama to an OpenAI API key and a LangChain LLM agent. The current application uses `knowledge/llm.py` (OpenAIEmbeddings and ChatOpenAI) and `knowledge/agent.py` (create_agent with a scoped document-search tool). Defaults: text-embedding-3-small and gpt-4.1-mini. `.env` is private and presently has no configured key; user must fill OPENAI_API_KEY locally. The launcher now starts Django/worker, not Ollama. Existing originals and chat/admin records are preserved. Old embeddings require re-indexing through the UI or reindex_documents command. No bulk paid re-index or live OpenAI request was made without a key. Read the current README for setup and tests. The historical Ollama description below records the original implementation, not the current provider choice.


Updated: 19 October 2026. This note preserves project context from the Codex chat **Explain Django project structure** (thread ID `01a14f21-6d7a-7c72-baab-c75fd28ac111`). The original chat contains the full conversation; this file is a practical handoff, not a verbatim transcript.

## User and objective

The user is a Django beginner and wants step-by-step, plain-language explanations. They first requested a read-only explanation of their Hello World project, then upload architecture diagrams, then a complete document chatbot architecture, then implementation. They asked about embeddings, RAG, and CSRF and have been given introductory explanations.

The implemented goal is a website where users upload several files and ask questions about their contents in chat. Use retrieval-augmented generation: extract text, chunk, embed, retrieve authorized passages, and ask an LLM to answer with citations. Uploads do not train the model. The user explicitly selected **local models through Ollama**, with no hosted API key.

## Canonical location and Git

- Repository and project root: `/Users/shivanivijay/smart_summeriser`.
- Old root: `/Users/shivanivijay/django_learning/helloworld`; all its contents were moved. The old directory remains empty.
- Preserve the existing `.git` in the new repository. No commits or pushes were requested or made during this session.
- The repository's original README is preserved as `README.repository.md`; `README.md` is the application setup guide.
- A new independent environment was created at `.venv/`; use `.venv/bin/python`, not the system Python or the old sibling environment.
- `.gitignore` excludes `.venv/`, `.deps/`, `.ollama/`, `private_uploads/`, `db.sqlite3`, `.env`, caches, and macOS metadata. The local database and models moved with the project.
- Absolute references in editable documentation and scripts were updated to the new root.

## Implemented application

Product label: Papertrail. Django 5.2.17, Python 3.11, pypdf 6.21.1; see `requirements.txt`.

Existing `home` app and routes are preserved:
- `/`: original Hello World text (including its original spelling).
- `/about/`: original About text.

New `knowledge` app:
- Accounts: signup, login, and POST logout, using Django authentication and CSRF protection.
- `/knowledge/`: responsive upload/library/chat workspace.
- Multiple private uploads: PDF, TXT, Markdown, CSV; maximum five files per request and 10 MB per file.
- Owner checks on uploads, downloads, deletes, chat history, and retrieval. Sources are not publicly served from a media URL.
- Original files use generated storage names under `private_uploads/`.
- `Document` rows provide a durable SQLite queue: queued, processing, ready, failed. The worker claims jobs with a conditional update.
- Text extraction, overlapping chunks, real Ollama embeddings, and exact cosine-similarity search over authorized chunks.
- SQLite stores vectors as JSON alongside chunk text and source metadata; no separate vector database or queue service is required for this learning implementation.
- Selected ready documents provide chat evidence. Recent questions supply basic follow-up context.
- LLM instructions require evidence-grounded answers and source IDs. Citation IDs are checked against retrieved passages. Citations include source text and page numbers when available.
- Saved conversations and messages, expandable citations, downloads, retries, and re-indexing.
- Deletion removes originals and chunks and replaces previous assistant answers citing that document with a removal notice. User questions remain. Processing files cannot be deleted until processing finishes or is recovered.
- Failures are shown instead of fabricated answers.

## Important code

- `helloworld/settings.py`: apps, private storage, environment-based model settings, local hosts.
- `helloworld/urls.py`: preserves old routes; adds authentication and knowledge routes.
- `knowledge/models.py`: Document, Chunk, Conversation, Message; citations are JSON on Message.
- `knowledge/forms.py`: validates the complete upload selection.
- `knowledge/services.py`: Ollama HTTP calls, extraction, chunking, indexing, similarity search, prompt assembly, citation checks.
- `knowledge/views.py`, `knowledge/urls.py`: HTTP endpoints and ownership checks.
- `knowledge/management/commands/process_documents.py`: queue worker, `--once`, and `--recover`.
- `knowledge/templates/` and `knowledge/static/knowledge/`: authentication screens, workspace, CSS, and JavaScript. Responses and source content are inserted as text, not unsanitized HTML.
- `knowledge/migrations/0001_initial.py`: applied schema.
- `knowledge/tests.py`: 16 automated tests.
- `scripts/run_local.py`: starts migrations, Ollama if needed, worker, and web server; cleans up processes it started on Ctrl+C.
- `scripts/smoke_ollama.py`: real-model integration test in a temporary database and temporary file directory; optional `--wait` for models.
- `examples/leave-policy.txt`: fictional test policy with 25 days of annual leave.

## Local models and running

The official Ollama v0.40.6 runtime was downloaded to `.ollama/runtime/`. Both `embeddinggemma` and `llama3.2:3b` were downloaded to `.ollama/models/` (roughly 2.5 GB combined). They do not need downloading again. Ollama also generated its normal identity key in the user's home directory; never copy secrets into Git or this note.

Default configuration:
- `OLLAMA_URL=http://127.0.0.1:11434`
- `EMBED_MODEL=embeddinggemma`
- `CHAT_MODEL=llama3.2:3b`
- `MODEL_TIMEOUT=180`
- `RAG_MIN_SCORE=0.35`

Set identical model environment variables for Django and its worker. Changing embedding models requires re-indexing. `.env` is not automatically loaded.

```bash
cd /Users/shivanivijay/smart_summeriser
source .venv/bin/activate
python scripts/run_local.py
```

Open `http://127.0.0.1:8000/knowledge/`, create an account, upload files, wait for ready, select sources, ask questions. Preserve the database and any accounts or documents in it; no user credentials are recorded in this note.

The launcher was started from the new root during relocation. Process state is temporary: check whether ports 8000 and 11434 are listening before starting another instance. Do not assume process IDs or session IDs remain valid across chats.

For manual model startup:

```bash
OLLAMA_MODELS="$PWD/.ollama/models" .ollama/runtime/ollama serve
```

For interrupted indexing, stop all workers before running `python manage.py process_documents --recover`.

## Verification already completed

After relocation:
- `python manage.py check`: no issues.
- All 16 knowledge-app tests passed, covering ownership, CSRF, uploads, processing, retries, citation handling, failure paths, deletion, and chat persistence.
- The real Ollama smoke test passed from the new directory: upload policy → extract → embed → retrieve → answer → save citations. It returned 25 days of annual leave with source `[1]`.
- Git root verified as `/Users/shivanivijay/smart_summeriser`; local environments, models, and database are ignored.
- Earlier JavaScript syntax checks passed, and the login page rendered in the browser.

```bash
python manage.py test knowledge
python scripts/smoke_ollama.py
```

## Architecture artifacts and limitations

`architecture/` holds both HTML and Markdown versions of the earlier file-upload and RAG chatbot architectures. HTML diagrams work offline; Markdown uses Mermaid. A PDF architecture document was also preserved. The earlier diagrams are proposals; README explains actual simplifications.

This is a local learning application, not a production deployment. Text-based PDFs only; OCR and encrypted PDFs are unsupported. PDF maximum: 200 pages. Extracted-text maximum: one million characters. UTF-8 is required for text formats. CSV is treated as text. Exact vector search scans selected chunks and is intended for small collections. It is a constrained RAG pipeline, not an autonomous tool-using agent. Citation-ID validation does not prove claim accuracy; evaluate grounding and retrieval on representative questions. Production needs deployment hardening, quotas, parser isolation/resource limits, monitored workers, and scalable storage/search.

## Pending Codex chat move

The user requested moving this session's context into the new project. Codex now lists `smart_summeriser` as a saved local Git project with ID `a79f46ba-357c-4a5a-801d-a41dbd48610d`.

A native `move_thread_to_project` call was attempted for the current chat. Codex returned `confirmation_required`, reporting the old source directory `/Users/shivanivijay/django_learning/helloworld` as an additional project source. The tool instructions require the human user to perform the move in the sidebar when additional source access is needed. Do not edit Codex internal databases or bypass that access confirmation. The chat's full history stays intact; this context file supplies a handoff if work continues in another chat. Until the user completes the sidebar move, explicitly use the new repository as the working directory for commands.

## Resume Q&A retrieval fix

The uploaded resume was indexed correctly (three chunks), but a fixed cosine cutoff of 0.35 rejected all passages for basic questions (name-question maximum score 0.143). Bypassing that gate exposed a second problem: the local LLM returned the correct name without brackets, and the app discarded it as uncited. Default retrieval now takes the five best passages with no hard cutoff; RAG_MIN_SCORE remains an optional explicit override. Standalone short questions no longer automatically inherit an unrelated previous question. Ollama is asked for structured JSON with answerable, answer, and source_ids; Django validates IDs and renders citation markers. Unsupported questions still return a refusal. No embedding migration or file re-upload is required. Twenty-two tests passed, and real local checks against the existing resume succeeded for name, skills, experience, and an unsupported-question refusal. The app still uses direct Ollama RAG, not LangChain; adding LangChain was not part of this bug fix.


## Employment chronology correction

The user reported “recent employer” incorrectly returned Alstom. Local reproduction confirmed that error despite both employers being present in the extracted text. The resume lists Siemens Healthineers 11/2022–03/2025 versus Alstom 08/2019–12/2021. Added knowledge/chronology.py: structured employer/date records, source-adjacency validation, independent employment-section date inventory, Python calendar ordering, bounded retry if a newer range was omitted, and explicit ambiguity handling. Includes recently/employed wording, student roles, education exclusion, and year/month/Present-style dates. Temporal extraction excludes prior assistant answers. Two real local phrasings now return Siemens with the 2025 end date and a source citation. No employer name is hardcoded in the logic. No document re-upload or embedding migration is needed. Regression tests also exposed and corrected an unrelated flaky filename assertion: a random UUID ending in “a” can contain “a.txt”, so the test now compares the full basename to the original name.


## Employment wording and role correction

The exact question “what is the recent employement” bypassed chronological validation because the routing required exact spelling. Close vocabulary typos and latest role/job/position questions now use the same source-verified date path. Employment answers include the exact supported role as well as employer and dates. Full titles adjacent to an explicit employment heading can be recovered from source text, avoiding a generic professional-summary title. Unsupported extra extracted entries no longer poison a valid latest record; citation numbers are independently matched against retrieved evidence. The independent date inventory still rejects an older answer if a newer employment range is omitted. All 47 automated tests pass. Real local tests with a previous incorrect Data Scientist assistant answer returned Work Student at Siemens Healthineers (11/2022–03/2025) for both the exact misspelled question and “What is her latest role?”. The existing upload was used; no re-index or re-upload was needed.
