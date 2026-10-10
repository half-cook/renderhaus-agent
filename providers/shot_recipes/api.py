"""Deterministic local shot lookup and storyboard validation."""
from __future__ import annotations

from typing import Literal

from providers.shot_recipes.contracts import request_for
from providers.shot_recipes.library import card_bytes, load_index, nearest_ids, normalize, parse_card, read_frontmatter, neutral_text


def shot_recipe_search(
    query: str | None = None, card_id: str | None = None, category: str | None = None,
    max_duration_s: float | None = None, energy: str | None = None, limit: int = 8,
    mode: Literal['search', 'validate_storyboard'] = 'search', storyboard: dict | None = None,
) -> dict:
    """Find neutral shot recipes locally, or validate a storyboard and separate audio stems."""
    try:
        request = request_for(dict(query=query, card_id=card_id, category=category,
                                   max_duration_s=max_duration_s, energy=energy, limit=limit,
                                   mode=mode, storyboard=storyboard))
        if request.mode == 'validate_storyboard':
            from providers.shot_recipes.storyboard import validate_storyboard

            return validate_storyboard(request.storyboard)
        index = load_index()
        if request.card_id:
            if request.card_id not in index:
                return {'ok': False, 'errors': ['Unknown shot card id.'], 'results': [],
                        'nearest_ids': nearest_ids(request.card_id)}
            cards = [index[request.card_id]]
        else:
            query_text = normalize(request.query or '')
            terms = set(query_text.split())
            ranked = []
            for card in index.values():
                if request.category and card['category'] != request.category:
                    continue
                if request.energy and card['energy'] != request.energy:
                    continue
                if request.max_duration_s is not None and card['duration_s'] > request.max_duration_s:
                    continue
                phrases = [normalize(card['id']), *(normalize(k) for k in (*card['aliases'], *card['keywords']))]
                front = read_frontmatter(card_bytes(card).decode('utf-8'))
                words = set(normalize(' '.join([card['summary'], card['category'], *card['keywords'], *card['aliases'],
                                                *front.values()])).split())
                score = (100 if query_text and query_text in phrases else 0) + len(terms & words)
                if terms and not score:
                    continue
                ranked.append((score, card['id']))
            cards = [index[card_id] for _, card_id in sorted(ranked, key=lambda row: (-row[0], row[1]))[:request.limit]]
        fields = ('id', 'summary', 'category', 'duration_s', 'energy', 'camera_move',
                  'easing', 'component_hint', 'sfx_cue')
        result = {'ok': True, 'results': [{field: card[field] for field in fields} for card in cards]}
        if request.card_id:
            result['recipe'] = parse_card(request.card_id)
        return result
    except (ValueError, OSError, KeyError, TypeError) as exc:
        error = str(exc) if isinstance(exc, ValueError) else 'Shot library is unavailable or invalid.'
        return {'ok': False, 'errors': [neutral_text(error)], 'results': []}


TOOL_HANDLERS = {'shot_recipe_search': shot_recipe_search}
GATEWAY_TOOLS = tuple(TOOL_HANDLERS)
