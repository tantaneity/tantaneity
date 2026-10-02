from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

GITHUB_API = "https://api.github.com"
RAW_BASE = "https://raw.githubusercontent.com"
OWNER = "tantaneity"
GENERATOR_SUFFIX = "-gen"
START_MARKER = "<!-- generators:start -->"
END_MARKER = "<!-- generators:end -->"
README_PATH = Path("README.md")
REQUEST_TIMEOUT_SECONDS = 20
REPOS_PER_PAGE = 100
ROW_BUDGET_PERCENT = 96
MIN_IMAGE_PERCENT = 12
MEDIA_PREFIX = "media/"
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp")
MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)")
HTML_IMAGE = re.compile(r"<img[^>]+src=\"([^\"]+)\"")


@dataclass(frozen=True)
class Generator:
    name: str
    url: str
    image: str | None


def fetch_json(path: str) -> Any:
    request = urllib.request.Request(f"{GITHUB_API}{path}")
    request.add_header("Accept", "application/vnd.github+json")
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")

    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return json.load(response)


def read_repo_readme(name: str) -> str:
    try:
        payload = fetch_json(f"/repos/{OWNER}/{name}/readme")
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return ""
        raise

    return base64.b64decode(payload["content"]).decode("utf-8", errors="replace")


def is_image(reference: str) -> bool:
    return reference.lower().split("?")[0].endswith(IMAGE_EXTENSIONS)


def find_lead_image(name: str, branch: str) -> str | None:
    readme = read_repo_readme(name)
    for pattern in (MARKDOWN_IMAGE, HTML_IMAGE):
        for reference in pattern.findall(readme):
            if not is_image(reference):
                continue
            if reference.startswith("http"):
                return reference
            return f"{RAW_BASE}/{OWNER}/{name}/{branch}/{reference.lstrip('./')}"

    return find_media_image(name, branch)


def find_media_image(name: str, branch: str) -> str | None:
    tree = fetch_json(f"/repos/{OWNER}/{name}/git/trees/{branch}?recursive=1").get("tree", [])
    paths = sorted(
        entry["path"] for entry in tree
        if entry["path"].startswith(MEDIA_PREFIX) and is_image(entry["path"])
    )
    return f"{RAW_BASE}/{OWNER}/{name}/{branch}/{paths[0]}" if paths else None


def collect_generators() -> list[Generator]:
    repos = fetch_json(f"/users/{OWNER}/repos?per_page={REPOS_PER_PAGE}&sort=pushed")
    found: list[Generator] = []
    for repo in repos:
        if repo["fork"] or repo["archived"] or not repo["name"].endswith(GENERATOR_SUFFIX):
            continue
        found.append(Generator(
            name=repo["name"],
            url=repo["html_url"],
            image=find_lead_image(repo["name"], repo["default_branch"])
        ))

    return found


def render_block(generators: list[Generator]) -> str:
    shown = [one for one in generators if one.image]
    width = max(MIN_IMAGE_PERCENT, ROW_BUDGET_PERCENT // len(shown)) if shown else 0
    images = " ".join(f'<img src="{one.image}" width="{width}%">' for one in shown)
    links = " · ".join(f"[{one.name}]({one.url})" for one in generators)
    return f"{images}\n\n{links}" if images else links


def replace_block(readme: str, block: str) -> str:
    start = readme.index(START_MARKER) + len(START_MARKER)
    end = readme.index(END_MARKER)
    return readme[:start] + "\n" + block + "\n" + readme[end:]


def main() -> None:
    generators = collect_generators()
    if not generators:
        raise RuntimeError("no generator repositories found")

    README_PATH.write_text(replace_block(README_PATH.read_text(), render_block(generators)))
    print(f"generators: {', '.join(one.name for one in generators)}")


if __name__ == "__main__":
    main()
