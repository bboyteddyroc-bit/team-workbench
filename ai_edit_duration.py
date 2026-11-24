"""Deterministic duration diagnostics. Never extend or repeat footage to fill time."""
import math

POLICY='duration-repair-v1'

def sample_times(duration):
    # Cover the beginning, middle and end, bounded to 4–12 samples/source (≤60/request).
    count=min(12,max(4,math.ceil(duration/2)))
    last=max(0,duration-1/24)
    return sorted(set(round(last*i/(count-1),3) for i in range(count)))

def budget(snap):
    target=snap['brief']['target'];tolerance=max(.5,target*.1)
    sources=[{'source_id':s['id'],'available_frames':math.floor(s['duration']*24),'duration':math.floor(s['duration']*24)/24} for s in snap['source_info']]
    return {'target_seconds':target,'target_frames':round(target*24),'accepted_min_seconds':target-tolerance,'accepted_max_seconds':target+tolerance,'source_capacity_seconds':sum(s['duration'] for s in sources),'sources':sources,'rule':'先分配镜头时长，再选择源区间。总长=sum(end-start)，24fps取整。不得重复使用同一源时间区间、变速、定格、循环或无依据扩展凑时长。总容量不是内容可用性证明。'}

def diagnose(plan,snap):
    target=snap['brief']['target'];duration=plan['duration'];gap=target-duration
    issues=[]
    if abs(gap)>max(.5,target*.1):issues.append(f'实际 {duration:.2f} 秒，目标 {target:g} 秒，差额 {gap:+.2f} 秒')
    shots=plan['shots'];unused=[]
    for s in snap['source_info']:
        intervals=sorted((p['start'],p['end']) for p in shots if p['source_id']==s['id'])
        cursor=0
        for start,end in intervals:
            if start<cursor-1/48:issues.append(f"素材 {s['id']} 重复使用源区间，不能靠重复凑时长")
            if start>cursor+1/24:unused.append({'source_id':s['id'],'start':cursor,'end':start})
            cursor=max(cursor,end)
        end=math.floor(s['duration']*24)/24
        if end>cursor+1/24:unused.append({'source_id':s['id'],'start':cursor,'end':end})
    return {'issues':list(dict.fromkeys(issues)),'target':target,'actual':duration,'gap':gap,'unselected_intervals':unused,'note':'未选区间仅为时间范围，不代表已确认内容可用；必须结合抽帧与ASR选择，不能盲目补齐。'}
