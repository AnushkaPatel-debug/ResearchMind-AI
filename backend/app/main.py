import json
from uuid import uuid4
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from .config import settings
from .db import SessionLocal, Document, Conversation, Message
from .rag.pipeline import Retriever, extract_pdf
from .agents.workflow import ResearchWorkflow

app = FastAPI(title='ResearchMind AI', version='1.0.0', description='Evidence-grounded document research API')
app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_origin], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])
_retriever = None

def get_retriever():
    global _retriever
    if _retriever is None:
        _retriever = Retriever()
    return _retriever

def get_db():
    with SessionLocal() as db:
        yield db

class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=4000)
    mode: str = Field(default='chat', pattern='^(chat|compare|report)$')
    document_ids: list[str] = Field(default_factory=list)
    conversation_id: str | None = None

@app.get('/api/health')
def health():
    return {'status': 'ok', 'ai_configured': bool(settings.openai_api_key)}

@app.get('/api/stats')
def stats(db: Session = Depends(get_db)):
    docs = db.query(Document).all()
    return {'documents': len(docs), 'pages': sum(d.pages for d in docs), 'chunks': sum(d.chunks for d in docs), 'conversations': db.query(Conversation).count()}

@app.get('/api/documents')
def documents(db: Session = Depends(get_db)):
    return [{'id': d.id, 'name': d.name, 'pages': d.pages, 'chunks': d.chunks, 'uploaded_at': d.uploaded_at.isoformat()} for d in db.query(Document).order_by(Document.uploaded_at.desc()).all()]

@app.post('/api/documents', status_code=201)
async def upload(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename or not file.filename.lower().endswith('.pdf'):
        raise HTTPException(400, 'Only PDF files are supported')
    data = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f'Maximum file size is {settings.max_upload_mb} MB')
    if not data.startswith(b'%PDF'):
        raise HTTPException(400, 'Invalid PDF file')
    try:
        pages = extract_pdf(data)
    except Exception:
        raise HTTPException(400, 'PDF could not be read')
    if not any(text.strip() for _, text in pages):
        raise HTTPException(422, 'No extractable text found. Scanned PDFs need OCR.')
    doc_id = str(uuid4())
    try:
        chunks = get_retriever().add(doc_id, file.filename[:255], pages)
    except Exception as exc:
        raise HTTPException(503, f'Indexing failed: {str(exc)[:200]}')
    doc = Document(id=doc_id, name=file.filename[:255], pages=len(pages), chunks=chunks)
    db.add(doc)
    db.commit()
    return {'id': doc.id, 'name': doc.name, 'pages': doc.pages, 'chunks': doc.chunks}

@app.delete('/api/documents/{document_id}')
def delete_document(document_id: str, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(404, 'Document not found')
    get_retriever().delete(document_id)
    db.delete(doc)
    db.commit()
    return {'deleted': True}

@app.post('/api/ask')
def ask(payload: AskRequest, db: Session = Depends(get_db)):
    if payload.document_ids:
        existing = {d.id for d in db.query(Document).filter(Document.id.in_(payload.document_ids)).all()}
        if len(existing) != len(set(payload.document_ids)):
            raise HTTPException(400, 'One or more documents do not exist')
    conv = db.get(Conversation, payload.conversation_id) if payload.conversation_id else None
    if payload.conversation_id and not conv:
        raise HTTPException(404, 'Conversation not found')
    if not conv:
        conv = Conversation(id=str(uuid4()), title=payload.question[:75])
        db.add(conv)
    try:
        result = ResearchWorkflow(get_retriever()).run(payload.question, payload.mode, payload.document_ids or None)
    except Exception as exc:
        raise HTTPException(503, f'AI processing failed: {str(exc)[:200]}')
    db.add(Message(conversation_id=conv.id, role='user', content=payload.question))
    db.add(Message(conversation_id=conv.id, role='assistant', content=result['answer'], citations_json=json.dumps(result['citations'])))
    db.commit()
    return {'conversation_id': conv.id, **result}

@app.get('/api/conversations')
def conversations(db: Session = Depends(get_db)):
    return [{'id': c.id, 'title': c.title, 'created_at': c.created_at.isoformat()} for c in db.query(Conversation).order_by(Conversation.created_at.desc()).all()]

@app.get('/api/conversations/{conversation_id}')
def conversation(conversation_id: str, db: Session = Depends(get_db)):
    conv = db.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(404, 'Conversation not found')
    return {'id': conv.id, 'title': conv.title, 'messages': [{'role': m.role, 'content': m.content, 'citations': json.loads(m.citations_json)} for m in db.query(Message).filter_by(conversation_id=conv.id).order_by(Message.id).all()]}
