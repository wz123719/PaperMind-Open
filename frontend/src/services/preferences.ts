import {api} from './api';
import type {HighlightColor} from './highlights';

export type WorkspacePreferences = {
  parse_mode: 'docling' | 'native';
  parse_formulas: boolean;
  parse_source_preferred: boolean;
  default_reader_mode: 'bilingual' | 'translation' | 'original';
  default_highlight_color: HighlightColor;
  default_bundle_pdf: boolean;
  show_outline_by_default: boolean;
  show_ai_panel_by_default: boolean;
};

export type ModelSettings = {
  endpoint: string;
  model: string;
  key_env: string;
  revision: string | null;
  configured?: boolean;
  source?: 'workspace' | 'task';
  uses_default_model?: boolean;
  has_saved_key?: boolean;
  masked_key?: string | null;
  use_system_proxy?: boolean;
};

export type VaultSettings = {
  root: string;
  subdir: string;
  revision: string | null;
  configured: boolean;
};

export type WorkspaceCapabilities = {
  docling_available: boolean;
  formula_backend: string;
};

export type SettingsOverview = {
  preferences: WorkspacePreferences;
  llm: ModelSettings;
  translation_model: ModelSettings;
  glossary_model: ModelSettings;
  vault: VaultSettings;
  capabilities: WorkspaceCapabilities;
};

export const DEFAULT_PREFERENCES: WorkspacePreferences = {
  parse_mode: 'docling',
  parse_formulas: true,
  parse_source_preferred: true,
  default_reader_mode: 'bilingual',
  default_highlight_color: 'yellow',
  default_bundle_pdf: false,
  show_outline_by_default: true,
  show_ai_panel_by_default: true,
};

export const LLM_PRESETS = [
  {label: 'DeepSeek 官方', endpoint: 'https://api.deepseek.com/chat/completions', model: 'deepseek-chat'},
  {label: 'DeepSeek Flash', endpoint: 'https://api.deepseek.com/chat/completions', model: 'deepseek-flash'},
  {label: '硅基流动 Qwen', endpoint: 'https://api.siliconflow.cn/v1/chat/completions', model: 'Qwen/Qwen2.5-72B-Instruct'},
  {label: 'Kimi (Moonshot)', endpoint: 'https://api.moonshot.cn/v1/chat/completions', model: 'moonshot-v1-8k'},
  {label: 'OpenAI 兼容', endpoint: 'https://api.openai.com/v1/chat/completions', model: 'gpt-4o-mini'},
  {label: '本地 Ollama', endpoint: 'http://127.0.0.1:11434/v1/chat/completions', model: 'qwen2.5:14b'},
];

const jsonPost = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify(body),
});

export function fetchPreferences(): Promise<WorkspacePreferences & {capabilities: WorkspaceCapabilities}> {
  return api<WorkspacePreferences & {capabilities: WorkspaceCapabilities}>('/v1/workspace-preferences');
}

export function savePreferences(
  prefs: Partial<WorkspacePreferences>,
): Promise<WorkspacePreferences & {capabilities: WorkspaceCapabilities}> {
  return api<WorkspacePreferences & {capabilities: WorkspaceCapabilities}>('/v1/workspace-preferences', jsonPost(prefs));
}

export function fetchSettingsOverview(): Promise<SettingsOverview> {
  return api<SettingsOverview>('/v1/settings-overview');
}

export function saveGlobalLlm(payload: {
  endpoint: string;
  model: string;
  key_env: string;
  api_key?: string;
  clear_api_key?: boolean;
  use_system_proxy: boolean;
}): Promise<ModelSettings> {
  return api<ModelSettings>('/v1/reading-settings', jsonPost(payload));
}

export function testGlobalLlm(payload: {
  endpoint: string;
  model: string;
  key_env: string;
  api_key?: string;
  use_system_proxy: boolean;
}): Promise<{ok: boolean; latency_ms: number; model: string}> {
  return api<{ok: boolean; latency_ms: number; model: string}>('/v1/reading-settings/test', jsonPost(payload));
}

export function saveTaskModel(
  task: 'translation' | 'glossary',
  payload: {
    endpoint: string;
    model: string;
    key_env: string;
    expected_revision: string | null;
    api_key?: string;
    clear_api_key?: boolean;
    use_system_proxy: boolean;
  },
): Promise<ModelSettings> {
  return api<ModelSettings>(`/v1/task-model-settings/${task}`, jsonPost(payload));
}

export function resetTaskModel(task: 'translation' | 'glossary'): Promise<ModelSettings> {
  return api<ModelSettings>(`/v1/task-model-settings/${task}`, {method: 'DELETE'});
}

export function testTaskModel(
  task: 'translation' | 'glossary',
  payload: {
    endpoint: string;
    model: string;
    key_env: string;
    api_key?: string;
    use_system_proxy: boolean;
  },
): Promise<{ok: boolean; latency_ms: number; model: string}> {
  return api<{ok: boolean; latency_ms: number; model: string}>(`/v1/task-model-settings/${task}/test`, jsonPost(payload));
}

export function saveVaultSettings(payload: {
  root: string;
  subdir: string;
  expected_revision: string | null;
}): Promise<VaultSettings> {
  return api<VaultSettings>('/v1/vault-settings', jsonPost(payload));
}

export function validateVaultSettings(payload: {root: string; subdir: string}): Promise<{valid: boolean; output: string}> {
  return api<{valid: boolean; output: string}>('/v1/vault-settings/validate', jsonPost(payload));
}
