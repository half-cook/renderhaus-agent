#!/usr/bin/env python3
"""Rebuild the neutral art catalog from committed, internal text provenance."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROVENANCE = ROOT / 'third_party/lemo-opuscar'
CATALOG = ROOT / 'agent/deep_agent/skills/art-style-motion/references/catalog'


def pattern(term: str) -> str:
    escaped = re.escape(term)
    return rf'(?<!\w){escaped}(?!\w)' if term.isascii() else escaped


def slugify(name: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')


def prose(text: str) -> str:
    text = re.sub(r'```.*?```', '', text, flags=re.S)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'^\s*(?:#{1,6}|>)\s+', '', text, flags=re.M)
    text = re.sub(r'[*`]', '', text)
    return re.sub(r'\s+', ' ', text).strip()


def sections(text: str) -> dict[int, str]:
    parts = re.split(r'^## (\d+)\.[^\n]*\n', text, flags=re.M)
    return {int(parts[i]): parts[i + 1].split('\n---\n')[0].strip()
            for i in range(1, len(parts), 2)}


def category(name: str) -> str:
    for expression, family in [
        ('woodcut|engraving|copperplate|print|lithograph|silkscreen|newsprint|halftone', 'Print and printmaking'),
        ('oil|gouache|watercolor|charcoal|crayon|pastel|tempera|painting|sketch', 'Drawing and painting'),
        ('mosaic|glass|manuscript|miniature|silk|hand-block', 'Craft and materials'),
        ('pixel|cartoon|comics|caricature', 'Illustration and animation'),
        ('blueprint|marker|typewriter|titles|poster|axonometric', 'Graphic design'),
    ]:
        if re.search(expression, name, re.I):
            return family
    return 'Cinematic treatments'


USES = {
    'Print and printmaking': ['Editorial explainers', 'Travel stories', 'Poster sequences'],
    'Drawing and painting': ['Personal stories', 'Atmospheric art shorts', 'Illustrated explanations'],
    'Craft and materials': ['Material-led stories', 'Process explanations', 'Chapter sequences'],
    'Illustration and animation': ['Character shorts', 'Concept explanations', 'Playful sequences'],
    'Graphic design': ['Technical explanations', 'Title sequences', 'Visual diagrams'],
    'Cinematic treatments': ['Visual essays', 'Atmospheric shorts', 'Scene studies'],
}


def shot_note(text: str, seconds: float) -> str:
    framings = [
        (r'over.{0,20}shoulder', 'over-the-shoulder view'),
        (r'\b(?:POV|subjective)\b', 'subjective view'),
        (r'\b(?:close|detail|macro)\b', 'detail view'),
        (r'\b(?:wide|panorama|aerial)\b', 'establishing view'),
        (r'\b(?:top.down|overhead)\b', 'overhead view'),
        (r'\b(?:low|ground.level)\b', 'low view'),
    ]
    framing = next((label for expression, label in framings if re.search(expression, text, re.I)), 'medium view')
    moves = [(r'push(?:es)?(?: slowly)?(?: in| closer)?', 'push toward the focal subject'),
             (r'pull(?:s)?(?: slowly)? back|ease(?:s)? back', 'pull back to show context'),
             (r'track|truck|dolly|pan\b', 'track laterally through the composition'),
             (r'crane|tilt up|rise', 'rise to reveal the scene'),
             (r'tilt down', 'tilt down to a material detail'),
             (r'locked|static|hold', 'hold the composition for comprehension')]
    movement = [label for expression, label in moves if re.search(expression, text, re.I)]
    action = '; '.join(movement) or 'keep the focal subject legible while its material responds'
    return f'Use an {framing}; {action}. Source pacing example {seconds:g} s; retime to the actual story.'


def build() -> tuple[dict, dict]:
    source = json.loads((PROVENANCE / 'source.json').read_text())
    metadata = json.loads((PROVENANCE / 'normalization.json').read_text())
    vocabulary = json.loads((PROVENANCE / 'scan_terms.json').read_text())
    files = source['files']
    for path, text in files.items():
        if hashlib.sha256(text.encode()).hexdigest() != source['sha256'][path]:
            raise ValueError(f'Original source checksum changed: {path}')
    board = json.loads(files['styleboard/opuscar98_styles.json'])
    guide_paths = sorted(path for path in files if path.endswith('/style.json'))
    assert len(board['films']) == 98 and len(guide_paths) == 43 and len(files) == 130
    titles = [title for film in board['films'] for title in (film['title'], film['zh'])]
    titles += [json.loads(files[path])['film'] for path in guide_paths]
    terms = sorted(set(titles + vocabulary['deny_terms']), key=lambda term: (-len(term), term))
    expressions = {term: re.compile(pattern(term), re.I) for term in terms}
    folded_terms = {term: term.casefold() for term in terms}
    replacements = vocabulary['replacements']
    scrubs = []
    mapping = {}

    def scrub(text: str, slug: str, field: str) -> str:
        before = text
        text = re.sub(r'\bReferences?:.*?(?=\bAvoid:|$)', '', text, flags=re.I | re.S)
        text = re.sub(r'\bas (?:in|seen in)\b[^.;]*', '', text, flags=re.I)
        text = re.sub(r'\bafter\s+[^.\n]+', '', text) if re.search(
            r'\bafter\s+(?:Käthe|Welsh painter|the Strobridge)', text) else text
        for phrase, replacement in vocabulary['context_replacements'].items():
            text = re.sub(pattern(phrase), replacement, text, flags=re.I)
        folded = before.casefold()
        matched = [term for term in terms if folded_terms[term] in folded and expressions[term].search(before)]
        for term in matched:
            text = expressions[term].sub(replacements.get(term, 'original subject'), text)
        text = prose(text)
        text = re.sub(r'\s+([.,;])', r'\1', text)
        if text != before:
            scrubs.append({'slug': slug, 'field': field, 'reason': 'descriptive-only adaptation',
                           'terms': matched, 'before': before, 'after': text})
        return text

    rows = []
    for film, name in zip(board['films'], metadata['film_names'], strict=True):
        slug = slugify(name)
        family = category(name)
        mapping[f"styleboard/opuscar98_styles.json#{film['no']}"] = slug
        if name != film['style_en']:
            scrubs.append({'slug': slug, 'field': 'name', 'reason': 'Authored neutral display label',
                           'terms': [term for term in terms if expressions[term].search(film['style_en'])],
                           'before': film['style_en'], 'after': name})
        prompt = scrub(film['prompt_en'], slug, 'style_prompt')
        notes = []
        for i, shot in enumerate(film['shots']):
            note = shot_note(shot['en'], shot['sec'])
            notes.append(note)
            scrubs.append({'slug': slug, 'field': f'shot_direction_notes[{i}]',
                           'reason': 'Replace example plot and characters with reusable camera direction',
                           'terms': [term for term in terms if folded_terms[term] in shot['en'].casefold()
                                     and expressions[term].search(shot['en'])],
                           'before': shot['en'], 'after': note})
        direction = ('Connect shots through a consistent palette, focal scale, and an original subject. '
                     'Use material-specific transitions; adapt event timing to the actual story and recording.')
        notes.append(direction)
        scrubs.append({'slug': slug, 'field': 'direction', 'reason': 'Remove demo-specific story and timing',
                       'terms': [term for term in terms if folded_terms[term] in film['direction_en'].casefold()
                                 and expressions[term].search(film['direction_en'])],
                       'before': film['direction_en'], 'after': direction})
        rows.append({'slug': slug, 'name': name, 'category': family, 'dimension': film['render'],
                     'style_prompt': prompt, 'shot_direction_notes': notes, 'typical_uses': USES[family],
                     'keywords': sorted(set(re.findall(r'[a-z]+', name.lower())) - {'and', 'with'}), 'aliases': []})

    for path in guide_paths:
        guide = json.loads(files[path])
        authored = metadata['guides'][guide['slug']]
        slug = authored['slug']
        mapping[path] = slug
        if authored['name'] != guide['en']:
            scrubs.append({'slug': slug, 'field': 'name', 'reason': 'Authored neutral display label',
                           'terms': [term for term in terms if expressions[term].search(guide['en'])],
                           'before': guide['en'], 'after': authored['name']})
        parts = sections(files[path.replace('style.json', 'STYLE.md')])
        prompt = scrub('\n\n'.join(parts[i] for i in (1, 2, 3, 4) if i in parts), slug, 'style_prompt')
        notes = [scrub(parts[i], slug, f'shot_direction_notes[{i}]') for i in (5, 6, 8, 11) if i in parts]
        family = guide['category_en'].replace('&', 'and').replace('Keynote', 'Presentation')
        uses = [scrub(use, slug, 'typical_uses') for use in guide['uses']]
        rows.append({'slug': slug, 'name': authored['name'], 'category': family,
                     'dimension': authored['dimension'], 'style_prompt': prompt,
                     'shot_direction_notes': notes, 'typical_uses': uses,
                     'keywords': sorted(set(re.findall(r'[a-z]+', authored['name'].lower())) - {'and', 'with'})
                                 + authored['aliases'], 'aliases': authored['aliases']})

    assert len(rows) == len({row['slug'] for row in rows}) == 141
    assert len({row['name'] for row in rows}) == 141
    remaining = []
    for row in rows:
        for field, value in row.items():
            text = json.dumps(value, ensure_ascii=False)
            folded = text.casefold()
            for term in terms:
                if folded_terms[term] in folded and expressions[term].search(text):
                    remaining.append({'slug': row['slug'], 'field': field, 'term': term})
    if remaining:
        raise ValueError(f'Unsafe derivative fields: {remaining}')
    index = {'schema_version': 1, 'metadata': 'Renderhaus-authored derivative metadata and descriptive-only prompt adaptations.',
             'counts': {'film_prompts': 98, 'style_guides': 43, 'exact_duplicates': 0, 'catalog_styles': 141},
             'styles': sorted(rows, key=lambda row: row['slug'])}
    source_matches = []
    for path, text in files.items():
        folded = text.casefold()
        source_matches.extend({'source_path': path, 'term': term, 'count': len(expressions[term].findall(text))}
                              for term in terms if folded_terms[term] in folded and expressions[term].search(text))
    scan = {'notice': 'INTERNAL PROVENANCE ONLY. Never return this report or original text to the planner or user.',
            'source_commit': source['commit'], 'read_date': '2026-10-10', 'files_scanned': len(files),
            'deny_terms': sorted(terms), 'source_mapping': mapping, 'source_matches': source_matches,
            'scrubbed_styles': len({row['slug'] for row in scrubs}),
            'flagged_styles': len({row['slug'] for row in scrubs if row['terms']}),
            'scrubs': scrubs, 'remaining_public_matches': remaining,
            'dedupe': 'No identical source records or identical reusable prompts across the two sets. Medium families overlap; retain their distinct palettes, camera grammar and motion treatments.',
            'dimension_note': metadata['notice']}
    return index, scan


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Check generated bytes without writing')
    args = parser.parse_args()
    index, scan = build()
    outputs = {CATALOG / 'index.json': json.dumps(index, ensure_ascii=False, indent=2) + '\n',
               PROVENANCE / 'BRAND_SCAN.json': json.dumps(scan, ensure_ascii=False, indent=2) + '\n',
               CATALOG / 'LICENSE': (PROVENANCE / 'LICENSE').read_text()}
    for path, text in outputs.items():
        if args.check:
            if not path.exists() or path.read_text() != text:
                raise SystemExit(f'Catalog drift: {path.relative_to(ROOT)}')
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
    print(f"ok art catalog ({len(index['styles'])} styles, {scan['scrubbed_styles']} adapted, {scan['flagged_styles']} with denied terms)")


if __name__ == '__main__':
    main()
