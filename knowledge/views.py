import json
import logging
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse, FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST, require_GET
from .forms import validate_uploads
from .models import Document, Conversation, Message
from .services import answer, ModelError
from django.conf import settings

logger = logging.getLogger(__name__)


def signup(request):
    form = UserCreationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        login(request, user)
        return redirect('workspace')
    return render(request, 'registration/signup.html', {'form': form})


@login_required
def workspace(request):
    return render(request, 'knowledge/workspace.html')


@login_required
@require_GET
def documents(request):
    rows = list(Document.objects.filter(owner=request.user).order_by('-pk').values('id', 'name', 'size', 'status', 'error', 'embedding_model'))
    for row in rows:
        row['needs_reindex'] = row.pop('embedding_model') != settings.EMBED_MODEL and row['status'] == 'ready'
    return JsonResponse({'documents': rows})


@login_required
@require_POST
def upload(request):
    files = request.FILES.getlist('files')
    try:
        validate_uploads(files)
    except ValidationError as exc:
        return JsonResponse({'error': ' '.join(exc.messages)}, status=400)
    saved = []
    try:
        with transaction.atomic():
            for file in files:
                doc = Document(owner=request.user, name=file.name[:255], size=file.size)
                doc.file.save(file.name, file, save=False)
                saved.append(doc)
                doc.save()
    except Exception:
        for doc in saved:
            doc.file.delete(save=False)
        logger.exception('Upload failed')
        return JsonResponse({'error': 'Could not save the files. Please retry.'}, status=500)
    # Document rows are the durable job queue; workers see only committed rows.
    return JsonResponse({'count': len(saved)}, status=201)


@login_required
@require_GET
def download(request, pk):
    doc = get_object_or_404(Document, pk=pk, owner=request.user)
    response = FileResponse(doc.file.open('rb'), as_attachment=True, filename=doc.name, content_type='application/octet-stream')
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@login_required
@require_POST
def delete(request, pk):
    doc = get_object_or_404(Document, pk=pk, owner=request.user)
    claimed = Document.objects.filter(pk=pk).exclude(status__in=['processing', 'deleting']).update(status='deleting')
    if not claimed:
        return JsonResponse({'error': 'Wait for processing to finish before deleting this file.'}, status=409)
    # Remove historical answers that may quote the document; preserve user questions.
    for message in Message.objects.filter(conversation__owner=request.user, role='assistant'):
        if any(c.get('document_id') == pk for c in message.citations):
            message.content = 'This answer was removed because one of its source documents was deleted.'
            message.citations = []
            message.save(update_fields=['content', 'citations'])
    try:
        doc.file.delete(save=False)
    except OSError:
        Document.objects.filter(pk=pk).update(status=doc.status)
        return JsonResponse({'error': 'The stored file could not be removed. Please retry.'}, status=503)
    doc.delete()
    return JsonResponse({'ok': True})


@login_required
@require_POST
def retry(request, pk):
    doc = get_object_or_404(Document, pk=pk, owner=request.user)
    changed = Document.objects.filter(pk=doc.pk, status__in=['ready', 'failed']).update(status='queued', error='')
    return JsonResponse({'ok': bool(changed)})


@login_required
@require_GET
def conversations(request):
    return JsonResponse({'conversations': list(Conversation.objects.filter(owner=request.user).order_by('-pk').values('id', 'title'))})


@login_required
@require_GET
def history(request, pk):
    conversation = get_object_or_404(Conversation, pk=pk, owner=request.user)
    return JsonResponse({'messages': list(conversation.messages.order_by('pk').values('role', 'content', 'citations'))})


@login_required
@require_POST
def chat(request):
    try:
        data = json.loads(request.body)
        if not isinstance(data, dict):
            raise ValueError()
        question = data.get('question')
        ids = data.get('document_ids')
        if not isinstance(question, str) or not 1 <= len(question.strip()) <= 2000:
            raise ValueError()
        if not isinstance(ids, list) or not ids or len(ids) > 30 or any(type(i) is not int for i in ids):
            raise ValueError()
        conversation_id = data.get('conversation_id')
        if conversation_id is not None and type(conversation_id) is not int:
            raise ValueError()
    except (ValueError, TypeError):
        return JsonResponse({'error': 'Enter a question of up to 2,000 characters and select ready documents.'}, status=400)
    docs = list(Document.objects.filter(pk__in=ids, owner=request.user, status='ready'))
    if len(docs) != len(set(ids)):
        return JsonResponse({'error': 'Some selected documents are unavailable or still processing.'}, status=400)
    conversation = get_object_or_404(Conversation, pk=conversation_id, owner=request.user) if conversation_id else None
    history = list(conversation.messages.order_by('-pk')[:6])[::-1] if conversation else []
    try:
        content, citations = answer(question.strip(), docs, history)
    except ModelError as exc:
        return JsonResponse({'error': str(exc)}, status=503)
    # Recheck after slow model calls: a document may have been removed meanwhile.
    if Document.objects.filter(pk__in=ids, owner=request.user, status='ready').count() != len(docs):
        return JsonResponse({'error': 'Your sources changed while answering. Please retry.'}, status=409)
    with transaction.atomic():
        if conversation is None:
            conversation = Conversation.objects.create(owner=request.user, title=question[:100])
        Message.objects.create(conversation=conversation, role='user', content=question.strip())
        Message.objects.create(conversation=conversation, role='assistant', content=content, citations=citations)
    return JsonResponse({'conversation_id': conversation.pk, 'answer': content, 'citations': citations})
