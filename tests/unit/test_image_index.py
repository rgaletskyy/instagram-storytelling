"""Cataloguing the image library: what is read, what is skipped, what is written."""

import asyncio
import io

import pytest
from openpyxl import Workbook, load_workbook
from PIL import Image

from instagram_marketing_agent import image_index
from instagram_marketing_agent.image_index import (
    COLUMNS,
    EMPTY,
    INDEX_SHEET,
    INVENTORY_SHEET,
    PARALLELISM,
    ImageFacts,
    drive_file_id,
    read_inventory,
)

pytestmark = pytest.mark.unit

DRIVE = "https://drive.google.com/file/d/{}/view?usp=drivesdk"


def _inventory(tmp_path, rows):
    """An inventory in the real one's shape: links live in the cell, not the text."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = INVENTORY_SHEET
    sheet.append(
        ["#", "Папка (верхній рівень)", "Шлях", "Файл", "Тип", "Розмір, KB",
         "Дата зміни", "Локальний файл", "Google Drive", "Рекомендовано (пілот)"]
    )
    for number, (folder, name, kind, recommended, file_id) in enumerate(rows, 1):
        sheet.append(
            [number, folder, f"{folder}/{name}", name, kind, 100.5, "2024-06-11",
             "Відкрити", "Відкрити", recommended]
        )
        sheet.cell(row=number + 1, column=8).hyperlink = f"file:///G:/{folder}/{name}"
        sheet.cell(row=number + 1, column=9).hyperlink = DRIVE.format(file_id)

    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "index_inventory.xlsx"
    workbook.save(path)
    return path


@pytest.fixture
def indexed(monkeypatch):
    """Stand in for Drive and the vision model; record what each was asked for."""
    seen = {"downloads": [], "described": 0}

    async def fake_download(client, url):
        seen["downloads"].append(url)
        buffer = io.BytesIO()
        Image.new("RGB", (64, 64), "red").save(buffer, "JPEG")
        return buffer.getvalue()

    async def fake_describe(image, model=None):
        seen["described"] += 1
        return ImageFacts(
            description="Рудий пес на дивані",
            breed="такса",
            tags=["собака", "такса", "лайфстайл"],
            kind="лайфстайл",
        )

    monkeypatch.setattr(image_index, "download", fake_download)
    monkeypatch.setattr(image_index, "describe", fake_describe)
    return seen


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://drive.google.com/file/d/1zfNagl-Ut1U/view?usp=drivesdk", "1zfNagl-Ut1U"),
        ("https://drive.google.com/uc?export=download&id=1KDImHUh25", "1KDImHUh25"),
        ("https://drive.google.com/open?id=1sLDqCZ&authuser=0", "1sLDqCZ"),
    ],
)
def test_the_file_id_is_read_out_of_either_link_shape(url, expected):
    assert drive_file_id(url) == expected


def test_a_link_with_no_id_is_refused():
    with pytest.raises(ValueError, match="no Drive file id"):
        drive_file_id("https://example.com/photo.jpg")


def test_only_recommended_images_are_read_by_default(tmp_path):
    inventory = _inventory(
        tmp_path,
        [
            ("Grooming", "a.jpg", "зображення", "так", "id_a"),
            ("Grooming", "b.jpg", "зображення", None, "id_b"),
            ("Grooming", "clip.mp4", "відео", "так", "id_c"),
        ],
    )

    assert [r.file for r in read_inventory(inventory)] == ["a.jpg"]
    assert [r.file for r in read_inventory(inventory, only_recommended=False)] == [
        "a.jpg",
        "b.jpg",
    ]


def test_video_and_stray_files_are_never_read(tmp_path):
    """The inventory's own type column, and the extension, both have to agree."""
    inventory = _inventory(
        tmp_path,
        [
            ("B2B", "clip.mp4", "відео", "так", "id_a"),
            ("B2B", "notes.pdf", "зображення", "так", "id_b"),
            ("B2B", "photo.HEIC", "зображення", "так", "id_c"),
        ],
    )

    assert [r.file for r in read_inventory(inventory)] == ["photo.HEIC"]


def test_a_folder_can_be_picked_out(tmp_path):
    inventory = _inventory(
        tmp_path,
        [
            ("Dogs_from_Grooming", "a.jpg", "зображення", "так", "id_a"),
            ("B2B-партнери", "b.jpg", "зображення", "так", "id_b"),
        ],
    )

    rows = read_inventory(inventory, folder="grooming")
    assert [r.file for r in rows] == ["a.jpg"]
    assert rows[0].drive_url == DRIVE.format("id_a")


async def test_the_index_is_written_in_the_pilot_shape(tmp_path, indexed):
    inventory = _inventory(
        tmp_path, [("Grooming", "a.jpg", "зображення", "так", "id_a")]
    )
    out = tmp_path / "images_index.xlsx"

    count, failures = await image_index.build_index(inventory, out)

    assert (count, failures) == (1, [])
    sheet = load_workbook(out)[INDEX_SHEET]
    assert [c.value for c in sheet[1]] == list(COLUMNS)
    written = [c.value for c in sheet[2]]
    assert written[1:3] == ["a.jpg", "Grooming"]
    assert written[5] == "Рудий пес на дивані"
    # Absent fields carry the pilot's dash rather than an empty cell.
    assert written[6] == EMPTY and written[7] == EMPTY
    assert written[9] == "собака, такса, лайфстайл"
    # The link columns stay clickable, as they are in the inventory.
    assert sheet.cell(row=2, column=5).hyperlink.target == DRIVE.format("id_a")


async def test_a_name_already_in_the_index_is_skipped_whatever_its_folder(
    tmp_path, indexed
):
    """Matching is on 'Файл' alone, so the same name elsewhere counts as done."""
    first = _inventory(
        tmp_path / "one", [("Grooming", "IMG_0830.HEIC", "зображення", "так", "id_a")]
    )
    second = _inventory(
        tmp_path / "two", [("UGC", "IMG_0830.HEIC", "зображення", "так", "id_b")]
    )
    out = tmp_path / "images_index.xlsx"

    assert (await image_index.build_index(first, out))[0] == 1
    assert (await image_index.build_index(second, out))[0] == 0
    assert indexed["described"] == 1


async def test_one_name_twice_in_a_run_is_described_once(tmp_path, indexed):
    """237 filenames repeat in the real inventory, mostly between subfolders."""
    inventory = _inventory(
        tmp_path,
        [
            ("Сток", "1.jpg", "зображення", "так", "id_a"),
            ("Сток", "1.jpg", "зображення", "так", "id_b"),
            ("Сток", "2.jpg", "зображення", "так", "id_c"),
        ],
    )
    out = tmp_path / "images_index.xlsx"

    count, _ = await image_index.build_index(inventory, out)

    assert count == 2
    assert [c.value for c in load_workbook(out)[INDEX_SHEET]["B"]][1:] == [
        "1.jpg",
        "2.jpg",
    ]


def test_the_file_column_is_found_by_its_header_not_its_position(tmp_path):
    """A re-ordered or hand-edited index must not be matched on the wrong column."""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = INDEX_SHEET
    sheet.append(["Файл", "#", "Папка", "Опис"])
    sheet.append(["a.jpg", 1, "Grooming", "опис"])
    out = tmp_path / "images_index.xlsx"
    workbook.save(out)

    assert image_index.indexed_filenames(out) == {"a.jpg"}


def test_an_index_without_the_file_column_is_refused(tmp_path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = INDEX_SHEET
    sheet.append(["#", "Папка", "Опис"])
    out = tmp_path / "images_index.xlsx"
    workbook.save(out)

    with pytest.raises(ValueError, match="no 'Файл' column"):
        image_index.indexed_filenames(out)


def test_no_index_yet_means_nothing_is_skipped(tmp_path):
    assert image_index.indexed_filenames(tmp_path / "not-there.xlsx") == set()


async def test_a_second_run_only_describes_what_is_missing(tmp_path, indexed):
    inventory = _inventory(
        tmp_path,
        [
            ("Grooming", "a.jpg", "зображення", "так", "id_a"),
            ("Grooming", "b.jpg", "зображення", "так", "id_b"),
        ],
    )
    out = tmp_path / "images_index.xlsx"

    await image_index.build_index(inventory, out, limit=1)
    assert indexed["described"] == 1

    count, _ = await image_index.build_index(inventory, out)

    assert count == 1
    assert indexed["described"] == 2
    assert load_workbook(out)[INDEX_SHEET].max_row == 3


def test_five_images_run_at_once_by_default():
    assert PARALLELISM == 5


async def test_no_more_than_the_parallelism_are_in_flight(tmp_path, monkeypatch):
    """The ceiling holds across save boundaries, not just within one chunk."""
    inventory = _inventory(
        tmp_path,
        [("Grooming", f"{i}.jpg", "зображення", "так", f"id_{i}") for i in range(12)],
    )
    live = {"now": 0, "peak": 0}

    async def slow_download(client, url):
        live["now"] += 1
        live["peak"] = max(live["peak"], live["now"])
        try:
            await asyncio.sleep(0.01)
            buffer = io.BytesIO()
            Image.new("RGB", (8, 8), "red").save(buffer, "JPEG")
            return buffer.getvalue()
        finally:
            live["now"] -= 1

    async def fake_describe(image, model=None):
        return ImageFacts(description="опис")

    monkeypatch.setattr(image_index, "download", slow_download)
    monkeypatch.setattr(image_index, "describe", fake_describe)

    count, _ = await image_index.build_index(
        inventory, tmp_path / "out.xlsx", parallelism=3
    )

    assert count == 12
    assert live["peak"] == 3


async def test_a_parallelism_above_the_save_cadence_is_not_throttled(
    tmp_path, monkeypatch
):
    """A chunk must never be smaller than what may run at once."""
    inventory = _inventory(
        tmp_path,
        [("Grooming", f"{i}.jpg", "зображення", "так", f"id_{i}") for i in range(16)],
    )
    live = {"now": 0, "peak": 0}

    async def slow_download(client, url):
        live["now"] += 1
        live["peak"] = max(live["peak"], live["now"])
        try:
            await asyncio.sleep(0.01)
            buffer = io.BytesIO()
            Image.new("RGB", (8, 8), "red").save(buffer, "JPEG")
            return buffer.getvalue()
        finally:
            live["now"] -= 1

    async def fake_describe(image, model=None):
        return ImageFacts(description="опис")

    monkeypatch.setattr(image_index, "download", slow_download)
    monkeypatch.setattr(image_index, "describe", fake_describe)

    await image_index.build_index(inventory, tmp_path / "out.xlsx", parallelism=16)

    assert live["peak"] == 16


async def test_a_folder_with_nothing_recommended_says_so(tmp_path, indexed):
    """Six real folders carry no pilot mark; 'already indexed' would be a lie."""
    inventory = _inventory(
        tmp_path,
        [
            ("B2B", "a.jpg", "зображення", None, "id_a"),
            ("B2B", "b.jpg", "зображення", None, "id_b"),
            ("Grooming", "c.jpg", "зображення", "так", "id_c"),
        ],
    )

    with pytest.raises(ValueError, match="none is marked"):
        await image_index.build_index(inventory, tmp_path / "out.xlsx", folder="B2B")

    # ...and --index-all is exactly what the message tells you to reach for.
    count, _ = await image_index.build_index(
        inventory, tmp_path / "out.xlsx", only_recommended=False, folder="B2B"
    )
    assert count == 2


async def test_an_unknown_folder_lists_the_ones_there_are(tmp_path, indexed):
    inventory = _inventory(
        tmp_path, [("Grooming", "a.jpg", "зображення", "так", "id_a")]
    )

    with pytest.raises(ValueError, match="Grooming"):
        await image_index.build_index(inventory, tmp_path / "out.xlsx", folder="Nope")


async def test_an_index_that_is_already_complete_is_not_an_error(tmp_path, indexed):
    """That is the one case the 'nothing left to index' message is for."""
    inventory = _inventory(
        tmp_path, [("Grooming", "a.jpg", "зображення", "так", "id_a")]
    )
    out = tmp_path / "out.xlsx"

    assert await image_index.build_index(inventory, out) == (1, [])
    assert await image_index.build_index(inventory, out) == (0, [])


async def test_a_parallelism_below_one_is_refused(tmp_path):
    inventory = _inventory(
        tmp_path, [("Grooming", "a.jpg", "зображення", "так", "id_a")]
    )
    with pytest.raises(ValueError, match="at least 1"):
        await image_index.build_index(inventory, tmp_path / "out.xlsx", parallelism=0)


async def test_an_image_that_fails_is_reported_and_left_for_next_time(
    tmp_path, indexed, monkeypatch
):
    """No row means a later run retries it, and the failure is never silent."""
    inventory = _inventory(
        tmp_path,
        [
            ("Grooming", "good.jpg", "зображення", "так", "id_a"),
            ("Grooming", "gone.jpg", "зображення", "так", "id_b"),
        ],
    )
    out = tmp_path / "images_index.xlsx"

    async def half_broken(client, url):
        if url.endswith("id_b/view?usp=drivesdk"):
            raise RuntimeError("404 not found")
        buffer = io.BytesIO()
        Image.new("RGB", (64, 64), "red").save(buffer, "JPEG")
        return buffer.getvalue()

    monkeypatch.setattr(image_index, "download", half_broken)
    count, failures = await image_index.build_index(inventory, out)

    assert count == 1
    assert failures and "gone.jpg" in failures[0] and "404" in failures[0]
    assert [c.value for c in load_workbook(out)[INDEX_SHEET][2]][1] == "good.jpg"
