"""Explicit shared-case Kalodata projection. No private-query cache imports or retries."""
from datetime import date, datetime, timedelta, timezone
from kalodata_integration import QueryError, number


def period(days=30):
    end=datetime.now(timezone.utc).date()-timedelta(days=1)
    return {'days':days,'period_start':str(end-timedelta(days=days-1)),'period_end':str(end),'region':'US','currency':'USD'}


def fetch(service, case, options):
    start=date.fromisoformat(options['period_start']);end=date.fromisoformat(options['period_end'])
    if (end-start).days+1 not in (7,30) or end<start:
        raise QueryError('案例查询日期区间无效，未调用 Kalodata')
    from video_case_skill import detail_body,coerce_numbers,flatten_rich_text
    from video_case_commercial import date_text
    detail=service.post('/video/detail',detail_body(case['video'],start,end))
    if not isinstance(detail,dict) or not detail:
        raise QueryError('本次 Kalodata 查询未返回视频；原因尚未确认，原资料保留且未自动重试')
    if str(detail.get('video_id',''))!=case['video']:
        raise QueryError('Kalodata 返回的视频 ID 不匹配，未保存')
    handle=str(detail.get('belonged_creator_handle') or '').lstrip('@').lower()
    if handle and case['handle'] and handle!=case['handle'].lower():
        raise QueryError('Kalodata 返回的视频作者不匹配，未保存')
    if detail.get('video_region') and detail['video_region']!='US':
        raise QueryError('Kalodata 返回的视频市场不匹配，未保存')
    detail=coerce_numbers(detail)
    def nonnegative(key):
        n=number(detail.get(key));return n if n is not None and 0<=n<1e16 else None
    result={'provider':'Kalodata','endpoint':'/video/detail','data_type':'third_party_estimate','video_id':case['video'],
        'title':flatten_rich_text(detail.get('video_title'))[:10000],'handle':handle,
        'creator_id':str(detail.get('belonged_creator_id')) if str(detail.get('belonged_creator_id','')).isdigit() else None,
        'publish_date':date_text(detail.get('publish_date')),'creator_debut':date_text(detail.get('creator_debut')),
        'region':'US','currency':'USD','period_start':str(start),'period_end':str(end),'collected':datetime.now(timezone.utc).timestamp(),
        'period_views':nonnegative('views'),'gmv':nonnegative('revenue'),'units':nonnegative('sales_volumn'),
        'gpm':nonnegative('video_gpm'),'duration':nonnegative('duration'),'likes':nonnegative('digg_count'),
        'comments':nonnegative('comment_count'),'shares':nonnegative('share_count'),'product_count':nonnegative('product_number'),
        'limitations':['第三方区间估算，不是结算订单或累计播放','接口不保证返回封面、发布时间、收藏数、逐字稿或创意拆解；缺失不补零，商品类目不从榜单筛选参数推断']}
    result['extra_metrics']={k:nonnegative(k) for k in ('ads_roas','ad_revenue_ratio','ad_view_ratio','ads_views','ads_period','ad_cpa')}
    growth=number(detail.get('revenue_growth_rate'));result['extra_metrics']['revenue_growth_rate']=growth if growth is not None and abs(growth)<1e16 else None
    # /video/detail real response 7707267947466607885 was verified against the
    # website: 61.644627283192065 means 61.64%, NOT a 0..1 fraction.
    # Use an explicit endpoint/field contract, never a <=1 magnitude guess:
    # 0.25 from this field means 0.25%, not 25%. Preserve original unit evidence.
    raw_view_ratio=result['extra_metrics']['ad_view_ratio']
    result['extra_metric_provenance']={'ad_view_ratio':{'raw_value':raw_view_ratio,
        'raw_unit':'percentage_points','display_unit':'fraction',
        'contract':'video/detail.ad_view_ratio · API/website same-video verification'}}
    result['extra_metrics']['ad_view_ratio']=raw_view_ratio/100 if raw_view_ratio is not None and raw_view_ratio<=100 else None
    revenue_ratio=result['extra_metrics']['ad_revenue_ratio']
    if revenue_ratio is not None and revenue_ratio>1:result['extra_metrics']['ad_revenue_ratio']=None
    # Preserve the provider's ordered trend without inventing per-point dates or cadence.
    trend=detail.get('revenue_trend')
    if isinstance(trend,list) and len(trend)<=366:
        values=[number(value) for value in trend]
        if all(value is not None and 0<=value<1e16 for value in values):
            result['revenue_trend']=values
    result['provider_flags']={k:int(detail[k]) for k in ('ad','ai_video') if type(detail.get(k)) is bool or (type(detail.get(k)) in (int,float) and detail[k] in (0,1))}
    result['skill']={'repository':'https://github.com/sailtonight/kalodata-skill','revision':'6900ef27ceaae636dcde4dfeae3af9a1e171f917','need_extra':True}
    return result
