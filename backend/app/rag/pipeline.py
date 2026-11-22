"""Local TF-IDF retrieval fallback plus optional OpenAI embeddings via Chroma."""
import math
import re
from collections import Counter
from pathlib import Path
from uuid import uuid4
import fitz
import chromadb
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
from ..config import settings


def split_text(text: str, chunk_size=1100, overlap=180):
    if chunk_size <= overlap or overlap < 0:
        raise ValueError('chunk_size must exceed nonnegative overlap')
    text = re.sub(r'\s+', ' ', text).strip()
    if not text:
        return []
    return [text[i:i + chunk_size] for i in range(0, len(text), chunk_size - overlap) if text[i:i + chunk_size] and (i == 0 or len(text[i:i + chunk_size]) > overlap)]


def extract_pdf(data: bytes):
    with fitz.open(stream=data, filetype='pdf') as doc:
        return [(i + 1, page.get_text()) for i, page in enumerate(doc)]


def tokenize(text):
    return re.findall(r'[a-z0-9]{2,}', text.lower())


def score(query, document):
    q, d = Counter(tokenize(query)), Counter(tokenize(document))
    if not q or not d:
        return 0.0
    return sum(q[t] * d[t] for t in q) / (math.sqrt(sum(v*v for v in q.values())) * math.sqrt(sum(v*v for v in d.values())))


class Retriever:
    def __init__(self):
        self.client = chromadb.PersistentClient(path=str(Path(settings.storage_dir) / 'chroma'))
        embedding_fn = (OpenAIEmbeddingFunction(api_key=settings.openai_api_key, model_name=settings.embedding_model)
                        if settings.openai_api_key else None)
        self.collection = self.client.get_or_create_collection('researchmind', embedding_function=embedding_fn, metadata={'hnsw:space': 'cosine'})
        self.semantic = bool(settings.openai_api_key)

    def add(self, doc_id, name, pages):
        records = [(str(uuid4()), chunk, {'document_id': doc_id, 'filename': name, 'page': number})
                   for number, text in pages for chunk in split_text(text)]
        for start in range(0, len(records), 100):
            batch = records[start:start + 100]
            if self.semantic:
                self.collection.add(ids=[r[0] for r in batch], documents=[r[1] for r in batch], metadatas=[r[2] for r in batch])
            else:
                # Chroma requires embeddings. Deterministic hashed vectors enable offline use.
                self.collection.add(ids=[r[0] for r in batch], documents=[r[1] for r in batch], metadatas=[r[2] for r in batch], embeddings=[hash_embedding(r[1]) for r in batch])
        return len(records)

    def search(self, query, document_ids=None, limit=6):
        if not query.strip() or self.collection.count() == 0:
            return []
        kwargs = {'n_results': min(max(limit * 4, 12), self.collection.count()), 'include': ['documents', 'metadatas', 'distances']}
        if document_ids:
            kwargs['where'] = {'document_id': {'$in': document_ids}} if len(document_ids) > 1 else {'document_id': document_ids[0]}
        try:
            if self.semantic:
                result = self.collection.query(query_texts=[query], **kwargs)
            else:
                result = self.collection.query(query_embeddings=[hash_embedding(query)], **kwargs)
        except Exception:
            return []
        hits = [{'text': t, **m, 'score': round(score(query, t), 3)} for t, m in zip(result['documents'][0], result['metadatas'][0])]
        if not self.semantic:
            hits.sort(key=lambda x: x['score'], reverse=True)
        return hits[:limit]

    def delete(self, doc_id):
        self.collection.delete(where={'document_id': doc_id})


def hash_embedding(text, dimensions=384):
    import hashlib
    vec = [0.0] * dimensions
    for token in tokenize(text):
        h = int.from_bytes(hashlib.sha256(token.encode()).digest()[:8], 'big')
        vec[h % dimensions] += 1 if (h >> 8) % 2 else -1
    norm = math.sqrt(sum(x*x for x in vec)) or 1
    return [x/norm for x in vec]
