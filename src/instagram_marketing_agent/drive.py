"""Google Drive: reading the content library, and writing screenshots back to it.

Reading a public file needs no credentials -- the inventory's links are shared.
Writing does: a screenshot folder is created in the user's own Drive, so the
upload half needs an OAuth refresh token and does nothing without one.

Spoken over httpx rather than google-api-python-client: four endpoints, and the
SDK would pull a dependency tree in for them.
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import time
from pathlib import Path

import httpx

from .config import load_dotenv

DRIVE_API = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
TOKEN_URL = "https://oauth2.googleapis.com/token"
FOLDER_MIME = "application/vnd.google-apps.folder"

CLIENT_ID_ENV = "GOOGLE_OAUTH_CLIENT_ID"
CLIENT_SECRET_ENV = "GOOGLE_OAUTH_CLIENT_SECRET"
REFRESH_TOKEN_ENV = "GOOGLE_OAUTH_REFRESH_TOKEN"

_FILE_ID = re.compile(r"/file/d/([\w-]+)|/folders/([\w-]+)|[?&]id=([\w-]+)")

# One access token serves a whole run; exchanging the refresh token per upload
# would be a round trip for every screenshot.
_token: tuple[str, float] | None = None


def file_id(url: str) -> str:
    """The file id out of a Drive link, in any of the shapes one comes in."""
    found = _FILE_ID.search(url or "")
    if not found:
        raise ValueError(f"no Drive file id in {url!r}")
    return next(group for group in found.groups() if group)


async def download(client: httpx.AsyncClient, drive_url: str) -> bytes:
    """Fetch one public Drive file.

    Goes straight to the download host with `confirm=t`: the /uc endpoint
    answers a large file with an HTML interstitial instead of the bytes, and a
    photograph off a phone -- let alone a video -- is big enough to hit it.
    """
    identifier = file_id(drive_url)
    response = await client.get(
        "https://drive.usercontent.google.com/download",
        params={"id": identifier, "export": "download", "confirm": "t"},
        follow_redirects=True,
    )
    response.raise_for_status()
    if response.headers.get("content-type", "").startswith("text/html"):
        raise RuntimeError(
            f"Drive returned a web page rather than the file for {identifier} -- "
            f"it is probably not shared publicly"
        )
    return response.content


def _credential(name: str) -> str:
    load_dotenv()
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"{name} is not set, so screenshots cannot be uploaded to Drive. "
            f"Uploading needs {CLIENT_ID_ENV}, {CLIENT_SECRET_ENV} and "
            f"{REFRESH_TOKEN_ENV} in .env; the refresh token comes from running "
            f"the OAuth consent flow once for the drive scope -- drive.file is "
            f"not enough, because the screenshots go beside a video this app "
            f"did not upload."
        )
    return value


async def access_token(client: httpx.AsyncClient) -> str:
    """A bearer token for the user's Drive, cached until it is nearly stale."""
    global _token
    if _token and _token[1] > time.time():
        return _token[0]

    response = await client.post(
        TOKEN_URL,
        data={
            "client_id": _credential(CLIENT_ID_ENV),
            "client_secret": _credential(CLIENT_SECRET_ENV),
            "refresh_token": _credential(REFRESH_TOKEN_ENV),
            "grant_type": "refresh_token",
        },
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Drive refused the refresh token ({response.status_code}): "
            f"{response.text.strip()[:300]}"
        )
    payload = response.json()
    # A minute of slack, so a token cannot expire between the check and the use.
    _token = (payload["access_token"], time.time() + payload.get("expires_in", 3600) - 60)
    return _token[0]


def folder_link(folder_id: str) -> str:
    """The address a person opens to see the folder."""
    return f"https://drive.google.com/drive/folders/{folder_id}"


async def _find_folder(
    client: httpx.AsyncClient, token: str, name: str, parent: str | None
) -> str | None:
    """An existing folder of that name, so a re-run reuses it."""
    escaped = name.replace("\\", "\\\\").replace("'", "\\'")
    query = (
        f"name = '{escaped}' and mimeType = '{FOLDER_MIME}' and trashed = false"
        + (f" and '{parent}' in parents" if parent else "")
    )
    response = await client.get(
        f"{DRIVE_API}/files",
        params={
            "q": query,
            "fields": "files(id)",
            "pageSize": 1,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Drive search failed ({response.status_code}): "
            f"{response.text.strip()[:300]}"
        )
    files = response.json().get("files") or []
    return files[0]["id"] if files else None


async def parent_of(client: httpx.AsyncClient, url_or_id: str) -> str:
    """The folder a Drive file sits in.

    Read rather than configured, so a screenshot folder is created beside the
    clip it came from and the library keeps its own shape.
    """
    token = await access_token(client)
    identifier = file_id(url_or_id) if "/" in url_or_id else url_or_id
    response = await client.get(
        f"{DRIVE_API}/files/{identifier}",
        params={"fields": "parents", "supportsAllDrives": "true"},
        headers={"Authorization": f"Bearer {token}"},
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"could not read where {identifier} lives ({response.status_code}): "
            f"{response.text.strip()[:300]}"
        )
    parents = response.json().get("parents") or []
    if not parents:
        raise RuntimeError(
            f"{identifier} reports no parent folder, so there is nowhere beside "
            f"it to put the screenshots"
        )
    return parents[0]


async def public_folder(
    client: httpx.AsyncClient, name: str, parent: str
) -> tuple[str, str]:
    """The id and link of a link-readable folder called `name` inside `parent`.

    Shared as anyone-with-the-link: the index is read by people and tools that
    have the spreadsheet, not a Drive account each.
    """
    token = await access_token(client)
    found = await _find_folder(client, token, name, parent)
    if found:
        return found, folder_link(found)

    response = await client.post(
        f"{DRIVE_API}/files",
        params={"fields": "id", "supportsAllDrives": "true"},
        headers={"Authorization": f"Bearer {token}"},
        json={"name": name, "mimeType": FOLDER_MIME, "parents": [parent]},
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Drive would not create the folder {name!r} "
            f"({response.status_code}): {response.text.strip()[:300]}"
        )
    folder = response.json()["id"]

    shared = await client.post(
        f"{DRIVE_API}/files/{folder}/permissions",
        params={"supportsAllDrives": "true"},
        headers={"Authorization": f"Bearer {token}"},
        json={"role": "reader", "type": "anyone"},
    )
    if shared.status_code >= 400:
        raise RuntimeError(
            f"the folder {name!r} was created but could not be shared "
            f"({shared.status_code}): {shared.text.strip()[:300]}"
        )
    return folder, folder_link(folder)


async def upload(client: httpx.AsyncClient, path: Path, parent_id: str) -> str:
    """Put one file in a folder and return its id."""
    token = await access_token(client)
    metadata = {"name": path.name, "parents": [parent_id]}
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    boundary = "instagram-marketing-agent"
    body = (
        f"--{boundary}\r\n"
        "Content-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{json.dumps(metadata)}\r\n"
        f"--{boundary}\r\n"
        f"Content-Type: {media_type}\r\n\r\n"
    ).encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()

    response = await client.post(
        DRIVE_UPLOAD,
        params={
            "uploadType": "multipart",
            "fields": "id",
            "supportsAllDrives": "true",
        },
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/related; boundary={boundary}",
        },
        content=body,
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Drive would not accept {path.name} ({response.status_code}): "
            f"{response.text.strip()[:300]}"
        )
    return response.json()["id"]
