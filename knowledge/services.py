"""Small local RAG pipeline. SQLite is an exact-search vector store, not ANN."""
import json
import logging
import math
import re
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError
from django.conf import settings
from django.db import transaction
from .models import Document, Chunk

logger = logging.getLogger(__name__)


class ModelError(Exception):
    pass


def ollama(endpoint, payload):
    request = Request(settings.OLLAMA_URL + endpoint, data=json.dumps(payload).encode(),
                      headers={'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=settings.MODEL_TIMEOUT) as response:
            data = json.load(response)
        if not isinstance(data, dict) or 'error' in data:
            raise ValueError('Model error')
        return data
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise ModelError('Cannot reach the configured Ollama model. Start Ollama and pull the models listed in README.md, then retry.') from exc


def embed(texts):
    try:
        vectors = ollama('/api/embed', {'model': settings.EMBED_MODEL, 'input': texts, 'truncate': False})['embeddings']
        if len(vectors) != len(texts) or not vectors:
            raise ValueError()
        dimension = len(vectors[0])
        if not dimension or any(len(v) != dimension or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in v) or not any(v) for v in vectors):
            raise ValueError()
        return vectors
    except (KeyError, TypeError, ValueError) as exc:
        raise ModelError('Ollama returned invalid embeddings. Check the embedding model.') from exc


def extract(document):
    with document.file.open('rb') as stream:
        if Path(document.name).suffix.lower() == '.pdf':
            from pypdf import PdfReader
            reader = PdfReader(stream)
            if reader.is_encrypted:
                raise ValueError('Password-protected PDFs are unsupported.')
            if len(reader.pages) > 200:
                raise ValueError('PDFs must contain at most 200 pages.')
            pages = [(n + 1, page.extract_text() or '') for n, page in enumerate(reader.pages)]
        else:
            pages = [(None, stream.read().decode('utf-8-sig'))]
    if sum(len(text) for _, text in pages) > 1_000_000:
        raise ValueError('Extracted text exceeds the one-million-character limit.')
    if not any(text.strip() for _, text in pages):
        raise ValueError('No readable text found. Scanned PDFs need OCR, which is not included.')
    return pages


def split_pages(pages):
    chunks = []
    for page, text in pages:
        words = text.split()
        for start in range(0, len(words), 180):
            passage = ' '.join(words[start:start + 220])
            if passage:
                chunks.append((page, passage))
    return chunks


def process_document(pk):
    # Atomic compare-and-set prevents two workers claiming the same job.
    if not Document.objects.filter(pk=pk, status='queued').update(status='processing', error=''):
        return False
    try:
        document = Document.objects.get(pk=pk)
        pieces = split_pages(extract(document))
        chunks = []
        for start in range(0, len(pieces), 16):
            batch = pieces[start:start + 16]
            vectors = embed([text for _, text in batch])
            chunks.extend(Chunk(document=document, page=page, text=text, position=start+i, vector=vector)
                          for i, ((page, text), vector) in enumerate(zip(batch, vectors)))
        with transaction.atomic():
            if not Document.objects.filter(pk=pk, status='processing').exists():
                return False
            document.chunks.all().delete()
            Chunk.objects.bulk_create(chunks)
            Document.objects.filter(pk=pk).update(status='ready', error='', embedding_model=settings.EMBED_MODEL)
    except Document.DoesNotExist:
        return False
    except Exception as exc:
        logger.exception('Indexing document %s failed', pk)
        error = str(exc) if isinstance(exc, (ModelError, ValueError, UnicodeError)) else 'Could not process this document. Check the worker log and retry.'
        Document.objects.filter(pk=pk).update(status='failed', error=error[:500])
    return True


def cosine(a, b):
    if len(a) != len(b):
        raise ModelError('Embedding dimensions changed. Re-index the selected documents.')
    denominator = math.sqrt(sum(x*x for x in a) * sum(x*x for x in b))
    return sum(x*y for x, y in zip(a, b)) / denominator if denominator else 0


def retrieve(query, documents):
    vector = embed([query])[0]
    ranked = sorted(((cosine(vector, c.vector), c) for c in Chunk.objects.filter(document__in=documents, document__status='ready', document__embedding_model=settings.EMBED_MODEL).select_related('document')),
                    key=lambda pair: pair[0], reverse=True)
    # Always offer the best passages by default. The LLM determines answerability
    # from their text, rather than treating a raw cosine value as confidence.
    selected = [c for score, c in ranked[:5] if settings.RAG_MIN_SCORE is None or score >= settings.RAG_MIN_SCORE]
    return selected


def answer_schema(sources):
    return {
        'type': 'object',
        'properties': {
            'answerable': {'type': 'boolean'},
            'answer': {'type': 'string'},
            'source_ids': {'type': 'array', 'items': {'type': 'string', 'enum': [s['id'] for s in sources]}},
        },
        'required': ['answerable', 'answer', 'source_ids'],
        'additionalProperties': False,
    }


def render_grounded_response(raw_content, sources):
    try:
        response = json.loads(raw_content)
    except (ValueError, TypeError):
        raise ModelError('Ollama returned an invalid structured answer. Please retry.') from None
    if not isinstance(response, dict) or type(response.get('answerable')) is not bool:
        raise ModelError('Ollama returned an invalid structured answer. Please retry.')
    if not response['answerable']:
        return 'I could not find enough relevant information in the selected documents to answer that question.', []
    content = response.get('answer')
    ids = response.get('source_ids')
    valid = {s['id'] for s in sources}
    if (not isinstance(content, str) or not content.strip() or not isinstance(ids, list)
            or not ids or any(not isinstance(i, str) for i in ids) or not set(ids) <= valid):
        return 'I could not produce a reliably cited answer. Please rephrase your question or review these retrieved passages.', sources
    content = content.strip()
    # The model supplies source IDs separately; Django renders the visible citations.
    # Also reject fabricated bracketed references in its answer text.
    inline_ids = set(re.findall(r'\[(\d+)\]', content))
    if not inline_ids <= set(ids):
        return 'I could not produce a reliably cited answer. Please rephrase your question or review these retrieved passages.', sources
    missing = [source['id'] for source in sources if source['id'] in ids and source['id'] not in inline_ids]
    if missing:
        content += ' ' + ' '.join(f'[{i}]' for i in missing)
    return content, [s for s in sources if s['id'] in ids]


def answer(question, documents, history):
    if any(d.embedding_model != settings.EMBED_MODEL for d in documents):
        raise ModelError('Embedding model changed. Re-index the selected documents.')
    # Import lazily because the agent uses the retrieval/validation functions above.
    from .agent import answer_with_agent
    return answer_with_agent(question, documents, history)
