import base64
import io
import os
import tempfile
from typing import Callable, cast

import httpx
import pyttsx3
import speech_recognition as sr
from dotenv import load_dotenv
from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydub import AudioSegment

load_dotenv()

TRAVELAI_API_URL = os.getenv(
    "TRAVELAI_API_URL",
    "http://localhost:5000/api"
)

ALLOWED_ORIGIN = os.getenv(
    "NODE_BACKEND_ORIGIN",
    "http://localhost:5000"
)

app = FastAPI(title="TravelAI Voice Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[ALLOWED_ORIGIN],
    allow_methods=["POST"],
    allow_headers=["*"],
)


try:
    _tts_engine = pyttsx3.init("espeak")
except Exception as exc:
    print(f"Failed to initialize Linux TTS: {exc}")
    _tts_engine = None

if _tts_engine:
    _tts_engine.setProperty("rate", 150)
    _tts_engine.setProperty("volume", 1.0)


_recognizer = sr.Recognizer()
_recognizer.dynamic_energy_threshold = True
_recognizer.pause_threshold = 0.8


def speak_to_bytes(text: str) -> bytes:
    """
    Convert text to WAV audio bytes using Linux eSpeak/eSpeak-NG.
    """

    if _tts_engine is None:
        raise HTTPException(
            status_code=500,
            detail="Text-to-speech engine is not available."
        )

    with tempfile.NamedTemporaryFile(
        suffix=".wav",
        delete=False
    ) as tmp:
        tmp_path = tmp.name

    try:
        _tts_engine.save_to_file(text, tmp_path)
        _tts_engine.runAndWait()

        with open(tmp_path, "rb") as f:
            return f.read()

    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def transcribe_audio(
    raw_audio_bytes: bytes,
    content_type: str
) -> str:

    try:
        audio_segment = AudioSegment.from_file(
            io.BytesIO(raw_audio_bytes)
        )
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Could not process audio: {exc}"
        ) from exc

    wav_buffer = io.BytesIO()

    audio_segment.export(
        wav_buffer,
        format="wav"
    )

    wav_buffer.seek(0)

    with sr.AudioFile(wav_buffer) as source:
        audio_data = _recognizer.record(source)

    try:
        recognize_google = cast(
            Callable[[sr.AudioData], str],
            getattr(_recognizer, "recognize_google")
        )
        command = recognize_google(audio_data)
        return command.lower()

    except sr.UnknownValueError:
        return ""

    except sr.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "Speech recognition service "
                "(Google) is unavailable."
            ),
        ) from exc


async def fetch_recent_trips(
    auth_token: str
) -> str:

    try:
        async with httpx.AsyncClient(
            timeout=10
        ) as client:

            resp = await client.get(
                f"{TRAVELAI_API_URL}/trips",
                headers={
                    "Authorization": f"Bearer {auth_token}"
                },
            )

        if resp.status_code != 200:
            return (
                "I couldn't reach your trip history right now. "
                "Please try again shortly."
            )

        data = resp.json()

        trips = data.get("trips", [])

        if not trips:
            return (
                "You don't have any saved trips yet. "
                "Want me to help you plan one?"
            )

        top = trips[:3]

        names = ", ".join(
            t.get(
                "destination",
                "an unnamed trip"
            )
            for t in top
        )

        return (
            f"You have {len(trips)} saved trips. "
            f"The most recent ones are: {names}."
        )

    except httpx.HTTPError:
        return (
            "I'm having trouble connecting to TravelAI "
            "right now. Please try again."
        )


async def process_travel_intent(
    command: str,
    auth_token: str | None
) -> str:

    if not command:
        return (
            "Sorry, I could not understand what you said. "
            "Please speak again."
        )

    if (
        "my trip" in command
        or "previous trip" in command
        or "trip history" in command
    ):

        if not auth_token:
            return "Please log in to view your trip history."

        return await fetch_recent_trips(auth_token)

    if (
        "flight" in command
        or "fly" in command
        or "plane" in command
    ):
        return (
            "Where would you like to fly to, "
            "and what is your departure date?"
        )

    if (
        "hotel" in command
        or "stay" in command
        or "room" in command
    ):
        return "Which city are you looking to book a hotel in?"

    if "cancel" in command:
        return (
            "Please provide your booking reference number "
            "to cancel."
        )

    if (
        "hello" in command
        or "hi" in command
        or "hey" in command
    ):
        return (
            "Hello! I am your travel assistant. "
            "How can I help you plan your trip?"
        )

    if (
        "exit" in command
        or "stop" in command
        or "bye" in command
    ):
        return "Goodbye! Have a great trip."

    return (
        "I can help you book flights, search hotels, "
        "or check your trip history. How can I assist you?"
    )


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "travelai-voice-agent"
    }


@app.post("/voice/query")
async def voice_query(
    audio: UploadFile,
    user_id: str | None = Form(default=None),
    user_name: str | None = Form(default=None),
    auth_token: str | None = Form(default=None),
):

    raw_bytes = await audio.read()

    if not raw_bytes:
        raise HTTPException(
            status_code=400,
            detail="No audio data received."
        )

    transcript = transcribe_audio(
        raw_bytes,
        audio.content_type or ""
    )

    reply_text = await process_travel_intent(
        transcript,
        auth_token
    )

    reply_audio = speak_to_bytes(reply_text)

    return {
        "transcript": transcript,
        "reply": reply_text,
        "audio_base64": base64.b64encode(
            reply_audio
        ).decode("utf-8"),
    }