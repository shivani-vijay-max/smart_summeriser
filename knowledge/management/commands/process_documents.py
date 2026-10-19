import time
from django.core.management.base import BaseCommand
from knowledge.models import Document
from knowledge.services import process_document


class Command(BaseCommand):
    help = 'Process SQLite-backed indexing queue. Run continuously alongside runserver.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Drain current queue then exit.')
        parser.add_argument('--recover', action='store_true', help='Reset interrupted jobs; use only when no other workers run.')

    def handle(self, *args, **options):
        if options['recover']:
            Document.objects.filter(status='processing').update(status='queued')
        self.stdout.write('Indexing worker started. Ctrl+C to stop.')
        try:
            while True:
                ids = list(Document.objects.filter(status='queued').values_list('pk', flat=True))
                for pk in ids:
                    process_document(pk)
                    self.stdout.write(f'Processed document {pk}')
                if options['once']:
                    return
                time.sleep(2)
        except KeyboardInterrupt:
            self.stdout.write('Worker stopped. Use --recover if an indexing job was interrupted.')
