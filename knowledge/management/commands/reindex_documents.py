from django.conf import settings
from django.core.management.base import BaseCommand
from knowledge.models import Document


class Command(BaseCommand):
    help = 'Queue documents needing the current local Ollama embedding model.'

    def add_arguments(self, parser):
        parser.add_argument('--owner', help='Optionally restrict to one username.')

    def handle(self, *args, **options):
        documents = Document.objects.filter(status__in=['ready', 'failed']).exclude(embedding_model=settings.EMBED_MODEL)
        if options['owner']:
            documents = documents.filter(owner__username=options['owner'])
        count = documents.update(status='queued', error='')
        self.stdout.write(f'Queued {count} document(s) for local Ollama embeddings. Keep process_documents running.')
