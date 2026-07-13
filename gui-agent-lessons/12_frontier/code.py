"""L12 · 最小复现：SoM 有无消融实验。

复现的 idea：
    SoM 标注（L05）让通用 VLM 的 grounding 变准（答编号不答坐标）。
    消融：有 SoM vs 无 SoM，视觉路线成功率差多少？

最小实现（≤200 行核心）：
    - 视觉路线 A（有 SoM）：截图画框编号 → VLM 答编号 → click(n) 精确
    - 视觉路线 B（无 SoM）：截图直接喂 → VLM 答坐标 → 点击坐标（mock 模拟飘）
    - 本地任务集跑两版，对比成功率

mock VLM 的诚实处理：
    - A 的 mock 按编号答（精确命中，模拟「SoM 让 VLM 准」）
    - B 的 mock 按坐标答 + 随机偏移（模拟「VLM 坐标飘」）
    这验证的是「机制本身」（编号 vs 坐标的精度差），不是「真实 VLM 能力」——
    真实复现需 --real + glm-4v-plus，repro_note 诚实标注。

跑法：
    cd gui-agent-lessons/00_overview/test_pages && python -m http.server 8765
    cd gui-agent-lessons/12_frontier
    python code.py
"""
from __future__ import annotations

import importlib.util
import random
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_HERE = Path(__file__).resolve().parent
_LESSONS = _HERE.parent


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, _LESSONS / rel / "code.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_l01 = _load("l01_code", "01_playwright")
_l02 = _load("l02_code", "02_observation")
BrowserSession = _l01.BrowserSession

L00_BASE = "http://127.0.0.1:8765"


# ──────────────────────────────────────────────────────────────
# 消融实验：有 SoM vs 无 SoM
# ──────────────────────────────────────────────────────────────

def get_target_bbox(session, selector: str) -> dict:
    """获取目标元素的 bbox（用于无 SoM 版的坐标点击对照）。"""
    el = session.page.locator(selector).first
    return el.bounding_box()


def run_with_som(session, target_selector: str, target_idx: int) -> bool:
    """有 SoM 版：VLM 答编号 → click(idx) 精确。
    mock VLM：直接答对编号（模拟 SoM 让 VLM 准）。
    SoM 编号精确命中目标元素，所以总是成功。
    """
    try:
        INTERACTIVE = ('a, button, input, select, textarea, '
                       '[role="button"], [role="link"], [role="textbox"]')
        els = session.page.locator(INTERACTIVE)
        el = els.nth(target_idx - 1)
        # 验证编号对应的元素确实是目标（SoM 让编号→元素映射精确）
        text = el.inner_text()
        return "LangGraph" in text
    except Exception:
        return False


def run_without_som(session, target_selector: str, target_bbox: dict,
                    coord_drift: int = 12) -> bool:
    """无 SoM 版：VLM 答坐标 → 点击坐标（mock 模拟飘）。
    coord_drift: 坐标偏移像素（模拟 VLM grounding 飘）。
    VLM 的坐标飘通常垂直方向更明显（行高小），水平方向较准（元素宽）。

    判定「点对」的方式：点击坐标下方的元素是不是目标链接。
    （比检查 URL 导航更稳——不依赖导航时序。）
    """
    try:
        cx = target_bbox["x"] + target_bbox["width"] / 2
        cy = target_bbox["y"] + target_bbox["height"] / 2
        # 垂直漂移略大于半高（模拟 VLM 对 y 不准），水平漂移小
        cx += random.uniform(-coord_drift * 0.4, coord_drift * 0.4)
        cy += random.uniform(-coord_drift, coord_drift)
        # 用 document.elementFromPoint 查点击点下方的元素，看是不是目标 <a>
        hit_tag = session.page.evaluate(
            "(coords) => { const el = document.elementFromPoint(coords.x, coords.y); "
            "return el ? (el.tagName + '|' + (el.textContent||'').slice(0,30)) : 'null'; }",
            {"x": cx, "y": cy})
        # 命中目标：元素是 <A> 且含目标文本
        return hit_tag.startswith("A|") and "LangGraph" in hit_tag
    except Exception:
        return False


def check_clicked_correctly(session, expected_url_contains: str) -> bool:
    """检查点击后是否到了预期页（功能性验收）。"""
    return expected_url_contains in session.url


# ──────────────────────────────────────────────────────────────
# 跑消融
# ──────────────────────────────────────────────────────────────

def run_ablation(coord_drift: int = 30) -> dict:
    """跑 SoM 有无消融。
    coord_drift: 无 SoM 版的坐标偏移（模拟 VLM 飘的程度）。
    """
    # 任务：从 index 页点「LangGraph 发布列表」链接进 search 页
    # 目标元素：a:has-text("LangGraph 发布列表")，编号 3（L04 实测）
    target_selector = 'a:has-text("LangGraph 发布列表")'
    target_idx = 3
    expected = "search.html"

    results = {"with_som": [], "without_som": []}
    n_trials = 10  # 多次跑取平均（无 SoM 版有随机性）

    with BrowserSession(headless=True) as s:
        for i in range(n_trials):
            # ── 有 SoM 版 ──
            s.goto(f"{L00_BASE}/index.html")
            try:
                s.page.wait_for_load_state("domcontentloaded", timeout=3000)
            except Exception:
                pass
            ok = run_with_som(s, target_selector, target_idx)
            results["with_som"].append(ok)

            # ── 无 SoM 版 ──
            s.goto(f"{L00_BASE}/index.html")
            try:
                s.page.wait_for_load_state("domcontentloaded", timeout=3000)
            except Exception:
                pass
            bbox = get_target_bbox(s, target_selector)
            if bbox:
                # run_without_som 直接返回「坐标是否命中目标元素」
                ok = run_without_som(s, target_selector, bbox, coord_drift)
            else:
                ok = False
            results["without_som"].append(ok)

    return results


# ──────────────────────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────────────────────

def _server_up() -> bool:
    import urllib.request
    try:
        urllib.request.urlopen(L00_BASE + "/index.html", timeout=1).read()
        return True
    except Exception:
        return False


def main():
    print("=" * 60)
    print("L12 最小复现：SoM 有无消融实验")
    print("=" * 60)

    try:
        import playwright  # noqa: F401
    except ImportError:
        print("\n⚠️ playwright 未安装，跳过。")
        return
    if not _server_up():
        print(f"\n⚠️ L00 本地服务未起（{L00_BASE}），请先跑:")
        print(f"   cd gui-agent-lessons/00_overview/test_pages && python -m http.server 8765")
        return

    print("\n── 复现的 idea ───────────────────────────────────")
    print("  SoM 标注让通用 VLM 的 grounding 变准（答编号不答坐标）。")
    print("  消融：有 SoM（编号精确）vs 无 SoM（坐标飘），成功率差多少？")

    print("\n── 最小实现 ─────────────────────────────────────")
    print("  有 SoM：VLM 答编号 → click(idx) 精确命中")
    print("  无 SoM：VLM 答坐标 + 随机偏移(模拟飘) → 点击坐标可能落空")
    print("  10 次试验取成功率，坐标偏移=30px（模拟 VLM grounding 误差）")

    # coord_drift=12: 模拟 VLM 坐标飘（目标链接高 20px，±12 垂直漂移有时中有时不中）
    random.seed(42)  # 可复现
    results = run_ablation(coord_drift=12)

    som_rate = sum(results["with_som"]) / len(results["with_som"])
    nosom_rate = sum(results["without_som"]) / len(results["without_som"])

    print(f"\n── 对照实验结果（10 次试验）─────────────────────")
    print(f"  {'路线':<12} {'成功次数':<10} {'成功率'}")
    print(f"  {'有 SoM':<12} {sum(results['with_som']):<10} {som_rate:.0%}")
    print(f"  {'无 SoM':<12} {sum(results['without_som']):<10} {nosom_rate:.0%}")

    print(f"\n── 结果解读 ─────────────────────────────────────")
    if som_rate > nosom_rate:
        print(f"  ✅ 有 SoM 成功率 ({som_rate:.0%}) > 无 SoM ({nosom_rate:.0%})")
        print(f"  → 支持 idea：SoM 标注让 grounding 更准（编号 vs 坐标）")
    else:
        print(f"  ⚠️ 结果不符合预期（见 repro_note.md 归因）")

    print(f"\n── 诚实标注 ─────────────────────────────────────")
    print(f"  这是 mock 复现：无 SoM 版的『坐标飘』用随机偏移模拟，不是真实 VLM。")
    print(f"  验证的是『编号 vs 坐标的精度差』这个机制，不是『真实 VLM grounding 能力』。")
    print(f"  真实复现需 --real + glm-4v-plus，让 VLM 真看图答坐标。repro_note.md 详述。")

    print(f"\n── 方法论回顾 ───────────────────────────────────")
    print(f"  ① 抽核心 idea：SoM 让 grounding 更准")
    print(f"  ② 最小实现：两版视觉路线 + 坐标偏移模拟飘")
    print(f"  ③ 对照实验：10 次试验取成功率")
    print(f"  ④ 复现笔记：见 repro_note.md（诚实记录限制）")

    print(f"\n{'='*60}")
    print(f"💡 专用模型 vs 通用 VLM+脚手架：三轴框架（成本/泛化/可控）")
    print(f"   SoM/简单 DSL 会被下一代 VLM 吃掉；安全层/评估层不会（工程价值）。")
    print(f"   我不转述观点，做对照实验——这是前沿追踪的核心方法。")


if __name__ == "__main__":
    main()
