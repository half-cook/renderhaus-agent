"""Dependency-free request boundary and shared continuity calibration."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import http.client
import io
import ipaddress
import math
import queue
import re
import socket
import ssl
import threading
import time
from urllib.parse import urlsplit

from agent.deep_agent.continuity_qc import (
    ContinuityConfig,
    DINO_MODEL,
    DINOV3_MODEL,
    SIGLIP_MODEL,
    cosine_similarity,
    load_calibration,
)

MODEL_IDS = {"siglip": SIGLIP_MODEL, "dinov2": DINO_MODEL, "dinov3": DINOV3_MODEL}
CALIBRATION = load_calibration()


@dataclass(frozen=True)
class Limits:
    max_frames: int = 8
    max_frame_bytes: int = 8 * 1024 * 1024
    max_total_bytes: int = 24 * 1024 * 1024
    max_pixels: int = 20_000_000
    max_pairs: int = 64
    max_id_length: int = 128
    url_timeout: float = 10.0


class RequestError(ValueError):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)


def _invalid(message):
    raise RequestError("invalid_input", message)


def _validate_url(url):
    if not isinstance(url, str) or not url or len(url) > 8192 or any(ord(c) <= 32 for c in url):
        _invalid("Frame URLs must be bounded HTTPS URLs.")
    try:
        parsed = urlsplit(url)
        host, port = parsed.hostname, parsed.port
    except ValueError:
        _invalid("Frame URL is invalid.")
    if (
        parsed.scheme != "https"
        or not host
        or port not in (None, 443)
        or parsed.username
        or parsed.password
        or parsed.fragment
        or "\\" in url
    ):
        _invalid("Frame URLs must use HTTPS port 443 without credentials or fragments.")
    host = host.rstrip(".").lower()
    if (
        host == "localhost"
        or host.endswith((".localhost", ".local", ".internal", ".home"))
        or "." not in host
        and ":" not in host
    ):
        _invalid("Frame URLs must target public hosts.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if not re.fullmatch(r"[a-z0-9.-]+", host):
            _invalid("Frame URL hostname is invalid.")
    else:
        if not address.is_global:
            _invalid("Frame URLs must target public hosts.")
    return parsed


def _public_addresses(host, resolver=None):
    answers = (resolver or socket.getaddrinfo)(host, 443, socket.AF_UNSPEC, socket.SOCK_STREAM)
    addresses = list(dict.fromkeys(answer[4][0] for answer in answers))
    if not addresses or not all(ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("Frame URL resolved to a non-public address.")
    return addresses


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Keep TLS hostname validation while connecting to the already vetted IP."""

    def __init__(self, host, address, timeout):
        super().__init__(host, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        sock = socket.create_connection((self.address, 443), timeout=self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except Exception:
            sock.close()
            raise


def fetch_url(url, max_bytes, timeout):
    """Enforce a wall-clock limit across DNS, TLS, headers, and body reads."""
    _validate_url(url)
    deadline = time.monotonic() + timeout
    result = queue.Queue(maxsize=1)

    def fetch():
        try:
            result.put((True, _fetch_url(url, max_bytes, deadline)))
        except Exception as error:
            result.put((False, error))

    threading.Thread(target=fetch, daemon=True).start()
    try:
        ok, value = result.get(timeout=timeout)
    except queue.Empty:
        raise TimeoutError("Frame URL fetch timed out.") from None
    if not ok:
        raise value
    return value


def _fetch_url(url, max_bytes, deadline):
    """Pin a public address, reject redirects, and bound streamed bytes."""
    parsed = _validate_url(url)
    addresses = _public_addresses(parsed.hostname)
    if not addresses:
        raise ValueError("Frame URL DNS is invalid.")
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Frame URL fetch timed out.")
    connection = _PinnedHTTPSConnection(parsed.hostname, addresses[0], remaining)
    try:
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        connection.request("GET", path, headers={"Accept": "image/*"})
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError("Frame URL must return HTTP 200 without redirects.")
        length = response.getheader("Content-Length")
        if length is not None and (int(length) < 0 or int(length) > max_bytes):
            raise ValueError("Frame URL exceeds the byte limit.")
        data = bytearray()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Frame URL fetch timed out.")
            if connection.sock is not None:
                connection.sock.settimeout(remaining)
            chunk = response.read1(min(64 * 1024, max_bytes + 1 - len(data)))
            if not chunk:
                if time.monotonic() > deadline:
                    raise TimeoutError("Frame URL fetch timed out.")
                break
            data.extend(chunk)
            if len(data) > max_bytes:
                raise ValueError("Frame URL exceeds the byte limit.")
        return bytes(data)
    finally:
        connection.close()


def decode_image(data, max_pixels):
    from PIL import Image

    with Image.open(io.BytesIO(data)) as image:
        width, height = image.size
        if width <= 0 or height <= 0 or width * height > max_pixels:
            raise ValueError("Frame image exceeds the pixel limit.")
        if getattr(image, "n_frames", 1) != 1:
            raise ValueError("Frames must be still images.")
        return image.convert("RGB")


def _string_choices(value, choices, name):
    if (
        not isinstance(value, list)
        or not value
        or len(value) > len(choices)
        or not all(isinstance(item, str) and item in choices for item in value)
        or len(set(value)) != len(value)
    ):
        _invalid(f"{name} must contain distinct supported names.")
    return value


def _parse_request(payload, limits):
    if not isinstance(payload, dict) or set(payload) - {"frames", "models", "pairs", "return"}:
        _invalid("Input must be an object with only frames, models, pairs, and return.")
    frames = payload.get("frames")
    if not isinstance(frames, list) or not 1 <= len(frames) <= limits.max_frames:
        _invalid("Input must contain frames within the worker frame limit.")
    ids = []
    for frame in frames:
        if not isinstance(frame, dict) or set(frame) not in ({"id", "b64"}, {"id", "url"}):
            _invalid("Each frame must have an id and exactly one of b64 or url.")
        frame_id = frame["id"]
        if (
            not isinstance(frame_id, str)
            or not 1 <= len(frame_id) <= limits.max_id_length
            or not re.fullmatch(r"[A-Za-z0-9_.:-]+", frame_id)
            or frame_id in ids
        ):
            _invalid("Frame IDs must be unique bounded ASCII identifiers.")
        ids.append(frame_id)
        if "url" in frame:
            _validate_url(frame["url"])
        else:
            encoded = frame["b64"]
            if (
                not isinstance(encoded, str)
                or not encoded
                or len(encoded) > 4 * ((limits.max_frame_bytes + 2) // 3)
            ):
                _invalid("Frame base64 must be nonempty and within the byte limit.")
    models = _string_choices(payload.get("models", ["siglip", "dinov2"]), MODEL_IDS, "models")
    returns = _string_choices(
        payload.get("return", ["similarities", "scores"]),
        {"embeddings", "similarities", "scores"},
        "return",
    )
    if "scores" in returns and ("siglip" not in models or len(models) != 2):
        _invalid("Scores require SigLIP and exactly one DINO model.")
    pairs = payload.get("pairs", [[a, b] for a, b in zip(ids, ids[1:])])
    if not isinstance(pairs, list) or len(pairs) > limits.max_pairs:
        _invalid("Pairs must be a list within the pair limit.")
    for pair in pairs:
        if (
            not isinstance(pair, list)
            or len(pair) != 2
            or not all(isinstance(item, str) and item in ids for item in pair)
            or pair[0] == pair[1]
        ):
            _invalid("Each pair must name two distinct existing frame IDs.")
    return frames, ids, models, returns, pairs


def _normalized_rows(rows, count):
    if not isinstance(rows, (list, tuple)) or len(rows) != count:
        raise ValueError("Embedding frame count mismatch.")
    vectors = []
    dimension = None
    for row in rows:
        if (
            not isinstance(row, (list, tuple))
            or not row
            or not all(type(value) in (int, float) and math.isfinite(value) for value in row)
        ):
            raise ValueError("Embedding is invalid.")
        if dimension is not None and dimension != len(row):
            raise ValueError("Embedding dimensions mismatch.")
        dimension = len(row)
        norm = math.hypot(*row)
        if not norm or not math.isfinite(norm):
            raise ValueError("Embedding norm is invalid.")
        vectors.append([float(value / norm) for value in row])
    return vectors


def process_request(payload, embedder, *, image_decoder=None, url_fetcher=None, limits=None):
    """Return JSON data or a sanitized error. Heavy dependencies are injected."""
    limits = limits or Limits()
    try:
        frames, ids, models, returns, pairs = _parse_request(payload, limits)
        if any(model not in embedder.available_models for model in models):
            raise RequestError(
                "model_unavailable", "Requested model was not baked into this worker."
            )
        decoded, total = [], 0
        for frame in frames:
            if "b64" in frame:
                try:
                    data = base64.b64decode(frame["b64"], validate=True)
                except (ValueError, TypeError):
                    _invalid("Frame base64 is invalid.")
            else:
                try:
                    data = (url_fetcher or fetch_url)(
                        frame["url"], limits.max_frame_bytes, limits.url_timeout
                    )
                except Exception:
                    raise RequestError(
                        "fetch_error", "Frame URL could not be fetched within worker limits."
                    ) from None
            total += len(data)
            if not data or len(data) > limits.max_frame_bytes or total > limits.max_total_bytes:
                _invalid("Frame data exceeds the per-frame or total byte limit.")
            try:
                decoded.append((image_decoder or decode_image)(data, limits.max_pixels))
            except Exception:
                raise RequestError(
                    "image_error", "Frame image could not be decoded within worker limits."
                ) from None
        vectors = {}
        try:
            for model in models:
                vectors[model] = dict(
                    zip(
                        ids,
                        _normalized_rows(embedder.embed_batch(model, decoded), len(ids)),
                        strict=True,
                    )
                )
        except Exception:
            raise RequestError(
                "embedding_error", "Requested embeddings could not be computed."
            ) from None
        output = {"models": {model: MODEL_IDS[model] for model in models}, "pairs": []}
        for before, after in pairs:
            similarities = {
                model: cosine_similarity(vectors[model][before], vectors[model][after])
                for model in models
            }
            row = {"before": before, "after": after}
            if "similarities" in returns:
                row["similarities"] = similarities
            if "scores" in returns:
                dino = next(model for model in models if model != "siglip")
                accepted, p_siglip, p_dino = CALIBRATION.decide(
                    similarities["siglip"], similarities[dino], MODEL_IDS[dino], ContinuityConfig()
                )
                row.update(
                    accepted=accepted,
                    probabilities={"siglip": p_siglip, dino: p_dino},
                    score=(p_siglip + p_dino) / 2,
                )
            output["pairs"].append(row)
        if "embeddings" in returns:
            output["embeddings"] = vectors
        return output
    except RequestError as error:
        return {"error": {"code": error.code, "message": error.message}}
    except Exception:
        return {
            "error": {"code": "worker_error", "message": "Worker could not process this request."}
        }
