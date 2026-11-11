"""Transcript handling: SRT/VTT parsing and Sarvam speech-to-text.

Video and audio are reviewed through their words. Sarvam's `saaras:v3` model
returns word-level timings, so a flagged phrase can be pinned to the second it
is spoken. When a file cannot be transcribed (no audio track, unsupported
container, no ffmpeg on the host) the API says so and offers the transcript path
instead of pretending the media was reviewed.
"""
from __future__ import annotations

import io
import re
import shutil
import subprocess
import tempfile

import httpx

from app.core.config import settings

TIMECODE = re.compile(
    r"(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}|\d{1,2}:\d{2}[,.]\d{1,3})\s*-->\s*"
    r"(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}|\d{1,2}:\d{2}[,.]\d{1,3})"
)
INLINE_TIME = re.compile(r"^\s*\[?(\d{1,2}:\d{2}(?::\d{2})?)\]?\s*[-–:]?\s*(.+)$")
AUDIO_TYPES = {"audio/wav", "audio/mpeg", "audio/mp3", "audio/mp4", "audio/x-m4a", "audio/ogg", "audio/webm", "audio/flac"}
VIDEO_EXT = (".mp4", ".mov", ".mkv", ".webm", ".avi")


def _seconds(stamp: str) -> float:
    stamp = stamp.replace(",", ".")
    parts = [float(p) for p in stamp.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def parse_transcript(raw: str, fmt: str = "auto") -> list[dict]:
    """Return [{start, end, text}] from SRT, VTT or timestamped plain text."""
    raw = (raw or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not raw:
        return []

    segments: list[dict] = []
    blocks = re.split(r"\n\s*\n", raw)
    for block in blocks:
        match = TIMECODE.search(block)
        if not match:
            continue
        body = TIMECODE.sub("", block)
        lines = [ln.strip() for ln in body.split("\n") if ln.strip()]
        # drop a leading numeric cue index
        if lines and lines[0].isdigit():
            lines = lines[1:]
        text = " ".join(lines).strip()
        if text:
            segments.append({"start": _seconds(match.group(1)), "end": _seconds(match.group(2)), "text": text})

    if not segments:
        for line in raw.split("\n"):
            match = INLINE_TIME.match(line)
            if match:
                segments.append({"start": _seconds(match.group(1)), "end": _seconds(match.group(1)) + 5.0, "text": match.group(2).strip()})

    if not segments:
        # plain text: split into sentences, 4 seconds each, so timecodes stay meaningful
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", raw) if s.strip()]
        for i, sentence in enumerate(sentences):
            segments.append({"start": i * 4.0, "end": (i + 1) * 4.0, "text": sentence})

    return segments


def segments_from_words(words: list[str], starts: list[float], ends: list[float]) -> list[dict]:
    """Group word timings into caption-sized segments."""
    segments: list[dict] = []
    buffer: list[str] = []
    seg_start = None
    for word, start, end in zip(words, starts, ends):
        if seg_start is None:
            seg_start = start
        buffer.append(word)
        joined = " ".join(buffer)
        if len(buffer) >= 14 or word.endswith((".", "?", "!", ",")) and len(buffer) >= 6:
            segments.append({"start": round(seg_start, 2), "end": round(end, 2), "text": joined.strip()})
            buffer, seg_start = [], None
    if buffer and seg_start is not None:
        segments.append({"start": round(seg_start, 2), "end": round(ends[-1], 2), "text": " ".join(buffer).strip()})
    return segments


def wav_duration(data: bytes) -> float:
    """Exact duration from a RIFF/WAVE header, no decoder needed."""
    try:
        if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
            return 0.0
        pos = 12
        byte_rate = 0
        data_size = 0
        while pos + 8 <= len(data):
            chunk_id = data[pos : pos + 4]
            size = int.from_bytes(data[pos + 4 : pos + 8], "little")
            if chunk_id == b"fmt ":
                byte_rate = int.from_bytes(data[pos + 16 : pos + 20], "little")
            elif chunk_id == b"data":
                data_size = size
                break
            pos += 8 + size + (size % 2)
        if byte_rate <= 0:
            return 0.0
        return round(data_size / byte_rate, 2)
    except Exception:
        return 0.0


def split_sentences(text: str, max_words: int = 14) -> list[str]:
    """Caption-sized chunks: sentence boundaries first, then a word cap."""
    text = (text or "").strip()
    if not text:
        return []
    chunks: list[str] = []
    for part in re.split(r"(?<=[.!?])\s+", text):
        words = part.split()
        if len(words) <= max_words:
            chunks.append(part.strip())
        else:
            for i in range(0, len(words), max_words):
                chunks.append(" ".join(words[i : i + max_words]))
    return [c for c in chunks if c]


def segments_proportional(text: str, duration: float) -> list[dict]:
    """When the model gives no usable word timings, spread the words over the runtime.

    Timing is then an estimate, and the response says so, rather than pretending
    a phrase was spoken at a second we do not actually know.
    """
    chunks = split_sentences(text)
    if not chunks:
        return []
    total_words = sum(len(c.split()) for c in chunks) or 1
    span = duration or max(2.0, total_words / 2.5)
    segments, cursor = [], 0.0
    for chunk in chunks:
        share = span * len(chunk.split()) / total_words
        segments.append({"start": round(cursor, 2), "end": round(cursor + share, 2), "text": chunk})
        cursor += share
    return segments


def ensure_wav(data: bytes, filename: str) -> tuple[bytes, bool]:
    """Normalise any audio to 16 kHz mono wav so duration and STT both work."""
    if data[:4] == b"RIFF":
        return data, False
    binary = ffmpeg_binary()
    if binary is None:
        return data, False
    suffix = filename[filename.rfind(".") :] if "." in filename else ".bin"
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = f"{tmp}/in{suffix}", f"{tmp}/out.wav"
        with open(src, "wb") as handle:
            handle.write(data)
        try:
            subprocess.run(
                [binary, "-y", "-i", src, "-vn", "-ac", "1", "-ar", "16000", dst],
                check=True, capture_output=True, timeout=180,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return data, False
        return open(dst, "rb").read(), True


def ffmpeg_binary() -> str | None:
    """System ffmpeg if present, else the binary bundled with imageio-ffmpeg.

    Shipping ffmpeg as a pip dependency means video upload works on a clean
    Windows or Linux machine with no extra install.
    """
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # pragma: no cover - optional dependency
        return None


def ffmpeg_available() -> bool:
    return ffmpeg_binary() is not None


def extract_audio(data: bytes, filename: str) -> bytes | None:
    """Pull a mono 16k wav out of a video container."""
    binary = ffmpeg_binary()
    if binary is None:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        src = f"{tmp}/in{filename[filename.rfind('.'):] if '.' in filename else '.bin'}"
        dst = f"{tmp}/out.wav"
        with open(src, "wb") as handle:
            handle.write(data)
        try:
            subprocess.run(
                [binary, "-y", "-i", src, "-vn", "-ac", "1", "-ar", "16000", dst],
                check=True, capture_output=True, timeout=180,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return None
        try:
            return open(dst, "rb").read()
        except OSError:
            return None


async def transcribe(data: bytes, filename: str, content_type: str) -> dict:
    """Send audio to Sarvam and return segments with timings."""
    name = filename.lower()
    is_video = name.endswith(VIDEO_EXT) or content_type.startswith("video/")

    audio = data
    converted = False
    if is_video:
        extracted = extract_audio(data, name)
        if extracted is None:
            return {
                "ok": False,
                "reason": "video-needs-audio",
                "message": (
                    "Could not read an audio track from that video. Upload the audio file, or paste "
                    "the transcript (SRT/VTT) — both give the same timestamped review."
                ),
            }
        audio, converted = extracted, True
    else:
        audio, converted = ensure_wav(data, name)

    duration = wav_duration(audio)

    from app.services.sarvam import api_key as sarvam_key

    if not sarvam_key():
        return {"ok": False, "reason": "no-model", "message": "Speech-to-text needs SARVAM_API_KEY."}

    boundary = "----brandsetgo"
    parts = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\nsaaras:v3\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"with_timestamps\"\r\n\r\ntrue\r\n"
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"audio.wav\"\r\n"
        f"Content-Type: audio/wav\r\n\r\n"
    ).encode() + audio + f"\r\n--{boundary}--\r\n".encode()

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                settings.sarvam_stt_url,
                content=parts,
                headers={
                    "api-subscription-key": sarvam_key(),
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                },
            )
        if response.status_code >= 400:
            return {"ok": False, "reason": "stt-error", "message": response.text[:300]}
        body = response.json()
    except Exception as exc:  # pragma: no cover - network dependent
        return {"ok": False, "reason": "stt-unreachable", "message": str(exc)[:200]}

    transcript = (body.get("transcript") or "").strip()
    timings = body.get("timestamps") or {}
    words = timings.get("words") or []
    starts = timings.get("start_time_seconds") or []
    ends = timings.get("end_time_seconds") or []

    # word-level only when the model actually returned distinct word timings
    usable_words = len(words) >= 4 and len({round(float(x), 2) for x in starts}) >= 4
    timing = "word" if usable_words else "estimated"

    if usable_words:
        segments = segments_from_words(words, starts, ends)
        duration = max([duration] + [float(x) for x in ends])
    else:
        if not duration:
            duration = round(len(transcript.split()) / 2.5, 2)
        segments = segments_proportional(transcript, duration)

    return {
        "ok": bool(segments),
        "segments": segments,
        "duration_s": round(duration or max([s["end"] for s in segments], default=0.0), 2),
        "language": body.get("language_code", ""),
        "engine": "sarvam saaras:v3",
        "timing": timing,
        "word_count": len(transcript.split()),
        "converted_audio": converted,
        "message": (
            ""
            if segments
            else "No speech was detected in that file."
        ),
    }


def attach_timecodes(findings: list, segments: list[dict]) -> None:
    """Map a finding's character span back to the segment, and therefore the second."""
    if not segments:
        return
    offsets: list[tuple[int, int, dict]] = []
    cursor = 0
    for segment in segments:
        text = segment.get("text", "")
        offsets.append((cursor, cursor + len(text), segment))
        cursor += len(text) + 1  # the join adds one newline per segment

    for finding in findings:
        start = getattr(finding, "span_start", 0) or 0
        end = getattr(finding, "span_end", 0) or start
        if end <= start:
            continue  # document-level finding, not tied to a spoken moment
        for seg_start, seg_end, segment in offsets:
            if seg_start <= start < seg_end or (start <= seg_start < max(end, start + 1)):
                finding.timecode_start = float(segment.get("start", 0.0))
                finding.timecode_end = float(segment.get("end", 0.0))
                break


def format_timecode(seconds: float | None) -> str:
    if seconds is None:
        return ""
    total = int(seconds)
    return f"{total // 60:02d}:{total % 60:02d}"
