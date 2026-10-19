import json
import tempfile
from unittest.mock import patch
from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from .models import Document, Chunk, Conversation, Message
from .services import process_document, answer, ModelError, split_pages


class WorkflowTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings = override_settings(MEDIA_ROOT=self.directory.name)
        self.settings.enable()
        self.addCleanup(self.settings.disable)
        self.user = User.objects.create_user('alice', password='test-password')
        self.other = User.objects.create_user('bob', password='other-password')
        self.client.force_login(self.user)

    def upload(self, name='policy.txt', content=b'Employees receive 25 days of annual leave.'):
        return self.client.post('/documents/upload/', {'files': [SimpleUploadedFile(name, content)]})

    def ready(self):
        self.upload()
        document = Document.objects.get()
        with patch('knowledge.services.embed', return_value=[[1., 0.]]):
            process_document(document.pk)
        document.refresh_from_db()
        return document

    def test_signup_login_workspace_and_original_pages(self):
        self.assertEqual(self.client.get('/knowledge/').status_code, 200)
        self.assertContains(self.client.get('/'), 'Hellow World')
        self.assertContains(self.client.get('/about/'), 'about page')
        self.client.logout()
        self.assertEqual(self.client.get('/knowledge/').status_code, 302)
        response = self.client.post('/accounts/signup/', {'username': 'charlie', 'password1': 'StrongPass481!', 'password2': 'StrongPass481!'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(username='charlie').exists())

    def test_multiple_uploads_are_private_and_queue_is_durable(self):
        response = self.client.post('/documents/upload/', {'files': [SimpleUploadedFile('a.txt', b'One'), SimpleUploadedFile('b.md', b'Two')]})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Document.objects.filter(owner=self.user, status='queued').count(), 2)
        doc = Document.objects.first()
        self.assertNotIn('a.txt', doc.file.name)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get('/documents/').json()['documents'], [])
        for suffix, method in [('download/', 'get'), ('delete/', 'post'), ('retry/', 'post')]:
            self.assertEqual(getattr(self.client, method)(f'/documents/{doc.pk}/{suffix}').status_code, 404)

    def test_upload_validates_whole_selection(self):
        self.assertEqual(self.upload('fake.pdf', b'not a pdf').status_code, 400)
        self.assertEqual(self.upload('program.exe', b'code').status_code, 400)
        self.assertEqual(self.upload(content=b'').status_code, 400)
        self.assertFalse(Document.objects.exists())

    def test_index_and_retry_replace_chunks(self):
        doc = self.ready()
        self.assertEqual(doc.status, 'ready')
        self.assertEqual(doc.chunks.count(), 1)
        self.client.post(f'/documents/{doc.pk}/retry/')
        with patch('knowledge.services.embed', return_value=[[1., 0.]]):
            call_command('process_documents', once=True)
        self.assertEqual(doc.chunks.count(), 1)

    def test_failed_model_marks_document_failed(self):
        self.upload()
        doc = Document.objects.get()
        with patch('knowledge.services.embed', side_effect=ModelError('Model unavailable')):
            process_document(doc.pk)
        doc.refresh_from_db()
        self.assertEqual(doc.status, 'failed')
        self.assertEqual(doc.chunks.count(), 0)

    def test_non_utf8_fails_without_false_ready(self):
        self.upload(content=b'\xff\xfe')
        doc = Document.objects.get()
        process_document(doc.pk)
        doc.refresh_from_db()
        self.assertEqual(doc.status, 'failed')

    def test_scanned_pdf_reports_no_readable_text(self):
        import io
        from pypdf import PdfWriter
        output = io.BytesIO()
        writer = PdfWriter(); writer.add_blank_page(width=100, height=100); writer.write(output)
        self.assertEqual(self.upload('scan.pdf', output.getvalue()).status_code, 201)
        doc = Document.objects.get(); process_document(doc.pk); doc.refresh_from_db()
        self.assertEqual(doc.status, 'failed')
        self.assertIn('OCR', doc.error)

    def test_chat_end_to_end_saves_answer_and_citations(self):
        doc = self.ready()
        with patch('knowledge.services.embed', return_value=[[1., 0.]]), patch('knowledge.services.ollama', return_value={'message': {'content': 'Employees receive 25 days [1].'}}):
            response = self.client.post('/chat/message/', json.dumps({'question': 'How much leave?', 'document_ids': [doc.pk]}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertIn('25 days', response.json()['answer'])
        self.assertEqual(response.json()['citations'][0]['document_id'], doc.pk)
        self.assertEqual(Message.objects.count(), 2)
        self.assertEqual(self.client.get(f"/chat/{response.json()['conversation_id']}/").status_code, 200)

    def test_unauthorized_documents_and_conversations_rejected(self):
        doc = self.ready()
        conversation = Conversation.objects.create(owner=self.user)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(f'/chat/{conversation.pk}/').status_code, 404)
        response = self.client.post('/chat/message/', json.dumps({'question':'leave?', 'document_ids':[doc.pk]}), content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_chat_invalid_payload_and_csrf(self):
        for payload in [[], {'question': 5}, {'question':'x','document_ids':['1']}, {}]:
            self.assertEqual(self.client.post('/chat/message/', json.dumps(payload), content_type='application/json').status_code, 400)
        client = Client(enforce_csrf_checks=True); client.force_login(self.user)
        self.assertEqual(client.post('/documents/upload/').status_code, 403)

    def test_model_failure_does_not_save_fake_answer(self):
        doc = self.ready()
        with patch('knowledge.views.answer', side_effect=ModelError('Start Ollama')):
            response = self.client.post('/chat/message/', json.dumps({'question':'leave?', 'document_ids':[doc.pk]}), content_type='application/json')
        self.assertEqual(response.status_code, 503)
        self.assertFalse(Message.objects.exists())

    def test_unknown_citation_is_not_displayed_as_grounded_answer(self):
        doc = self.ready()
        with patch('knowledge.services.embed', return_value=[[1.,0.]]), patch('knowledge.services.ollama', return_value={'message': {'content':'Wrong source [99]'}}):
            content, sources = answer('leave?', [doc], [])
        self.assertIn('could not produce', content)
        self.assertNotIn('99', [s['id'] for s in sources])

    def test_no_relevant_passages_does_not_call_chat_model(self):
        doc = self.ready()
        with patch('knowledge.services.embed', return_value=[[0.,1.]]), patch('knowledge.services.ollama') as model:
            content, sources = answer('unrelated?', [doc], [])
        self.assertEqual(sources, [])
        model.assert_not_called()

    def test_delete_cleans_vectors_file_and_historical_quotes(self):
        doc = self.ready(); path = doc.file.path
        conversation = Conversation.objects.create(owner=self.user)
        message = Message.objects.create(conversation=conversation, role='assistant', content='25 days', citations=[{'document_id':doc.pk}])
        self.assertEqual(self.client.post(f'/documents/{doc.pk}/delete/').status_code, 200)
        self.assertFalse(Document.objects.exists()); self.assertFalse(Chunk.objects.exists())
        from pathlib import Path
        self.assertFalse(Path(path).exists())
        message.refresh_from_db(); self.assertEqual(message.citations, []); self.assertNotIn('25 days',message.content)

    def test_processing_cannot_be_retried_or_deleted(self):
        self.upload(); doc=Document.objects.get(); doc.status='processing';doc.save()
        self.assertEqual(self.client.post(f'/documents/{doc.pk}/delete/').status_code,409)
        self.assertFalse(self.client.post(f'/documents/{doc.pk}/retry/').json()['ok'])

    def test_chunks_preserve_page_and_overlap(self):
        chunks = split_pages([(3, ' '.join(str(i) for i in range(300)))])
        self.assertEqual(chunks[0][0],3)
        self.assertEqual(chunks[0][1].split()[-40:],chunks[1][1].split()[:40])
