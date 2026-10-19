from django.urls import path
from . import views

urlpatterns = [
    path('knowledge/', views.workspace, name='workspace'),
    path('accounts/signup/', views.signup, name='signup'),
    path('documents/', views.documents, name='documents'),
    path('documents/upload/', views.upload, name='upload'),
    path('documents/<int:pk>/download/', views.download, name='download'),
    path('documents/<int:pk>/delete/', views.delete, name='delete-document'),
    path('documents/<int:pk>/retry/', views.retry, name='retry-document'),
    path('chat/conversations/', views.conversations, name='conversations'),
    path('chat/<int:pk>/', views.history, name='history'),
    path('chat/message/', views.chat, name='chat'),
]
