"""在摄像头画面旁显示整张卡的填写进度。"""

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from capture_result import chinese_font
from permit_fields import FIELDS, PARTICIPANTS, PARTICIPANT_FIELDS, PERMIT_NUMBER_FIELD, UNIT_REQUIRED_FIELDS


WIDTH = 512
BACKGROUND = (248, 250, 249)
INK = (24, 45, 38)
SECONDARY = (77, 99, 91)
GREEN = (16, 109, 70)
GREEN_LIGHT = (218, 241, 226)
GRAY = (85, 102, 96)
GRAY_LIGHT = (231, 237, 234)

ENGLISH_LABELS = {
    "施工许可信息表": "Permit entry form", "许可证编号": "Permit number",
    "参建单位": "Participants", "其他字段": "Other fields", "已填写": "Filled", "待扫描": "Pending",
    "必填": "Required", "未扫描": "Ready to scan", "缺少必填项 · 待重拍": "Rescan full card",
    "未识别 · 请重拍": "Try again", "已录入": "Recorded", "该编号已录入": "Already recorded",
    "录入失败": "Save failed", "职务": "Role", "姓名": "Name", "证件名称": "Title",
    "发证机构": "Issued by", "发证日期": "Issue date", "建设单位": "Owner", "工程名称": "Project",
    "建设地址": "Address", "建设规模": "Scale", "合同工期": "Contract dates", "合同价格": "Price",
    "备注": "Notes", "勘察单位": "Survey", "设计单位": "Design", "施工单位": "Construction",
    "监理单位": "Supervision", "工程总承包单位": "General contractor",
}


def _fit(text, font, width):
    if font.getlength(text) <= width:
        return text
    while text and font.getlength(text + "…") > width:
        text = text[:-1]
    return text + "…"


def render_form(report, status):
    chinese = chinese_font()
    font = chinese or ImageFont.load_default()
    heading = chinese.font_variant(size=22) if chinese else font
    small = chinese.font_variant(size=12) if chinese else font

    def localize(text):
        if chinese:
            return text
        return ENGLISH_LABELS.get(text, text.encode("ascii", errors="replace").decode("ascii"))

    extra_fields = PARTICIPANT_FIELDS[len(UNIT_REQUIRED_FIELDS):]
    other_fields = [field for field in FIELDS if field != PERMIT_NUMBER_FIELD]
    units_start = 124
    unit_height = 43 + 18 * len(extra_fields)
    other_header = units_start + unit_height * len(PARTICIPANTS)
    height = max(552, other_header + 21 + 18 * len(other_fields) + 10)
    image = Image.new("RGB", (WIDTH, height), BACKGROUND)
    draw = ImageDraw.Draw(image)

    def field_cell(label, value, x, y, width, label_width):
        filled = value is not None
        badge_x = x + width - 44
        color, background = (GREEN, GREEN_LIGHT) if filled else (GRAY, GRAY_LIGHT)
        draw.text((x, y), _fit(localize(label), font, label_width - 4), font=font, fill=SECONDARY)
        if filled:
            display = localize(str(value))
            draw.text((x + label_width, y), _fit(display, font, badge_x - x - label_width - 5), font=font, fill=INK)
        draw.rounded_rectangle((badge_x, y + 1, x + width, y + 17), radius=5, fill=background)
        caption = localize("已填写" if filled else "待扫描")
        caption_x = badge_x + (44 - small.getlength(caption)) / 2
        draw.text((caption_x, y + 1), caption, font=small, fill=color)

    total = len(FIELDS) + len(PARTICIPANTS) * len(PARTICIPANT_FIELDS)
    draw.text((16, 9), localize("施工许可信息表"), font=heading, fill=INK)
    status_color, status_background = GRAY, GRAY_LIGHT
    if status.entered_at:
        status_color, status_background = GREEN, GREEN_LIGHT
    elif status.label == "录入失败":
        status_color, status_background = (154, 55, 48), (251, 231, 228)
    elif status.label != "未扫描":
        status_color, status_background = (128, 83, 25), (251, 239, 213)
    caption = localize(status.label)
    draw.rounded_rectangle((342, 10, 496, 37), radius=8, fill=status_background)
    draw.text((342 + (154 - font.getlength(caption)) / 2, 13), caption, font=font, fill=status_color)
    progress = f"{localize('必填')} {status.filled}/{status.total}    {localize('已填写')} {total - len(report['未识别字段'])}/{total}"
    draw.text((16, 40), progress, font=small, fill=SECONDARY)
    if status.entered_at:
        time = status.entered_at.replace("T", " ")[:19]
        draw.text((496 - small.getlength(time), 40), time, font=small, fill=SECONDARY)
    draw.rounded_rectangle((16, 59, 496, 63), radius=2, fill=GRAY_LIGHT)
    if status.filled:
        draw.rounded_rectangle((16, 59, 16 + round(480 * status.filled / status.total), 63), radius=2, fill=GREEN)

    field_cell("许可证编号", report[PERMIT_NUMBER_FIELD], 16, 73, 480, 116)
    draw.text((16, 101), localize("参建单位"), font=font, fill=GREEN)
    y = units_start
    for unit in PARTICIPANTS:
        unit_fields = report["参建单位"][unit]
        field_cell(unit, unit_fields["单位名称"], 16, y, 480, 116)
        field_cell("职务", unit_fields["职务"], 132, y + 19, 199, 37)
        field_cell("姓名", unit_fields["姓名"], 344, y + 19, 152, 37)
        for offset, field in enumerate(extra_fields):
            field_cell(field, unit_fields[field], 132, y + 38 + offset * 18, 364, 88)
        y += unit_height
        draw.line((16, y - 3, 496, y - 3), fill=GRAY_LIGHT)

    draw.text((16, other_header), localize("其他字段"), font=font, fill=GREEN)
    for index, field in enumerate(other_fields):
        field_cell(field, report[field], 16, other_header + 21 + 18 * index, 480, 116)
    return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
