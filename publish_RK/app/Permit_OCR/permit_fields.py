"""从施工许可证演示卡的 OCR 文本框提取结构化字段。"""

import re
from dataclasses import dataclass, replace
from functools import cached_property
from typing import List, Tuple
from unicodedata import normalize


# ===== 代码编辑区 · 需要识别并输出到 JSON 的内容 =====
CARD_TITLE = "建筑工程施工许可证"
# 如果希望 JSON 的键叫「许可证编号」，把下一行的值改成该名称即可。
PERMIT_NUMBER_FIELD = "编号"

# 左边是 JSON 字段名，也可以直接作为卡面标签。右边是卡面上可能出现的其他写法。
# 例如新增一项："建设性质": ("工程性质",)，OCR 读到任一标签就会提取对应值。
FIELD_LABELS = {
    PERMIT_NUMBER_FIELD: (
        "编号", "许可证编号", "许可证号", "施工许可证编号", "施工许可证号", "建筑工程施工许可证编号",
    ),
    "发证机构": (),
    "发证日期": (),
    "建设单位": (),
    "工程名称": (),
    "建设地址": (),
    "建设规模": (),
    "合同工期": (),
    "合同价格": (),
    "备注": (),
}

# 参建单位表的每个类别都输出「单位名称」「职务」「姓名」。新类别加在这里。
# 例如："检测单位": ("质量检测单位",)，两种卡面写法会写入同一个 JSON 类别。
PARTICIPANT_LABELS = {
    "勘察单位": (),
    "设计单位": (),
    "施工单位": (),
    "监理单位": (),
    "工程总承包单位": (),
}

# 类别名称在卡面分成两行时，在这里写上、下两段的实际文字。
WRAPPED_UNIT_LABELS = {"工程总承包单位": ("工程总", "承包单位")}

# 参建单位表里的职务标签，其后的值会写入该单位的「姓名」。可以追加新的职务。
ROLES = ("项目负责人", "总监理工程师", "项目经理")

# 参建单位表同一行出现带标签的其他信息时，可以在这里加字段。
# 例如取消下方示例的注释，可提取「联系电话：138…」或表格中「电话」右边的值。
PARTICIPANT_EXTRA_LABELS = {
    # "联系电话": ("电话",),
}

# 许可证编号和每个参建单位的名称、职务、姓名为默认必填项。
# 如需等待更多顶层字段再自动录入，把字段名加在这里，例如 ("工程名称",)。
REQUIRED_EXTRA_FIELDS = ()

# 这里只填顶层 JSON 字段名。这些字段仍会写入 JSON，抓拍画面中省略标注。
JSON_ONLY_FIELDS = {"备注"}
# ===== 代码编辑区结束 =====


def compact_text(text):
    return "".join(normalize("NFKC", text).split())


def labels_to_fields(config):
    return {compact_text(label): field for field, aliases in config.items() for label in (field, *aliases)}


FIELDS = ("证件名称", *FIELD_LABELS)
PARTICIPANTS = tuple(PARTICIPANT_LABELS)
UNIT_REQUIRED_FIELDS = ("单位名称", "职务", "姓名")
PARTICIPANT_FIELDS = (*UNIT_REQUIRED_FIELDS, *PARTICIPANT_EXTRA_LABELS)
REQUIRED_FIELD_PATHS = (
    *((field,) for field in dict.fromkeys((PERMIT_NUMBER_FIELD, *REQUIRED_EXTRA_FIELDS))),
    *((unit, field) for unit in PARTICIPANTS for field in UNIT_REQUIRED_FIELDS),
)
FIELD_BY_LABEL = labels_to_fields(FIELD_LABELS)
UNIT_BY_LABEL = labels_to_fields(PARTICIPANT_LABELS)
EXTRA_BY_LABEL = labels_to_fields(PARTICIPANT_EXTRA_LABELS)
ROLE_BY_LABEL = {compact_text(role): role for role in ROLES}
LABELS = FIELD_BY_LABEL.keys() | UNIT_BY_LABEL.keys() | EXTRA_BY_LABEL.keys() | ROLE_BY_LABEL.keys()
NAME_PATTERN = re.compile(r"[\u3400-\u9fff·]{2,12}")


@dataclass(frozen=True)
class TextBox:
    box: List[List[float]]
    text: str
    score: float

    @cached_property
    def compact(self):
        return compact_text(self.text)

    @cached_property
    def edges(self):
        # RapidOCR 按左上、右上、右下、左下返回四边形。
        top_left, top_right, bottom_right, bottom_left = self.box
        left = (top_left[0] + bottom_left[0]) / 2
        right = (top_right[0] + bottom_right[0]) / 2
        y_left = (top_left[1] + bottom_left[1]) / 2
        y_right = (top_right[1] + bottom_right[1]) / 2
        height = max(1.0, (bottom_left[1] - top_left[1] + bottom_right[1] - top_right[1]) / 2)
        return left, right, y_left, y_right, height


@dataclass(frozen=True)
class Reading:
    value: str
    score: float
    boxes: Tuple[TextBox, ...]


def reading_from(value, *boxes):
    return Reading(value, min(block.score for block in boxes), boxes)


def split_label(block):
    text = normalize("NFKC", block.text).strip()
    label, _, value = text.partition(":")
    label = compact_text(label)
    if label in LABELS:
        return label, value.strip()
    # 有时 OCR 将标签和值合成一框，中间只保留了空格。
    for gap in reversed(list(re.finditer(r"\s+", text))):
        prefix = compact_text(text[:gap.start()])
        if prefix in LABELS:
            return prefix, text[gap.end():].lstrip(": ").strip()
    return label, value.strip()


def right_on_row(anchor, blocks):
    """使用标签框的基线寻找右侧同一行的单元格。"""
    left, right, y_left, y_right, height = anchor.edges
    slope = (y_right - y_left) / max(1.0, right - left)
    row = []
    for block in blocks:
        x1, _, y1, _, block_height = block.edges
        # 比较值框靠近标签的一侧，避免长字段受斜率误差影响。
        if x1 < right - 0.2 * height:
            continue
        expected_y = y_right + slope * (x1 - right)
        if abs(y1 - expected_y) <= 0.55 * max(height, block_height):
            row.append(block)
    return sorted(row, key=lambda block: block.edges[0])


def adjacent_value(anchor, row):
    if row:
        block = row[0]
        gap = block.edges[0] - anchor.edges[1]
        if gap <= 5 * anchor.edges[4] and split_label(block)[0] not in LABELS:
            return block
    return None


def wrapped_unit_labels(blocks):
    for unit, (first_line, second_line) in WRAPPED_UNIT_LABELS.items():
        if unit not in PARTICIPANT_LABELS:
            continue
        first_line, second_line = compact_text(first_line), compact_text(second_line)
        for top in blocks:
            if top.compact != first_line:
                continue
            left, right, y_left, _, height = top.edges
            for bottom in blocks:
                if bottom.compact != second_line:
                    continue
                x1, x2, y1, _, bottom_height = bottom.edges
                aligned = abs((x1 + x2) - (left + right)) <= (right - left)
                if aligned and 0 < y1 - y_left <= 1.6 * max(height, bottom_height):
                    yield TextBox(top.box[:2] + bottom.box[2:], unit, min(top.score, bottom.score))


def read_value(anchor, inline_value, row):
    if inline_value:
        return reading_from(inline_value, anchor)
    value_box = adjacent_value(anchor, row)
    if value_box:
        value = value_box.text.strip()
        if value:
            return reading_from(value, anchor, value_box)
    return None


def participant_readings(unit, anchor, inline_value, row):
    company = read_value(anchor, inline_value, row)
    if company:
        yield (unit, "单位名称"), company

    role_found = False
    for index, block in enumerate(row):
        label, inline = split_label(block)
        extra_field = EXTRA_BY_LABEL.get(label)
        if extra_field:
            reading = read_value(block, inline, row[index + 1:])
            if reading:
                yield (unit, extra_field), reading_from(reading.value, anchor, *reading.boxes)
        role = ROLE_BY_LABEL.get(label)
        if role_found or not role:
            continue
        role_found = True
        yield (unit, "职务"), reading_from(role, anchor, block)
        name = read_value(block, inline, row[index + 1:])
        if name:
            compact_name = compact_text(name.value)
            if NAME_PATTERN.fullmatch(compact_name):
                yield (unit, "姓名"), reading_from(compact_name, anchor, *name.boxes)


def extract_fields(blocks):
    readings = {}
    title = compact_text(CARD_TITLE)
    for block in [*blocks, *wrapped_unit_labels(blocks)]:
        label, inline_value = split_label(block)
        if block.compact == title:
            merge_readings(readings, {("证件名称",): reading_from(CARD_TITLE, block)})
        elif label in UNIT_BY_LABEL:
            unit = UNIT_BY_LABEL[label]
            row = right_on_row(block, blocks)
            merge_readings(readings, dict(participant_readings(unit, block, inline_value, row)))
        elif label in FIELD_BY_LABEL:
            field = FIELD_BY_LABEL[label]
            reading = read_value(block, inline_value, right_on_row(block, blocks))
            if reading is None:
                continue
            if field == PERMIT_NUMBER_FIELD:
                value = compact_text(reading.value)
                # 演示卡的 DEMO-年份-序号中，OCR 可能将前缀的 O 读成 0。
                value = re.sub(r"^DEM0(?=-[0-9]{4}-[0-9]{3}$)", "DEMO", value)
                reading = replace(reading, value=value)
            merge_readings(readings, {(field,): reading})
    return readings


def merge_readings(current, incoming):
    for field, reading in incoming.items():
        if field not in current or current[field].score < reading.score:
            current[field] = reading


def field_report(readings):
    # JSON 字段由上方的代码编辑区生成，新增配置后会自动进入输出。
    def value(field):
        reading = readings.get(field)
        return reading.value if reading else None

    fields = {field: value((field,)) for field in FIELDS}
    fields["参建单位"] = {
        unit: {field: value((unit, field)) for field in PARTICIPANT_FIELDS}
        for unit in PARTICIPANTS
    }
    missing = [field for field in FIELDS if fields[field] is None]
    missing.extend(
        f"参建单位.{unit}.{field}"
        for unit, details in fields["参建单位"].items()
        for field, content in details.items()
        if content is None
    )
    fields["未识别字段"] = missing
    return fields
