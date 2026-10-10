"""Deterministic lookup of descriptive style cards without provenance text."""

from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
import re
import unicodedata

REFERENCES = Path(__file__).parent / 'skills/art-style-motion/references'
_FIELDS = ('slug', 'name', 'category', 'dimension', 'style_prompt', 'shot_direction_notes',
           'typical_uses', 'keywords', 'aliases')
_SUMMARY_FIELDS = ('slug', 'name', 'category', 'dimension', 'typical_uses')
_INPUT_ALIASES = {
    'risograph': 'stencil-ink-print', 'hd-2d': 'pixel-sprites-with-depth',
    'backrooms': 'liminal-found-footage', 'dark-keynote': 'dark-tech-presentation',
    'ukiyoe': 'ukiyo-e-woodblock', 'swiss-motion': 'grid-based-motion',
}
_BUILTIN_INPUT_ALIASES = {
    'van gogh': 'flow-field-post-impressionism', 'post impressionism': 'flow-field-post-impressionism',
    'mucha': 'ornamental-art-nouveau', 'art nouveau': 'ornamental-art-nouveau',
    'bauhaus': 'geometric-primary-colors', 'klimt': 'gold-pattern-portrait',
    'munch': 'expressive-color-bands', 'kusama': 'repeating-dot-fields',
    'dali': 'soft-form-surrealism', 'hopper': 'hard-edged-window-light',
    'ghibli': 'cel-and-watercolor', 'ghibli like watercolor': 'cel-and-watercolor',
    'kirby': 'energy-ink-comics', 'kirby like comics': 'energy-ink-comics',
    'monet': 'pond-brushwork', 'monet water lilies': 'pond-brushwork',
    'seurat': 'optical-color-points', 'matisse': 'cut-paper', 'matisse cut paper': 'cut-paper',
    'haring': 'contour-dancers', 'rembrandt': 'warm-chiaroscuro',
    'shinkai': 'layered-cel-lighting', 'shinkai like light': 'layered-cel-lighting',
    'picasso': 'elongated-blue-forms', 'picasso blue period': 'elongated-blue-forms',
    'kurzgesagt': 'flat-concept-worlds', 'vox': 'document-evidence',
    '3blue1brown': 'continuous-mathematical-objects', '3b1b': 'continuous-mathematical-objects',
    'keynote': 'product-presentation', 'kinetic typography': 'kinetic-type',
    '8 bit': '8-bit', 'early cgi': 'early-ray-traced-cgi',
    'cave art': 'cave-painting', 'egyptian': 'egyptian-mural', 'gothic': 'gothic-illumination',
}
_STOPWORDS = frozenset('a an and art animated animation as available by catalog catalogue create '
                      'do don t never avoid no not without explainer film for from in look make me '
                      'motion of or please short show silent style styles the title titles titled '
                      'caption headline to use using video with'.split())
_QUOTES = re.compile(r'"([^"]*)"|“([^”]*)”|(?<!\w)\'([^\']*)\'(?!\w)')
_NEGATIVE = re.compile(r"\b(?:do not|don t|never|avoid|without|no|not)(?:\s+(?:use|using|a|the|any|style))*\s*$", re.I)
_SUBJECT = re.compile(r'\b(?:about|on|explaining|history of|life of|biography of)\s+'
                      r'(?:(?:the|ancient|art|life|history|of)\s+){0,4}$', re.I)


def _normalize(value: str) -> str:
    text = unicodedata.normalize('NFKD', value.casefold())
    return ' '.join(re.findall(r'[a-z0-9]+', text))


def _validate_query(query: str, limit: int = 8) -> None:
    if not isinstance(query, str) or len(query) > 500:
        raise ValueError('Style queries must be strings of at most 500 characters.')
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError('Style result limits must be integers from 1 to 20.')


@lru_cache(maxsize=1)
def _catalog() -> tuple[dict, ...]:
    rows = json.loads((REFERENCES / 'catalog/index.json').read_text())['styles']
    return tuple(sorted(({key: row[key] for key in _FIELDS} for row in rows), key=lambda row: row['slug']))


@lru_cache(maxsize=1)
def _builtins() -> tuple[dict, ...]:
    rows = []
    for filename, category in [('style-cards.md', 'Built-in art style'),
                               ('grammar-cards.md', 'Built-in animation grammar')]:
        for line in (REFERENCES / filename).read_text().splitlines():
            if not line.startswith('| ') or line.startswith(('| Card |', '| Grammar |')):
                continue
            name, material, motion, review = (cell.strip() for cell in line.strip('|').split('|'))
            name = re.sub(r'^\d+\s+', '', name)
            rows.append({'slug': _normalize(name).replace(' ', '-'), 'name': name, 'category': category,
                         'dimension': '3D' if 'ray-traced' in name.lower() else '2D',
                         'style_prompt': material, 'shot_direction_notes': [motion, review],
                         'typical_uses': ['Animated explainer' if 'grammar' in category else 'Animated art short'],
                         'keywords': _normalize(name).split(), 'aliases': []})
    return tuple(rows)


@lru_cache(maxsize=2)
def _names(builtins: bool = False) -> tuple[dict[str, dict], re.Pattern]:
    rows = _builtins() if builtins else _catalog()
    by_slug = {row['slug']: row for row in rows}
    names = {_normalize(name): row for row in rows for name in [row['slug'], row['name'], *row['aliases']]}
    for name, slug in (_BUILTIN_INPUT_ALIASES if builtins else _INPUT_ALIASES).items():
        if slug in by_slug:
            names[_normalize(name)] = by_slug[slug]
    pattern = '|'.join(re.escape(name) for name in sorted(names, key=lambda name: (-len(name), name)))
    return names, re.compile(r'(?<!\w)(?:' + pattern + r')(?!\w)')


@lru_cache(maxsize=1)
def _selection_patterns() -> tuple[re.Pattern, re.Pattern]:
    names = {**_names(True)[0], **_names()[0]}
    aliases = '|'.join(re.escape(name) for name in sorted(names, key=lambda name: (-len(name), name)))
    pattern = re.compile(r'(?<!\w)(?:' + aliases + r')(?!\w)')
    negative_list = re.compile(_NEGATIVE.pattern[:-1]
                               + rf'(?:(?:{aliases})(?:\s+(?:style|styles|grammar))?\s+(?:and|or|nor)\s+)+$')
    return pattern, negative_list


def _selection_text(prompt: str) -> str:
    def quoted(match):
        before, after = prompt[:match.start()], prompt[match.end():]
        title = re.search(r'\b(?:title[ds]?|caption|headline|called|named)\s*$', before, re.I)
        title = title or re.match(r'\s+as\s+(?:(?:the|a)\s+)?(?:title|headline|caption)\b', after, re.I)
        selected = re.search(r'\b(?:use|using|choose|select|apply|in|style of|inspired by)\s+(?:the\s+)?$', before, re.I)
        styled = re.match(r'\s*(?:style|look|grammar)\b', after, re.I)
        return next((value for value in match.groups() if value is not None), '') if not title and (selected or styled) else ''

    text = _normalize(_QUOTES.sub(quoted, prompt))
    pattern, negative_list = _selection_patterns()
    excluded = [(match.start(), match.end()) for match in pattern.finditer(text)
                if _NEGATIVE.search(text[:match.start()]) or negative_list.search(text[:match.start()])
                or _SUBJECT.search(text[:match.start()])]
    for start, end in reversed(excluded):
        text = text[:start] + ' ' + text[end:]
    return _normalize(text)


def _explicit(text: str, *, builtins: bool = False) -> dict | None:
    names, pattern = _names(builtins)
    match = pattern.search(text)
    return names[match[0]] if match else None


def _named_style(text: str) -> tuple[dict | None, bool]:
    candidates = []
    for builtins in [True, False]:
        names, pattern = _names(builtins)
        if match := pattern.search(text):
            candidates.append((match.start(), -len(match[0]), not builtins, names[match[0]]))
    if not candidates:
        return None, False
    _, _, catalog, selected = min(candidates, key=lambda row: row[:3])
    return selected, not catalog


def _rank(query: str) -> list[dict]:
    text = _normalize(query)
    if not text:
        return list(_catalog())
    terms = set(text.split()) - _STOPWORDS
    if not terms:
        return []
    exact = _names()[0].get(text)
    ranked = []
    for row in _catalog():
        score = 0
        matched = set()
        for fields, weight in [(['slug', 'name'], 20), (['aliases'], 15), (['keywords'], 10),
                               (['typical_uses'], 2), (['style_prompt', 'shot_direction_notes'], 1)]:
            values = [value for field in fields for value in (row[field] if isinstance(row[field], list) else [row[field]])]
            words = set(_normalize(' '.join(values)).split())
            overlap = words & terms
            score += len(overlap) * weight
            matched |= overlap
        if row is exact:
            score += 10_000
        if matched or row is exact:
            score += 100 * len(matched) / len(terms)
            ranked.append((score, row))
    return [row for _, row in sorted(ranked, key=lambda value: (-value[0], value[1]['slug']))]


def search_styles(query: str, limit: int = 8) -> list[dict]:
    """Return safe cards, ordered by exact match, relevance and stable slug."""
    _validate_query(query, limit)
    return deepcopy(_rank(query)[:limit])


def select_style(query: str, default_slug: str | None = None) -> dict:
    """Prefer a requested style, then a described look, then a configured default."""
    _validate_query(query)
    text = _selection_text(query)
    explicit, is_builtin = _named_style(text)
    matches = _rank(text)[:8] if text else []
    selected = explicit or (matches[0] if matches else None)
    basis = ('explicit built-in style' if is_builtin else 'explicit style') if explicit else (
        'described look' if selected else 'no matching style')
    if selected is None and default_slug is not None:
        selected = next((row for row in _catalog() if row['slug'] == default_slug), None)
        if selected:
            basis = 'default style'
    return {'selected': deepcopy(selected), 'basis': basis,
            'matches': deepcopy(matches)}


def _browse_request(text: str) -> bool:
    return bool(re.search(r'\b(?:show|list|browse|what|which)\b.*\bstyles\b', text)
                and re.search(r'\b(?:available|catalog|catalogue|film look|styles)\b', text)
                and not re.search(r'\b(?:do not|not|never|avoid)\s+(?:show|list|browse)\b', text))


def catalog_motion_request(prompt: str) -> bool:
    """Recognize catalog browsing and named styles without claiming subject mentions."""
    text = _selection_text(prompt)
    if _browse_request(text):
        return True
    motion = re.search(r'\b(?:animat\w*|videos?|shorts?|motion|move|moving|explainer)\b', text)
    _, pattern = _names(True)
    builtin_request = any(
        re.match(r'\s+(?:style|grammar|art|animation)\b', text[match.end():])
        or re.search(r'\b(?:using|in|style of|inspired by)\s*$', text[:match.start()])
        for match in pattern.finditer(text)
    )
    names, pattern = _names()
    builtin_slugs = {row['slug'] for row in _builtins()}
    named_catalog = any(
        names[match[0]]['slug'] not in builtin_slugs
        or re.match(r'\s+(?:style|grammar)\b', text[match.end():])
        or re.search(r'\b(?:catalog|catalogue)\b', text)
        for match in pattern.finditer(text)
    )
    return bool(motion and (named_catalog or builtin_request
                           or re.search(r'\b(?:catalog|catalogue)\b.*\bstyle|\bstyle\w*\b.*\b(?:catalog|catalogue)\b', text)))


def style_context(prompt: str) -> dict:
    """Read a full Studio brief and return only safe planning cards and summaries."""
    if not isinstance(prompt, str) or len(prompt) > 64_000:
        raise ValueError('Style briefs must be strings of at most 64000 characters.')
    text = _selection_text(prompt)
    named, is_builtin = _named_style(text)
    if _browse_request(text):
        selected, basis, mode, matches = None, 'available styles', 'browse', list(_catalog())
    elif named is not None:
        selected, basis, mode = named, 'explicit built-in style' if is_builtin else 'explicit style', 'select'
        matches = [] if is_builtin else [named]
    else:
        description = re.sub(r'\b(?:about|on|explaining)\b.*', '', text)[:500]
        matches = _rank(description)[:8] if description.strip() else []
        selected = matches[0] if matches else None
        basis, mode = 'described look' if selected else 'no matching style', 'select'
    return {'mode': mode, 'total': len(_catalog()), 'selected': deepcopy(selected), 'basis': basis,
            'matches': [{key: deepcopy(row[key]) for key in _SUMMARY_FIELDS} for row in matches]}
