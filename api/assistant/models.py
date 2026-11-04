import json
from django.db import models
from django.utils import timezone

class UploadedDocument(models.Model):
    title = models.CharField(max_length=255)
    original_filename = models.CharField(max_length=255)
    file_path = models.CharField(max_length=500)
    file_size = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    total_chunks = models.IntegerField(default=0)
    uploaded_at = models.DateTimeField(default=timezone.now)
    indexed_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-uploaded_at']

    def __str__(self):
        return f"{self.title} ({'Active' if self.is_active else 'Inactive'})"

class DocumentChunk(models.Model):
    document = models.ForeignKey(UploadedDocument, on_delete=models.CASCADE, related_name='chunks')
    chunk_index = models.IntegerField()
    section_title = models.CharField(max_length=255, default='General')
    section_hierarchy = models.JSONField(default=list, blank=True)
    content = models.TextField()
    token_count = models.IntegerField(default=0)
    embedding_json = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['document', 'chunk_index']

    def get_embedding(self):
        if self.embedding_json:
            return json.loads(self.embedding_json)
        return None

    def set_embedding(self, emb_list):
        self.embedding_json = json.dumps(emb_list)

    def __str__(self):
        return f"{self.document.title} - Chunk #{self.chunk_index} ({self.section_title})"

class ChatUsageLog(models.Model):
    user_id = models.CharField(max_length=255, default="anonymous")
    session_id = models.CharField(max_length=255, default="default")
    user_message = models.TextField()
    bot_response = models.TextField()
    prompt_tokens = models.IntegerField(default=0)
    completion_tokens = models.IntegerField(default=0)
    total_tokens = models.IntegerField(default=0)
    token_source = models.CharField(max_length=24, default='unavailable')
    model_name = models.CharField(max_length=128, blank=True, default='')
    confidence = models.FloatField(null=True, blank=True, default=None)
    confidence_type = models.CharField(max_length=32, blank=True, default="")
    confidence_basis = models.TextField(blank=True, default="")
    retrieved_chunks = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user_id} ({self.session_id}) at {self.created_at}"
