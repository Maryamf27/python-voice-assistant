# TravelAI Voice Agent (Python service)

This is the original team member's voice agent (speech recognition +
text-to-speech + travel intent matching), wrapped as an HTTP service so
the Node/Express backend can call it. The actual STT/TTS logic and
travel intent rules are unchanged from the original script — only the
I/O boundary changed (uploaded audio in, synthesized audio out) so it
can run as a service instead of a local CLI loop tied to a microphone
and speakers on one machine.

## Architecture

```
Browser (mic)
   |  records audio via MediaRecorder
   v
Next.js frontend
   |  POST audio -> Node backend
   v
Node/Express (POST /api/voice/query, JWT-protected)
   |  forwards audio + user's JWT -> Python service
   v
Python Voice Agent (this service)
   |  1. Speech-to-Text  (speech_recognition + Google Web Speech API)
   |  2. Intent matching (same keyword rules as the original script)
   |  3. Calls back into TravelAI's own API for "show me my trips"
   |  4. Text-to-Speech  (pyttsx3)
   v
Returns { transcript, reply, audio_base64 } back up the chain
```

The browser **never** talks to this service directly — only the Node
backend does, using `VOICE_AGENT_URL`.

## Requirements

- Python 3.10+
- **ffmpeg** installed and on your PATH (needed by `pydub` to convert
  the browser's recorded audio — usually `webm`/`opus` — into WAV
  before it's handed to `speech_recognition`)
  - macOS: `brew install ffmpeg`
  - Ubuntu/Debian: `sudo apt-get install ffmpeg`
  - Windows: download from ffmpeg.org and add to PATH
- **A TTS driver for `pyttsx3`**:
  - Windows: uses `sapi5` automatically (built in, matches the
    original script)
  - Linux: install `espeak` or `espeak-ng` (`sudo apt-get install
    espeak-ng`) — without this, `pyttsx3` will fail to produce any
    audio at all
  - macOS: uses the built-in `nsss` driver automatically

## Setup

```bash
cd voice-agent
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` if your Node backend isn't running on the defaults:

```env
TRAVELAI_API_URL=http://localhost:5000/api
NODE_BACKEND_ORIGIN=http://localhost:5000
```

## Run

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Then point the Node backend at it via its own `.env`:

```env
VOICE_AGENT_URL=http://localhost:8000
```

## Endpoints

- `GET /health` — basic liveness check
- `POST /voice/query` — multipart form: `audio` (file), `user_id`,
  `user_name`, `auth_token` (all sent by the Node backend, not the
  browser). Returns `{ transcript, reply, audio_base64 }`.

## What's real vs. what's still the original script's behavior

- **Speech-to-text**: same as the original script — Google's free Web
  Speech API via `speech_recognition.recognize_google()`. This is an
  unofficial, rate-limited endpoint (same limitation the original
  script already had); it's fine for a class/internship project but
  not for production traffic.
- **Intent logic**: same keyword-based `if/elif` matching as the
  original script (no LLM was added). One addition: "show me my
  trips" / "my previous trips" now calls the real `GET /api/trips`
  endpoint using the user's own JWT, instead of a canned reply —
  everything else still just asks a clarifying question the same way
  the original script did (e.g. "Which city are you looking to book a
  hotel in?"), since fully parsing a booking request (destination +
  budget + dates + travelers) from a single sentence would require
  adding real NLU/LLM parsing, which wasn't part of the original
  script and wasn't in scope here.
- **Text-to-speech**: same `pyttsx3` engine as the original script,
  now rendering to a WAV file instead of playing live through
  speakers, so the audio can be sent back over HTTP.

## Known limitations

- Google's free speech recognition endpoint can occasionally rate-limit
  or be unavailable — the service returns a clean `502` in that case
  rather than crashing.
- `pyttsx3` audio quality depends entirely on which OS driver is
  available (espeak on Linux sounds noticeably more robotic than
  Windows' sapi5 voices).
- No conversation memory between turns — each voice query is
  stateless, same as the original script.
