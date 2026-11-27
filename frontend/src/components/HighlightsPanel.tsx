import {useEffect,useState} from 'react';
import type {Region} from '../services/api';
import {
  HIGHLIGHT_COLORS,
  deleteHighlight,
  saveHighlightsToNote,
  updateHighlight,
  type Highlight,
  type HighlightColor,
} from '../services/highlights';
import {noteApi,type NoteRevision,type NoteRow} from '../services/notes';

export function HighlightsPanel({
  paperId,
  parseId,
  highlights,
  onChange,
  onLocate,
  onOpenNote,
}: {
  paperId: string;
  parseId: string | null;
  highlights: Highlight[];
  onChange: (next: Highlight[]) => void;
  onLocate: (regions: Region[], label: string) => void;
  onOpenNote: (noteId: string) => void;
}) {
  const [notesList, setNotesList] = useState<NoteRow[]>([]);
  const [noteId, setNoteId] = useState<string>('');
  const [sections, setSections] = useState<{id: string; title: string}[]>([]);
  const [sectionId, setSectionId] = useState<string>('');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftNote, setDraftNote] = useState('');
  const [busyId, setBusyId] = useState<string | null>(null);
  const [status, setStatus] = useState<{text: string; noteId?: string} | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let live = true;
    void noteApi<NoteRow[]>('/notes?paper_id=' + encodeURIComponent(paperId))
      .then(rows => {
        if (!live) return;
        setNotesList(rows);
        const saved = sessionStorage.getItem('note-selected-' + paperId);
        const picked = rows.find(r => r.id === saved)?.id || rows[0]?.id || '';
        setNoteId(picked);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [paperId]);

  useEffect(() => {
    let live = true;
    if (!noteId) {
      setSections([]);
      setSectionId('');
      return;
    }
    void noteApi<NoteRevision>('/notes/' + encodeURIComponent(noteId))
      .then(rev => {
        if (!live) return;
        const secs = rev.snapshot.sections.map(s => ({id: s.id, title: s.title}));
        setSections(secs);
        setSectionId(prev =>
          secs.some(s => s.id === prev)
            ? prev
            : secs.find(s => ['s11', 's12', 's05', 's02'].includes(s.id))?.id || secs[secs.length - 1]?.id || '',
        );
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [noteId]);

  async function handleColor(hl: Highlight, color: HighlightColor) {
    if (hl.color === color) return;
    setError('');
    setBusyId(hl.id);
    try {
      const updated = await updateHighlight(hl.id, {color});
      onChange(highlights.map(item => (item.id === hl.id ? updated : item)));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusyId(null);
    }
  }

  async function handleSaveAnnotation(hl: Highlight) {
    setError('');
    setBusyId(hl.id);
    try {
      const updated = await updateHighlight(hl.id, {note: draftNote});
      onChange(highlights.map(item => (item.id === hl.id ? updated : item)));
      setEditingId(null);
      setStatus({text: '批注已更新'});
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusyId(null);
    }
  }

  async function handleDelete(hl: Highlight) {
    setError('');
    setBusyId(hl.id);
    try {
      await deleteHighlight(hl.id);
      onChange(highlights.filter(item => item.id !== hl.id));
      if (editingId === hl.id) setEditingId(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusyId(null);
    }
  }

  async function handleAddToNote(ids: string[], tag: string) {
    if (!ids.length) return;
    setError('');
    setStatus(null);
    setBusyId(tag);
    try {
      const res = await saveHighlightsToNote({
        highlight_ids: ids,
        note_id: noteId || null,
        section_id: sectionId || null,
        parse_run_id: parseId,
      });
      if (!noteId) {
        setNoteId(res.note_id);
        void noteApi<NoteRow[]>('/notes?paper_id=' + encodeURIComponent(paperId))
          .then(rows => setNotesList(rows))
          .catch(() => {});
      }
      setStatus({
        text: `已将 ${res.count} 条高亮加入知识笔记「${res.section_title}」`,
        noteId: res.note_id,
      });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <aside className="ai-reading-panel highlights-panel" aria-label="高亮摘录">
      <h2>高亮摘录 ({highlights.length})</h2>
      <p className="reading-summary">
        在「英文原文」PDF 或「双语对照 / 中文译文」中划选任意句子即可永久高亮，并一键归档到知识笔记。
      </p>

      <div className="highlights-note-target">
        {notesList.length > 0 ? (
          <>
            <label>
              目标知识笔记
              <select aria-label="目标知识笔记" value={noteId} onChange={e => setNoteId(e.target.value)}>
                {notesList.map(n => (
                  <option key={n.id} value={n.id}>
                    {n.title || '未命名笔记'} · {n.id.slice(0, 6)}
                  </option>
                ))}
              </select>
            </label>
            {sections.length > 0 && (
              <label>
                插入章节
                <select aria-label="插入章节" value={sectionId} onChange={e => setSectionId(e.target.value)}>
                  {sections.map(s => (
                    <option key={s.id} value={s.id}>
                      {s.title}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </>
        ) : (
          <p className="reading-disclosure">当前论文尚未创建知识笔记，点击「加入知识笔记」时会自动新建。</p>
        )}
        <div className="reading-actions">
          <button
            type="button"
            className="primary"
            disabled={!highlights.length || busyId !== null}
            onClick={() => void handleAddToNote(highlights.map(h => h.id), 'all')}
          >
            全部高亮加入笔记 ({highlights.length})
          </button>
          {noteId && (
            <button type="button" onClick={() => onOpenNote(noteId)}>
              打开知识笔记
            </button>
          )}
        </div>
      </div>

      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {status && (
        <div className="notice" role="status">
          <span>{status.text}</span>{' '}
          {status.noteId && (
            <button type="button" onClick={() => onOpenNote(status.noteId!)}>
              立即查看 →
            </button>
          )}
        </div>
      )}

      {!highlights.length ? (
        <p className="structure-empty">
          还没有高亮摘录。用鼠标在正文划选句子后，点击上方工具栏的「保持高亮」或「高亮并加入笔记」。
        </p>
      ) : (
        <div className="highlight-list">
          {highlights.map(hl => (
            <article key={hl.id} className={`highlight-card hl-border-${hl.color}`}>
              <header className="highlight-card-head">
                <span className={`hl-badge hl-dot-${hl.color}`}>第 {hl.page_index + 1} 页</span>
                <div className="hl-swatches" role="group" aria-label="切换高亮颜色">
                  {HIGHLIGHT_COLORS.map(c => (
                    <button
                      key={c.id}
                      type="button"
                      className={`hl-swatch${hl.color === c.id ? ' active' : ''}`}
                      style={{backgroundColor: c.swatch}}
                      title={`切换为${c.label}`}
                      aria-label={`切换为${c.label}`}
                      disabled={busyId === hl.id}
                      onClick={() => void handleColor(hl, c.id)}
                    />
                  ))}
                </div>
              </header>

              <button
                type="button"
                className="highlight-quote-btn"
                title="点击定位到 PDF 原文"
                onClick={() => onLocate(hl.regions, hl.text)}
              >
                <blockquote>{hl.text}</blockquote>
              </button>

              {editingId === hl.id ? (
                <div className="highlight-note-editor">
                  <textarea
                    rows={2}
                    aria-label="高亮批注"
                    placeholder="写下你的理解、疑问或想法…"
                    value={draftNote}
                    onChange={e => setDraftNote(e.target.value)}
                  />
                  <div className="reading-actions">
                    <button
                      type="button"
                      className="primary"
                      disabled={busyId === hl.id}
                      onClick={() => void handleSaveAnnotation(hl)}
                    >
                      保存批注
                    </button>
                    <button type="button" onClick={() => setEditingId(null)}>
                      取消
                    </button>
                  </div>
                </div>
              ) : (
                hl.note && <p className="highlight-annotation">批注：{hl.note}</p>
              )}

              <div className="highlight-card-actions">
                <button
                  type="button"
                  disabled={busyId !== null}
                  onClick={() => void handleAddToNote([hl.id], hl.id)}
                >
                  ＋ 加入知识笔记
                </button>
                <button
                  type="button"
                  disabled={busyId === hl.id}
                  onClick={() => {
                    setEditingId(hl.id);
                    setDraftNote(hl.note || '');
                  }}
                >
                  {hl.note ? '编辑批注' : '添加批注'}
                </button>
                <button type="button" onClick={() => onLocate(hl.regions, hl.text)}>
                  原文定位
                </button>
                <button
                  type="button"
                  disabled={busyId === hl.id}
                  onClick={() => void handleDelete(hl)}
                >
                  删除
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
    </aside>
  );
}
