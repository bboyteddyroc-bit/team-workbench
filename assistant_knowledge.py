"""Local, bounded lexical retrieval over a versioned GitHub knowledge snapshot."""
import json
import math
import re
from collections import Counter
from pathlib import Path

PRODUCT_ROOT = Path(__file__).resolve().parent
ROOT = PRODUCT_ROOT / 'rules' / 'tiktok-github-0de6db7'


def tokens(text):
    text = text.lower()
    words = re.findall(r'[a-z0-9]+|[\u4e00-\u9fff]+', text)
    result = []
    for word in words:
        if re.fullmatch(r'[\u4e00-\u9fff]+', word):
            if len(word) == 1:
                continue
            result.extend(word[i:i + 2] for i in range(len(word) - 1))
        elif len(word) > 1 and word not in {'tiktok', 'shop', 'ai', 'the', 'and'}:
            result.append(word)
    return result


def product_context(query):
    """Always supply product orientation, then add bounded excerpts for this question."""
    path = PRODUCT_ROOT / 'docs' / 'AI_FEATURES.md'
    guide = path.read_text(encoding='utf-8-sig')
    sections = dict(re.findall(r'^## ([^\n]+)\n(.*?)(?=^## |\Z)', guide, re.M | re.S))
    overview = sections.pop('中台功能速览').strip()
    if not overview:
        raise ValueError('Empty product overview')

    query_tokens = set(tokens(query))
    generic = set(tokens('中台 功能 平台 助理 怎么 如何 使用 了解 支持 现在 所有 操作 可以'))
    specific = query_tokens - generic
    if re.search(r'快捷键|键位', query):
        sections['剪辑快捷键'] = (PRODUCT_ROOT / 'EDITOR_SHORTCUTS.md').read_text(encoding='utf-8-sig')
    ranked = []
    for title, section in sections.items():
        title_score = len(specific & set(tokens(title)))
        if re.search(r'安全与一致性修复|文档维护约定', title):
            continue
        for paragraph in section.strip().splitlines():
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            overlap = specific & set(tokens(paragraph))
            if overlap:
                ranked.append((len(overlap) * 2 + title_score, title, paragraph))
    ranked.sort(key=lambda hit: -hit[0])

    details = []
    seen = set()
    for _, title, paragraph in ranked:
        if paragraph in seen:
            continue
        seen.add(paragraph)
        text = paragraph[:1050]
        if len(paragraph) > 1050:
            text += '…'
        details.append(f'【{title}】{text}')
        if len(details) == 5:
            break
    if details:
        return overview + '\n\n相关操作说明\n' + '\n'.join(details)
    return overview


def retrieve(query, limit=3, max_chars=12000):
    manifest = json.loads((ROOT / 'manifest.json').read_text(encoding='utf-8'))
    q = set(tokens(query))
    if not q:
        return ''
    docs = []
    df = Counter()
    for entry in manifest['files']:
        path = (ROOT / entry['path']).resolve()
        if not path.is_relative_to(ROOT.resolve()) or path.suffix.lower() != '.md':
            raise ValueError('Invalid knowledge path')
        text = path.read_text(encoding='utf-8-sig')
        counts = Counter(tokens(entry['path'] + ' ' + text))
        df.update(counts.keys())
        docs.append((entry['path'], text, counts))
    scored = []
    for name, text, counts in docs:
        common = q & counts.keys()
        if not common:
            continue
        score = sum((1 + math.log((len(docs) + 1) / (df[t] + 1))) * min(counts[t], 3) for t in common)
        scored.append((score, name, text))
    scored.sort(key=lambda d: (-d[0], d[1]))
    sections = []
    remaining = max_chars
    for _, name, text in scored[:limit]:
        paragraphs = re.split(r'\n\s*\n', text)
        ranked = sorted(enumerate(paragraphs), key=lambda pair: (-len(q & set(tokens(pair[1]))), pair[0]))
        chosen = []
        allowance = min(4000, remaining)
        for idx, paragraph in ranked:
            if not (q & set(tokens(paragraph))):
                continue
            segment = paragraph.strip()[:allowance]
            if segment:
                chosen.append((idx, segment))
                allowance -= len(segment)
            if allowance <= 0:
                break
        if not chosen:
            continue
        excerpt = '\n\n'.join(p for _, p in sorted(chosen))
        sections.append('来源：' + name + '\n' + excerpt)
        remaining -= len(excerpt)
        if remaining <= 0:
            break
    return '\n\n---\n\n'.join(sections)
