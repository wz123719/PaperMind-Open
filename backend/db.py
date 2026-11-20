"""Transactional SQLite migrations: v2 parsing, v3 evidence-linked reading."""
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import (JSON, Column, Float, ForeignKey, Integer, MetaData, String,
                        Table, UniqueConstraint, create_engine, event)

ROOT = Path(__file__).resolve().parents[1]
STORAGE = Path(os.getenv('PAPERMIND_STORAGE', str(ROOT / 'storage'))).resolve()
MAX_BYTES = int(os.getenv('PAPERMIND_MAX_BYTES', str(50 * 1024 * 1024)))
LEASE_SECONDS = int(os.getenv('PAPERMIND_LEASE_SECONDS', '30'))
STORAGE.mkdir(parents=True, exist_ok=True)
engine = create_engine('sqlite:///' + str(STORAGE / 'papermind.sqlite3'),
                       connect_args={'check_same_thread': False, 'timeout': 30})

@event.listens_for(engine, 'connect')
def pragmas(conn, _):
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=30000')

meta = MetaData()
papers = Table('papers', meta,
    Column('id', String, primary_key=True), Column('title', String),
    Column('authors', JSON), Column('year', Integer),
    Column('doi', String, unique=True), Column('arxiv_id', String, unique=True),
    Column('created_at', Float, nullable=False))
paper_files = Table('paper_files', meta,
    Column('id', String, primary_key=True),
    Column('paper_id', String, ForeignKey('papers.id'), nullable=False),
    Column('sha256', String, unique=True, nullable=False),
    Column('version', Integer, nullable=False), Column('arxiv_version', Integer),
    Column('relative_path', String, unique=True, nullable=False),
    Column('source', String, nullable=False), Column('size', Integer, nullable=False),
    Column('pages', Integer, nullable=False), Column('created_at', Float, nullable=False),
    UniqueConstraint('paper_id', 'version'))
jobs = Table('jobs', meta,
    Column('id', String, primary_key=True), Column('type', String, nullable=False),
    Column('status', String, nullable=False), Column('payload', JSON, nullable=False),
    Column('attempts', Integer, nullable=False), Column('max_attempts', Integer, nullable=False),
    Column('available_at', Float, nullable=False), Column('worker_id', String),
    Column('lease_expires_at', Float), Column('heartbeat_at', Float),
    Column('checkpoint', JSON), Column('error', String), Column('result', JSON),
    Column('created_at', Float, nullable=False), Column('updated_at', Float, nullable=False))
job_events = Table('job_events', meta,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('job_id', String, ForeignKey('jobs.id'), nullable=False, index=True),
    Column('type', String, nullable=False), Column('data', JSON, nullable=False),
    Column('created_at', Float, nullable=False), sqlite_autoincrement=True)

schema_migrations = Table('schema_migrations', meta,
    Column('version', Integer, primary_key=True), Column('applied_at', Float, nullable=False))
parse_runs = Table('parse_runs', meta,
    Column('id', String, primary_key=True),
    Column('paper_file_id', String, ForeignKey('paper_files.id'), nullable=False, index=True),
    Column('job_id', String, ForeignKey('jobs.id'), nullable=False, unique=True),
    Column('file_sha256', String, nullable=False), Column('input_hash', String, nullable=False, index=True),
    Column('parser', String, nullable=False), Column('parser_version', String, nullable=False),
    Column('config_version', String, nullable=False), Column('config', JSON, nullable=False),
    Column('status', String, nullable=False), Column('warnings', JSON), Column('pages', JSON),
    Column('artifact_root', String), Column('error', String), Column('elapsed_seconds', Float),
    Column('created_at', Float, nullable=False), Column('completed_at', Float))
document_sections = Table('document_sections', meta,
    Column('id', String, primary_key=True), Column('parse_run_id', String, ForeignKey('parse_runs.id'), nullable=False, index=True),
    Column('parent_id', String), Column('title', String, nullable=False), Column('level', Integer, nullable=False),
    Column('reading_order', Integer, nullable=False), Column('regions', JSON, nullable=False))
document_blocks = Table('document_blocks', meta,
    Column('id', String, primary_key=True), Column('parse_run_id', String, ForeignKey('parse_runs.id'), nullable=False, index=True),
    Column('section_id', String, ForeignKey('document_sections.id')), Column('type', String, nullable=False),
    Column('text', String, nullable=False), Column('reading_order', Integer, nullable=False),
    Column('regions', JSON, nullable=False), Column('source', String, nullable=False),
    Column('quality_flags', JSON, nullable=False), Column('data', JSON, nullable=False))
file_parse_heads = Table('file_parse_heads', meta,
    Column('paper_file_id', String, ForeignKey('paper_files.id'), primary_key=True),
    Column('parse_run_id', String, ForeignKey('parse_runs.id'), nullable=False))

reading_settings = Table('reading_settings', meta,
    Column('id', String, primary_key=True), Column('config', JSON, nullable=False))
reading_runs = Table('reading_runs', meta,
    Column('id', String, primary_key=True),
    Column('parse_run_id', String, ForeignKey('parse_runs.id'), nullable=False, index=True),
    Column('job_id', String, ForeignKey('jobs.id'), nullable=False, unique=True),
    Column('input_hash', String, nullable=False, index=True),
    Column('config', JSON, nullable=False), Column('result', JSON),
    Column('created_at', Float, nullable=False), Column('completed_at', Float))
reading_stages = Table('reading_stages', meta,
    Column('run_id', String, ForeignKey('reading_runs.id'), primary_key=True),
    Column('stage_key', String, primary_key=True), Column('result', JSON, nullable=False))

chat_sessions = Table('chat_sessions', meta,
    Column('id', String, primary_key=True), Column('paper_id', String, ForeignKey('papers.id'), nullable=False),
    Column('paper_file_id', String, ForeignKey('paper_files.id'), nullable=False),
    Column('file_sha256', String, nullable=False), Column('parse_run_id', String, ForeignKey('parse_runs.id'), nullable=False),
    Column('title', String, nullable=False), Column('created_at', Float, nullable=False))
chat_messages = Table('chat_messages', meta,
    Column('id', String, primary_key=True), Column('session_id', String, ForeignKey('chat_sessions.id'), nullable=False, index=True),
    Column('turn_id', String, nullable=False), Column('role', String, nullable=False),
    Column('status', String, nullable=False), Column('content', String, nullable=False),
    Column('data', JSON, nullable=False), Column('sequence', Integer, nullable=False), Column('created_at', Float, nullable=False))
chat_turns = Table('chat_turns', meta,
    Column('id', String, primary_key=True), Column('session_id', String, ForeignKey('chat_sessions.id'), nullable=False, index=True),
    Column('job_id', String, ForeignKey('jobs.id'), nullable=False, unique=True),
    Column('user_message_id', String, ForeignKey('chat_messages.id'), nullable=False),
    Column('assistant_message_id', String, ForeignKey('chat_messages.id'), nullable=False),
    Column('idempotency_key', String, nullable=False), Column('request_hash', String, nullable=False),
    Column('snapshot', JSON, nullable=False), Column('created_at', Float, nullable=False),
    UniqueConstraint('session_id','idempotency_key'))
chat_events = Table('chat_events', meta,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('turn_id', String, ForeignKey('chat_turns.id'), nullable=False, index=True),
    Column('attempt', Integer, nullable=False), Column('type', String, nullable=False),
    Column('data', JSON, nullable=False), Column('created_at', Float, nullable=False), sqlite_autoincrement=True)

notes = Table('notes', meta,
    Column('id', String, primary_key=True), Column('paper_id', String, ForeignKey('papers.id'), nullable=False),
    Column('paper_file_id', String, ForeignKey('paper_files.id'), nullable=False),
    Column('file_sha256', String, nullable=False), Column('parse_run_id', String, ForeignKey('parse_runs.id')),
    Column('current_revision', String, nullable=False), Column('created_at', Float, nullable=False))
note_revisions = Table('note_revisions', meta,
    Column('id', String, primary_key=True), Column('note_id', String, ForeignKey('notes.id'), nullable=False, index=True),
    Column('parent_id', String), Column('snapshot', JSON, nullable=False), Column('content_hash', String, nullable=False),
    Column('operation', String, nullable=False), Column('created_at', Float, nullable=False))
note_operations = Table('note_operations', meta,
    Column('note_id', String, ForeignKey('notes.id'), primary_key=True), Column('key', String, primary_key=True),
    Column('request_hash', String, nullable=False), Column('revision_id', String, nullable=False))
note_reviews = Table('note_reviews', meta,
    Column('revision_id', String, ForeignKey('note_revisions.id'), primary_key=True),
    Column('content_hash', String, nullable=False), Column('reviewed_at', Float, nullable=False))
vault_settings = Table('vault_settings', meta,
    Column('id', String, primary_key=True), Column('config', JSON, nullable=False))
note_exports = Table('note_exports', meta,
    Column('id', String, primary_key=True), Column('note_id', String, ForeignKey('notes.id'), nullable=False, index=True),
    Column('revision_id', String, ForeignKey('note_revisions.id'), nullable=False),
    Column('request_key', String, nullable=False, unique=True), Column('plan', JSON, nullable=False),
    Column('status', String, nullable=False), Column('error', String),
    Column('created_at', Float, nullable=False), Column('completed_at', Float))

task_model_settings = Table('task_model_settings', meta,
    Column('id', String, primary_key=True), Column('config', JSON, nullable=False))
glossary_versions = Table('glossary_versions', meta,
    Column('id', String, primary_key=True), Column('paper_id', String, ForeignKey('papers.id'), nullable=False),
    Column('parent_id', String), Column('entries', JSON, nullable=False), Column('created_at', Float, nullable=False))
translation_runs = Table('translation_runs', meta,
    Column('id', String, primary_key=True), Column('parse_run_id', String, ForeignKey('parse_runs.id'), nullable=False),
    Column('job_id', String, ForeignKey('jobs.id'), nullable=False, unique=True),
    Column('request_key', String, nullable=False, unique=True), Column('request_hash', String, nullable=False),
    Column('snapshot', JSON, nullable=False), Column('created_at', Float, nullable=False))
translation_blocks = Table('translation_blocks', meta,
    Column('run_id', String, ForeignKey('translation_runs.id'), primary_key=True),
    Column('block_id', String, primary_key=True), Column('current_revision', String, nullable=False))
translation_revisions = Table('translation_revisions', meta,
    Column('id', String, primary_key=True), Column('run_id', String, ForeignKey('translation_runs.id'), nullable=False),
    Column('block_id', String, nullable=False), Column('parent_id', String),
    Column('cache_key', String, index=True), Column('result', JSON, nullable=False), Column('created_at', Float, nullable=False))
translation_batches = Table('translation_batches', meta,
    Column('id', String, primary_key=True), Column('run_id', String, ForeignKey('translation_runs.id'), nullable=False),
    Column('data', JSON, nullable=False), Column('created_at', Float, nullable=False))
translation_requests = Table('translation_requests', meta,
    Column('key', String, primary_key=True), Column('request_hash', String, nullable=False),
    Column('run_id', String, ForeignKey('translation_runs.id'), nullable=False))

SCHEMA_VERSION = 6

def init_db():
    migrate(engine)

def migrate(target_engine, after_ddl=None):
    """SQLite DDL participates in this explicit transaction; failure rolls it all back.

    An unversioned existing database is v1. No ALTER, row rewrite or ID reassignment
    is required for v2/v3. after_ddl is a test fault-injection hook, never an API input.
    """
    with target_engine.connect() as conn:
        conn.exec_driver_sql('BEGIN IMMEDIATE')
        try:
            existing = conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").scalars().all()
            version = conn.exec_driver_sql('SELECT max(version) FROM schema_migrations').scalar() if 'schema_migrations' in existing else None
            if version and version > SCHEMA_VERSION:
                raise RuntimeError('数据库版本高于此程序支持的版本')
            meta.create_all(conn)
            if after_ddl:
                after_ddl(conn)
            known = set(conn.execute(schema_migrations.select()).scalars())
            for v in range(1, SCHEMA_VERSION+1):
                if v not in known:
                    conn.execute(schema_migrations.insert().values(version=v, applied_at=time.time()))
            conn.exec_driver_sql(f'PRAGMA user_version={SCHEMA_VERSION}')
            conn.commit()
        except BaseException:
            conn.rollback()
            raise

def uid():
    return str(uuid.uuid4())

@contextmanager
def write_tx():
    with engine.connect() as conn:
        conn.exec_driver_sql('BEGIN IMMEDIATE')
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise

def emit(conn, job_id, kind, data):
    conn.execute(job_events.insert().values(job_id=job_id, type=kind, data=data, created_at=time.time()))
