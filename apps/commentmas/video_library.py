"""Generate and reuse public, comment-grounded video analyses. Personal records live elsewhere."""
import errno
import json
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

from collect_comments import VIDEO_ID, YouTubeAPI, YouTubeError, collect, parse_video_id
from filter_comments import digest, filter_source, save_results as save_filter, write_json
from firebase_backend import RecordConflict
from group_comments import group_source, save_results as save_groups
from perspective_agents import build_bundle
from web_data import WebData


FILES = ("01_filter/filtered.json", "02_group/groups.json", "03_agents/agents.json",
         "04_web/catalog.json", "04_web/translations.json")


class IntakeError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class LocalRecords:
    """The same compare-and-set contract as the Firestore record store."""
    def __init__(self, path):
        self.path = path
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, hash TEXT, body TEXT)")

    def load(self, key):
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT body FROM records WHERE id=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def save(self, key, value, expected_hash):
        body = json.dumps(value, ensure_ascii=False)
        with sqlite3.connect(self.path) as db:
            if expected_hash is None:
                changed = db.execute("INSERT OR IGNORE INTO records VALUES (?,?,?)", (key, digest(value), body))
            else:
                changed = db.execute("UPDATE records SET hash=?,body=? WHERE id=? AND hash=?",
                                     (digest(value), body, key, expected_hash))
            if not changed.rowcount:
                raise RecordConflict("The record changed.")


def generate_video(video_id, api, client, limit, directory, progress):
    videos = api.get("videos", part="snippet", id=video_id).get("items", [])
    if not videos:
        raise YouTubeError("videoNotFound")
    title = videos[0]["snippet"]["title"]
    rows = collect(api, video_id, None, True, max_rows=limit, order="relevance")
    if not rows:
        raise IntakeError(422, "This video has no public comments to analyze. Choose another video.")
    source = {"meta": {"video_id": video_id, "title": title}, "comments": rows}
    progress("filtering")
    filtered_dir = directory / "01_filter"
    save_filter(filtered_dir, filter_source(source, client, filtered_dir, topic=title, model=client.model))
    retained = json.loads((filtered_dir / "filtered.json").read_text(encoding="utf-8"))
    if not retained["comments"]:
        raise IntakeError(422, "The sampled comments did not contain a supported viewpoint. Try another video.")
    progress("grouping")
    groups_dir = directory / "02_group"
    result = group_source(retained, client, groups_dir, topic=title, context_rows=rows)
    if not result["groups"]:
        raise IntakeError(422, "No perspective had enough comment evidence to create an agent.")
    save_groups(groups_dir, result)
    grouped = json.loads((groups_dir / "groups.json").read_text(encoding="utf-8"))
    progress("creating_agents")
    agents = build_bundle(grouped, result, retained)
    write_json(directory / "03_agents/agents.json", agents)
    progress("preparing_cards")
    WebData(directory, client).prepare()
    return {name: json.loads((directory / name).read_text(encoding="utf-8")) for name in FILES}


class VideoLibrary:
    # A worker renews its claim during long model calls. A stopped instance leaves a retryable job.
    LEASE_SECONDS = 120

    def __init__(self, root, settings, client, demo=None, store=None, generate=generate_video):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.store = store if store is not None else LocalRecords(self.root / "videos.sqlite3")
        self.limit = int(settings.get("VIDEO_COMMENT_LIMIT", 100))
        if not 1 <= self.limit <= 500:
            raise ValueError("VIDEO_COMMENT_LIMIT must be between 1 and 500.")
        self.youtube_key = settings.get("YOUTUBE_API_KEY", "").strip()
        self.client, self.demo, self.generate = client, demo, generate
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="video-intake")
        self.lock = threading.RLock()
        self.active = None

    def options(self):
        return {"demo": self.demo, "comment_limit": self.limit, "can_generate": bool(self.youtube_key)}

    def _demo(self, vid):
        return self.demo and self.demo["video_id"] == vid

    def _public(self, record):
        if record["status"] == "running" and record["updated"] + self.LEASE_SECONDS <= time.time():
            return {"video_id": record["video_id"], "status": "failed",
                    "error": "Preparation was interrupted. Retry to prepare this video."}
        return {k: record[k] for k in ("video_id", "status", "stage", "error") if k in record}

    def status(self, vid):
        if not VIDEO_ID.fullmatch(vid):
            raise IntakeError(400, "Invalid video ID.")
        if self._demo(vid):
            return {"video_id": vid, "status": "ready"}
        record = self.store.load("jobs/" + vid)
        if not record:
            raise IntakeError(404, "This video has not been prepared yet.")
        return self._public(record)

    def start(self, url):
        try:
            vid = parse_video_id(url)
        except ValueError as exc:
            raise IntakeError(400, str(exc)) from None
        if self._demo(vid):
            return self.status(vid)
        key = "jobs/" + vid
        with self.lock:
            old = self.store.load(key)
            if old:
                public = self._public(old)
                if public["status"] != "failed":
                    return public
            if not self.youtube_key:
                raise IntakeError(503, "New videos need a YouTube API key on the server. Open a prepared video instead.")
            if self.active is not None:
                raise IntakeError(429, "Another video is being prepared. Please try again shortly.")
            record = {"video_id": vid, "status": "running", "stage": "collecting",
                      "attempt": uuid.uuid4().hex, "updated": time.time()}
            try:
                self.store.save(key, record, digest(old) if old else None)
            except RecordConflict:
                return self.status(vid)
            self.active = record["attempt"]
            self.worker.submit(self._run, record)
            return self._public(record)

    def _run(self, initial):
        record = initial
        vid = record["video_id"]
        key = "jobs/" + vid
        stop = threading.Event()
        update_lock = threading.Lock()

        def update(**changes):
            nonlocal record
            with update_lock:
                updated = {**record, **changes, "updated": time.time()}
                self.store.save(key, updated, digest(record))
                record = updated

        def heartbeat():
            while not stop.wait(self.LEASE_SECONDS / 3):
                try:
                    update()
                except Exception:
                    return  # A new owner can take over when the last successful renewal expires.

        def progress(stage):
            update(stage=stage)

        pulse = threading.Thread(target=heartbeat, daemon=True)
        pulse.start()
        outcome = None
        try:
            with TemporaryDirectory(dir=self.root) as temp:
                files = self.generate(vid, YouTubeAPI(self.youtube_key), self.client, self.limit, Path(temp), progress)
            # Public analysis and private rooms never share a record.
            self.store.save("datasets/" + record["attempt"], files, None)
            outcome = {"status": "ready", "stage": "ready"}
        except RecordConflict:
            pass  # A newer attempt owns this video.
        except Exception as exc:
            message = (str(exc) if isinstance(exc, (YouTubeError, IntakeError)) else
                       "We could not finish preparing the perspectives. Please retry.")
            print(f"Video preparation failed at {record['stage']}: {type(exc).__name__}", flush=True)
            outcome = {"status": "failed", "error": message}
        finally:
            stop.set()
            pulse.join()
            with self.lock:
                try:
                    if outcome:
                        update(**outcome)
                except RecordConflict:
                    pass
                finally:
                    self.active = None

    def directory(self, vid):
        if not VIDEO_ID.fullmatch(vid):
            raise IntakeError(400, "Invalid video ID.")
        record = self.store.load("jobs/" + vid)
        if not record or record["status"] != "ready":
            raise IntakeError(404, "The perspectives for this video are not ready. Return to Choose video.")
        path = self.root / "catalogs" / record["attempt"]
        with self.lock:
            if not (path / "04_web/catalog.json").is_file():
                files = self.store.load("datasets/" + record["attempt"])
                if files is None:
                    raise IntakeError(503, "The saved analysis is temporarily unavailable.")
                path.parent.mkdir(parents=True, exist_ok=True)
                with TemporaryDirectory(dir=path.parent) as temp:
                    prepared = Path(temp) / "complete"
                    for name in FILES:
                        write_json(prepared / name, files[name])
                    try:
                        prepared.rename(path)
                    except OSError as exc:
                        # Another server using this disk may have restored the same immutable attempt.
                        if exc.errno not in (errno.EEXIST, errno.ENOTEMPTY, errno.EACCES) or not (path / "04_web/catalog.json").is_file():
                            raise
        return path
