"""Verify the presentation's published files, a local build, or rebuild the pinned client."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT.parent / "apps" / "commentmas" / "frontend"
ORIGIN = "https://commentmas.vercel.app"
FIELDS = ("VITE_FIREBASE_API_KEY", "VITE_FIREBASE_AUTH_DOMAIN", "VITE_FIREBASE_PROJECT_ID", "VITE_FIREBASE_APP_ID")


def fetch(route):
    request = Request(ORIGIN + route, headers={"User-Agent": "CommentMAS-Release-Check"})
    with urlopen(request, timeout=30) as response:
        if response.geturl() != request.full_url:
            raise ValueError(f"Unexpected redirect for {route}")
        return response.read()


def verify(data, expected, route):
    if sha256(data).hexdigest() != expected:
        raise ValueError(f"Published release differs at {route}")
    return data


def read_manifest():
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    routes = manifest["assets"]
    if (manifest["origin"] != ORIGIN or "/" not in routes or manifest["entry_script"] not in routes
            or any(r != "/" and not re.fullmatch(r"/assets/[\w.-]+", r) for r in routes)):
        raise ValueError("Invalid presentation manifest.")
    return manifest


def public_build_environment(manifest):
    env = os.environ.copy()
    if all(env.get(name) for name in FIELDS):
        return env
    route = manifest["entry_script"]
    script = verify(fetch(route), manifest["assets"][route], route)
    # The four literals are the Firebase web configuration in this specific release.
    # Verify the script first so a newer or unexpected build cannot choose the settings.
    config = re.search(rb'\{apiKey:"([^"]+)",authDomain:"([^"]+)",projectId:"([^"]+)",appId:"([^"]+)"\}', script)
    if not config:
        raise ValueError("Provide the four VITE_FIREBASE_* settings for the recorded release.")
    env.update(dict(zip(FIELDS, (value.decode("ascii") for value in config.groups()))))
    return env


def check_dist(routes):
    dist = FRONTEND / "dist"
    if not (dist / "index.html").is_file():
        raise ValueError("No built client found. Run the build command first.")
    actual = {("/" if f == dist / "index.html" else "/" + f.relative_to(dist).as_posix()): f
              for f in dist.rglob("*") if f.is_file()}
    if set(actual) != set(routes):
        difference = sorted(set(actual).symmetric_difference(routes))
        raise ValueError("Build paths differ from the recorded release: " + ", ".join(difference))
    for route, path in actual.items():
        verify(path.read_bytes(), routes[route], route)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "check-dist", "verify-live"))
    action = parser.parse_args().action
    manifest = read_manifest()
    routes = manifest["assets"]
    if action == "verify-live":
        def check_route(route):
            verify(fetch(route), routes[route], route)
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(check_route, routes))
    else:
        if action == "build":
            npm = shutil.which("npm")
            if not npm:
                raise ValueError("Install Node.js 22.12 or later and npm first.")
            subprocess.run([npm, "run", "build"], cwd=FRONTEND, env=public_build_environment(manifest), check=True)
        check_dist(routes)
    print(f"{action}: all {len(routes)} files match the {manifest['captured']} presentation.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error)) from None
