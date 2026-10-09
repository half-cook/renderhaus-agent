"""Mureka fal schemas verified 2026-10-09.

https://fal.ai/models/mureka/api/generate/song/api
https://fal.ai/models/mureka/api/generate/instrumental/api
https://fal.ai/models/mureka/api/generate/lyrics-video/api
https://platform.mureka.ai/docs/en/faq.html
https://fal.ai/legal/terms-of-service
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import os
import re
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

DEFAULT_MODEL = 'mureka-9.5'
SONG_ENDPOINT = 'mureka/api/generate/song'
INSTRUMENTAL_ENDPOINT = 'mureka/api/generate/instrumental'
VIDEO_ENDPOINT = 'mureka/api/generate/lyrics-video'
VIDEO_MODEL = VIDEO_ENDPOINT
TOOL_ENDPOINTS = {'generate_song': SONG_ENDPOINT, 'generate_instrumental': INSTRUMENTAL_ENDPOINT, 'generate_lyrics_video': VIDEO_ENDPOINT}
GENERATING_TOOLS = tuple(TOOL_ENDPOINTS)
STYLES = ('pop', 'rock', 'jazz', 'r&b', 'edm', 'ambient', 'folk', 'latin', 'k-pop', 'j-pop', 'house', 'gospel', 'lo-fi')
LAYOUTS = tuple(f'layout_{index}' for index in range(1, 8))
ASPECT_RATIOS = ('16:9', '9:16', '3:4', '4:3')
TRAINING_METADATA = {
    'training_eligible': False, 'weights_license': 'closed-weights', 'license': 'commercial-service',
    'license_source': 'https://platform.mureka.ai/docs/en/faq.html',
    'hosted_terms_url': 'https://fal.ai/legal/terms-of-service', 'license_read_date': '2026-10-09',
    'training_reason': 'Commercial rights do not expressly permit model training; fal competing-model restrictions apply.',
}
FIELD_DESCRIPTIONS = {
    'prompt': 'Music description. Song accepts up to 2000 characters; instrumental up to 1024. With lyrics, song prompt controls musical style.',
    'lyrics': 'Lyrics to sing, 1 to 5000 characters. Omit for prompt-to-song.',
    'styles': 'Prompt-to-song genres only. Cannot accompany lyrics. Allowed values: ' + ', '.join(STYLES) + '.',
    'gender': 'Optional female or male vocal preference for lyrics-to-song.',
    'model': 'Configured default MUREKA_MODEL=mureka-9.5. Other IDs are UNVERIFIED, preview-only and cannot submit live.',
    'instrumental_id': 'Existing fal-hosted Mureka upload ID with purpose instrumental. Supply exactly one of this or prompt.',
    'song_id': 'Song ID from a completed Mureka fal music task. Lyrics video requires exactly one of song_id or upload_audio_id.',
    'upload_audio_id': 'Existing fal-hosted Mureka upload ID with purpose audio. Arbitrary audio URLs are not supported by this endpoint.',
    'layout': 'Allowed values: ' + ', '.join(LAYOUTS) + '.',
    'aspect_ratio': 'Allowed values: ' + ', '.join(ASPECT_RATIOS) + '.',
    'background_id': 'Existing Mureka upload ID with purpose lyrics-video.',
    'cover_url': 'Public HTTPS URL or image data URI for JPG, PNG or WebP. Forbidden for layout_1.',
    'lyrics_start_row': 'First included lyric row, starting at 1. Must pair with lyrics_end_row, without time selection.',
    'lyrics_end_row': 'Last included lyric row, at least lyrics_start_row. Must pair with lyrics_start_row.',
    'selection_start': 'Included audio range start in milliseconds, at least 0. Must pair with selection_end, without row selection.',
    'selection_end': 'Included audio range end in milliseconds, strictly greater than selection_start.',
    'job_id': 'Exact saved handle returned by a Mureka submit tool. Never invent IDs or submit again to poll.',
    'download': 'Persist and validate the completed audio or MP4. Dry-run handles never produce artifacts.',
}
ARGUMENT_RULES: dict[str, dict[str, Any]] = {}


@dataclass(frozen=True)
class Endpoint:
    id: str
    model: str
    api_url: str


ENDPOINTS = {VIDEO_ENDPOINT: Endpoint(VIDEO_ENDPOINT, VIDEO_MODEL, f'https://fal.ai/models/{VIDEO_ENDPOINT}/api')}


def configured_model(arguments: dict[str, Any] | None = None) -> str:
    model = (arguments or {}).get('model')
    if model is None:
        model = os.getenv('MUREKA_MODEL', DEFAULT_MODEL)
    if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', model):
        raise ValueError('Mureka model must be a nonempty safe model ID.')
    return model


def validate_https(value: str) -> None:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        valid = parsed.scheme == 'https' and host and not parsed.username and not parsed.password and not parsed.fragment and not any(c.isspace() for c in value)
        if parsed.port is not None and not 0 < parsed.port <= 65535:
            valid = False
    except ValueError:
        valid, host = False, None
    if not valid:
        raise ValueError('Media requires public HTTPS without embedded credentials.')
    host = host.rstrip('.').lower()
    if host == 'localhost' or host.endswith(('.localhost', '.local', '.internal')) or '.' not in host:
        raise ValueError('Media cannot use a private host.')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if not address.is_global:
        raise ValueError('Media cannot use a private address.')


class Request(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', allow_inf_nan=False, hide_input_in_errors=True)

    @model_validator(mode='after')
    def nonempty_strings(self) -> Request:
        for value in self.__dict__.values():
            if isinstance(value, str) and not value.strip():
                raise ValueError('Mureka text and identifiers cannot be blank.')
        return self

    def fal_body(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


class SongRequest(Request):
    prompt: str | None = Field(default=None, min_length=1, max_length=2000)
    lyrics: str | None = Field(default=None, min_length=1, max_length=5000)
    styles: list[Literal['pop', 'rock', 'jazz', 'r&b', 'edm', 'ambient', 'folk', 'latin', 'k-pop', 'j-pop', 'house', 'gospel', 'lo-fi']] | None = Field(default=None, min_length=1)
    gender: Literal['female', 'male'] | None = None
    model: str | None = None

    @model_validator(mode='after')
    def compatible_song(self) -> SongRequest:
        if self.lyrics is None and self.prompt is None:
            raise ValueError('Provide lyrics or prompt for song generation.')
        if self.lyrics is not None and self.styles is not None:
            raise ValueError('styles cannot accompany lyrics.')
        if self.gender is not None and self.lyrics is None:
            raise ValueError('gender is only supported with lyrics.')
        self.model = configured_model({'model': self.model})
        return self

    def fal_body(self) -> dict[str, Any]:
        return {**super().fal_body(), 'enable_safety_checker': True}


class InstrumentalRequest(Request):
    prompt: str | None = Field(default=None, min_length=1, max_length=1024)
    instrumental_id: str | None = Field(default=None, min_length=1)
    model: str | None = None

    @model_validator(mode='after')
    def single_source(self) -> InstrumentalRequest:
        if (self.prompt is None) == (self.instrumental_id is None):
            raise ValueError('Provide exactly one of prompt or instrumental_id.')
        self.model = configured_model({'model': self.model})
        return self

    def fal_body(self) -> dict[str, Any]:
        return {**super().fal_body(), 'enable_safety_checker': True}


class LyricsVideoRequest(Request):
    song_id: str | None = Field(default=None, min_length=1)
    upload_audio_id: str | None = Field(default=None, min_length=1)
    layout: Literal['layout_1', 'layout_2', 'layout_3', 'layout_4', 'layout_5', 'layout_6', 'layout_7'] = 'layout_1'
    aspect_ratio: Literal['16:9', '9:16', '3:4', '4:3'] = '9:16'
    background_id: str | None = Field(default=None, min_length=1)
    cover_url: str | None = None
    title: str | None = Field(default=None, min_length=1)
    lyrics_start_row: int | None = Field(default=None, ge=1)
    lyrics_end_row: int | None = Field(default=None, ge=1)
    selection_start: int | None = Field(default=None, ge=0)
    selection_end: int | None = Field(default=None, ge=0)

    @model_validator(mode='after')
    def supported_video(self) -> LyricsVideoRequest:
        if (self.song_id is None) == (self.upload_audio_id is None):
            raise ValueError('Provide exactly one of song_id or upload_audio_id.')
        row_values = self.lyrics_start_row, self.lyrics_end_row
        time_values = self.selection_start, self.selection_end
        rows = any(value is not None for value in row_values)
        times = any(value is not None for value in time_values)
        if rows and (times or None in row_values):
            raise ValueError('Pair lyric rows and do not combine them with time selection.')
        if times and None in time_values:
            raise ValueError('Pair selection_start with selection_end.')
        if rows and self.lyrics_end_row < self.lyrics_start_row:
            raise ValueError('lyrics_end_row must be at least lyrics_start_row.')
        if times and self.selection_end <= self.selection_start:
            raise ValueError('selection_end must exceed selection_start.')
        if self.cover_url is not None:
            if self.layout == 'layout_1':
                raise ValueError('cover_url is unsupported with layout_1.')
            if self.cover_url.startswith('data:'):
                match = re.fullmatch(r'data:image/(jpeg|png|webp);base64,([A-Za-z0-9+/=]+)', self.cover_url)
                try:
                    if not match or not base64.b64decode(match[2], validate=True):
                        raise ValueError('cover_url must contain an image data URI.')
                except binascii.Error:
                    raise ValueError('cover_url contains invalid base64.') from None
            else:
                validate_https(self.cover_url)
        return self


class PollRequest(Request):
    job_id: str
    download: bool = False


REQUESTS = {'generate_song': SongRequest, 'generate_instrumental': InstrumentalRequest, 'generate_lyrics_video': LyricsVideoRequest, 'get_music_task': PollRequest, 'get_video_task': PollRequest}


def request_for(tool: str, arguments: dict[str, Any]) -> Request:
    if tool not in REQUESTS:
        raise ValueError(f'Unknown Mureka tool {tool}.')
    return REQUESTS[tool].model_validate(arguments)


def validate_arguments(tool: str, arguments: dict[str, Any]) -> None:
    if tool == 'list_mureka_models':
        Request.model_validate(arguments)
        return
    request_for(tool, arguments)
