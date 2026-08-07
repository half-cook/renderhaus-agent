"""Local stdio MCP server exposing the full Mureka tool surface (parity with Gateway Lambda)."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from pydantic import Field
from pydantic.fields import FieldInfo

from mcps.mureka import api


mcp = FastMCP("renderhaus-mureka")


def _field_value(value: Any, default: Any) -> Any:
    if isinstance(value, FieldInfo):
        return getattr(value, "default", default)
    return value


@mcp.tool()
def text_to_music(
    prompt: str = Field(description="Music direction: genre, mood, tempo, instruments, use case."),
    lyrics: str | None = Field(default=None, description="Optional lyrics. Omit for instrumental."),
    model: str | None = Field(default=None, description="Mureka model id. Defaults to MUREKA_MODEL or auto."),
) -> dict:
    """Create a Mureka music task and return the task id immediately."""
    return api.text_to_music(
        prompt=prompt,
        lyrics=_field_value(lyrics, None),
        model=_field_value(model, None),
    )


@mcp.tool()
def create_instrumental(
    prompt: str = Field(description="Instrumental / BGM prompt."),
    model: str | None = None,
    n: int | None = None,
    instrumental_id: str | None = None,
    stream: bool | None = None,
) -> dict:
    """Generate instrumental music (POST /v1/instrumental/generate)."""
    return api.create_instrumental(
        prompt=prompt,
        model=_field_value(model, None),
        n=_field_value(n, None),
        instrumental_id=_field_value(instrumental_id, None),
        stream=_field_value(stream, None),
    )


@mcp.tool()
def create_song(
    lyrics: str = Field(description="Full lyrics for the song."),
    prompt: str = "",
    model: str | None = None,
    n: int | None = None,
    gender: str | None = None,
    reference_id: str | None = None,
    vocal_id: str | None = None,
    melody_id: str | None = None,
    instrumental_id: str | None = None,
    stream: bool | None = None,
) -> dict:
    """Generate a song from lyrics (POST /v1/song/generate)."""
    return api.create_song(
        lyrics=lyrics,
        prompt=prompt or "",
        model=_field_value(model, None),
        n=_field_value(n, None),
        gender=_field_value(gender, None),
        reference_id=_field_value(reference_id, None),
        vocal_id=_field_value(vocal_id, None),
        melody_id=_field_value(melody_id, None),
        instrumental_id=_field_value(instrumental_id, None),
        stream=_field_value(stream, None),
    )


@mcp.tool()
def create_song_from_prompt(
    prompt: str = Field(description="Natural-language song brief."),
    model: str | None = None,
    n: int | None = None,
    gender: str | None = None,
) -> dict:
    """Prompt-to-song without separate lyrics (POST /v1/song/easy-generate)."""
    return api.create_song_from_prompt(
        prompt=prompt,
        model=_field_value(model, None),
        n=_field_value(n, None),
        gender=_field_value(gender, None),
    )


@mcp.tool()
def generate_lyrics(prompt: str = Field(description="Theme / story for lyrics.")) -> dict:
    """Generate lyrics and title from a prompt."""
    return api.generate_lyrics(prompt=prompt)


@mcp.tool()
def extend_lyrics(lyrics: str, prompt: str = "") -> dict:
    """Extend existing lyrics."""
    return api.extend_lyrics(lyrics=lyrics, prompt=prompt)


@mcp.tool()
def query_music_task(
    job_id: str = Field(description="Mureka task id."),
    download: bool = Field(default=True, description="Download audio when succeeded."),
) -> dict:
    """Poll a Mureka music task and optionally download the finished audio."""
    return api.query_task(job_id=job_id, download=bool(_field_value(download, True)))


@mcp.tool()
def get_music_task(
    job_id: str = Field(description="Mureka task id returned by text_to_music."),
    download: bool = Field(default=True, description="Download the audio when succeeded."),
) -> dict:
    """Alias for query_music_task (kept for existing callers)."""
    return api.query_task(job_id=job_id, download=bool(_field_value(download, True)))


@mcp.tool()
def extend_song(
    lyrics: str,
    extend_at_ms: int = Field(description="Extension start time in milliseconds."),
    song_id: str | None = None,
    upload_audio_id: str | None = None,
) -> dict:
    """Extend an existing song from a timestamp."""
    return api.extend_song(
        lyrics=lyrics,
        extend_at_ms=extend_at_ms,
        song_id=_field_value(song_id, None),
        upload_audio_id=_field_value(upload_audio_id, None),
    )


@mcp.tool()
def region_edit_song(
    lyrics: str,
    edit_start_ms: int,
    edit_end_ms: int,
    song_id: str | None = None,
    upload_audio_id: str | None = None,
) -> dict:
    """Rewrite a time region of a song."""
    return api.region_edit_song(
        lyrics=lyrics,
        edit_start_ms=edit_start_ms,
        edit_end_ms=edit_end_ms,
        song_id=_field_value(song_id, None),
        upload_audio_id=_field_value(upload_audio_id, None),
    )


@mcp.tool()
def remix_song(
    prompt: str = "",
    song_id: str | None = None,
    upload_audio_id: str | None = None,
    n: int | None = None,
) -> dict:
    """Remix a song or uploaded audio."""
    return api.remix_song(
        prompt=prompt,
        song_id=_field_value(song_id, None),
        upload_audio_id=_field_value(upload_audio_id, None),
        n=_field_value(n, None),
    )


@mcp.tool()
def stem_song(
    song_id: str | None = None,
    upload_audio_id: str | None = None,
    model: str | None = None,
) -> dict:
    """Separate stems / vocal+instrumental."""
    return api.stem_song(
        song_id=_field_value(song_id, None),
        upload_audio_id=_field_value(upload_audio_id, None),
        model=_field_value(model, None),
    )


@mcp.tool()
def recognize_song(upload_audio_id: str | None = None, audio_url: str | None = None) -> dict:
    """Recognize / analyze audio."""
    return api.recognize_song(
        upload_audio_id=_field_value(upload_audio_id, None),
        audio_url=_field_value(audio_url, None),
    )


@mcp.tool()
def describe_song(upload_audio_id: str | None = None, song_id: str | None = None) -> dict:
    """Describe a song or upload."""
    return api.describe_song(
        upload_audio_id=_field_value(upload_audio_id, None),
        song_id=_field_value(song_id, None),
    )


@mcp.tool()
def transcribe_song(upload_audio_id: str | None = None, song_id: str | None = None) -> dict:
    """Transcribe music."""
    return api.transcribe_song(
        upload_audio_id=_field_value(upload_audio_id, None),
        song_id=_field_value(song_id, None),
    )


@mcp.tool()
def vocal_clone(upload_audio_id: str, name: str | None = None) -> dict:
    """Clone a vocal from uploaded audio."""
    return api.vocal_clone(upload_audio_id=upload_audio_id, name=_field_value(name, None))


@mcp.tool()
def generate_track(
    track_type: str = Field(description="vocals | accompaniment | instrument"),
    song_id: str | None = None,
    upload_audio_id: str | None = None,
    prompt: str = "",
) -> dict:
    """Generate a complementary track from reference audio."""
    return api.generate_track(
        track_type=track_type,
        song_id=_field_value(song_id, None),
        upload_audio_id=_field_value(upload_audio_id, None),
        prompt=prompt,
    )


@mcp.tool()
def generate_soundtrack(
    prompt: str = "",
    upload_file_id: str | None = None,
    audio_start: float | None = None,
    audio_end: float | None = None,
    model: str | None = None,
) -> dict:
    """Generate a soundtrack from image/video or prompt."""
    return api.generate_soundtrack(
        prompt=prompt,
        upload_file_id=_field_value(upload_file_id, None),
        audio_start=_field_value(audio_start, None),
        audio_end=_field_value(audio_end, None),
        model=_field_value(model, None),
    )


@mcp.tool()
def generate_lyrics_video(
    song_id: str | None = None,
    upload_audio_id: str | None = None,
    aspect_ratio: str | None = None,
    layout: str | None = None,
) -> dict:
    """Generate a lyrics video."""
    return api.generate_lyrics_video(
        song_id=_field_value(song_id, None),
        upload_audio_id=_field_value(upload_audio_id, None),
        aspect_ratio=_field_value(aspect_ratio, None),
        layout=_field_value(layout, None),
    )


@mcp.tool()
def upload_file(
    purpose: str = Field(description="reference|melody|instrumental|voice|audio|remix|soundtrack"),
    filename: str = Field(description="Original filename with extension."),
    content_b64: str = Field(description="Base64-encoded file bytes."),
) -> dict:
    """Upload a file to Mureka for use as a reference."""
    return api.upload_file(purpose=purpose, filename=filename, content_b64=content_b64)


@mcp.tool()
def create_speech(text: str, voice: str | None = None) -> dict:
    """Mureka text-to-speech."""
    return api.create_speech(text=text, voice=_field_value(voice, None))


@mcp.tool()
def create_podcast(script: str, title: str | None = None) -> dict:
    """Mureka podcast generation."""
    return api.create_podcast(script=script, title=_field_value(title, None))


@mcp.tool()
def query_billing() -> dict:
    """Query Mureka billing."""
    return api.query_billing()


@mcp.tool()
def list_mureka_models() -> dict:
    """Describe available Mureka models for this workspace."""
    return api.list_models()


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
