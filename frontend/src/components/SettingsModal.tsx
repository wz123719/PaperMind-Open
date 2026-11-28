import {useEffect, useState} from 'react';
import {HIGHLIGHT_COLORS} from '../services/highlights';
import {
  DEFAULT_PREFERENCES,
  LLM_PRESETS,
  fetchSettingsOverview,
  resetTaskModel,
  saveGlobalLlm,
  savePreferences,
  saveTaskModel,
  saveVaultSettings,
  testGlobalLlm,
  testTaskModel,
  validateVaultSettings,
  type ModelSettings,
  type SettingsOverview,
  type VaultSettings,
  type WorkspaceCapabilities,
  type WorkspacePreferences,
} from '../services/preferences';
import '../settings.css';

type TabId = 'parsing' | 'llm' | 'tasks' | 'obsidian';

export function SettingsModal({
  initialTab = 'parsing',
  onClose,
  onSaved,
}: {
  initialTab?: TabId;
  onClose: () => void;
  onSaved?: (overview: SettingsOverview) => void;
}) {
  const [tab, setTab] = useState<TabId>(initialTab);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const [caps, setCaps] = useState<WorkspaceCapabilities>({docling_available: true, formula_backend: 'code_formula_v2'});
  const [prefs, setPrefs] = useState<WorkspacePreferences>(DEFAULT_PREFERENCES);

  const [llm, setLlm] = useState<ModelSettings>({endpoint: '', model: '', key_env: '', revision: null, use_system_proxy: false});
  const [llmKey, setLlmKey] = useState('');
  const [clearLlmKey, setClearLlmKey] = useState(false);

  const [customTrans, setCustomTrans] = useState(false);
  const [origCustomTrans, setOrigCustomTrans] = useState(false);
  const [transModel, setTransModel] = useState<ModelSettings>({endpoint: '', model: '', key_env: '', revision: null, use_system_proxy: false});
  const [transKey, setTransKey] = useState('');
  const [clearTransKey, setClearTransKey] = useState(false);

  const [customGloss, setCustomGloss] = useState(false);
  const [origCustomGloss, setOrigCustomGloss] = useState(false);
  const [glossModel, setGlossModel] = useState<ModelSettings>({endpoint: '', model: '', key_env: '', revision: null, use_system_proxy: false});
  const [glossKey, setGlossKey] = useState('');
  const [clearGlossKey, setClearGlossKey] = useState(false);

  const [vault, setVault] = useState<VaultSettings>({root: '', subdir: 'PaperMind', revision: null, configured: false});
  const [origVault, setOrigVault] = useState<VaultSettings>({root: '', subdir: 'PaperMind', revision: null, configured: false});

  function applyOverview(ov: SettingsOverview) {
    setCaps(ov.capabilities);
    setPrefs(ov.preferences);
    setLlm(ov.llm);
    setLlmKey('');
    setClearLlmKey(false);

    const hasTrans = ov.translation_model.source === 'task';
    setCustomTrans(hasTrans);
    setOrigCustomTrans(hasTrans);
    setTransModel(ov.translation_model);
    setTransKey('');
    setClearTransKey(false);

    const hasGloss = ov.glossary_model.source === 'task';
    setCustomGloss(hasGloss);
    setOrigCustomGloss(hasGloss);
    setGlossModel(ov.glossary_model);
    setGlossKey('');
    setClearGlossKey(false);

    setVault(ov.vault);
    setOrigVault(ov.vault);
  }

  useEffect(() => {
    let live = true;
    setLoading(true);
    setError('');
    void fetchSettingsOverview()
      .then(ov => {
        if (live) applyOverview(ov);
      })
      .catch(e => {
        if (live) setError((e as Error).message);
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape' && !saving) onClose();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [saving, onClose]);

  async function handleTestLlm(kind: 'global' | 'translation' | 'glossary') {
    setTesting(kind);
    setError('');
    setNotice('');
    try {
      if (kind === 'global') {
        const res = await testGlobalLlm({
          endpoint: llm.endpoint.trim(),
          model: llm.model.trim(),
          key_env: llm.key_env.trim(),
          api_key: llmKey.trim() || undefined,
          use_system_proxy: !!llm.use_system_proxy,
        });
        setNotice(`全局默认模型连接成功 · ${res.model} · 耗时 ${res.latency_ms} ms`);
      } else {
        const target = kind === 'translation' ? transModel : glossModel;
        const keyVal = kind === 'translation' ? transKey : glossKey;
        const res = await testTaskModel(kind, {
          endpoint: target.endpoint.trim(),
          model: target.model.trim(),
          key_env: target.key_env.trim(),
          api_key: keyVal.trim() || undefined,
          use_system_proxy: !!target.use_system_proxy,
        });
        setNotice(`${kind === 'translation' ? '翻译专用' : '术语专用'}模型连接成功 · ${res.model} · 耗时 ${res.latency_ms} ms`);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setTesting(null);
    }
  }

  async function handleValidateVault() {
    setTesting('vault');
    setError('');
    setNotice('');
    try {
      const res = await validateVaultSettings({root: vault.root.trim(), subdir: vault.subdir.trim() || 'PaperMind'});
      setNotice(`Obsidian Vault 目录校验通过，导出路径：${res.output}`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setTesting(null);
    }
  }

  async function handleSaveAll() {
    if (saving) return;
    setSaving(true);
    setError('');
    setNotice('');
    try {
      // 1. Workspace parsing, reading & highlighting preferences
      await savePreferences(prefs);

      // 2. Global LLM settings (save whenever endpoint & model are provided)
      if (llm.endpoint.trim() && llm.model.trim()) {
        await saveGlobalLlm({
          endpoint: llm.endpoint.trim(),
          model: llm.model.trim(),
          key_env: llm.key_env.trim(),
          api_key: llmKey.trim() || undefined,
          clear_api_key: clearLlmKey || undefined,
          use_system_proxy: !!llm.use_system_proxy,
        });
      }

      // 3. Translation task model override or reset
      if (customTrans) {
        if (!transModel.endpoint.trim() || !transModel.model.trim()) {
          throw new Error('已开启「翻译专用模型」，请填写模型端点和模型名称，或取消勾选以沿用全局默认模型');
        }
        await saveTaskModel('translation', {
          endpoint: transModel.endpoint.trim(),
          model: transModel.model.trim(),
          key_env: transModel.key_env.trim(),
          expected_revision: origCustomTrans ? transModel.revision : null,
          api_key: transKey.trim() || undefined,
          clear_api_key: clearTransKey || undefined,
          use_system_proxy: !!transModel.use_system_proxy,
        });
      } else if (origCustomTrans) {
        await resetTaskModel('translation');
      }

      // 4. Glossary task model override or reset
      if (customGloss) {
        if (!glossModel.endpoint.trim() || !glossModel.model.trim()) {
          throw new Error('已开启「术语提取专用模型」，请填写模型端点和模型名称，或取消勾选以沿用全局默认模型');
        }
        await saveTaskModel('glossary', {
          endpoint: glossModel.endpoint.trim(),
          model: glossModel.model.trim(),
          key_env: glossModel.key_env.trim(),
          expected_revision: origCustomGloss ? glossModel.revision : null,
          api_key: glossKey.trim() || undefined,
          clear_api_key: clearGlossKey || undefined,
          use_system_proxy: !!glossModel.use_system_proxy,
        });
      } else if (origCustomGloss) {
        await resetTaskModel('glossary');
      }

      // 5. Obsidian Vault settings (save if root is filled and changed or not configured yet)
      const rootClean = vault.root.trim();
      const subdirClean = vault.subdir.trim() || 'PaperMind';
      if (rootClean && (rootClean !== origVault.root || subdirClean !== origVault.subdir || !origVault.configured)) {
        await saveVaultSettings({
          root: rootClean,
          subdir: subdirClean,
          expected_revision: origVault.revision,
        });
      }

      const fresh = await fetchSettingsOverview();
      applyOverview(fresh);
      onSaved?.(fresh);
      setNotice('全部偏好设置已保存并立即生效！');
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="settings-backdrop" role="dialog" aria-modal="true" aria-label="PaperMind 全局偏好设置" onClick={e => {if (e.target === e.currentTarget && !saving) onClose()}}>
      <div className="settings-shell">
        <header className="settings-header">
          <div>
            <h2>⚙ 全局偏好设置</h2>
            <p>一次性配置解析引擎、大模型 API、翻译专用模型与 Obsidian 同步路径，所有新任务自动生效。</p>
          </div>
          <button type="button" onClick={onClose} disabled={saving}>✕ 关闭</button>
        </header>

        <div className="settings-body">
          <nav className="settings-nav" aria-label="设置分类">
            <button type="button" aria-current={tab === 'parsing' ? 'page' : undefined} onClick={() => setTab('parsing')}>
              <span>📄 解析与阅读偏好</span>
              <small>{prefs.parse_mode === 'docling' ? 'Docling' : '快速原生'}</small>
            </button>
            <button type="button" aria-current={tab === 'llm' ? 'page' : undefined} onClick={() => setTab('llm')}>
              <span>🤖 全局 LLM 模型</span>
              <small className={llm.has_saved_key || llm.key_env ? 'ok' : 'warn'}>
                {llm.has_saved_key ? '已加密保存' : llm.key_env ? '环境变量' : '待填密钥'}
              </small>
            </button>
            <button type="button" aria-current={tab === 'tasks' ? 'page' : undefined} onClick={() => setTab('tasks')}>
              <span>🌐 翻译与术语模型</span>
              <small>{customTrans || customGloss ? '已单独指定' : '沿用全局'}</small>
            </button>
            <button type="button" aria-current={tab === 'obsidian' ? 'page' : undefined} onClick={() => setTab('obsidian')}>
              <span>📚 Obsidian 知识库</span>
              <small className={vault.configured ? 'ok' : 'warn'}>{vault.configured ? '已绑定' : '未配置'}</small>
            </button>
          </nav>

          <section className="settings-content">
            {loading ? (
              <p className="settings-loading">正在读取当前配置…</p>
            ) : (
              <>
                {tab === 'parsing' && (
                  <div className="settings-section">
                    <h3>PDF 解析默认策略</h3>
                    <div className="settings-field">
                      <label htmlFor="pref-parse-mode">默认解析引擎</label>
                      <select
                        id="pref-parse-mode"
                        value={prefs.parse_mode}
                        onChange={e => setPrefs({...prefs, parse_mode: e.target.value as 'docling' | 'native'})}
                      >
                        <option value="docling">Docling 深度解析（推荐：完整章节结构、表格、算法框与公式）</option>
                        <option value="native">快速原生提取（秒级完成，无需深度学习模型）</option>
                      </select>
                      <small className={caps.docling_available ? 'hint-ok' : 'hint-warn'}>
                        {caps.docling_available
                          ? `当前环境 Docling 已就绪 · 公式后端：${caps.formula_backend}`
                          : '当前 Python 环境未检测到 Docling，建议选择「快速原生提取」或检查 .venv 环境'}
                      </small>
                    </div>

                    <label className="settings-check">
                      <input
                        type="checkbox"
                        checked={prefs.parse_formulas}
                        disabled={prefs.parse_mode !== 'docling'}
                        onChange={e => setPrefs({...prefs, parse_formulas: e.target.checked})}
                      />
                      <div>
                        <strong>默认启用视觉公式识别（CodeFormulaV2）</strong>
                        <small>自动识别论文中的独立行间与多行数学公式并还原为标准 LaTeX。</small>
                      </div>
                    </label>

                    <label className="settings-check">
                      <input
                        type="checkbox"
                        checked={prefs.parse_source_preferred}
                        disabled={prefs.parse_mode !== 'docling'}
                        onChange={e => setPrefs({...prefs, parse_source_preferred: e.target.checked})}
                      />
                      <div>
                        <strong>arXiv 论文优先对齐官方 LaTeX 源码</strong>
                        <small>当已获取 arXiv TeX 源码时，优先用源码实现 100% 精确公式与表格对齐。</small>
                      </div>
                    </label>

                    <hr className="settings-divider" />
                    <h3>阅读器与高亮默认偏好</h3>

                    <div className="settings-field">
                      <label htmlFor="pref-reader-mode">打开已解析论文时的默认视图</label>
                      <select
                        id="pref-reader-mode"
                        value={prefs.default_reader_mode}
                        onChange={e =>
                          setPrefs({...prefs, default_reader_mode: e.target.value as 'bilingual' | 'translation' | 'original'})
                        }
                      >
                        <option value="bilingual">双语对照（英文原文 + 中文译文逐段对照）</option>
                        <option value="translation">中文译文（沉浸式连续中文阅读）</option>
                        <option value="original">英文原文（原始 PDF 页面与精确定位）</option>
                      </select>
                    </div>

                    <div className="settings-field">
                      <label>划句高亮默认颜色</label>
                      <div className="settings-color-row">
                        {HIGHLIGHT_COLORS.map(c => (
                          <button
                            key={c.id}
                            type="button"
                            className={`settings-color-pill${prefs.default_highlight_color === c.id ? ' active' : ''}`}
                            onClick={() => setPrefs({...prefs, default_highlight_color: c.id})}
                          >
                            <span className="swatch-dot" style={{backgroundColor: c.swatch}} />
                            {c.label}
                          </button>
                        ))}
                      </div>
                    </div>

                    <div className="settings-two-col">
                      <label className="settings-check">
                        <input
                          type="checkbox"
                          checked={prefs.show_outline_by_default}
                          onChange={e => setPrefs({...prefs, show_outline_by_default: e.target.checked})}
                        />
                        <div>
                          <strong>默认展开左侧论文目录</strong>
                        </div>
                      </label>
                      <label className="settings-check">
                        <input
                          type="checkbox"
                          checked={prefs.show_ai_panel_by_default}
                          onChange={e => setPrefs({...prefs, show_ai_panel_by_default: e.target.checked})}
                        />
                        <div>
                          <strong>默认展开右侧 AI 与高亮栏</strong>
                        </div>
                      </label>
                    </div>
                  </div>
                )}

                {tab === 'llm' && (
                  <div className="settings-section">
                    <h3>全局默认大模型（AI 精读 / 论文问答 / 默认翻译）</h3>
                    <p className="settings-desc">
                      支持任意 OpenAI 兼容接口。API 密钥通过 Windows DPAPI 绑定当前用户加密保存在本机，不会写入明文文件或上传。
                    </p>

                    <div className="settings-presets">
                      <span>快捷填入常用模型：</span>
                      {LLM_PRESETS.map(p => (
                        <button
                          key={p.label}
                          type="button"
                          onClick={() => setLlm({...llm, endpoint: p.endpoint, model: p.model})}
                        >
                          {p.label}
                        </button>
                      ))}
                    </div>

                    <div className="settings-field">
                      <label htmlFor="llm-endpoint">API 端点 URL（Chat Completions）</label>
                      <input
                        id="llm-endpoint"
                        placeholder="https://api.deepseek.com/chat/completions"
                        value={llm.endpoint}
                        onChange={e => setLlm({...llm, endpoint: e.target.value})}
                      />
                    </div>

                    <div className="settings-two-col">
                      <div className="settings-field">
                        <label htmlFor="llm-model">模型名称</label>
                        <input
                          id="llm-model"
                          placeholder="deepseek-chat"
                          value={llm.model}
                          onChange={e => setLlm({...llm, model: e.target.value})}
                        />
                      </div>
                      <div className="settings-field">
                        <label htmlFor="llm-env">备用环境变量名（可选）</label>
                        <input
                          id="llm-env"
                          placeholder="例如 DEEPSEEK_API_KEY"
                          value={llm.key_env}
                          onChange={e => setLlm({...llm, key_env: e.target.value})}
                        />
                      </div>
                    </div>

                    <div className="settings-field">
                      <label htmlFor="llm-key">API 密钥（DPAPI 加密保存）</label>
                      <div className="settings-inline-row">
                        <input
                          id="llm-key"
                          type="password"
                          autoComplete="off"
                          placeholder={
                            clearLlmKey
                              ? '将在保存时清除本地密钥'
                              : llm.has_saved_key
                              ? `已加密保存（${llm.masked_key || '已隐藏'}），留空保持不变`
                              : '粘贴你的 API Key，如 sk-...'
                          }
                          value={llmKey}
                          onChange={e => {
                            setLlmKey(e.target.value);
                            if (e.target.value) setClearLlmKey(false);
                          }}
                        />
                        {llm.has_saved_key && !clearLlmKey && (
                          <button type="button" className="hl-danger-btn" onClick={() => {setClearLlmKey(true); setLlmKey('')}}>
                            清除已存密钥
                          </button>
                        )}
                      </div>
                    </div>

                    <label className="settings-check">
                      <input
                        type="checkbox"
                        checked={!!llm.use_system_proxy}
                        onChange={e => setLlm({...llm, use_system_proxy: e.target.checked})}
                      />
                      <div>
                        <strong>请求模型 API 时跟随 Windows 系统代理</strong>
                        <small>如果你使用 Clash / v2ray 等本地代理访问海外模型端点（如 OpenAI / Claude），请勾选此项。</small>
                      </div>
                    </label>

                    <div className="settings-action-row">
                      <button
                        type="button"
                        disabled={testing !== null || !llm.endpoint.trim() || !llm.model.trim()}
                        onClick={() => void handleTestLlm('global')}
                      >
                        {testing === 'global' ? '正在测试连接…' : '⚡ 测试全局模型连通性'}
                      </button>
                    </div>
                  </div>
                )}

                {tab === 'tasks' && (
                  <div className="settings-section">
                    <h3>按任务单独指定模型（可选）</h3>
                    <p className="settings-desc">
                      默认情况下，学术翻译与术语提取直接沿用「全局 LLM 模型」。如果你想为翻译选用更快、更便宜或专门优化的模型，可在此单独覆盖。
                    </p>

                    <div className="settings-card">
                      <label className="settings-check">
                        <input
                          type="checkbox"
                          checked={customTrans}
                          onChange={e => setCustomTrans(e.target.checked)}
                        />
                        <div>
                          <strong>为「学术翻译」单独指定专用模型</strong>
                          <small>未勾选时自动沿用全局默认模型（取消勾选并保存后将恢复沿用全局设置）。</small>
                        </div>
                      </label>

                      {customTrans && (
                        <div className="settings-subform">
                          <div className="settings-field">
                            <label>翻译模型端点</label>
                            <input
                              placeholder="https://api.deepseek.com/chat/completions"
                              value={transModel.endpoint}
                              onChange={e => setTransModel({...transModel, endpoint: e.target.value})}
                            />
                          </div>
                          <div className="settings-two-col">
                            <div className="settings-field">
                              <label>翻译模型名</label>
                              <input
                                placeholder="deepseek-chat"
                                value={transModel.model}
                                onChange={e => setTransModel({...transModel, model: e.target.value})}
                              />
                            </div>
                            <div className="settings-field">
                              <label>备用环境变量名（可选）</label>
                              <input
                                value={transModel.key_env}
                                onChange={e => setTransModel({...transModel, key_env: e.target.value})}
                              />
                            </div>
                          </div>
                          <div className="settings-field">
                            <label>翻译专用 API 密钥（可选，留空沿用全局密钥）</label>
                            <div className="settings-inline-row">
                              <input
                                type="password"
                                autoComplete="off"
                                placeholder={
                                  clearTransKey
                                    ? '将在保存时清除专用密钥'
                                    : transModel.has_saved_key
                                    ? `已保存 (${transModel.masked_key})`
                                    : '留空则沿用全局密钥或环境变量'
                                }
                                value={transKey}
                                onChange={e => {
                                  setTransKey(e.target.value);
                                  if (e.target.value) setClearTransKey(false);
                                }}
                              />
                              {transModel.has_saved_key && !clearTransKey && (
                                <button type="button" className="hl-danger-btn" onClick={() => {setClearTransKey(true); setTransKey('')}}>
                                  清除密钥
                                </button>
                              )}
                            </div>
                          </div>
                          <div className="settings-inline-between">
                            <label className="checkbox-inline">
                              <input
                                type="checkbox"
                                checked={!!transModel.use_system_proxy}
                                onChange={e => setTransModel({...transModel, use_system_proxy: e.target.checked})}
                              />
                              跟随系统代理
                            </label>
                            <button
                              type="button"
                              disabled={testing !== null || !transModel.endpoint.trim() || !transModel.model.trim()}
                              onClick={() => void handleTestLlm('translation')}
                            >
                              {testing === 'translation' ? '测试中…' : '⚡ 测试翻译模型'}
                            </button>
                          </div>
                        </div>
                      )}
                    </div>

                    <div className="settings-card">
                      <label className="settings-check">
                        <input
                          type="checkbox"
                          checked={customGloss}
                          onChange={e => setCustomGloss(e.target.checked)}
                        />
                        <div>
                          <strong>为「术语表提取」单独指定专用模型</strong>
                          <small>未勾选时自动沿用全局默认模型。</small>
                        </div>
                      </label>

                      {customGloss && (
                        <div className="settings-subform">
                          <div className="settings-field">
                            <label>术语模型端点</label>
                            <input
                              placeholder="https://api.deepseek.com/chat/completions"
                              value={glossModel.endpoint}
                              onChange={e => setGlossModel({...glossModel, endpoint: e.target.value})}
                            />
                          </div>
                          <div className="settings-two-col">
                            <div className="settings-field">
                              <label>术语模型名</label>
                              <input
                                placeholder="deepseek-chat"
                                value={glossModel.model}
                                onChange={e => setGlossModel({...glossModel, model: e.target.value})}
                              />
                            </div>
                            <div className="settings-field">
                              <label>备用环境变量名（可选）</label>
                              <input
                                value={glossModel.key_env}
                                onChange={e => setGlossModel({...glossModel, key_env: e.target.value})}
                              />
                            </div>
                          </div>
                          <div className="settings-field">
                            <label>术语专用 API 密钥（可选）</label>
                            <div className="settings-inline-row">
                              <input
                                type="password"
                                autoComplete="off"
                                placeholder={
                                  clearGlossKey
                                    ? '将在保存时清除专用密钥'
                                    : glossModel.has_saved_key
                                    ? `已保存 (${glossModel.masked_key})`
                                    : '留空则沿用全局密钥或环境变量'
                                }
                                value={glossKey}
                                onChange={e => {
                                  setGlossKey(e.target.value);
                                  if (e.target.value) setClearGlossKey(false);
                                }}
                              />
                              {glossModel.has_saved_key && !clearGlossKey && (
                                <button type="button" className="hl-danger-btn" onClick={() => {setClearGlossKey(true); setGlossKey('')}}>
                                  清除密钥
                                </button>
                              )}
                            </div>
                          </div>
                          <div className="settings-inline-between">
                            <label className="checkbox-inline">
                              <input
                                type="checkbox"
                                checked={!!glossModel.use_system_proxy}
                                onChange={e => setGlossModel({...glossModel, use_system_proxy: e.target.checked})}
                              />
                              跟随系统代理
                            </label>
                            <button
                              type="button"
                              disabled={testing !== null || !glossModel.endpoint.trim() || !glossModel.model.trim()}
                              onClick={() => void handleTestLlm('glossary')}
                            >
                              {testing === 'glossary' ? '测试中…' : '⚡ 测试术语模型'}
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {tab === 'obsidian' && (
                  <div className="settings-section">
                    <h3>Obsidian 本地知识库（Vault）同步设置</h3>
                    <p className="settings-desc">
                      配置你的 Obsidian Vault 根目录后，在知识笔记界面可一键将论文笔记与高亮摘录同步为同名 <code>&lt;论文标题&gt;.md</code>（完全兼容 OneDrive / iCloud 同步盘与 Obsidian 双向链接）。
                    </p>

                    <div className="settings-field">
                      <label htmlFor="vault-root">Obsidian Vault 本地根目录（绝对路径）</label>
                      <input
                        id="vault-root"
                        placeholder="例如 D:\Obsidian\MyResearchVault"
                        value={vault.root}
                        onChange={e => setVault({...vault, root: e.target.value})}
                      />
                    </div>

                    <div className="settings-field">
                      <label htmlFor="vault-subdir">论文笔记存放子目录（使用 / 分隔）</label>
                      <input
                        id="vault-subdir"
                        placeholder="PaperMind"
                        value={vault.subdir}
                        onChange={e => setVault({...vault, subdir: e.target.value})}
                      />
                      <small>
                        示例输出路径：{vault.root.trim() ? `${vault.root.trim()}\\${(vault.subdir.trim() || 'PaperMind').replace(/\//g, '\\')}\\<论文标题>.md` : '填写根目录后显示'}
                      </small>
                    </div>

                    <label className="settings-check">
                      <input
                        type="checkbox"
                        checked={prefs.default_bundle_pdf}
                        onChange={e => setPrefs({...prefs, default_bundle_pdf: e.target.checked})}
                      />
                      <div>
                        <strong>同步到 Obsidian 时默认附带原始 PDF 副本</strong>
                        <small>关闭时仅导出纯 Markdown 与图片资源（推荐，节省 Vault 同步盘空间）。</small>
                      </div>
                    </label>

                    <div className="settings-action-row">
                      <button
                        type="button"
                        disabled={testing !== null || !vault.root.trim()}
                        onClick={() => void handleValidateVault()}
                      >
                        {testing === 'vault' ? '正在检验目录…' : '✓ 检验目录可写性'}
                      </button>
                    </div>
                  </div>
                )}
              </>
            )}
          </section>
        </div>

        <footer className="settings-footer">
          <div className="settings-status-area">
            {error && <span role="alert" className="settings-error">{error}</span>}
            {!error && notice && <span role="status" className="settings-notice">{notice}</span>}
            {!error && !notice && <span className="settings-hint">修改任意分类后，点击右侧按钮一次保存全部偏好。</span>}
          </div>
          <div className="settings-footer-actions">
            <button type="button" onClick={onClose} disabled={saving}>关闭</button>
            <button type="button" className="primary" onClick={() => void handleSaveAll()} disabled={loading || saving}>
              {saving ? '正在保存…' : '💾 保存全部设置'}
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}
