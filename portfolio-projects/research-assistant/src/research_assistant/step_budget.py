"""全局步数预算 + 运行时循环检测（AgentOps L01）。

为什么需要它（现状缺口）：
    max_rewrites=3 / max_re_research=2 / browser_max_steps=12 都是「局部限位」——
    每个回路自己有上限，但它们正交：一次运行的总步数 = split + researcher×N + summarize
    + writer×rewrite + research_team×re_research + reviewer×(rewrite+re_research)。
    叠乘后（3 子题 × 重查 2 × 打回 3）总步数仍可能撞到 langgraph 的 recursion_limit=25
    才停——而撞到 recursion_limit 是 GraphRecursionError（崩溃式），不是诚实收尾。

本模块给整条轨迹一个总里程表：
    - step_count：每个父图节点经过时 +1（用 add_int reducer 累加，并发安全）
    - 诚实收尾：超 max_total_steps 时设置 truncated=True，reviewer 强制 pass，
      writer 据此在报告里标注「因步数预算截断」（带着已有材料出部分结果，而非 raise）
    - 循环检测：动作签名（节点名+关键参数哈希）滑窗连续重复 N 次 → 判定原地打转

与 frontier-L08 循环检测的区别：
    frontier 是事后评估（跑完看轨迹发现绕路）；本模块是运行时执法（转到第 N 圈当场刹车）。
    签名思路复用 frontier-L08，但从「离线分析」变成「在线拦截」。
"""
from __future__ import annotations

import hashlib
from typing import Any

from .config import settings
from .logging_config import get_logger

log = get_logger("step_budget")


def step_delta(node: str, param: str = "") -> dict:
    """返回一个节点的步数增量 delta（每经过一个节点调一次）。

    返回的 dict 合并进节点的返回值：
        return {**real_result, **step_delta("writer", summary[:50])}

    step_count: 1 → 被 add_int reducer 累加进全局 step_count
    action_history: [signature] → 被 operator.add reducer 追加进签名历史

    关键：开关关闭时（enable_step_budget=False）仍记账（step_count 照累加），
    只是不触发截断判断——这样 run summary（L07）能看到步数，但不改变现状行为。
    """
    sig = _signature(node, param)
    return {"step_count": 1, "action_history": [sig]}


def _signature(node: str, param: str) -> str:
    """动作签名：节点名 + 关键参数的短哈希（复用 frontier-L08 思路，在线用）。

    参数只取前 80 字符再哈希——既去掉无关细节，又避免长文本撑爆 history。
    """
    h = hashlib.md5(param[:80].encode("utf-8")).hexdigest()[:8]
    return f"{node}:{h}"


def detect_loop(action_history: list[str], window: int | None = None) -> bool:
    """运行时循环检测：最近 window 个动作签名是否完全相同（原地打转）。

    策略（与 frontier-L08 的「连续 3+ 次同节点相似输出」对齐，但用签名）：
        看 action_history 末尾 window 条，若全是同一个签名 → 判定循环。
    window 默认读 config.loop_detect_window。

    返回 True 表示检测到循环（调用方应触发诚实收尾）。
    """
    if not action_history:
        return False
    w = window if window is not None else settings.loop_detect_window
    if len(action_history) < w:
        return False
    tail = action_history[-w:]
    return len(set(tail)) == 1


def should_truncate(state: dict) -> tuple[bool, str]:
    """判断是否该触发诚实收尾，返回 (是否截断, 原因)。

    两个触发条件（任一满足即截断）：
        1. 步数预算超限：step_count >= max_total_steps（enable_step_budget 时）
        2. 检测到循环：动作签名连续重复（enable_loop_detect 时）

    开关都关时永远返回 (False, "")——现状行为完全不变。
    """
    if settings.enable_step_budget:
        step_count = state.get("step_count", 0) or 0
        if step_count >= settings.max_total_steps:
            return True, f"步数预算超限（{step_count}/{settings.max_total_steps}）"
    if settings.enable_loop_detect:
        if detect_loop(state.get("action_history", [])):
            return True, "检测到动作循环（连续重复同一动作签名）"
    return False, ""


def honest_truncation_delta(reason: str) -> dict:
    """诚实收尾的 delta：标记 truncated=True（reviewer/writer 据此处理）。"""
    log.warning(f"触发诚实收尾：{reason}")
    return {"truncated": True}
