"""双来源事件对账：把两个来源中记录同一现实活动的事件配成一对一事件对（只读）。

定位
----
审计员怀疑两个来源记录了**同一批现实活动**（同一操作者、同一事件类型），
但两边时钟都有偏差与不确定度。本模块回答"哪条记录对应哪条记录、
哪些记录只有单侧才有"：在 A / B 两侧事件之间做**全局最优的一对一配对**。

配对规则
--------
- 复用 ``engine`` 的时钟校正区间：每个事件的真实时刻落在闭区间
  ``[lo, hi]``（页面未保存的假设通过 overrides 生效，与主时间线一致）；
- 两侧事件可配对 ⟺ ``actor`` **非空且相同**、``event_type`` 相同、
  且两个**闭区间的间距**不超过容差（毫秒）：

      distance = max(0, max(lo_a, lo_b) - min(hi_a, hi_b))

  区间重叠（含相切）时间距为 0，否则为最近的两个端点之间的距离；
- 所有时间量（区间间距、区间中点差）统一**四舍五入到整数毫秒**后再比较与展示。

求解（全局最优，非逐条贪心）
---------------------------
每条事件最多参与一对 → 二部图匹配，目标按字典序：

1. **最大化配对数**；
2. **最小化配对双方区间中点差绝对值之和**（中点差同样取整数毫秒）。

用最小费用最大流（SSP + 势函数，非负整数费用）精确求解：流量最大即配对数
最多，同流量下费用最小即中点差之和最小。为在同优解中**稳定输出**，边费用
附加一项由事件 ID 排序决定的微小扰动（主目标乘以足够大的基数，扰动永远不
会反超主目标），使结果完全确定、可复现；输出统一按事件 ID 排序。

只读：不写数据库、不新增约束、不合并记录；调整假设后可随时重新对账。
"""
from __future__ import annotations

import heapq
import math
from typing import Any

from . import engine
from .timeutil import fmt

MAX_SIDE_EVENTS = 200  # 每侧事件数上限：超出即明确拒绝，保证配对结果可人工核对


class ReconcileError(ValueError):
    """可直接映射为 HTTP 4xx 的对账请求错误。"""


def _ms(seconds: float) -> int:
    """秒 → 整数毫秒（四舍五入，半值进一）。"""
    return int(math.floor(seconds * 1000.0 + 0.5))


def _clean_tolerance(value: Any) -> float:
    """校验非负容差（毫秒）：必须是有限的非负数值。"""
    if isinstance(value, bool):
        raise ReconcileError(f"容差必须是非负数值（毫秒），收到: {value!r}")
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise ReconcileError(f"容差必须是非负数值（毫秒），收到: {value!r}") from exc
    if not math.isfinite(v):
        raise ReconcileError(f"容差必须是有限数值（不能为 NaN/无穷），收到: {value!r}")
    if v < 0:
        raise ReconcileError(f"容差不能为负（毫秒），收到: {v}")
    return v


# ------------------------------------------------------------ 最小费用最大流

class _MinCostFlow:
    """SSP + 势函数的最小费用最大流（非负整数费用，全程确定性）。

    节点编号固定、Dijkstra 堆按 (距离, 节点编号) 弹出、只在严格更短时松弛，
    同一输入永远得到同一条增广路；配合边费用中的确定性扰动，最终匹配唯一。
    """

    def __init__(self, n: int):
        self.graph: list[list[list]] = [[] for _ in range(n)]
        # 边: [to, 剩余容量, 费用, 反向边下标]

    def add_edge(self, u: int, v: int, cap: int, cost: int) -> int:
        self.graph[u].append([v, cap, cost, len(self.graph[v])])
        self.graph[v].append([u, 0, -cost, len(self.graph[u]) - 1])
        return len(self.graph[u]) - 1

    def min_cost_max_flow(self, s: int, t: int) -> tuple[int, int]:
        n = len(self.graph)
        potential = [0] * n
        flow = cost = 0
        inf = float("inf")
        while True:
            dist = [inf] * n
            prev_v = [-1] * n
            prev_e = [-1] * n
            dist[s] = 0
            heap = [(0, s)]
            while heap:
                d, u = heapq.heappop(heap)
                if d > dist[u]:
                    continue
                for ei, e in enumerate(self.graph[u]):
                    if e[1] <= 0:
                        continue
                    v = e[0]
                    nd = d + e[2] + potential[u] - potential[v]
                    if nd < dist[v]:
                        dist[v] = nd
                        prev_v[v] = u
                        prev_e[v] = ei
                        heapq.heappush(heap, (nd, v))
            if dist[t] == inf:
                return flow, cost
            for v in range(n):
                if dist[v] < inf:
                    potential[v] += dist[v]
            # 容量全为 1，每次增广 1 单位
            v = t
            while v != s:
                e = self.graph[prev_v[v]][prev_e[v]]
                e[1] -= 1
                self.graph[v][e[3]][1] += 1
                v = prev_v[v]
            flow += 1
            cost += potential[t]  # 势函数更新后 potential[t] 即该轮最短路真实费用


# ------------------------------------------------------------ 序列化

def _brief(node: "engine.Node") -> dict[str, Any]:
    e = node.raw
    mid = (node.lo + node.hi) / 2.0
    return {
        "id": e["id"],
        "source_id": e["source_id"],
        "event_type": e["event_type"],
        "actor": e.get("actor"),
        "summary": e.get("summary", ""),
        "lo": round(node.lo, 6),
        "hi": round(node.hi, 6),
        "lo_text": fmt(node.lo),
        "hi_text": fmt(node.hi),
        "midpoint": round(mid, 6),
        "midpoint_text": fmt(mid),
    }


# ------------------------------------------------------------ 主入口

def reconcile(source_a: str, source_b: str, tolerance_ms: Any,
              overrides: dict | None = None) -> dict[str, Any]:
    """对两个来源的事件做全局最优一对一配对（只读）。

    source_a / source_b 必须不同且都已登记；tolerance_ms 为非负容差（毫秒）；
    overrides 为页面当前（可能未保存）的来源时钟假设。每侧事件数超过
    ``MAX_SIDE_EVENTS`` 时明确拒绝。
    """
    tol = _clean_tolerance(tolerance_ms)
    source_a = (source_a or "").strip()
    source_b = (source_b or "").strip()
    if not source_a or not source_b:
        raise ReconcileError("必须选择两个来源")
    if source_a == source_b:
        raise ReconcileError(f"对账需要两个不同的来源，两侧都是: {source_a}")

    stored_sources, raw_events, _raw_edges = engine.load_model()
    for sid in (source_a, source_b):
        if sid not in stored_sources:
            raise ReconcileError(f"来源不存在: {sid}")

    sources = engine._effective_sources(stored_sources, overrides)
    nodes = engine._build_nodes(raw_events, sources)

    # 每侧事件按事件 ID 排序：匹配与输出的确定性基础
    side_a = sorted((n for n in nodes if n.raw["source_id"] == source_a),
                    key=lambda n: n.raw["id"])
    side_b = sorted((n for n in nodes if n.raw["source_id"] == source_b),
                    key=lambda n: n.raw["id"])
    for sid, side in ((source_a, side_a), (source_b, side_b)):
        if len(side) > MAX_SIDE_EVENTS:
            raise ReconcileError(
                f"来源 {sid} 有 {len(side)} 条事件，超过对账上限 "
                f"{MAX_SIDE_EVENTS} 条/侧；请拆分数据（或删除部分事件）后再对账")

    n_a, n_b = len(side_a), len(side_b)

    # 候选配对：actor 非空且相同 + event_type 相同 + 闭区间间距 ≤ 容差
    candidates: list[tuple[int, int, int, int]] = []  # (i, j, 间距ms, 中点差ms)
    for i, na in enumerate(side_a):
        actor = (na.raw.get("actor") or "").strip()
        if not actor:
            continue  # actor 为空的事件不参与任何配对
        for j, nb in enumerate(side_b):
            if (nb.raw.get("actor") or "").strip() != actor:
                continue
            if na.raw["event_type"] != nb.raw["event_type"]:
                continue
            dist_ms = _ms(max(0.0, max(na.lo, nb.lo) - min(na.hi, nb.hi)))
            if dist_ms > tol:
                continue
            mid_ms = _ms(abs((na.lo + na.hi) / 2.0 - (nb.lo + nb.hi) / 2.0))
            candidates.append((i, j, dist_ms, mid_ms))

    # 最小费用最大流：先最大化配对数，再最小化中点差之和。
    # 扰动项 rank 由 ID 排序决定且总和恒小于 PERTURB_BASE，
    # 因此绝不会反超主目标（中点差），只用于同优解的确定性选择。
    src, sink = 0, n_a + n_b + 1
    mcf = _MinCostFlow(n_a + n_b + 2)
    for i in range(n_a):
        mcf.add_edge(src, 1 + i, 1, 0)
    for j in range(n_b):
        mcf.add_edge(1 + n_a + j, sink, 1, 0)
    perturb_base = min(n_a, n_b) * n_a * n_b + 1
    edge_refs: list[tuple[int, int, int, int, int]] = []
    for i, j, dist_ms, mid_ms in candidates:
        rank = i * n_b + j
        ei = mcf.add_edge(1 + i, 1 + n_a + j, 1,
                          mid_ms * perturb_base + rank)
        edge_refs.append((i, j, dist_ms, mid_ms, ei))
    mcf.min_cost_max_flow(src, sink)

    matched_a: dict[int, tuple[int, int, int]] = {}  # i -> (j, 间距ms, 中点差ms)
    for i, j, dist_ms, mid_ms, ei in edge_refs:
        if mcf.graph[1 + i][ei][1] == 0:  # 容量耗尽 → 该边携带 1 单位流
            matched_a[i] = (j, dist_ms, mid_ms)

    pairs = [{
        "a": _brief(side_a[i]),
        "b": _brief(side_b[j]),
        "interval_distance_ms": dist_ms,
        "midpoint_diff_ms": mid_ms,
    } for i, (j, dist_ms, mid_ms) in sorted(matched_a.items())]
    # 稳定输出：配对按 (A 事件 ID, B 事件 ID) 排序
    pairs.sort(key=lambda p: (p["a"]["id"], p["b"]["id"]))

    matched_b = {j for j, _, _ in matched_a.values()}
    unmatched_a = [_brief(n) for i, n in enumerate(side_a) if i not in matched_a]
    unmatched_b = [_brief(n) for j, n in enumerate(side_b) if j not in matched_b]

    return {
        "reconcile_type": "dual-source-reconciliation",
        "source_a": {"id": source_a,
                     "name": sources[source_a].get("name", source_a),
                     "event_count": n_a},
        "source_b": {"id": source_b,
                     "name": sources[source_b].get("name", source_b),
                     "event_count": n_b},
        "tolerance_ms": tol,
        "limits": {"max_side_events": MAX_SIDE_EVENTS},
        "summary": {
            "events_a": n_a,
            "events_b": n_b,
            "candidate_pairs": len(candidates),
            "matched_pairs": len(pairs),
            "unmatched_a": len(unmatched_a),
            "unmatched_b": len(unmatched_b),
            "total_midpoint_diff_ms": sum(p["midpoint_diff_ms"] for p in pairs),
        },
        "pairs": pairs,
        "unmatched": {"a": unmatched_a, "b": unmatched_b},
        "notice": ("对账为只读分析：不新增约束、不合并记录、不写数据库；"
                   "调整来源时钟假设（含未保存调整）后重新对账即可看到配对变化。"),
    }
