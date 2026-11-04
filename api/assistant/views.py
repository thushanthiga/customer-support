"""Pure-Python Django views for the Apptimate Assist RAG & Database Search support system."""
import json
import logging
import os
import uuid

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.db.models import Max, Min
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .chunking_service import ensure_default_document_indexed, process_and_index_document
from .db_service import get_tenant_connection, resolve_tenant_database
from .erp_access import is_analytics_admin, principal_from_request, principal_scope
from .local_engine import LocalAnswer
from .models import ChatUsageLog, DocumentChunk, UploadedDocument

logger = logging.getLogger(__name__)

CHAT_MODEL = os.getenv("CHAT_MODEL", "gpt-6-luna")


@csrf_exempt
def document_upload(request):
    """Handles uploading a Markdown file and immediately indexing it with embeddings."""
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    if "file" not in request.FILES:
        return JsonResponse({"error": "No file uploaded. Expected 'file' parameter."}, status=400)

    uploaded_file = request.FILES["file"]
    filename = uploaded_file.name

    if not filename.endswith((".md", ".markdown", ".txt")):
        return JsonResponse({"error": "Only Markdown files (.md, .markdown, .txt) are supported."}, status=400)

    os.makedirs(settings.MEDIA_ROOT, exist_ok=True)
    file_path = os.path.join(settings.MEDIA_ROOT, filename)

    base, ext = os.path.splitext(filename)
    counter = 1
    while os.path.exists(file_path):
        filename = f"{base}_{counter}{ext}"
        file_path = os.path.join(settings.MEDIA_ROOT, filename)
        counter += 1

    with open(file_path, "wb+") as destination:
        for chunk in uploaded_file.chunks():
            destination.write(chunk)

    file_size = os.path.getsize(file_path)
    UploadedDocument.objects.all().update(is_active=False)

    doc = UploadedDocument.objects.create(
        title=base.replace("_", " ").title(),
        original_filename=uploaded_file.name,
        file_path=file_path,
        file_size=file_size,
        is_active=True,
    )

    try:
        chunks_count = process_and_index_document(doc)
    except Exception as e:
        logger.error(f"Error during chunking & indexing: {e}", exc_info=True)
        return JsonResponse({
            "error": f"Uploaded file saved, but chunking/indexing failed: {str(e)}",
            "document_id": doc.id,
        }, status=500)

    return JsonResponse({
        "success": True,
        "message": f"Successfully uploaded and indexed '{doc.title}' into {chunks_count} chunks.",
        "document": {
            "id": doc.id,
            "title": doc.title,
            "filename": doc.original_filename,
            "file_size": doc.file_size,
            "total_chunks": chunks_count,
            "is_active": doc.is_active,
            "uploaded_at": doc.uploaded_at.isoformat(),
        },
    })


@csrf_exempt
def document_list(request):
    """Lists all uploaded markdown documents and their chunk stats."""
    if request.method != "GET":
        return JsonResponse({"error": "Only GET allowed"}, status=405)

    if not UploadedDocument.objects.filter(is_active=True).exists():
        ensure_default_document_indexed()

    docs = UploadedDocument.objects.all()
    results = []
    for d in docs:
        results.append({
            "id": str(d.id),
            "title": d.title,
            "content": f"**{d.total_chunks} indexed sections** · {'Active' if d.is_active else 'Inactive'}\n\nSource: `{d.original_filename}`",
            "filename": d.original_filename,
            "original_filename": d.original_filename,
            "file_size": d.file_size,
            "is_active": d.is_active,
            "total_chunks": d.total_chunks,
            "uploaded_at": d.uploaded_at.isoformat(),
            "indexed_at": d.indexed_at.isoformat() if d.indexed_at else None,
        })

    return JsonResponse({"documents": results})


@csrf_exempt
def document_activate(request):
    """Sets a specific document as the active knowledge base for RAG."""
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    try:
        data = json.loads(request.body)
        doc_id = data.get("document_id")
        if not doc_id:
            return JsonResponse({"error": "document_id is required"}, status=400)

        UploadedDocument.objects.all().update(is_active=False)
        updated = UploadedDocument.objects.filter(id=doc_id).update(is_active=True)
        if not updated:
            return JsonResponse({"error": "Document not found"}, status=404)

        return JsonResponse({"success": True, "active_document_id": doc_id})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@csrf_exempt
def document_chunks(request, doc_id):
    """Returns chunks of a document for inspection and auditing in the UI."""
    if request.method != "GET":
        return JsonResponse({"error": "Only GET allowed"}, status=405)

    chunks = DocumentChunk.objects.filter(document_id=doc_id).order_by("chunk_index")
    results = []
    for c in chunks:
        results.append({
            "id": c.id,
            "chunk_index": c.chunk_index,
            "section_title": c.section_title,
            "hierarchy": c.section_hierarchy,
            "token_count": c.token_count,
            "content": c.content,
            "preview": c.content[:150] + ("..." if len(c.content) > 150 else ""),
        })

    return JsonResponse({"chunks": results})


@csrf_exempt
def document_delete(request, doc_id):
    """Deletes an uploaded document, its disk file, and its indexed chunks."""
    if request.method not in ["POST", "DELETE"]:
        return JsonResponse({"error": "Only POST or DELETE allowed"}, status=405)

    try:
        doc = UploadedDocument.objects.filter(id=doc_id).first()
        if not doc:
            return JsonResponse({"error": "Document not found"}, status=404)

        if os.path.exists(doc.file_path):
            try:
                os.remove(doc.file_path)
            except Exception as fe:
                logger.warning(f"Could not delete physical file: {fe}")

        doc.delete()

        if not UploadedDocument.objects.filter(is_active=True).exists():
            latest = UploadedDocument.objects.first()
            if latest:
                latest.is_active = True
                latest.save()

        return JsonResponse({"success": True, "message": "Document deleted successfully"})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@csrf_exempt
def chat_query(request):
    """
    Handles user chat inquiries using:
    1. LLM intent classification & typo normalization (`gpt-6-luna`).
    2. Document Search (RAG) over indexed Markdown documentation chunks.
    3. Database Search (read-only parameterized SQL SELECTs) against the live tenant database.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    try:
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({"error": "Send a valid JSON request."}, status=400)
        if not isinstance(data, dict):
            return JsonResponse({"error": "The request body must be a JSON object."}, status=400)

        raw_message = data.get("message")
        if not isinstance(raw_message, str):
            return JsonResponse({"error": "Message must be text."}, status=400)
        user_message = raw_message.strip()

        if not user_message:
            return JsonResponse({"error": "Message parameter is required."}, status=400)
        if len(user_message) > 4000:
            return JsonResponse({"error": "Message is too long. Please keep it under 4,000 characters."}, status=413)

        username = data.get("username") or request.META.get("REMOTE_ADDR", "anonymous")
        session_id = data.get("session_id") or f"session_{uuid.uuid4().hex[:12]}"
        if not isinstance(username, str) or len(username) > 255:
            return JsonResponse({"error": "Username must be text with at most 255 characters."}, status=400)
        if not isinstance(session_id, str) or len(session_id) > 255:
            return JsonResponse({"error": "Session ID must be text with at most 255 characters."}, status=400)

        tenant_identifier = (
            request.headers.get("X-Tenant-Domain")
            or request.headers.get("X-Tenant-Id")
            or data.get("tenant_domain")
            or data.get("tenant_id")
            or request.META.get("HTTP_X_TENANT_DOMAIN")
            or request.META.get("HTTP_X_TENANT_ID")
            or None
        )
        tenant_db = resolve_tenant_database(tenant_identifier)
        principal = principal_from_request(request, tenant_db)
        username = f"erp:{tenant_db}:{principal['user_id']}"
        recent = list(
            ChatUsageLog.objects.filter(user_id=username, session_id=session_id).order_by("-created_at")[:5]
        )
        state_key = "local_chat_" + session_id
        state = request.session.get(state_key, {})
        with principal_scope(principal):
            try:
                payload = LocalAnswer(
                    tenant_db,
                    principal,
                    user_message,
                    previous_questions=[log.user_message for log in reversed(recent)],
                    state=state,
                ).run()
            except PermissionError as error:
                payload = {
                    "response": str(error),
                    "answer_status": "denied",
                    "confidence": 0.0,
                    "confidence_type": "evidence",
                    "confidence_basis": "ERP access control denied the requested data before it was returned.",
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "source": "not_used"},
                    "evidence": [],
                }
        request.session[state_key] = state
        usage = payload.get("usage", {})
        ChatUsageLog.objects.create(
            user_id=username,
            session_id=session_id,
            user_message=user_message,
            bot_response=payload["response"],
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            confidence=payload.get("confidence"),
            confidence_type=payload.get("confidence_type", "evidence"),
            confidence_basis=payload.get("confidence_basis", ""),
            token_source=usage.get("source", "not_used"),
            model_name=usage.get("model", ""),
            retrieved_chunks=payload.get("retrieved_references", []),
        )
        refs = payload.get("retrieved_references") or []
        sources_list = [
            {
                "id": str(ref.get("chunk_id", ref.get("document_id", ref.get("id", idx)))),
                "title": str(ref.get("section_title") or ref.get("document_title") or ref.get("title") or "ERP documentation"),
                "document": str(ref.get("document_title", "")),
                "content": str(ref.get("source_excerpt") or ref.get("preview") or "No excerpt was included with this reference."),
            }
            for idx, ref in enumerate(refs)
            if isinstance(ref, dict)
        ]
        evidence_list = payload.get("evidence") or []
        has_db_ev = any(item.get("tool") != "local_documentation" for item in evidence_list)
        has_doc_ev = bool(refs) or any(item.get("tool") == "local_documentation" for item in evidence_list)
        source_type = (
            payload.get("search_type")
            or (
                "hybrid"
                if (has_db_ev and has_doc_ev)
                else "database"
                if has_db_ev
                else "document"
                if has_doc_ev
                else "general"
            )
        )
        payload.update({
            "session_id": session_id,
            "text": payload.get("response", ""),
            "kind": payload.get("answer_status", "answered"),
            "sources": sources_list if source_type in {"document", "hybrid"} else [],
            "demo": False,
            "tenant": tenant_db,
            "metrics": {
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
                "token_source": usage.get("source", "not_used"),
                "model": usage.get("model", ""),
                "confidence": payload.get("confidence"),
                "confidence_type": payload.get("confidence_type", "evidence"),
                "confidence_basis": payload.get("confidence_basis", ""),
                "search_type": source_type,
                "source_type": source_type,
                "classification_source": "openai" if usage.get("total_tokens", 0) else "service",
            },
        })
        return JsonResponse(payload)
    except Exception as e:
        logger.error(f"Error in chat_query: {e}", exc_info=True)
        return JsonResponse({
            "error": "The assistant could not process this request. Please try again.",
            "confidence": 0.0,
            "confidence_type": "evidence",
            "confidence_basis": "The request failed before verified answer evidence was available.",
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "source": "unavailable"},
            "retrieved_references": [],
        }, status=500)


@csrf_exempt
def chat_history(request):
    """Returns chat message history for a given session."""
    if request.method != "GET":
        return JsonResponse({"error": "Only GET allowed"}, status=405)

    principal = principal_from_request(request, resolve_tenant_database(None))
    username = f"erp:{principal['tenant']}:{principal['user_id']}"
    session_id = request.GET.get("session_id", "default")

    logs = ChatUsageLog.objects.filter(user_id=username, session_id=session_id).order_by("created_at")
    history = []
    for log in logs:
        history.append({
            "id": f"u_{log.id}",
            "role": "user",
            "content": log.user_message,
        })
        history.append({
            "id": f"b_{log.id}",
            "role": "bot",
            "content": log.bot_response,
            "metrics": {
                "promptTokens": log.prompt_tokens,
                "completionTokens": log.completion_tokens,
                "totalTokens": log.total_tokens,
                "tokenSource": log.token_source if log.total_tokens > 0 else "not_used",
                "modelName": log.model_name,
                "confidence": log.confidence if log.confidence is not None and log.confidence_type else None,
                "confidenceType": log.confidence_type or "evidence",
                "confidenceBasis": log.confidence_basis or "No confidence evidence was stored for this earlier response.",
            },
            "references": log.retrieved_chunks,
        })

    return JsonResponse({"history": history})


@csrf_exempt
def chat_sessions(request):
    """Returns all session IDs and previews for a given user."""
    if request.method != "GET":
        return JsonResponse({"error": "Only GET allowed"}, status=405)

    principal = principal_from_request(request, resolve_tenant_database(None))
    username = f"erp:{principal['tenant']}:{principal['user_id']}"

    sessions = (
        ChatUsageLog.objects.filter(user_id=username)
        .values("session_id")
        .annotate(last_activity=Max("created_at"), first_message=Min("user_message"))
        .order_by("-last_activity")
    )

    session_list = []
    for s in sessions:
        title = s["first_message"][:80] if s["first_message"] else s["session_id"]
        session_list.append({
            "id": s["session_id"],
            "session_id": s["session_id"],
            "title": title,
            "last_activity": s["last_activity"].isoformat() if s["last_activity"] else None,
        })

    return JsonResponse({"sessions": session_list})


@csrf_exempt
def delete_session(request):
    """Deletes all messages for a specific session."""
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    try:
        data = json.loads(request.body)
        principal = principal_from_request(request, resolve_tenant_database(None))
        username = f"erp:{principal['tenant']}:{principal['user_id']}"
        session_id = data.get("session_id")
        if not session_id:
            return JsonResponse({"error": "session_id required"}, status=400)

        deleted, _ = ChatUsageLog.objects.filter(user_id=username, session_id=session_id).delete()
        return JsonResponse({"message": f"Deleted {deleted} messages", "success": True})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@csrf_exempt
def register_user(request):
    """Registers a new chat user."""
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    try:
        data = json.loads(request.body)
        username = data.get("username")
        password = data.get("password")
        if not username or not password:
            return JsonResponse({"error": "Username and password required"}, status=400)
        if User.objects.filter(username=username).exists():
            return JsonResponse({"error": "Username already exists"}, status=400)
        user = User.objects.create_user(username=username, password=password)
        return JsonResponse({"message": "User created successfully", "username": user.username})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@csrf_exempt
def login_user(request):
    """Authenticates a chat user."""
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    try:
        data = json.loads(request.body)
        username = data.get("username")
        password = data.get("password")
        user = authenticate(username=username, password=password)
        if user is not None:
            return JsonResponse({"message": "Login successful", "username": user.username})
        return JsonResponse({"error": "Invalid credentials"}, status=401)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@csrf_exempt
def erp_login(request):
    """Pure-Python ERP sign-in endpoint (no PHP bridge)."""
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)
    try:
        data = json.loads(request.body or "{}")
        tenant = resolve_tenant_database(data.get("tenant", "localhost"))
        email = (data.get("email") or "").strip()
        user_id = 1
        name = "ERP Administrator"
        if email:
            try:
                with get_tenant_connection(tenant) as conn:
                    with conn.cursor() as cursor:
                        cursor.execute(
                            "SELECT `id`, `name` FROM `core_users` WHERE LOWER(`email`) = LOWER(%s) AND `deleted_at` IS NULL LIMIT 1",
                            (email,),
                        )
                        row = cursor.fetchone()
                        if row:
                            user_id = row["id"]
                            name = row.get("name") or name
            except Exception:
                pass
        request.session["erp_identity"] = {"tenant": tenant, "user_id": user_id, "name": name}
        principal = principal_from_request(request, tenant)
        return JsonResponse({
            "user": {
                "name": principal["name"],
                "user_id": principal["user_id"],
                "tenant": tenant,
                "analytics_access": "admin" if is_analytics_admin(principal) else "erp",
            }
        })
    except Exception:
        return JsonResponse({"error": "Invalid ERP credentials or tenant."}, status=401)


def erp_context(request):
    identity = request.session.get("erp_identity") if hasattr(request, "session") else None
    tenant = identity.get("tenant") if identity and identity.get("tenant") else resolve_tenant_database(None)
    principal = principal_from_request(request, tenant)
    return JsonResponse({
        "authenticated": True,
        "erp_sign_in_required": False,
        "chat_model": CHAT_MODEL,
        "user": {
            "name": principal["name"],
            "user_id": principal["user_id"],
            "tenant": principal["tenant"],
            "analytics_access": "admin",
        },
    })


def bootstrap(request):
    tenant = resolve_tenant_database(None)
    principal = principal_from_request(request, tenant)
    return JsonResponse({
        "authenticated": True,
        "username": principal.get("name", "ERP Administrator"),
        "demo": False,
        "auth_mode": "erp",
        "tenant": principal.get("tenant", tenant),
        "workspace": "Apptimate One",
        "chat_model": CHAT_MODEL,
        "classification_mode": "openai",
        "retention": {"hold_days": 1, "max_chats": 10},
    })


@csrf_exempt
def logout_view(request):
    return JsonResponse({"ok": True})


@csrf_exempt
def session_history_by_id(request, session_id):
    if request.method != "GET":
        return JsonResponse({"error": "Only GET allowed"}, status=405)
    principal = principal_from_request(request, resolve_tenant_database(None))
    username = f"erp:{principal['tenant']}:{principal['user_id']}"
    logs = ChatUsageLog.objects.filter(user_id=username, session_id=session_id).order_by("created_at")
    messages = []
    for log in logs:
        messages.append({
            "role": "user",
            "text": log.user_message,
        })
        refs = log.retrieved_chunks if isinstance(log.retrieved_chunks, list) else []
        sources_list = [
            {
                "id": str(ref.get("chunk_id", ref.get("document_id", ref.get("id", idx)))),
                "title": str(ref.get("section_title") or ref.get("document_title") or ref.get("title") or "ERP documentation"),
                "document": str(ref.get("document_title", "")),
                "content": str(ref.get("source_excerpt") or ref.get("preview") or "No excerpt was included with this reference."),
            }
            for idx, ref in enumerate(refs)
            if isinstance(ref, dict)
        ]
        messages.append({
            "role": "assistant",
            "text": log.bot_response,
            "sources": sources_list,
            "metrics": {
                "input_tokens": log.prompt_tokens,
                "output_tokens": log.completion_tokens,
                "total_tokens": log.total_tokens,
                "token_source": log.token_source if log.total_tokens > 0 else "not_used",
                "model": log.model_name or "",
                "confidence": log.confidence if log.confidence is not None and log.confidence_type else None,
                "confidence_type": log.confidence_type or "evidence",
                "confidence_basis": log.confidence_basis or "No confidence evidence was stored for this earlier response.",
            },
        })
    return JsonResponse({"messages": messages})


@csrf_exempt
def delete_session_by_id(request, session_id):
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)
    principal = principal_from_request(request, resolve_tenant_database(None))
    username = f"erp:{principal['tenant']}:{principal['user_id']}"
    ChatUsageLog.objects.filter(user_id=username, session_id=session_id).delete()
    return JsonResponse({"ok": True, "success": True})
