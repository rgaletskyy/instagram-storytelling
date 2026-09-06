"""Catalogue the image library.

Reads the inventory of the Drive folder, downloads each photo by its Drive
link, looks at it, and writes a searchable index in the shape of
`index_pilot.xlsx` -- the same thirteen columns, filled in Ukrainian.

A separate tool from the campaign pipeline: nothing here generates anything, and
it runs over thousands of files rather than the handful in `content/input/`.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import httpx
from openpyxl import Workbook, load_workbook
from pydantic import BaseModel, Field

from . import llm
from .config import (
    CLAUDE_DESCRIBE_MODEL,
    DEEPSEEK_MODEL_PREFIX,
    DESCRIBE_MODEL,
    IMAGE_SUFFIXES,
    RESOURCES_DIR,
)

logger = logging.getLogger(__name__)

INDEX_DIR = RESOURCES_DIR / "images_index"
INVENTORY_FILE = INDEX_DIR / "index_inventory.xlsx"
OUTPUT_FILE = INDEX_DIR / "images_index.xlsx"

INVENTORY_SHEET = "Повний список"
INDEX_SHEET = "Індекс"

# The columns of index_pilot.xlsx, in its order. The first five and the last are
# carried over from the inventory; the seven in between are what the model adds.
COLUMNS = (
    "#",
    "Файл",
    "Папка",
    "Локальний шлях",
    "Google Drive",
    "Опис",
    "Продукт",
    "Бренд",
    "Порода",
    "Теги",
    "Тип",
    "Текст на фото",
    "Розмір, KB",
)
# What the pilot writes in a field that does not apply.
EMPTY = "—"
LINK_LABEL = "Відкрити"

# Rows the inventory marks as images; the rest are video and stray files.
IMAGE_KIND = "зображення"
RECOMMENDED = "так"

# Images in flight at once. Each one is a download plus a vision call, and the
# library runs to thousands of files, so the ceiling is about not opening three
# thousand sockets at once rather than about speed.
PARALLELISM = 5
# One description is long by design -- it is what a later step matches a brief
# against -- and adaptive thinking shares the budget with it.
DESCRIBE_MAX_TOKENS = 6000
# Rows written per save. A run over the full library takes hours; saving as it
# goes means an interrupted one keeps what it had already described. A save is
# a barrier, so a chunk never holds fewer images than may run at once.
BATCH = 10

_DRIVE_ID = re.compile(r"/file/d/([\w-]+)|[?&]id=([\w-]+)")


class ImageFacts(BaseModel):
    """What the model reads off one photograph, one field per index column."""

    description: str = ""
    product: str = ""
    brand: str = ""
    breed: str = ""
    tags: list[str] = Field(default_factory=list)
    kind: str = ""
    text_in_image: str = ""


@dataclass(frozen=True)
class InventoryRow:
    """One file as the inventory lists it."""

    number: int
    file: str
    folder: str
    path: str
    local_url: str
    drive_url: str
    size_kb: float | None

    @property
    def key(self) -> str:
        """What an already-indexed image is recognised by: the 'Файл' column.

        Not unique in the inventory -- 237 filenames repeat, mostly between
        subfolders of one top-level folder -- so the first row to carry a name
        is the one that gets described and the rest are skipped as duplicates.
        """
        return self.file


def _cell_link(cell) -> str:
    """The URL behind a cell. The text is only ever the word 'Відкрити'."""
    return cell.hyperlink.target if cell.hyperlink else ""


def read_inventory(
    inventory: Path = INVENTORY_FILE,
    only_recommended: bool = True,
    folder: str | None = None,
) -> list[InventoryRow]:
    """The image rows of the inventory, in its own order."""
    if not inventory.exists():
        raise FileNotFoundError(f"no inventory at {inventory}")

    workbook = load_workbook(inventory)
    if INVENTORY_SHEET not in workbook.sheetnames:
        raise ValueError(
            f"{inventory.name} has no sheet {INVENTORY_SHEET!r}; "
            f"it has {workbook.sheetnames}"
        )
    sheet = workbook[INVENTORY_SHEET]

    rows: list[InventoryRow] = []
    for number in range(2, sheet.max_row + 1):
        kind = sheet.cell(row=number, column=5).value
        if kind != IMAGE_KIND:
            continue
        if only_recommended and sheet.cell(row=number, column=10).value != RECOMMENDED:
            continue
        top_folder = str(sheet.cell(row=number, column=2).value or "")
        if folder and folder.lower() not in top_folder.lower():
            continue

        name = str(sheet.cell(row=number, column=4).value or "")
        if Path(name).suffix.lower() not in IMAGE_SUFFIXES:
            # The inventory calls it an image; the extension says otherwise, and
            # the vision API goes by what the bytes actually are.
            logger.warning("skipping %s: not an image extension", name)
            continue

        size = sheet.cell(row=number, column=6).value
        rows.append(
            InventoryRow(
                number=int(sheet.cell(row=number, column=1).value or number - 1),
                file=name,
                folder=top_folder,
                path=str(sheet.cell(row=number, column=3).value or ""),
                local_url=_cell_link(sheet.cell(row=number, column=8)),
                drive_url=_cell_link(sheet.cell(row=number, column=9)),
                size_kb=float(size) if size not in (None, "") else None,
            )
        )
    workbook.close()
    return rows


def drive_file_id(url: str) -> str:
    """The file id out of a Drive link, in either shape it comes in."""
    found = _DRIVE_ID.search(url or "")
    if not found:
        raise ValueError(f"no Drive file id in {url!r}")
    return found.group(1) or found.group(2)


async def download(client: httpx.AsyncClient, drive_url: str) -> bytes:
    """Fetch one public Drive file.

    Goes straight to the download host with `confirm=t`: the /uc endpoint
    answers a large file with an HTML interstitial instead of the bytes, and
    photographs off a phone are big enough to hit it.
    """
    file_id = drive_file_id(drive_url)
    response = await client.get(
        "https://drive.usercontent.google.com/download",
        params={"id": file_id, "export": "download", "confirm": "t"},
        follow_redirects=True,
    )
    response.raise_for_status()
    if response.headers.get("content-type", "").startswith("text/html"):
        raise RuntimeError(
            f"Drive returned a web page rather than the file for {file_id} -- "
            f"it is probably not shared publicly"
        )
    return response.content


def _instructions() -> str:
    """What to write about one photograph.

    The description is not read by a person browsing the library -- it is what a
    later step matches a brief against when it picks images for a post. So it
    has to carry everything that is actually in the frame, in plain declarative
    Ukrainian: whatever goes unsaid here is invisible to that choice.
    """
    return (
        "Опиши це фото для внутрішнього каталогу контенту бренду HealthyDoggo "
        "(зоотовари, догляд за собаками). Відповідай ВИКЛЮЧНО українською.\n\n"
        "Опис читатиме не людина, а програма, яка за ним автоматично добирає "
        "фото під тему майбутнього допису. Тому опиши МАКСИМАЛЬНО детально "
        "все, що реально видно в кадрі: те, чого ти не назвеш, для добору не "
        "існує. Пиши фактами, без реклами й без оцінок на кшталт 'гарне фото'. "
        "Не вигадуй нічого, чого не видно, і не здогадуйся про те, що поза "
        "кадром.\n\n"
        "description — суцільний текст на 6-10 речень, який послідовно "
        "покриває:\n"
        "1. Тварина: скільки тварин, вид, порода, розмір і вік на вигляд "
        "(цуценя/доросла/стара), колір і тип шерсті, стрижка, поза (стоїть, "
        "сидить, лежить, біжить, спить), куди дивиться, вираз морди, язик, "
        "вуха, хвіст, аксесуари — нашийник, шлея, бандана, повідець, одяг.\n"
        "2. Люди: скільки, стать і приблизний вік на вигляд, що саме роблять, "
        "чи видно обличчя чи лише руки, одяг і його кольори, взаємодія з "
        "твариною (тримає, гладить, годує, купає, грає).\n"
        "3. Товар: яка саме упаковка (банка, пакет, тюбик, пляшка, коробка), "
        "її колір і форма, як вона розміщена (в руках, на столі, поряд із "
        "твариною), чи читається етикетка.\n"
        "4. Місце й обстановка: приміщення чи вулиця, яка саме кімната або "
        "локація, меблі, підлога й покриття, стіни й фон, рослини, іграшки, "
        "миски, реквізит, пора року й погода, якщо вони видні.\n"
        "5. Світло й колір: денне чи студійне, м'яке чи контрастне, звідки "
        "падає, тепле чи холодне, домінуючі кольори кадру, загальна яскравість "
        "(світле/темне фото).\n"
        "6. Кадр і композиція: план (крупний, середній, загальний), ракурс "
        "(на рівні очей, зверху, знизу), орієнтація (вертикальна, "
        "горизонтальна, квадратна), де в кадрі головний об'єкт і з якого боку "
        "залишається вільний простір, куди можна покласти текст.\n"
        "7. Технічний стан: різкість, розмиття, шум, засвітлення, чи кадр "
        "обрізаний, чи є водяний знак, логотип або сторонні написи.\n\n"
        "product — назва товару, якщо його видно на фото (банка, пакет, тюбик "
        "із читабельним маркуванням). Порожньо, якщо товару немає.\n"
        "brand — бренд на упаковці, якщо його видно й можна прочитати. "
        "Не вгадуй.\n"
        "breed — порода собаки (або іншої тварини) в кадрі. Порожньо, якщо "
        "тварини немає або порода не впізнається.\n"
        "tags — 10-18 коротких ключових слів для пошуку, кожне окремим "
        "елементом: вид і порода тварини, вік, колір шерсті, дія, люди, "
        "локація, реквізит, пора року, світло, план зйомки, орієнтація кадру, "
        "настрій, наявність вільного місця під текст.\n"
        "kind — одне слово, що це за кадр: 'лайфстайл' (жива сцена з "
        "твариною чи людиною), 'продуктове' (товар як головний об'єкт), "
        "'креатив' (банер, колаж, макет із версткою), 'скріншот' "
        "(знімок екрана, переписка, відгук), 'інше'.\n"
        "text_in_image — текст, який видно НА фото (напис, підпис, цінник, "
        "текст на упаковці), дослівно. Порожньо, якщо тексту немає.\n\n"
        "Порожнє поле залишай порожнім рядком — не вигадуй і не пиши "
        "'невідомо'."
    )


async def describe(image: Path, model: str = DESCRIBE_MODEL) -> ImageFacts:
    """Read one photograph into the index's fields.

    Follows DESCRIBE_MODEL like the rest of the app, so the catalogue can be
    built on whichever vision model is configured.
    """
    if model.startswith(DEEPSEEK_MODEL_PREFIX):
        from .deepseek import describe_json

        data, media_type = llm._api_ready(image)
        payload = await describe_json(
            model=model,
            image=data,
            media_type=media_type,
            prompt=_instructions()
            + "\n\nВідповідь — один json об'єкт із полями: description, "
            "product, brand, breed, tags (масив рядків), kind, text_in_image.",
            max_tokens=DESCRIBE_MAX_TOKENS,
        )
        return ImageFacts.model_validate(payload)

    response = await llm.anthropic_client().messages.parse(
        model=model,
        max_tokens=DESCRIBE_MAX_TOKENS,
        thinking={"type": "adaptive"},
        messages=[
            {
                "role": "user",
                "content": [
                    llm._image_block(image),
                    {"type": "text", "text": _instructions()},
                ],
            }
        ],
        output_format=ImageFacts,
    )
    facts = response.parsed_output
    if facts is None or not facts.description.strip():
        raise RuntimeError(f"no description returned (stop_reason={response.stop_reason})")
    return facts


def _row_values(row: InventoryRow, facts: ImageFacts) -> list:
    """One indexed image, in the pilot's column order."""
    return [
        row.number,
        row.file,
        row.folder,
        LINK_LABEL if row.local_url else EMPTY,
        LINK_LABEL if row.drive_url else EMPTY,
        facts.description.strip() or EMPTY,
        facts.product.strip() or EMPTY,
        facts.brand.strip() or EMPTY,
        facts.breed.strip() or EMPTY,
        ", ".join(t.strip() for t in facts.tags if t.strip()) or EMPTY,
        facts.kind.strip() or EMPTY,
        facts.text_in_image.strip() or EMPTY,
        row.size_kb if row.size_kb is not None else EMPTY,
    ]


def indexed_filenames(out: Path) -> set[str]:
    """Every 'Файл' already in the index, or nothing if there is no index yet."""
    if not out.exists():
        return set()
    workbook = load_workbook(out, read_only=True)
    try:
        return _filenames(workbook[INDEX_SHEET])
    finally:
        workbook.close()


def _filenames(sheet) -> set[str]:
    """The 'Файл' column of an index sheet, found by its header.

    By header rather than by position, so a hand-edited or re-ordered index is
    still read correctly instead of silently matching on the wrong column.
    """
    headers = [cell.value for cell in sheet[1]]
    if "Файл" not in headers:
        raise ValueError(
            f"the index sheet has no 'Файл' column; its headers are {headers}"
        )
    column = headers.index("Файл") + 1
    return {
        str(sheet.cell(row=r, column=column).value).strip()
        for r in range(2, sheet.max_row + 1)
        if sheet.cell(row=r, column=column).value
    }


def open_index(out: Path) -> tuple[Workbook, set[str]]:
    """The index workbook and the filenames already in it.

    An existing file is added to rather than replaced, so a run that stopped
    half way is resumed instead of paying for every description again.
    """
    if out.exists():
        workbook = load_workbook(out)
        return workbook, _filenames(workbook[INDEX_SHEET])

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = INDEX_SHEET
    sheet.append(list(COLUMNS))
    return workbook, set()


def append_row(workbook: Workbook, row: InventoryRow, facts: ImageFacts) -> None:
    """Write one image, keeping the two link columns clickable."""
    sheet = workbook[INDEX_SHEET]
    sheet.append(_row_values(row, facts))
    written = sheet.max_row
    for column, url in ((4, row.local_url), (5, row.drive_url)):
        if url:
            sheet.cell(row=written, column=column).hyperlink = url
            sheet.cell(row=written, column=column).style = "Hyperlink"


async def _index_one(
    client: httpx.AsyncClient, row: InventoryRow, model: str
) -> ImageFacts:
    """Download one image and describe it, cleaning up after itself."""
    data = await download(client, row.drive_url)
    suffix = Path(row.file).suffix or ".jpg"
    handle, name = tempfile.mkstemp(suffix=suffix)
    local = Path(name)
    try:
        with open(handle, "wb") as f:
            f.write(data)
        return await describe(local, model)
    finally:
        local.unlink(missing_ok=True)


def _why_nothing_matched(
    inventory: Path, only_recommended: bool, folder: str | None
) -> str:
    """Say which filter emptied the list, and what to do about it.

    Six of the eleven top-level folders carry no 'Рекомендовано (пілот)' mark at
    all, so asking for one of them without --index-all is the ordinary way to
    end up with nothing, and 'nothing matched' on its own does not explain it.
    """
    everything = read_inventory(inventory, only_recommended=False, folder=folder)
    if everything and only_recommended:
        where = f" under {folder!r}" if folder else ""
        return (
            f"{len(everything)} images are listed{where}, but none is marked "
            f"'{RECOMMENDED}' in the 'Рекомендовано (пілот)' column. Pass "
            f"--index-all to index them anyway."
        )
    if folder:
        known = sorted({r.folder for r in read_inventory(inventory, False)})
        return (
            f"no images in a folder matching {folder!r}. The inventory lists: "
            + ", ".join(known)
        )
    return f"no images listed in {inventory.name}"


async def build_index(
    inventory: Path = INVENTORY_FILE,
    out: Path = OUTPUT_FILE,
    only_recommended: bool = True,
    folder: str | None = None,
    limit: int | None = None,
    model: str = DESCRIBE_MODEL,
    parallelism: int = PARALLELISM,
) -> tuple[int, list[str]]:
    """Describe every image the inventory lists and write them to `out`.

    `parallelism` is how many images are downloaded and described at once.

    Returns how many were indexed and what could not be, so a failure is
    reported rather than left as a gap nobody notices.
    """
    if parallelism < 1:
        raise ValueError(f"parallelism must be at least 1, got {parallelism}")

    rows = read_inventory(inventory, only_recommended, folder)
    if not rows:
        # Distinct from "everything is already indexed", which is what an empty
        # todo list means further down.
        raise ValueError(_why_nothing_matched(inventory, only_recommended, folder))

    workbook, done = open_index(out)

    # A name is claimed as soon as it is queued, so two inventory rows sharing
    # one filename cannot both be described into the index in a single run.
    todo: list[InventoryRow] = []
    seen = set(done)
    for row in rows:
        if row.key in seen:
            continue
        seen.add(row.key)
        todo.append(row)
    skipped = len(rows) - len(todo)

    if limit is not None:
        todo = todo[:limit]

    if not todo:
        if skipped:
            print(
                f"nothing to do: all {skipped} listed images are already in "
                f"{out.name} by filename",
                file=sys.stderr,
            )
        return 0, []

    if skipped:
        print(
            f"skipping {skipped} of {len(rows)} listed images already in "
            f"{out.name} by filename",
            file=sys.stderr,
        )

    out.parent.mkdir(parents=True, exist_ok=True)
    gate = asyncio.Semaphore(parallelism)
    indexed = 0
    failures: list[str] = []

    async def one(client, row):
        async with gate:
            return await _index_one(client, row, model)

    # Long enough for a large photograph on a slow link, bounded so a stalled
    # download cannot hold up a run over thousands of files.
    timeout = httpx.Timeout(180.0, connect=15.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        # Saving between chunks would otherwise throttle a parallelism set
        # higher than the save cadence.
        chunk = max(BATCH, parallelism)
        for start in range(0, len(todo), chunk):
            batch = todo[start : start + chunk]
            results = await asyncio.gather(
                *(one(client, row) for row in batch), return_exceptions=True
            )
            for row, result in zip(batch, results, strict=True):
                if isinstance(result, BaseException):
                    failures.append(f"{row.folder}/{row.file}: {result}")
                    logger.warning("could not index %s: %s", row.file, result)
                    continue
                append_row(workbook, row, result)
                indexed += 1
            workbook.save(out)
            print(
                f"{min(start + chunk, len(todo))}/{len(todo)} "
                f"({indexed} indexed, {len(failures)} failed)",
                file=sys.stderr,
            )
    return indexed, failures


def report(indexed: int, failures: list[str], out: Path) -> int:
    """Say what was written and what could not be, for either entry point."""
    if not indexed and not failures:
        print("nothing left to index -- every listed image is already in it")
        return 0

    print(f"indexed {indexed} images into {out}")
    for failure in failures[:10]:
        print(f"  failed: {failure}", file=sys.stderr)
    if len(failures) > 10:
        print(f"  ...and {len(failures) - 10} more", file=sys.stderr)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="image-index",
        description="Describe the image library into a searchable index.",
    )
    parser.add_argument(
        "--inventory", type=Path, default=INVENTORY_FILE, help="the inventory workbook"
    )
    parser.add_argument(
        "--out", type=Path, default=OUTPUT_FILE, help="the index to write or extend"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="every image in the inventory, not only those marked "
        "'Рекомендовано (пілот)'",
    )
    parser.add_argument(
        "--folder", default=None, help="only images under this top-level folder"
    )
    parser.add_argument(
        "--limit", type=int, default=None, metavar="N", help="stop after N images"
    )
    parser.add_argument(
        "--parallel",
        type=int,
        default=PARALLELISM,
        metavar="N",
        help=f"images downloaded and described at once (default {PARALLELISM})",
    )
    parser.add_argument(
        "--model",
        default=DESCRIBE_MODEL,
        help=f"vision model to describe with (default {DESCRIBE_MODEL}, from "
        f"DESCRIBE_MODEL; unset it to use {CLAUDE_DESCRIBE_MODEL})",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    try:
        indexed, failures = asyncio.run(
            build_index(
                inventory=args.inventory,
                out=args.out,
                only_recommended=not args.all,
                folder=args.folder,
                limit=args.limit,
                model=args.model,
                parallelism=args.parallel,
            )
        )
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    return report(indexed, failures, args.out)


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        raise SystemExit(main())
