"""将本次抓拍的重要字段标在照片上，并列出提取值。"""

import os
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from permit_fields import FIELDS, JSON_ONLY_FIELDS, PARTICIPANTS, PARTICIPANT_FIELDS


BOX_COLOR = (62, 167, 16)
PHOTO_WIDTH = 544
PHOTO_HEIGHT = 608
PANEL_WIDTH = 412


@lru_cache(maxsize=1)
def chinese_font():
    windows_fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    neighboring_font = Path(__file__).resolve().parents[1] / "Fire_Seg" / "Arial-Unicode.ttf"
    candidates = (
        Path(__file__).resolve().parent / "fonts" / "SourceHanSansCN-Regular.otf",
        windows_fonts / "msyh.ttc",
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
        Path("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"),
        neighboring_font,
    )
    for path in candidates:
        try:
            return ImageFont.truetype(str(path), 15)
        except OSError:
            continue
    return None


def _field_rows(readings):
    for label in FIELDS:
        reading = readings.get((label,))
        if reading:
            yield label, [reading.value]

    for unit in PARTICIPANTS:
        company, role, name = (readings.get((unit, field)) for field in PARTICIPANT_FIELDS[:3])
        person = " ".join(reading.value for reading in (role, name) if reading)
        values = [value for value in (company.value if company else "", person) if value]
        for field in PARTICIPANT_FIELDS[3:]:
            extra = readings.get((unit, field))
            if extra:
                values.append(f"{field} {extra.value}")
        if values:
            yield unit, values


def _wrap(value, font, width):
    line = ""
    for char in value:
        if line and font.getlength(line + char) > width:
            yield line
            line = ""
        line += char
    if line:
        yield line


def _panel(readings, min_height):
    font = chinese_font()
    if font is None:
        font = title_font = ImageFont.load_default()
        title = "Important fields"
        rows = [("Found", [str(len(readings))]), ("Details", ["See terminal or JSON"])]
    else:
        title_font = font.font_variant(size=22)
        title = f"本次抓拍 · {len(readings)} 项重要字段"
        rows = list(_field_rows(readings)) or [("结果", ["未识别到重要字段"])]

    label_x, value_x, right = 16, 132, PANEL_WIDTH - 16
    line_height, row_padding, first_row = 21, 5, 53
    layout = [
        (list(_wrap(label, font, value_x - label_x - 9)),
         [line for value in values for line in _wrap(value, font, right - value_x)])
        for label, values in rows
    ]
    row_heights = [max(len(labels), len(lines)) * line_height + row_padding for labels, lines in layout]
    height = max(min_height, first_row + 10 + sum(row_heights))
    image = Image.new("RGB", (PANEL_WIDTH, height), (249, 251, 250))
    draw = ImageDraw.Draw(image)
    draw.text((label_x, 13), title, font=title_font, fill=(20, 64, 53))
    draw.line((label_x, 45, right, 45), fill=(205, 221, 215))
    y = first_row
    for (labels, lines), row_height in zip(layout, row_heights):
        for index, label in enumerate(labels):
            draw.text((label_x, y + index * line_height), label, font=font, fill=(71, 92, 86))
        for index, line in enumerate(lines):
            draw.text((value_x, y + index * line_height), line, font=font, fill=(25, 40, 36))
        y += row_height
    return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)


def render_capture(frame, readings):
    important = {
        field: reading for field, reading in readings.items()
        if len(field) > 1 or field[0] not in JSON_ONLY_FIELDS
    }
    height, width = frame.shape[:2]
    scale = min(1.0, PHOTO_WIDTH / width, PHOTO_HEIGHT / height)
    photo_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    photo = cv2.resize(frame, photo_size, interpolation=cv2.INTER_AREA)
    ratio = np.array(photo_size) / (width, height)

    # 同一字段或同一行的多个结果可能引用同一文字框。
    quads = {
        tuple(tuple(point) for point in block.box)
        for reading in important.values()
        for block in reading.boxes
    }
    for quad in quads:
        points = np.rint(np.asarray(quad) * ratio).astype(np.int32)
        cv2.polylines(photo, [points], True, BOX_COLOR, 2, cv2.LINE_AA)

    margin = 12
    panel = _panel(important, photo_size[1] + 2 * margin)
    canvas = np.full((panel.shape[0], PHOTO_WIDTH + 2 * margin + PANEL_WIDTH, 3), (32, 39, 35), dtype=np.uint8)
    x = (PHOTO_WIDTH + 2 * margin - photo_size[0]) // 2
    y = (panel.shape[0] - photo_size[1]) // 2
    canvas[y:y + photo_size[1], x:x + photo_size[0]] = photo
    canvas[:, -PANEL_WIDTH:] = panel
    return canvas, photo
