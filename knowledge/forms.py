from pathlib import Path
from django import forms
from django.conf import settings


def validate_uploads(files):
    if not 1 <= len(files) <= 5:
        raise forms.ValidationError('Select between 1 and 5 files.')
    for file in files:
        if not file.size or file.size > settings.MAX_UPLOAD_BYTES:
            raise forms.ValidationError('Each file must be nonempty and at most 10 MB.')
        if Path(file.name).suffix.lower() not in {'.pdf', '.txt', '.md', '.csv'}:
            raise forms.ValidationError('Supported files: PDF, TXT, Markdown, and CSV.')
        header = file.read(1024)
        file.seek(0)
        if Path(file.name).suffix.lower() == '.pdf':
            if not header.startswith(b'%PDF-'):
                raise forms.ValidationError('This file does not contain a valid PDF header.')
        elif b'\x00' in header:
            raise forms.ValidationError('Text files must contain UTF-8 text, not binary data.')
