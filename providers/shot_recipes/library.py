"""Read imported recipe text while keeping provenance out of customer results."""
from __future__ import annotations

from difflib import get_close_matches
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).parent
SLUG = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*\Z')
CATEGORIES = ('camera', 'data', 'effects', 'interaction', 'opening', 'outro',
              'rhythm', 'transition', 'typography', 'ui-entrance')
CUES = ('transition', 'impact', 'riser', 'ui', 'text', 'data', 'ambience', 'none')


@lru_cache(maxsize=1)
def _catalog() -> dict:
    payload = json.loads((ROOT / 'index.json').read_text(encoding='utf-8'))
    cards = payload['cards']
    index = {card['id']: card for card in cards}
    if len(index) != 157 or len(cards) != len(index):
        raise ValueError('The shot library must contain 157 unique cards.')
    for card_id, card in index.items():
        source = Path(card['source_path'])
        if (not SLUG.fullmatch(card_id) or card['category'] not in CATEGORIES
                or source.parts[:2] != ('references', 'shots') or len(source.parts) != 4
                or source.parts[2] != card['category'] or source.suffix != '.md'
                or not SLUG.fullmatch(source.stem)):
            raise ValueError('Invalid shot library identity.')
    return payload


def load_index() -> dict[str, dict]:
    return {card['id']: card for card in _catalog()['cards']}


def normalize(text: str) -> str:
    return ' '.join(re.findall(r'[a-z0-9]+|[\u3400-\u9fff]', text.lower()))


def find_named_card(prompt: str) -> str | None:
    """Match an exact id or an unambiguous multiword alias in an instruction."""
    text = ' ' + normalize(prompt) + ' '
    card_context = bool(re.search(r'\b(?:card|recipe|style)\b', prompt, re.I))
    matches = []
    for card_id, card in load_index().items():
        phrases = [normalize(card_id), *(normalize(k) for k in card['aliases'])]
        for phrase in phrases:
            explicit_single = card_context or bool(re.search(r"['\"]\s*" + re.escape(phrase) + r"\s*['\"]", prompt, re.I))
            if (len(phrase.split()) >= 2 or explicit_single) and ' ' + phrase + ' ' in text:
                matches.append((len(phrase), card_id))
    if not matches:
        return None
    longest = max(length for length, _ in matches)
    winners = {card_id for length, card_id in matches if length == longest}
    return next(iter(winners)) if len(winners) == 1 else None


def nearest_ids(card_id: str) -> list[str]:
    return get_close_matches(card_id, sorted(load_index()), n=5, cutoff=0)


def neutral_text(text: str) -> str:
    """Remove names found by the import review and non-resolvable code paths."""
    text = re.sub(r'参考实现[^\n]*', '', text)
    try:
        terms = _catalog().get('brand_terms', [])
    except (ValueError, OSError, KeyError, TypeError):
        return 'Recipe information is unavailable.'
    for term in sorted(terms, key=len, reverse=True):
        pattern = re.escape(term)
        if term.isascii() and re.fullmatch(r'[A-Za-z0-9 .-]+', term):
            pattern = r'(?<![A-Za-z0-9])' + pattern + r'(?![A-Za-z0-9])'
        text = re.sub(pattern, 'reference', text, flags=0 if term == 'Linear' else re.I)
    text = re.sub(r'https?://\S+|(?:demos|template|gallery|assets|workbench|jianying-export)/\S+',
                  '[source reference]', text)
    text = re.sub(r'\S+\.(?:tsx|ts|jsx|js|mp3|wav|mp4|webm)\b', '[source reference]', text)
    return text.strip()



def card_bytes(entry: dict) -> bytes:
    # Paths come only from the validated index, never from request data.
    return (ROOT / 'cards' / entry['category'] / Path(entry['source_path']).name).read_bytes()


def read_frontmatter(text: str) -> dict[str, str]:
    """Read the upstream single-line scalars, including its non-YAML quoted prose."""
    if not text.startswith('---\n'):
        raise ValueError('Shot card frontmatter is missing.')
    front = text.split('---', 2)[1]
    fields = {}
    for line in front.splitlines():
        if ':' in line:
            key, value = line.split(':', 1)
            fields[key.strip()] = value.strip()
    required = {'name', '一句话', '适用', '时长', '能量'}
    if not required <= fields.keys() or not all(fields[key] for key in required):
        raise ValueError('Shot card frontmatter is incomplete.')
    return fields


def parse_table(text: str) -> list[dict[str, str]]:
    rows = []
    for line in text.splitlines():
        if not line.strip().startswith('|'):
            continue
        cells = [neutral_text(cell.strip().replace(r'\|', '|'))
                 for cell in re.split(r'(?<!\\)\|', line.strip().strip('|'))]
        if len(cells) >= 2 and not re.fullmatch(r'[: -]+', cells[0]):
            rows.append(cells)
    return [{'parameter': cells[0], 'value': cells[1], 'notes': ' | '.join(cells[2:])}
             for cells in rows[1:]]

def parse_card(card_id: str) -> dict:
    if not SLUG.fullmatch(card_id) or card_id not in load_index():
        raise ValueError('Unknown shot card id.')
    entry = load_index()[card_id]
    data = card_bytes(entry)
    if hashlib.sha256(data).hexdigest() != entry['sha256']:
        raise ValueError('Shot card integrity check failed.')
    text = data.decode('utf-8')
    frontmatter = read_frontmatter(text)
    body = text.split('---', 2)[2]
    sections = {}
    for match in re.finditer(r'^##\s+([^\n]+)\n([\s\S]*?)(?=^##\s|\Z)', body, re.M):
        sections[match[1].strip()] = match[2].strip()
    table = parse_table(sections.get('参数表', ''))
    return {
        'intent': neutral_text(sections.get('意图', '')),
        'animation': neutral_text(sections.get('动效核心', '')),
        'parameter_table': table,
        'sound_cue': entry['sfx_cue'],
        'sound_timing': re.findall(r'\bf\d+\b|\b\d+(?:\.\d+)?[fs]\b', sections.get('声音', '')),
        'known_pitfalls': neutral_text(sections.get('已知坑', '')),
        'timing': neutral_text(frontmatter['时长']),
    }
