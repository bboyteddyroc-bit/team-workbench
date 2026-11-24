"""Provider fetch status independent from human review/media analysis state."""

def projection(row):
    kd=row.get('source',{}).get('kalodata') or {};job=next((j for j in row.get('jobs',[]) if j['kind']=='kalodata'),None)
    state=job.get('state') if job else None
    if state in ('queued','submitting','running'):
        return {'state':'loading','label':'平台数据获取中','message':'按精确视频ID优先获取；返回即展示，不等待视频下载或AI分析。','has_data':bool(kd),'collected':kd.get('collected')}
    if job and state=='attention':
        return {'state':'unavailable','label':'本次平台取数未成功','message':job.get('error') or '请核对处理记录；不将缺失当作0，也不使用其他视频数据。','has_data':bool(kd),'collected':kd.get('collected')}
    if kd:
        return {'state':'ready','label':'平台数据已返回','message':'以下为Kalodata实际返回字段；缺失仍显示未提供。视频与AI可在后台继续，旧数据不自动长期刷新。','has_data':True,'collected':kd.get('collected')}
    source=row.get('source',{}) or {};metadata=next((j for j in row.get('jobs',[]) if j['kind']=='metadata'),None)
    if metadata and metadata.get('state') in ('queued','submitting','running'):
        return {'state':'loading','label':'公开视频数据获取中','message':'正在通过 Apify 采集单视频；商业数据按周查询。','has_data':bool(source.get('collected')),'collected':source.get('collected')}
    if metadata and metadata.get('state')=='attention':
        return {'state':'unavailable','label':'公开视频取数需核对','message':metadata.get('error') or '未获取到公开视频数据，未自动重试。','has_data':bool(source.get('collected')),'collected':source.get('collected')}
    if source.get('collected'):
        return {'state':'ready','label':'公开视频快照已返回','message':'基础指标为采集时快照；Kalodata 商业数据另行查询。','has_data':True,'collected':source.get('collected')}
    return {'state':'empty','label':'尚无平台指标','message':'有视频或AI初稿不等于平台已收录；未返回的指标不补零。','has_data':False,'collected':None}
