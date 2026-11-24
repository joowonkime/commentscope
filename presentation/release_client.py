"""Check or prepare the team's fixed Vercel browser release using Python 3.12+."""
import argparse
import hashlib
import json
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
RELEASE = ROOT / "release"
PREVIEW = ROOT / "frontend" / ".release"
ORIGIN = "https://commentmas.vercel.app"
MARKER = b"__REVIEW_FIREBASE_WEB_API_KEY__"
WEB_KEY = re.compile(rb"AIza[A-Za-z0-9_-]{35}")
ASSET_PATH = re.compile(r"/assets/[A-Za-z0-9_.-]+")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_manifest():
    manifest = json.loads((RELEASE / "manifest.json").read_text(encoding="utf-8"))
    paths = manifest["assets"]
    if (manifest["origin"] != ORIGIN or "/" not in paths or manifest["entry_script"] not in paths
            or any(path != "/" and not ASSET_PATH.fullmatch(path) for path in paths)):
        raise ValueError("Invalid release manifest.")
    return manifest


def filename(route):
    return "index.html" if route == "/" else route[1:]


def checked(data, expected, route):
    if digest(data) != expected:
        raise ValueError(f"Release checksum mismatch at {route}")
    return data


def repository_files(manifest):
    files = {}
    for route, expected in manifest["assets"].items():
        name = filename(route)
        path = RELEASE / name
        if route == manifest["entry_script"]:
            path = path.with_suffix(".js.in")
            expected = manifest["script_template_sha256"]
        files[route] = checked(path.read_bytes(), expected, route)
    if files[manifest["entry_script"]].count(MARKER) != 1:
        raise ValueError("Expected a single Firebase browser configuration slot.")
    return files


def fetch(route):
    request = Request(ORIGIN + route, headers={"User-Agent": "ReView-Presentation-Check"})
    with urlopen(request, timeout=30) as response:
        if response.geturl() != request.full_url:
            raise ValueError(f"Unexpected redirect at {route}")
        return response.read()


def restore_script(manifest, template):
    route = manifest["entry_script"]
    expected = manifest["assets"][route]
    supplied = os.environ.get("REVIEW_FIREBASE_WEB_API_KEY")
    if supplied:
        keys = [supplied.encode("ascii")]
    else:
        # Read only the browser configuration already sent to every visitor.
        cached = PREVIEW / filename(route)
        if cached.is_file():
            previous = cached.read_bytes()
            if digest(previous) == expected:
                return previous
        try:
            keys = WEB_KEY.findall(fetch(route))
        except (URLError, OSError):
            keys = []
    for key in keys:
        if WEB_KEY.fullmatch(key):
            candidate = template.replace(MARKER, key)
            if digest(candidate) == expected:
                return candidate
    raise ValueError("Matching Firebase web configuration unavailable. Set REVIEW_FIREBASE_WEB_API_KEY "
                     "to the public web key for this release and retry.")


def prepare(manifest, files):
    script = manifest["entry_script"]
    files[script] = restore_script(manifest, files[script])
    PREVIEW.parent.mkdir(parents=True, exist_ok=True)
    # Validate all inputs first. Replace assets before switching the HTML entry point.
    with tempfile.TemporaryDirectory(dir=PREVIEW.parent) as directory:
        stage = Path(directory)
        for route, data in files.items():
            path = stage / filename(route)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (PREVIEW / "assets").mkdir(parents=True, exist_ok=True)
        for route in sorted(files, key=lambda r: r == "/"):
            name = filename(route)
            os.replace(stage / name, PREVIEW / name)
    print(f"Prepared {len(files)} verified routes in {PREVIEW}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "verify-live", "prepare"))
    action = parser.parse_args().action
    manifest = read_manifest()
    files = repository_files(manifest)
    if action == "check":
        print(f"Verified {len(files)} stored routes including the redacted script template.")
    elif action == "verify-live":
        def verify(route):
            checked(fetch(route), manifest["assets"][route], route)
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(verify, files))
        print(f"All {len(files)} public routes match the recorded release.")
    else:
        prepare(manifest, files)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, URLError) as exc:
        raise SystemExit(str(exc)) from None
