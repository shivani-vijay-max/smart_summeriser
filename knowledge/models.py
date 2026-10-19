from uuid import uuid4
from pathlib import Path
from django.conf import settings
from django.db import models


def private_path(instance, filename):
    return f'{instance.owner_id}/{uuid4().hex}{Path(filename).suffix.lower()}'


class Document(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    file = models.FileField(upload_to=private_path)
    name = models.CharField(max_length=255)
    size = models.PositiveIntegerField()
    status = models.CharField(max_length=20, default='queued')
    error = models.TextField(blank=True)
    embedding_model = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class Chunk(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name='chunks')
    text = models.TextField()
    page = models.PositiveIntegerField(null=True)
    position = models.PositiveIntegerField()
    vector = models.JSONField()


class Conversation(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField(max_length=100, default='New conversation')
    created_at = models.DateTimeField(auto_now_add=True)


class Message(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=12)
    content = models.TextField()
    citations = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
