from django.urls import path
from . import views

urlpatterns = [
    path('bootstrap/', views.bootstrap, name='bootstrap'),
    path('login/', views.erp_login, name='login_view'),
    path('logout/', views.logout_view, name='logout_view'),
    path('auth/erp/login/', views.erp_login, name='erp_login'),
    path('erp/login/', views.erp_login, name='erp_login_alias'),
    path('auth/erp/context/', views.erp_context, name='erp_context'),
    # Auth
    path('auth/register/', views.register_user, name='register_user'),
    path('auth/login/', views.login_user, name='login_user'),

    # Document upload & RAG chunking management
    path('documents/', views.document_list, name='document_list'),
    path('documents/upload/', views.document_upload, name='document_upload'),
    path('documents/activate/', views.document_activate, name='document_activate'),
    path('documents/<int:doc_id>/chunks/', views.document_chunks, name='document_chunks'),
    path('documents/<int:doc_id>/delete/', views.document_delete, name='document_delete'),

    # Support Chatbot
    path('chat/', views.chat_query, name='chat_query'),
    path('history/', views.chat_history, name='chat_history'),
    path('sessions/', views.chat_sessions, name='chat_sessions'),
    path('sessions/delete/', views.delete_session, name='delete_session'),
    path('sessions/<str:session_id>/delete/', views.delete_session_by_id, name='delete_session_by_id'),
    path('sessions/<str:session_id>/', views.session_history_by_id, name='session_history_by_id'),
]
