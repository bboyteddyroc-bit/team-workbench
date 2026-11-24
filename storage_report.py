"""Read-only, bounded storage inventory; reparse points inside categories are skipped."""
import os
import stat
import time
from pathlib import Path

CATEGORIES=(('media','AI 生成视频'),('assets','上传素材'),('edits','剪辑导出成片'),('edit_footage','剪辑导入素材'),('voice','配音相关'),('libtv','外部生成工作文件'))

def scan(path, deadline, limit=100000):
    total=count=errors=skipped=0; largest=[]; truncated=False
    stack=[path]
    while stack:
        if time.monotonic()>deadline or count>=limit:
            truncated=True; break
        current=stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if time.monotonic()>deadline or count>=limit:
                        truncated=True;break
                    try:
                        info=entry.stat(follow_symlinks=False)
                        if getattr(info,'st_file_attributes',0)&stat.FILE_ATTRIBUTE_REPARSE_POINT or entry.is_symlink():
                            skipped+=1;continue
                        if entry.is_dir(follow_symlinks=False): stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            count+=1;total+=info.st_size
                            largest.append((info.st_size,entry.name));largest.sort(reverse=True);del largest[10:]
                    except OSError: errors+=1
        except OSError: errors+=1
        if truncated:break
    return {'bytes':total,'files':count,'errors':errors,'skipped_links':skipped,'truncated':truncated,'largest':[{'name':name,'bytes':size} for size,name in largest]}

def report(hub):
    deadline=time.monotonic()+8
    categories=[]
    for key,label in CATEGORIES:
        source=hub.directory/key
        try: source=source.resolve(strict=True)
        except OSError:
            categories.append({'key':key,'label':label,'available':False});continue
        categories.append({'key':key,'label':label,'available':True,**scan(source,deadline)})
    backups=[]
    for key,label in CATEGORIES:
        p=hub.directory/(key+'.before-d-migration')
        if p.is_dir():backups.append({'label':label+'（C盘迁移前备份）',**scan(p,deadline)})
    # The original abandoned copy is an optional known sibling, never used as a source.
    try:
        media=hub.media.resolve(strict=True)
        if media.parent.name=='SeedanceHubData-migrated':
            old=media.parent.parent/'SeedanceHubData'
            if old.is_dir():backups.append({'label':'D盘第一次未完成的复制',**scan(old,deadline)})
    except OSError:pass
    with hub.db() as db:
        exports={row[0]:row[1] for row in db.execute('SELECT state,COUNT(*) FROM edit_exports GROUP BY state')}
    return {'categories':categories,'backups':backups,'exports':exports,'note':'统计为文件逻辑大小快照；跳过目录链接，扫描不完整时为下限。任务状态为累计数量。'}
