import os
import tempfile
from pathlib import Path

# Isolate all test data from the actual library, before importing backend modules.
_temp = tempfile.TemporaryDirectory(prefix='papermind-tests-')
os.environ['PAPERMIND_STORAGE'] = _temp.name
os.environ['PAPERMIND_MAX_BYTES'] = '65536'
os.environ['PAPERMIND_LEASE_SECONDS'] = '2'

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject, DictionaryObject
from backend.db import engine, meta, init_db, STORAGE
from backend.app import app

def pdf_bytes(title='Research fixture', doi=None, arxiv=None):
    import io
    writer = PdfWriter()
    page = writer.add_blank_page(612, 792)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(b'BT /F1 20 Tf 60 700 Td (PaperMind upload verification) Tj ET')
    page[NameObject('/Contents')] = writer._add_object(stream)
    writer.add_blank_page(612, 792)
    metadata = {'/Title': title, '/Author': 'Test Author'}
    if doi: metadata['/DOI'] = doi
    if arxiv: metadata['/arXivID'] = arxiv
    writer.add_metadata(metadata)
    data = io.BytesIO()
    writer.write(data)
    return data.getvalue()

@pytest.fixture(autouse=True)
def clean():
    init_db()
    with engine.begin() as conn:
        for table in reversed(meta.sorted_tables):
            conn.execute(table.delete())
    yield

@pytest.fixture
def client():
    with TestClient(app, base_url='http://127.0.0.1', headers={'X-PaperMind-Client': 'workspace'}) as c:
        yield c

def pytest_sessionfinish(session, exitstatus):
    engine.dispose()
    _temp.cleanup()
