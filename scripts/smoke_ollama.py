"""Real-model LangChain/Ollama integration check in a temporary database and file directory.

Run: .venv/bin/python scripts/smoke_ollama.py
Requires the configured Ollama models; never changes the project database.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'helloworld.settings')
import django
django.setup()

from django.test import Client, override_settings
from django.test.utils import setup_test_environment, setup_databases, teardown_databases, teardown_test_environment
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from knowledge.models import Document
from knowledge.services import process_document
import json
import time
from urllib.request import urlopen
from django.conf import settings

if '--wait' in sys.argv:
    print('Waiting up to five minutes for the configured model downloads…', flush=True)
    for attempt in range(150):
        try:
            with urlopen(settings.OLLAMA_URL + '/api/tags', timeout=2) as response:
                names = {model['name'] for model in json.load(response)['models']}
            if all(name in names or name + ':latest' in names for name in [settings.EMBED_MODEL, settings.CHAT_MODEL]):
                break
        except OSError:
            pass
        time.sleep(2)
    else:
        raise SystemExit('Models are not ready yet; finish the downloads and rerun this script.')

setup_test_environment()
database = setup_databases(verbosity=0, interactive=False)
try:
    with tempfile.TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
        user = User.objects.create_user('smoke-test-user')
        client = Client()
        client.force_login(user)
        content = (ROOT / 'examples/leave-policy.txt').read_bytes()
        response = client.post('/documents/upload/', {'files': [SimpleUploadedFile('leave-policy.txt', content)]})
        assert response.status_code == 201, response.content
        document = Document.objects.get()
        process_document(document.pk)
        document.refresh_from_db()
        assert document.status == 'ready', document.error
        response = client.post('/chat/message/', json.dumps({'question': 'How many days of annual leave do full-time employees receive?', 'document_ids': [document.pk]}), content_type='application/json')
        assert response.status_code == 200, response.content
        result = response.json()
        assert '25' in result['answer'], result
        assert result['citations'], result
        print('PASS: real LangChain + Ollama upload → extraction → embedding → retrieval → answer → saved citations')
        print(result['answer'])
finally:
    teardown_databases(database, verbosity=0)
    teardown_test_environment()
