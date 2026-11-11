"""Transcript parsing, timestamped flags and the media ingestion errors."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services import media
from conftest import signup_ok, unique_email

SRT = """1
00:00:00,000 --> 00:00:03,000
Meet Noir Oud, our new evening fragrance.

2
00:00:03,000 --> 00:00:08,000
Clinically proven to cure anxiety and help you sleep.

3
00:00:08,000 --> 00:00:12,000
Guaranteed to last 24 hours.
"""

VTT = """WEBVTT

00:00:01.000 --> 00:00:04.000
Our serum cures acne.

00:00:04.000 --> 00:00:07.500
Shop now.
"""


def test_parse_srt_keeps_timings():
    segments = media.parse_transcript(SRT, "srt")
    assert len(segments) == 3
    assert segments[1]["start"] == 3.0 and segments[1]["end"] == 8.0
    assert "cure anxiety" in segments[1]["text"]


def test_parse_vtt_with_dots():
    segments = media.parse_transcript(VTT, "vtt")
    assert len(segments) == 2
    assert segments[0]["start"] == 1.0


def test_parse_plain_text_still_gets_timecodes():
    segments = media.parse_transcript("One sentence. Two sentences. Three.", "text")
    assert len(segments) == 3
    assert segments[2]["start"] == 8.0


def test_transcript_endpoint(client, admin_client):
    signup_ok(client, account_type="creator", email=unique_email("media"))
    data = client.post("/api/content/transcript", json={"content": SRT, "format": "srt"}).json()
    assert data["engine"] == "transcript"
    assert len(data["segments"]) == 3
    assert data["duration_s"] == 12.0


def test_transcribe_without_a_model_says_so(client, admin_client):
    signup_ok(client, account_type="creator", email=unique_email("stt"))
    response = client.post(
        "/api/content/transcribe",
        files={"file": ("clip.wav", b"RIFF0000WAVE", "audio/wav")},
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] in ("no-model", "stt-error", "stt-unreachable")
    assert detail["alternative"]


def test_video_review_flags_the_exact_seconds(client, admin_client):
    signup_ok(client, account_type="creator", email=unique_email("video"))
    brand = client.get("/api/brands").json()[0]
    client.post(f"/api/brands/{brand['id']}/policies/approve", json={"approver": "owner"})

    transcript = media.parse_transcript(SRT, "srt")
    content = client.post(
        "/api/content",
        json={
            "brand_id": brand["id"],
            "title": "Reel – 30s launch",
            "channel": "instagram_caption",
            "modality": "video",
            "transcript": transcript,
        },
    ).json()
    assert content["version_id"]

    review = client.post("/api/reviews", json={"content_version_id": content["version_id"]}).json()
    assert review["modality"] == "video"
    assert review["content"]["transcript"], "the transcript travels with the review"

    timed = [f for f in review["findings"] if f["timecode_start"] is not None]
    assert timed, "a spoken finding must carry a timecode"
    cure = next(
        f for f in timed if f["agent"] == "legal" and f["guideline_code"] == "IN-DMR-S3"
    )
    assert cure["timecode_start"] == 3.0
    assert cure["timecode_end"] == 8.0
    assert cure["guideline_code"] == "IN-DMR-S3"
    assert "Schedule I" in cure["guideline_citation"]
    assert cure["severity"] == "critical"
    assert review["hard_blocker"] is True
    assert review["routing"]["route"] == "legal"
