"""Local, bounded lexical retrieval over a versioned GitHub knowledge snapshot."""
import json
import math
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent / 'rules' / 'tiktok-github-0de6db7'


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
