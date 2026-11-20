export const knowledgeReadingVersion = 'knowledge_dimension_v1';

export function isKnowledgeReading(run: {pipeline_version?:string}) {
  return run.pipeline_version === knowledgeReadingVersion;
}

export function readingDate(timestamp?:number) {
  return typeof timestamp==='number'&&Number.isFinite(timestamp)
    ? new Intl.DateTimeFormat('zh-CN',{dateStyle:'short',timeStyle:'medium',hour12:false}).format(timestamp*1000)
    : '';
}
