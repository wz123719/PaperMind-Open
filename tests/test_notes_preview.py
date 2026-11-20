import subprocess
from pathlib import Path

def test_actual_react_preview_escapes_html_blocks_urls_and_remote_images():
    node='node'
    script=r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),{createRequire}=require('node:module');
const req=createRequire(process.cwd()+'/frontend/package.json'),ts=req('typescript'),React=req('react'),{renderToStaticMarkup}=req('react-dom/server');
function compiled(path,requireFn){const code=ts.transpileModule(fs.readFileSync(path,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText;const exports={};new Function('require','exports',code)(requireFn,exports);return exports}
const services=compiled('frontend/src/services/notes.ts',req);
assert.equal(services.safeNoteUrl('javascript:alert(1)'),null);
assert.equal(services.safeNoteUrl('data:text/html,test'),null);
assert.equal(services.safeNoteUrl('https://example.test/a'),'https://example.test/a');
const component=compiled('frontend/src/components/MarkdownPreview.tsx',p=>p==='../services/notes'?services:req(p)).MarkdownPreview;
const text=['# 中文😀','<script>alert(1)</script>','[bad](javascript:alert(1))','![remote](https://example.invalid/x.png)','![local](asset:known)','[[知识联系]]','','|列|值|','|---|---|','|A|3|','','$$','x^{-2}','$$','','```js','<script>code</script>','```'].join('\n');
const html=renderToStaticMarkup(React.createElement(component,{text,assets:[{id:'known',url:'/api/v1/parse-runs/safe/assets/local.png'}]}));
assert(!html.includes('<script>'));assert(!html.includes('href="javascript:'));assert(!html.includes('src="https:'));
assert(html.includes('src="/api/v1/parse-runs/safe/assets/local.png"'));assert(html.includes('x^{-2}'));assert(html.includes('[[知识联系]]'));
assert(html.includes('<table'));assert(html.includes('<pre'));assert(html.includes('&lt;script&gt;'));
console.log('React preview: escaped HTML, dangerous links blocked, only local registered images, Unicode/math/wikilinks preserved');
'''
    result=subprocess.run([node,'-e',script],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,encoding='utf-8',timeout=15)
    assert result.returncode==0,result.stderr
