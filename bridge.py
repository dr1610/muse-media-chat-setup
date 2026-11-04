"""Local, authenticated Muse connector for speech and image replies."""

import argparse
import base64
import hmac
import http.client
import json
import os
import secrets
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlencode, urlsplit

from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, StrictInt

ROOT = Path(__file__).resolve().parent
MAX_RESULT = 32 * 1024 * 1024
ID = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")]
VoiceID = Annotated[str, Field(min_length=1, max_length=120)]
Percent = Annotated[StrictInt, Field(ge=0, le=100)]
Caption = Annotated[str, Field(max_length=2000)]
NonemptyText = Annotated[str, Field(min_length=1, max_length=4000)]


class RequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TurnOverrides(RequestBody):
    voice_percent: Percent | None = None
    image_percent: Percent | None = None
    caption: Caption | None = None
    voice_id: VoiceID | None = None


class SettingsChange(TurnOverrides):
    expected_revision: Annotated[StrictInt, Field(ge=0)]
    proactive_percent: Percent | None = None


class TurnRequest(RequestBody):
    request_id: ID
    chat_id: ID
    overrides: TurnOverrides = Field(default_factory=TurnOverrides)


class JobRequest(RequestBody):
    request_id: ID
    turn_id: ID
    kind: Literal["voice", "image"]
    text: NonemptyText
    caption: Caption | None = None


class ChatSettings(BaseModel):
    voice_percent: Percent
    image_percent: Percent
    proactive_percent: Percent
    caption: Caption | None
    voice_id: VoiceID
    revision: int


class TurnResult(BaseModel):
    id: ID
    media: dict[str, bool]
    settings: ChatSettings


class JobResult(BaseModel):
    id: ID
    kind: Literal["voice", "image"]
    status: Literal["queued", "running", "succeeded", "failed"]
    file_path: str | None = None
    error: str | None = None


class Capabilities(BaseModel):
    voice_enabled: bool
    voice_language: Literal["ja", "en"]
    voice_caption_supported: bool
    image_enabled: bool
    voices: list[str]
    proactive_delivery: bool
    character_md: str


def atomic_json(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def local_request(base, route, payload=None, token=None, timeout=300):
    target = urlsplit(base)
    if (target.scheme != "http" or target.hostname not in ("127.0.0.1", "localhost")
            or target.username or target.password or target.path not in ("", "/")
            or target.query or target.fragment):
        raise ValueError("Backend URL must be a local HTTP origin.")
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload, ensure_ascii=False).encode()
    connection = http.client.HTTPConnection(target.hostname, target.port or 80, timeout=timeout)
    try:
        connection.request("POST" if body is not None else "GET", route, body, headers)
        with connection.getresponse() as response:
            if response.status >= 300:
                raise RuntimeError(f"Backend returned HTTP {response.status}.")
            result = response.read(MAX_RESULT + 1)
        if len(result) > MAX_RESULT:
            raise ValueError("Backend result is too large.")
        return result
    finally:
        connection.close()


def workflow_values(value, replacements):
    if isinstance(value, dict):
        return {key: workflow_values(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [workflow_values(item, replacements) for item in value]
    return replacements.get(value, value) if isinstance(value, str) else value


class Bridge:
    def __init__(self, root, config):
        self.root = root
        self.config = config
        self.data = root / "data"
        self.data.mkdir(exist_ok=True)
        self.state_path = self.data / "state.json"
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.state = (json.loads(self.state_path.read_text(encoding="utf-8"))
                      if self.state_path.exists() else {"chats": {}, "turns": {}, "jobs": {}})
        self.character = (root / "examples/character.md").read_text(encoding="utf-8")
        _, positive = self.character.split("\n## Fixed appearance prompt\n", 1)
        self.positive, self.negative = (part.strip() for part in
                                        positive.split("\n## Negative appearance prompt\n", 1))
        self.workflow = None
        voice = config["voice"]
        image = config["image"]
        voice_backend = voice.get("backend", "irodori")
        if voice_backend not in ("irodori", "kokoro"):
            raise ValueError("voice.backend must be irodori or kokoro.")
        self.voice_language = "ja" if voice_backend == "irodori" else "en"
        self.voice_caption_supported = voice_backend == "irodori"
        if voice["initial_voice"] not in voice["allowed_voices"]:
            raise ValueError("initial_voice must also appear in allowed_voices.")
        if image["backend"] not in ("webui", "comfyui"):
            raise ValueError("image.backend must be webui or comfyui.")
        if image["enabled"] and image["backend"] == "comfyui":
            path = root / image["workflow"]
            workflow = path.read_text(encoding="utf-8-sig")
            if '"__PROMPT__"' not in workflow or not image["output_node"]:
                raise ValueError("Set __PROMPT__ and configure the Save Image output node ID.")
            self.workflow = json.loads(workflow)
        for job in self.state["jobs"].values():
            if job["status"] in ("queued", "running"):
                job.update(status="failed", error="bridge_restarted")
        self.save()

    def save(self):
        atomic_json(self.state_path, self.state)

    def store(self, collection, key, value):
        records = self.state[collection]
        previous = records.get(key)
        records[key] = value
        try:
            self.save()
        except OSError:
            if previous is None:
                records.pop(key)
            else:
                records[key] = previous
            raise

    def settings(self, chat_id):
        defaults = {"voice_percent": 100, "image_percent": 100, "proactive_percent": 0,
                    "caption": None, "voice_id": self.config["voice"]["initial_voice"], "revision": 0}
        settings = {**defaults, **self.state["chats"].get(chat_id, {})}
        if settings["voice_id"] not in self.config["voice"]["allowed_voices"]:
            settings["voice_id"] = defaults["voice_id"]
        return settings

    def changes(self, body, exclude=()):
        changes = body.model_dump(exclude_unset=True, exclude=set(exclude))
        if any(value is None for key, value in changes.items() if key != "caption"):
            raise HTTPException(422, "Only caption can be null.")
        if "voice_id" in changes and changes["voice_id"] not in self.config["voice"]["allowed_voices"]:
            raise HTTPException(422, "Choose a locally allowed voice ID.")
        if changes.get("caption") is not None and not self.voice_caption_supported:
            raise HTTPException(422, "The selected voice backend does not support acting captions.")
        return changes

    def generate_voice(self, turn, request):
        config = self.config["voice"]
        payload = {"model": config["model"], "voice": turn["settings"]["voice_id"],
                   "input": request["text"], "response_format": "wav"}
        caption = turn["settings"]["caption"]
        if caption is None:
            caption = request["caption"]
        if self.voice_caption_supported and caption is not None:
            payload["irodori"] = {"caption": caption}
        token = os.environ.get(config["token_env"]) if config["token_env"] else None
        if config["token_env"] and not token:
            raise ValueError("The configured voice backend token is unavailable.")
        data = local_request(config["url"], "/v1/audio/speech", payload, token)
        if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
            raise ValueError("Voice backend did not return a WAV.")
        return data

    def generate_image(self, request):
        config = self.config["image"]
        prompt = self.positive + ", " + request["text"]
        if config["backend"] == "webui":
            payload = {"prompt": prompt, "negative_prompt": self.negative,
                       "width": config["width"], "height": config["height"],
                       "steps": config["steps"], "seed": -1, "batch_size": 1, "n_iter": 1}
            response = json.loads(local_request(config["url"], "/sdapi/v1/txt2img", payload))
            image = response["images"][0]
            data = base64.b64decode(image.split(",", 1)[-1], validate=True)
        else:
            data = self.comfy_image(config, prompt)
        if data[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError("Image backend did not return a PNG.")
        return data

    def comfy_image(self, config, prompt):
        workflow = workflow_values(self.workflow, {"__PROMPT__": prompt,
                                   "__NEGATIVE__": self.negative, "__SEED__": secrets.randbits(53)})
        base = config["url"]
        accepted = json.loads(local_request(base, "/prompt", {"prompt": workflow}, timeout=15))
        prompt_id = str(uuid.UUID(accepted["prompt_id"]))
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            history = json.loads(local_request(base, "/history/" + prompt_id, timeout=10))
            if prompt_id in history:
                result = history[prompt_id]
                if result.get("status", {}).get("status_str") == "error":
                    raise RuntimeError("ComfyUI workflow failed.")
                item = result["outputs"][config["output_node"]]["images"][0]
                if item.get("type") != "output":
                    raise ValueError("Configure a Save Image output node.")
                query = urlencode({"filename": item["filename"],
                                   "subfolder": item.get("subfolder", ""), "type": "output"})
                return local_request(base, "/view?" + query, timeout=20)
            time.sleep(2)
        raise TimeoutError("ComfyUI job timed out.")

    def run_job(self, job_id):
        with self.lock:
            job = self.state["jobs"][job_id]
            request = job["request"]
            turn = self.state["turns"][request["turn_id"]]
        try:
            with self.lock:
                self.store("jobs", job_id, {**job, "status": "running"})
            data = (self.generate_voice(turn, request) if request["kind"] == "voice"
                    else self.generate_image(request))
            destination = self.data / (job_id + (".wav" if request["kind"] == "voice" else ".png"))
            destination.write_bytes(data)
            with self.lock:
                self.store("jobs", job_id, {**job, "status": "succeeded"})
        except Exception as error:
            with self.lock:
                failed = {**job, "status": "failed", "error": type(error).__name__}
                try:
                    self.store("jobs", job_id, failed)
                except OSError:
                    self.state["jobs"][job_id] = failed

    @staticmethod
    def public_job(job_id, job):
        result = {"id": job_id, "status": job["status"], "kind": job["request"]["kind"]}
        if job["status"] == "succeeded":
            result["file_path"] = f"/v1/jobs/{job_id}/file"
        if "error" in job:
            result["error"] = job["error"]
        return result


def create_app(bridge, key):
    app = FastAPI(title="Muse Media Chat Bridge", version="0.1.0", docs_url=None, redoc_url=None)
    bearer = HTTPBearer(auto_error=False)

    def authenticate(credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer)]):
        if credentials is None or not hmac.compare_digest(credentials.credentials.encode(), key.encode()):
            raise HTTPException(401, "Bearer authentication required.",
                                headers={"WWW-Authenticate": "Bearer"})

    auth = [Depends(authenticate)]

    @app.get("/v1/capabilities", dependencies=auth, response_model=Capabilities)
    def capabilities():
        return {"voice_enabled": bridge.config["voice"]["enabled"],
                "voice_language": bridge.voice_language,
                "voice_caption_supported": bridge.voice_caption_supported,
                "image_enabled": bridge.config["image"]["enabled"],
                "voices": bridge.config["voice"]["allowed_voices"],
                "proactive_delivery": False, "character_md": bridge.character}

    @app.get("/v1/settings/{chat_id}", dependencies=auth, response_model=ChatSettings)
    def settings(chat_id: ID):
        with bridge.lock:
            return bridge.settings(chat_id)

    @app.post("/v1/settings/{chat_id}", dependencies=auth, response_model=ChatSettings)
    def update_settings(chat_id: ID, change: SettingsChange):
        changes = bridge.changes(change, {"expected_revision"})
        with bridge.lock:
            saved = bridge.settings(chat_id)
            if saved["revision"] != change.expected_revision:
                raise HTTPException(409, "Reload current settings before retrying.")
            if not changes or all(saved[key] == value for key, value in changes.items()):
                return saved
            saved.update(changes, revision=saved["revision"] + 1)
            bridge.store("chats", chat_id, saved)
            return saved

    @app.post("/v1/turns", dependencies=auth, response_model=TurnResult)
    def create_turn(body: TurnRequest):
        changes = bridge.changes(body.overrides)
        with bridge.lock:
            turns = bridge.state["turns"]
            request = body.model_dump(exclude_unset=True)
            if body.request_id in turns:
                turn = turns[body.request_id]
                if turn["request"] != request:
                    raise HTTPException(409, "Turn request ID already used.")
            else:
                saved = {**bridge.settings(body.chat_id), **changes}
                media = {kind: bridge.config[kind]["enabled"] and
                         secrets.randbelow(100) < saved[kind + "_percent"]
                         for kind in ("voice", "image")}
                turn = {"request": request, "media": media, "settings": saved}
                bridge.store("turns", body.request_id, turn)
            return {"id": body.request_id, "media": turn["media"], "settings": turn["settings"]}

    @app.post("/v1/jobs", dependencies=auth, status_code=202,
              response_model=JobResult, response_model_exclude_none=True)
    def submit_job(body: JobRequest):
        request = body.model_dump()
        if not body.text.strip() or (body.kind == "image" and body.caption is not None):
            raise HTTPException(422, "Provide text and use caption only for voice.")
        with bridge.lock:
            turn = bridge.state["turns"].get(body.turn_id)
            if turn is None:
                raise HTTPException(404, "Unknown turn.")
            if not turn["media"][body.kind]:
                raise HTTPException(409, "This medium is disabled for the turn.")
            jobs = bridge.state["jobs"]
            for job_id, job in jobs.items():
                previous = job["request"]
                if previous["request_id"] == body.request_id:
                    if previous != request:
                        raise HTTPException(409, "Job request ID already used.")
                    return bridge.public_job(job_id, job)
                if previous["turn_id"] == body.turn_id and previous["kind"] == body.kind:
                    raise HTTPException(409, "This turn already has a job for that medium.")
            if body.caption is not None and not bridge.voice_caption_supported:
                raise HTTPException(422, "The selected voice backend does not support acting captions.")
            if body.kind == "voice" and turn["settings"]["voice_id"] not in bridge.config["voice"]["allowed_voices"]:
                raise HTTPException(409, "Create a new turn with a currently allowed voice.")
            if sum(job["status"] in ("queued", "running") for job in jobs.values()) >= 4:
                raise HTTPException(429, "Queue full.", headers={"Retry-After": "10"})
            job_id = uuid.uuid4().hex
            job = {"request": request, "status": "queued"}
            bridge.store("jobs", job_id, job)
            bridge.pool.submit(bridge.run_job, job_id)
            return bridge.public_job(job_id, job)

    @app.get("/v1/jobs/{job_id}", dependencies=auth,
             response_model=JobResult, response_model_exclude_none=True)
    def job_status(job_id: ID):
        with bridge.lock:
            job = bridge.state["jobs"].get(job_id)
            if job is None:
                raise HTTPException(404, "Unknown job.")
            return bridge.public_job(job_id, job)

    @app.get("/v1/jobs/{job_id}/file", dependencies=auth, response_class=FileResponse,
             responses={200: {"content": {"audio/wav": {"schema": {"type": "string", "format": "binary"}},
                                          "image/png": {"schema": {"type": "string", "format": "binary"}}}}})
    def job_file(job_id: ID):
        with bridge.lock:
            job = bridge.state["jobs"].get(job_id)
            if job is None or job["status"] != "succeeded":
                raise HTTPException(404, "Completed file unavailable.")
            suffix, mime = ((".wav", "audio/wav") if job["request"]["kind"] == "voice"
                            else (".png", "image/png"))
            path = bridge.data / (job_id + suffix)
            if not path.is_file():
                raise HTTPException(404, "Completed file unavailable.")
        return FileResponse(path, media_type=mime, filename=path.name,
                            headers={"Cache-Control": "no-store"})

    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--init", action="store_true", help="Create local settings and a new API key.")
    parser.add_argument("--export-openapi", type=Path, help="Write the connector schema and exit.")
    args = parser.parse_args()
    config_path = ROOT / "config.json"
    key_path = ROOT / "data/bridge-key.txt"
    if args.init:
        if not config_path.exists():
            shutil.copyfile(ROOT / "config.example.json", config_path)
        key_path.parent.mkdir(exist_ok=True)
        if not key_path.exists():
            with key_path.open("x", encoding="ascii") as stream:
                stream.write(secrets.token_urlsafe(32))
        print("Edit config.json and enter data/bridge-key.txt in the Muse credentials form.")
        return
    if args.export_openapi:
        args.export_openapi.write_text(json.dumps(create_app(None, "").openapi(), indent=2) + "\n",
                                      encoding="utf-8")
        return
    if not config_path.is_file() or not key_path.is_file():
        parser.error("Run setup.cmd or python bridge.py --init first.")
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    key = key_path.read_text(encoding="ascii").strip()
    if len(key) < 32:
        parser.error("The bridge key must contain at least 32 characters.")
    bridge = Bridge(ROOT, config)
    import uvicorn
    uvicorn.run(create_app(bridge, key), host="127.0.0.1", port=config["port"], access_log=False)


if __name__ == "__main__":
    main()
