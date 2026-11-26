"""更新通道。

用户界面的「通道一、二…」对应工程师设置里的仓库顺序；切换通道会清空旧检查结果。
"""
from publish_switcher.common.errors import SyncError
from publish_switcher.repositories.discovery import normalize
from publish_switcher.updates.release import mirror_locations


def channel_name(index):
    numbers = ("一", "二", "三", "四", "五", "六", "七", "八", "九", "十",
               "十一", "十二", "十三", "十四", "十五", "十六")
    return "通道" + numbers[index]


def selected_channel(repositories, index, release_url):
    values = normalize(repositories)
    if type(index) is not int or not 0 <= index < len(values):
        raise SyncError("更新通道已变化，请重新选择。")
    locations = mirror_locations(release_url, values)
    # Custom external release URLs remain exact. Repository metadata URLs map
    # against the full list before we restrict downloads to the selected item.
    address = locations[index] if len(locations) == len(values) else locations[0]
    return [values[index]], address
