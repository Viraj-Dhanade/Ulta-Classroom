import os
from pathlib import Path

from sarvamai import SarvamAI

# Load the single setting without adding a dotenv dependency.
for line in Path(__file__).with_name(".env").read_text(encoding="utf-8").splitlines():
    name, separator, value = line.partition("=")
    if separator and name.strip() == "SARVAM_API_KEY":
        os.environ.setdefault(name.strip(), value.strip().strip("\"'"))

api_key = os.environ.get("SARVAM_API_KEY", "").strip()
if not api_key:
    raise SystemExit("Paste your key into .env as SARVAM_API_KEY before running.")

client = SarvamAI(api_subscription_key=api_key)
try:
    response = client.chat.completions(
        model="sarvam-105b-conversations",
        messages=[{"role": "user", "content": "Say hello in one short sentence."}],
    )
except Exception:
    raise SystemExit("Sarvam request failed. Check your credentials and connection.") from None

print(response.choices[0].message.content)
