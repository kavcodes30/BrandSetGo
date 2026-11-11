"""Write SARVAM_API_KEY into backend/.env without printing the key."""
import os
import pathlib
import re

key = os.environ.get("SARVAM_KEY", "").strip()
if not key:
    raise SystemExit("no key supplied")

env = pathlib.Path(__file__).resolve().parent.parent / "backend" / ".env"
if not env.exists():
    env.write_text(pathlib.Path(__file__).resolve().parent.parent.joinpath("backend", ".env.example").read_text())

text = env.read_text()
text = re.sub(r"(?m)^SARVAM_API_KEY=.*$", "SARVAM_API_KEY=" + key, text)
env.write_text(text)
print("ok")
