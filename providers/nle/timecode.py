"""Frame arithmetic shared by the NLE interchange formats."""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Any


_TIMECODE = re.compile(r"^(\d{2}):(\d{2}):(\d{2})([:;])(\d{2})$")
_RATES = {
    Fraction(24), Fraction(25), Fraction(30), Fraction(50), Fraction(60),
    Fraction(24000, 1001), Fraction(30000, 1001), Fraction(60000, 1001),
}


@dataclass(frozen=True, slots=True)
class FrameRate:
    value: Fraction
    drop_frame: bool = False

    @classmethod
    def parse(cls, value: Any, drop_frame: bool = False) -> FrameRate:
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ValueError("renderConfig.fps must be a supported frame rate.")
        aliases = {"23.976": "24000/1001", "29.97": "30000/1001", "59.94": "60000/1001"}
        try:
            rate = Fraction(aliases.get(str(value), str(value)))
        except (ValueError, ZeroDivisionError) as exc:
            raise ValueError("renderConfig.fps must be a supported frame rate.") from exc
        if rate not in _RATES:
            raise ValueError("Unsupported frame rate. Use 24, 25, 30, 50, 60 or an exact NTSC rate.")
        if not isinstance(drop_frame, bool):
            raise ValueError("renderConfig.dropFrame must be a boolean.")
        if drop_frame and rate not in {Fraction(30000, 1001), Fraction(60000, 1001)}:
            raise ValueError("Drop-frame requires 30000/1001 or 60000/1001 fps.")
        return cls(rate, drop_frame)

    @property
    def nominal(self) -> int:
        return round(self.value)

    @property
    def dropped(self) -> int:
        return self.nominal // 15 if self.drop_frame else 0

    @property
    def frames_per_day(self) -> int:
        return self.nominal * 86400 - self.dropped * (1440 - 144)

    def seconds_to_frames(self, value: Any, field: str, *, positive: bool = False) -> int:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{field} must be a finite number of seconds.")
        try:
            seconds = Fraction(str(value))
        except (ValueError, ZeroDivisionError) as exc:
            raise ValueError(f"{field} must be a finite number of seconds.") from exc
        if seconds < 0 or (positive and seconds == 0):
            raise ValueError(f"{field} must be {'greater than' if positive else 'at least'} zero.")
        frames = int(seconds * self.value + Fraction(1, 2))
        if positive and frames == 0:
            raise ValueError(f"{field} must cover at least one frame.")
        return frames

    def parse_timecode(self, value: str) -> int:
        match = _TIMECODE.fullmatch(value)
        if match is None:
            raise ValueError("Timecode must be HH:MM:SS:FF, or HH:MM:SS;FF for drop-frame.")
        hours, minutes, seconds, separator, frames = match.groups()
        h, m, s, f = int(hours), int(minutes), int(seconds), int(frames)
        if h > 23 or m > 59 or s > 59 or f >= self.nominal:
            raise ValueError(f"Invalid timecode {value} for this frame rate.")
        if (separator == ";") != self.drop_frame:
            raise ValueError("Source and record timecodes must match the sequence dropFrame mode.")
        if self.drop_frame and m % 10 and s == 0 and f < self.dropped:
            raise ValueError(f"Timecode {value} is a skipped drop-frame label.")
        total_minutes = h * 60 + m
        return ((h * 3600 + m * 60 + s) * self.nominal + f
                - self.dropped * (total_minutes - total_minutes // 10))

    def timecode(self, frames: int) -> str:
        if frames < 0 or frames >= self.frames_per_day:
            raise ValueError("NLE export does not support timecodes crossing the 24-hour boundary.")
        if self.drop_frame:
            ten_minutes = self.nominal * 600 - self.dropped * 9
            minute = self.nominal * 60 - self.dropped
            blocks, remainder = divmod(frames, ten_minutes)
            frames += self.dropped * 9 * blocks
            if remainder >= self.dropped:
                frames += self.dropped * ((remainder - self.dropped) // minute)
        seconds, frame = divmod(frames, self.nominal)
        minutes, second = divmod(seconds, 60)
        hour, minute = divmod(minutes, 60)
        separator = ";" if self.drop_frame else ":"
        return f"{hour:02}:{minute:02}:{second:02}{separator}{frame:02}"

    def xml_time(self, frames: int) -> str:
        seconds = Fraction(frames, 1) / self.value
        if seconds.denominator == 1:
            return f"{seconds.numerator}s"
        return f"{seconds.numerator}/{seconds.denominator}s"
