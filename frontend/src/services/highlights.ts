import {api, type Region} from './api';

export type HighlightColor = 'yellow' | 'green' | 'blue' | 'pink';

export type Highlight = {
  id: string;
  paper_id: string;
  paper_file_id: string;
  page_index: number;
  text: string;
  color: HighlightColor;
  note: string;
  regions: Region[];
  created_at: number;
};

export type SaveHighlightsResult = {
  note_id: string;
  revision_id: string;
  section_id: string;
  section_title: string;
  count: number;
};

export const HIGHLIGHT_COLORS: {id: HighlightColor; label: string; swatch: string}[] = [
  {id: 'yellow', label: '黄色', swatch: '#f5c430'},
  {id: 'green', label: '绿色', swatch: '#4db874'},
  {id: 'blue', label: '蓝色', swatch: '#4a96eb'},
  {id: 'pink', label: '粉色', swatch: '#eb6c9b'},
];

export function listHighlights(fid: string): Promise<Highlight[]> {
  return api<Highlight[]>(`/v1/files/${fid}/highlights`);
}

export function createHighlight(
  fid: string,
  payload: {page_index: number; text: string; regions: Region[]; color?: HighlightColor; note?: string},
): Promise<Highlight> {
  return api<Highlight>(`/v1/files/${fid}/highlights`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  });
}

export function updateHighlight(
  hid: string,
  payload: {color?: HighlightColor; note?: string},
): Promise<Highlight> {
  return api<Highlight>(`/v1/highlights/${hid}`, {
    method: 'PATCH',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  });
}

export function deleteHighlight(hid: string): Promise<{deleted: string}> {
  return api<{deleted: string}>(`/v1/highlights/${hid}`, {method: 'DELETE'});
}

export function saveHighlightsToNote(payload: {
  highlight_ids: string[];
  note_id?: string | null;
  section_id?: string | null;
  parse_run_id?: string | null;
}): Promise<SaveHighlightsResult> {
  return api<SaveHighlightsResult>('/v1/highlights/save-to-note', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  });
}
