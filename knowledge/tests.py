import json
import tempfile
from unittest.mock import patch
from django.test import TransactionTestCase, Client, override_settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from .models import Document, Chunk, Conversation, Message
from .services import process_document, answer, ModelError, split_pages

from typing import Any
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field


class LocalAgentTestModel(BaseChatModel):
    mode: str = 'research'
    final_text: str = '{"answerable":true,"answer":"Employees receive 25 days.","source_ids":["1"]}'
    refinements: list[str] = Field(default_factory=list)
    calls: int = 0
    last_messages: list[Any] = Field(default_factory=list)

    @property
    def _llm_type(self):
        return 'local-agent-test-model'

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        self.last_messages = list(messages)
        index = sum(isinstance(m, ToolMessage) for m in messages) - 1
        if self.mode == 'research' and index < len(self.refinements):
            message = AIMessage(content='', tool_calls=[{'name':'search_documents','args':{'query':self.refinements[max(index,0)]},'id':f'refine-{index}'}])
        else:
            message = AIMessage(content=self.final_text if self.mode == 'answer' else 'Research complete')
        return ChatResult(generations=[ChatGeneration(message=message)])


class WorkflowTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings = override_settings(MEDIA_ROOT=self.directory.name)
        self.settings.enable()
        self.addCleanup(self.settings.disable)
        self.user = User.objects.create_user('alice', password='test-password')
        self.other = User.objects.create_user('bob', password='other-password')
        self.client.force_login(self.user)
        self.research_model = LocalAgentTestModel()
        self.final_model = LocalAgentTestModel(mode='answer')
        self.last_schema = None
        def factory(format=None):
            if format is not None:
                self.last_schema = format
                return self.final_model
            return self.research_model
        mocked = patch('knowledge.agent.get_chat_model', side_effect=factory)
        mocked.start()
        self.addCleanup(mocked.stop)

    def upload(self, name='policy.txt', content=b'Employees receive 25 days of annual leave.'):
        return self.client.post('/documents/upload/', {'files': [SimpleUploadedFile(name, content)]})

    def ready(self):
        self.upload()
        document = Document.objects.get()
        with patch('knowledge.services.embed', return_value=[[1.0, 0.0]]):
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
        self.assertNotEqual(doc.file.name.rsplit('/',1)[-1], doc.name)
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
        with patch('knowledge.services.embed', return_value=[[1.0, 0.0]]):
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
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.write(output)
        self.assertEqual(self.upload('scan.pdf', output.getvalue()).status_code, 201)
        doc = Document.objects.get()
        process_document(doc.pk)
        doc.refresh_from_db()
        self.assertEqual(doc.status, 'failed')
        self.assertIn('OCR', doc.error)

    def test_chat_end_to_end_saves_answer_and_citations(self):
        doc = self.ready()
        with patch('knowledge.services.embed', return_value=[[1.0, 0.0]]), patch.object(self.final_model, 'final_text', json.dumps({'answerable': True, 'answer': 'Employees receive 25 days.', 'source_ids': ['1']})):
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
        response = self.client.post('/chat/message/', json.dumps({'question': 'leave?', 'document_ids': [doc.pk]}), content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_chat_invalid_payload_and_csrf(self):
        for payload in [[], {'question': 5}, {'question': 'x', 'document_ids': ['1']}, {}]:
            self.assertEqual(self.client.post('/chat/message/', json.dumps(payload), content_type='application/json').status_code, 400)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post('/documents/upload/').status_code, 403)

    def test_model_failure_does_not_save_fake_answer(self):
        doc = self.ready()
        with patch('knowledge.views.answer', side_effect=ModelError('Start Ollama')):
            response = self.client.post('/chat/message/', json.dumps({'question': 'leave?', 'document_ids': [doc.pk]}), content_type='application/json')
        self.assertEqual(response.status_code, 503)
        self.assertFalse(Message.objects.exists())

    def test_unknown_citation_is_not_displayed_as_grounded_answer(self):
        doc = self.ready()
        with patch('knowledge.services.embed', return_value=[[1.0, 0.0]]), patch.object(self.final_model, 'final_text', json.dumps({'answerable': True, 'answer': 'Wrong source [99]', 'source_ids': ['99']})):
            content, sources = answer('leave?', [doc], [])
        self.assertIn('could not produce', content)
        self.assertNotIn('99', [s['id'] for s in sources])

    def test_no_relevant_passages_does_not_call_chat_model(self):
        doc = self.ready()
        with override_settings(RAG_MIN_SCORE=0.35), patch('knowledge.services.embed', return_value=[[0.0, 1.0]]), patch('knowledge.agent.get_chat_model') as model:
            content, sources = answer('unrelated?', [doc], [])
        self.assertEqual(sources, [])
        model.assert_not_called()

    def test_delete_cleans_vectors_file_and_historical_quotes(self):
        doc = self.ready()
        path = doc.file.path
        conversation = Conversation.objects.create(owner=self.user)
        message = Message.objects.create(conversation=conversation, role='assistant', content='25 days', citations=[{'document_id': doc.pk}])
        self.assertEqual(self.client.post(f'/documents/{doc.pk}/delete/').status_code, 200)
        self.assertFalse(Document.objects.exists())
        self.assertFalse(Chunk.objects.exists())
        from pathlib import Path
        self.assertFalse(Path(path).exists())
        message.refresh_from_db()
        self.assertEqual(message.citations, [])
        self.assertNotIn('25 days', message.content)

    def test_processing_cannot_be_retried_or_deleted(self):
        self.upload()
        doc = Document.objects.get()
        doc.status = 'processing'
        doc.save()
        self.assertEqual(self.client.post(f'/documents/{doc.pk}/delete/').status_code, 409)
        self.assertFalse(self.client.post(f'/documents/{doc.pk}/retry/').json()['ok'])

    def test_chunks_preserve_page_and_overlap(self):
        chunks = split_pages([(3, ' '.join((str(i) for i in range(300))))])
        self.assertEqual(chunks[0][0], 3)
        self.assertEqual(chunks[0][1].split()[-40:], chunks[1][1].split()[:40])

    def test_ollama_is_configured_without_openai_key_or_client(self):
        from django.conf import settings
        self.assertEqual(settings.EMBED_MODEL, 'embeddinggemma')
        self.assertEqual(settings.CHAT_MODEL, 'llama3.2:3b')
        self.assertFalse(hasattr(settings, 'OPENAI_API_KEY'))
        self.assertContains(self.client.get('/knowledge/'), 'Local · Ollama')
        self.assertNotContains(self.client.get('/knowledge/'), 'OpenAI key missing')

    def test_hosted_vectors_are_not_selectable_and_can_be_reindexed_locally(self):
        doc = self.ready()
        Document.objects.filter(pk=doc.pk).update(embedding_model='openai:text-embedding-3-small')
        doc.refresh_from_db()
        self.assertTrue(self.client.get('/documents/').json()['documents'][0]['needs_reindex'])
        with self.assertRaisesMessage(ModelError, 'Re-index'):
            answer('leave?', [doc], [])
        call_command('reindex_documents')
        doc.refresh_from_db()
        self.assertEqual(doc.status, 'queued')
        with patch('knowledge.services.embed', return_value=[[1.0, 0.0]]):
            process_document(doc.pk)
        doc.refresh_from_db()
        self.assertEqual(doc.embedding_model, 'embeddinggemma')
        self.assertFalse(self.client.get('/documents/').json()['documents'][0]['needs_reindex'])

    def test_resume_name_with_low_similarity_reaches_model_and_renders_citation(self):
        doc = self.ready()
        doc.chunks.update(text='Alex Example. Software developer with Python experience.')
        with override_settings(RAG_MIN_SCORE=None), patch('knowledge.services.embed', return_value=[[0.143, 0.99]]), patch.object(self.final_model, 'final_text', json.dumps({'answerable': True, 'answer': 'The candidate is Alex Example.', 'source_ids': ['1']})) as model:
            content, sources = answer('what is the name of the candidate', [doc], [])
        self.assertIn('Alex Example', content)
        self.assertIn('[1]', content)
        self.assertEqual(sources[0]['document_id'], doc.pk)
        self.assertIn('Alex Example', self.final_model.last_messages[-1].content)
        self.assertIn('source_ids', self.last_schema['properties'])

    def test_model_can_decline_when_retrieved_passages_do_not_answer(self):
        doc = self.ready()
        with override_settings(RAG_MIN_SCORE=None), patch('knowledge.services.embed', return_value=[[0.0, 1.0]]), patch.object(self.final_model, 'final_text', json.dumps({'answerable': False, 'answer': 'The document does not specify this.', 'source_ids': []})):
            content, sources = answer('What is the salary?', [doc], [])
        self.assertIn('could not find enough', content)
        self.assertEqual(sources, [])

    def test_current_question_is_not_polluted_by_unrelated_short_question(self):
        doc = self.ready()
        conversation = Conversation.objects.create(owner=self.user)
        previous = Message.objects.create(conversation=conversation, role='user', content='What is the annual leave policy?')
        with patch('knowledge.services.embed', return_value=[[1.0, 0.0]]) as embedding, patch.object(self.final_model, 'final_text', json.dumps({'answerable': True, 'answer': '25 days.', 'source_ids': ['1']})):
            answer('What is the candidate name?', [doc], [previous])
        embedding.assert_called_once_with(['What is the candidate name?'])

    def test_invalid_json_is_a_retryable_error_not_an_answer(self):
        doc = self.ready()
        with patch('knowledge.services.embed', return_value=[[1.0, 0.0]]), patch.object(self.final_model, 'final_text', 'not JSON'):
            with self.assertRaisesMessage(ModelError, 'invalid structured answer'):
                answer('leave?', [doc], [])


    def test_langchain_research_agent_can_refine_its_search(self):
        from .services import retrieve
        doc = self.ready()
        self.research_model.refinements = ['Python technologies']
        with patch('knowledge.services.embed', return_value=[[1.,0.]]), patch('knowledge.agent.retrieve', wraps=retrieve) as search:
            content, sources = answer('What skills?', [doc], [])
        self.assertEqual(search.call_count,2)
        self.assertEqual(self.research_model.calls,2)
        self.assertIn('[1]',content)
        self.assertEqual(sources[0]['document_id'],doc.pk)

    def test_search_budget_and_step_limit_still_produce_grounded_answer(self):
        from .services import retrieve
        doc=self.ready()
        self.research_model.refinements=['one','two','three','four','five','six','seven','eight']
        with patch('knowledge.services.embed',return_value=[[1.,0.]]), patch('knowledge.agent.retrieve',wraps=retrieve) as search:
            content,sources=answer('leave?', [doc], [])
        self.assertEqual(search.call_count,3)
        self.assertIn('25 days',content)
        self.assertEqual(sources[0]['document_id'],doc.pk)

    def test_search_tool_cannot_access_unselected_documents(self):
        from django.conf import settings
        doc=self.ready()
        hidden=Document.objects.create(owner=self.other,name='private.txt',file='unused',size=1,status='ready',embedding_model=settings.EMBED_MODEL)
        Chunk.objects.create(document=hidden,text='PRIVATE UNSELECTED CONTENT',vector=[1.,0.],position=0)
        self.research_model.refinements=['private information']
        with patch('knowledge.services.embed',return_value=[[1.,0.]]):
            content,sources=answer('leave?', [doc], [])
        self.assertEqual([s['document_id'] for s in sources],[doc.pk])
        self.assertNotIn('PRIVATE UNSELECTED CONTENT',self.final_model.last_messages[-1].content)

    def test_ollama_model_failure_is_safe_and_does_not_save_chat(self):
        import httpx
        doc=self.ready()
        with patch('knowledge.services.embed',return_value=[[1.,0.]]), patch('knowledge.agent.get_chat_model',side_effect=httpx.ConnectError('private transport details')):
            response=self.client.post('/chat/message/',json.dumps({'question':'leave?','document_ids':[doc.pk]}),content_type='application/json')
        self.assertEqual(response.status_code,503)
        self.assertNotIn('private transport details',response.json()['error'])
        self.assertFalse(Message.objects.exists())


    def test_latest_employer_uses_dates_even_when_model_picks_older_job(self):
        doc=self.ready()
        doc.chunks.update(text='WORK EXPERIENCE Engineer Earlier Systems 08/2019 - 12/2021. Work Student Newer Healthcare 11/2022 - 03/2025. EDUCATION University 2022 - 2026.')
        timeline={'answerable':True,'answer':'Earlier Systems','source_ids':['1'],'employment_history':[
            {'employer':'Earlier Systems','start_date':'08/2019','end_date':'12/2021','source_ids':['1']},
            {'employer':'Newer Healthcare','start_date':'11/2022','end_date':'03/2025','source_ids':['1']},
        ]}
        with patch('knowledge.services.embed',return_value=[[1.,0.]]), patch.object(self.final_model,'final_text',json.dumps(timeline)):
            text,sources=answer('what is the recent employer',[doc],[])
        self.assertIn('Newer Healthcare',text)
        self.assertIn('03/2025',text)
        self.assertNotIn('Earlier Systems',text)
        self.assertEqual(sources[0]['document_id'],doc.pk)

    def test_incomplete_employment_extraction_is_not_presented_as_latest(self):
        doc=self.ready()
        doc.chunks.update(text='WORK EXPERIENCE Earlier Systems 2019 - 2021. Newer Healthcare 2022 - 2025. EDUCATION University 2026 - 2027.')
        payload={'answerable':True,'answer':'Earlier Systems','source_ids':['1'],'employment_history':[
            {'employer':'Earlier Systems','start_date':'2019','end_date':'2021','source_ids':['1']} ]}
        with patch('knowledge.services.embed',return_value=[[1.,0.]]),patch.object(self.final_model,'final_text',json.dumps(payload)):
            text,sources=answer('What is the most recent employer?',[doc],[])
        self.assertIn('could not reliably compare',text)
        self.assertNotIn('listed is Earlier',text)
        self.assertEqual(self.final_model.calls,2)

    def test_wrong_prior_assistant_answer_is_excluded_from_chronology_prompt(self):
        doc=self.ready()
        doc.chunks.update(text='WORK EXPERIENCE Current Employer 2022 - Present.')
        conversation=Conversation.objects.create(owner=self.user)
        previous=Message.objects.create(conversation=conversation,role='assistant',content='WRONG PRIOR EMPLOYER CLAIM')
        payload={'answerable':True,'answer':'Current Employer','source_ids':['1'],'employment_history':[
            {'employer':'Current Employer','start_date':'2022','end_date':'Present','source_ids':['1']}]}
        with patch('knowledge.services.embed',return_value=[[1.,0.]]),patch.object(self.final_model,'final_text',json.dumps(payload)):
            text,sources=answer('Who is the current employer?',[doc],[previous])
        self.assertIn('Current Employer',text)
        self.assertNotIn('WRONG PRIOR',str([m.content for m in self.final_model.last_messages]))


    def test_misspelled_recent_employment_cannot_fall_back_to_generic_profession(self):
        doc=self.ready()
        doc.chunks.update(text='Alex Example Data Scientist. WORK EXPERIENCE Engineer Earlier Co 08/2019 - 12/2021. Work Student Healthcare Co 11/2022 - 03/2025.')
        payload={'answerable':True,'answer':'Data Scientist','source_ids':['1'],'employment_history':[
            {'employer':'Healthcare Co','role':'Work Student','start_date':'11/2022','end_date':'03/2025','source_ids':['1']}]}
        conversation=Conversation.objects.create(owner=self.user)
        old=Message.objects.create(conversation=conversation,role='assistant',content='The recent employment is Data Scientist.')
        for question in ['what is the recent employement','what is the recent employment','what is her latest role?']:
            with self.subTest(question=question),patch('knowledge.services.embed',return_value=[[1.,0.]]),patch.object(self.final_model,'final_text',json.dumps(payload)):
                text,sources=answer(question,[doc],[old])
            self.assertIn('Work Student at Healthcare Co',text)
            self.assertIn('03/2025',text)
            self.assertNotIn('Data Scientist',text)
            self.assertIn('employment_history',self.last_schema['required'])
            self.assertNotIn('The recent employment is Data Scientist.',str([m.content for m in self.final_model.last_messages]))
            self.assertEqual(sources[0]['document_id'],doc.pk)
