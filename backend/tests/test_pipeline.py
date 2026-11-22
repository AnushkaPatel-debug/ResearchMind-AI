from app.rag.pipeline import split_text, score, hash_embedding
from app.agents.workflow import ResearchWorkflow

def test_chunks_overlap():
    chunks = split_text('a' * 2500, 1000, 200)
    assert len(chunks) == 3
    assert chunks[0][-200:] == chunks[1][:200]

def test_empty_chunks():
    assert split_text('  ') == []

def test_similarity():
    assert score('machine learning', 'machine learning research') > score('machine learning', 'banana fruit')

def test_embedding():
    assert len(hash_embedding('research')) == 384
    assert hash_embedding('research') == hash_embedding('research')

def test_workflow_no_evidence():
    class Empty:
        def search(self, *args, **kwargs): return []
    result = ResearchWorkflow(Empty()).run('What is the conclusion?')
    assert result['citations'] == []
    assert 'could not find' in result['answer']
