"""提取 ftrace 事件字段并归一化 myself_kswapd 事件别名。"""

import re
from typing import Mapping, Optional, Tuple


# 仅接受 ftrace 时间戳后的事件字段，或历史 fixture 的 ``cpu=N ...`` 事件字段。
# 这避免把 payload 中恰好出现的事件名识别为新的 tracepoint。
EVENT_FIELD_RE = re.compile(
    r"(?:\b\d+(?:\.\d+)?\s*:\s*|\bcpu=\d+\s+\.\.\.\s+)"
    r"(?P<event>[A-Za-z0-9_]+(?::[A-Za-z0-9_]+)?):\s*(?P<payload>.*)$"
)

EVENT_ALIASES = {
    "myself_kswapd_request_begin": "request_begin",
    "myself_kswapd:request_begin": "request_begin",
    "myself_kswapd_priority_round": "priority_round",
    "myself_kswapd:priority_round": "priority_round",
    "myself_kswapd_request_end": "request_end",
    "myself_kswapd:request_end": "request_end",
    "lruvec_snapshot": "lruvec_snapshot",
    "myself_kswapd:lruvec_snapshot": "lruvec_snapshot",
    "myself_kswapd_lruvec_snapshot": "lruvec_snapshot",
}


def extract_event(line: str, accepted_aliases: Mapping[str, str]) -> Optional[Tuple[str, str]]:
    """返回规范事件名和 payload；未知事件或非事件字段返回 ``None``。"""
    match = EVENT_FIELD_RE.search(line)
    if match:
        event = accepted_aliases.get(match.group("event"))
        if event is not None:
            return event, match.group("payload")

    # 兼容历史单元测试使用的“事件名从行首开始”的简化 trace 文本；不在行内
    # 搜索别名，因此 payload 中出现同名文本仍不会被误识别。
    for alias, event in accepted_aliases.items():
        prefix = f"{alias}:"
        if line.startswith(prefix):
            return event, line[len(prefix):].lstrip()
    return None
