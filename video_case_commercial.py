"""Typed provider-only commercial detail rows. No factual inference from request filters."""
from datetime import datetime
import math,re

NUMERIC=(('units','区间销量','units'),('gpm','GPM · 千次播放收入','gpm'),('product_count','关联商品数','product_count'),('duration','视频时长（秒）','duration'))
EXTRA=(('ads_views','广告播放量'),('ads_roas','广告ROAS'),('ads_period','广告投放天数'),('ad_cpa','单笔成交广告成本'),('ad_view_ratio','广告播放占比'),('ad_revenue_ratio','广告收入占比'),('revenue_growth_rate','收入增长率'))


def finite(value,negative=False):
    if type(value) not in (int,float) or not math.isfinite(value) or abs(value)>=1e16:return None
    if not negative and value<0:return None
    return value


def date_text(value):
    if not isinstance(value,str):return None
    for pattern,fmt in [(r'\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}','%Y/%m/%d %H:%M:%S'),(r'\d{4}-\d{2}-\d{2}','%Y-%m-%d')]:
        if re.fullmatch(pattern,value):
            try:datetime.strptime(value,fmt);return value
            except ValueError:return None
    return None


def projection(row):
    kd=row.get('source',{}).get('kalodata',{}) or {};extra=kd.get('extra_metrics',{}) or {};flags=kd.get('provider_flags',{}) or {};result=[]
    scope=f"{kd.get('region','US')} · {kd.get('currency','USD')} · {kd.get('period_start','?')} — {kd.get('period_end','?')}（UTC查询区间）"
    def add(key,label,value,kind='number',note=''):
        result.append({'key':key,'label':label,'value':value,'kind':kind,'missing':value is None,'source':'Kalodata' if value is not None else '未提供','scope':scope,'note':note,'collected':kd.get('collected'),'endpoint':kd.get('endpoint','/video/detail')})
    for key,label,source in NUMERIC:add(key,label,finite(kd.get(source)))
    for key,label in EXTRA:
        add(key,label,finite(extra.get(key),negative=key=='revenue_growth_rate'),'ratio' if key.endswith('_ratio') else 'number','增长率保留供应商原值，不猜测单位' if key=='revenue_growth_rate' else '占比按0–1小数转百分比' if key.endswith('_ratio') else '')
    for key,label,zero,one in [('ad','广告视频','自然视频（供应商标记）','广告视频（供应商标记）'),('ai_video','AI生成标记','非AI（供应商标记）','AI生成（供应商标记）')]:
        value=flags.get(key);add(key,label,one if type(value) in (int,bool) and value==1 else zero if type(value) in (int,bool) and value==0 else None,'text','这是供应商标记，不是人工鉴定，也不代表商家可见性')
    published=date_text(kd.get('publish_date'))
    add('publish_date','平台发布时间',published,'text','平台返回的所在市场时间，未附UTC偏移；不擅自按北京时间换算')
    add('creator_debut','达人入驻日期',date_text(kd.get('creator_debut')),'text','达人入驻日期不是视频发布时间')
    trend=kd.get('revenue_trend')
    if isinstance(trend,list) and trend and len(trend)<=366 and all(finite(v) is not None for v in trend):
        add('revenue_trend','收入趋势（原始顺序）','，'.join(str(v) for v in trend),'text','供应商趋势数列；时间点及间隔未确认，不推断日期或作累计值')
    else:
        add('revenue_trend','收入趋势（原始顺序）',None,'text','缺失或格式无效；不推断日期')
    add('creator_id','所属达人ID',kd.get('creator_id') if isinstance(kd.get('creator_id'),str) and re.fullmatch(r'\d{5,25}',kd['creator_id']) else None,'text')
    return result
