"""双来源事件对账的纯标准库测试（无需 FastAPI / 网络）。

用法:  python tests/test_reconcile.py
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATA_DIR = tempfile.mkdtemp(prefix="audit-reconcile-test-")
os.environ["DATA_DIR"] = DATA_DIR

from app.db import db, init_db  # noqa: E402
from app.importer import import_payload, reset_all  # noqa: E402
from app.reconcile import MAX_SIDE_EVENTS, ReconcileError, reconcile  # noqa: E402

init_db(load_sample=False)

EXAMPLE = os.path.join(os.path.dirname(__file__), "..", "examples",
                       "login-anomaly.json")


def load_sample():
    reset_all()
    with open(EXAMPLE, encoding="utf-8") as f:
        import_payload(json.load(f))


def db_snapshot():
    with db() as conn:
        counts = {t: conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
                  for t in ("events", "sources", "constraints")}
        assumptions = [(r["id"], r["clock_offset"], r["uncertainty"])
                       for r in conn.execute(
                           "SELECT id, clock_offset, uncertainty FROM sources ORDER BY id")]
    return counts, assumptions


def pair_keys(result):
    return [(p["a"]["id"], p["b"]["id"]) for p in result["pairs"]]


class PairingRules(unittest.TestCase):
    """配对规则：actor 非空且相同、event_type 相同、闭区间间距 ≤ 容差。"""

    def test_basic_pairs_and_unmatched(self):
        reset_all()
        import_payload({
            "sources": [{"id": "s1", "uncertainty": 0.1},
                        {"id": "s2", "uncertainty": 0.1}],
            "events": [
                {"id": "e1", "source": "s1", "time": 100, "type": "login", "actor": "u1"},
                # [99.95,100.15] 与 e1 [99.9,100.1] 重叠 → 间距 0，中点差 50ms
                {"id": "e2", "source": "s2", "time": 100.05, "type": "login", "actor": "u1"},
                {"id": "e3", "source": "s1", "time": 200, "type": "logout", "actor": "u2"},
                # 区间间距 204.9-200.1 = 4.8s = 4800ms，中点差 5000ms
                {"id": "e4", "source": "s2", "time": 205, "type": "logout", "actor": "u2"},
                {"id": "e5", "source": "s1", "time": 300, "type": "click", "actor": "u3"},
                {"id": "e6", "source": "s2", "time": 400, "type": "view", "actor": "u4"},
            ],
        })
        r = reconcile("s1", "s2", 5000)
        self.assertEqual(r["reconcile_type"], "dual-source-reconciliation")
        self.assertEqual(pair_keys(r), [("e1", "e2"), ("e3", "e4")])
        p1, p2 = r["pairs"]
        self.assertEqual(p1["interval_distance_ms"], 0)      # 区间重叠
        self.assertEqual(p1["midpoint_diff_ms"], 50)
        self.assertEqual(p2["interval_distance_ms"], 4800)   # 不重叠：最近端点距离
        self.assertEqual(p2["midpoint_diff_ms"], 5000)
        s = r["summary"]
        self.assertEqual((s["events_a"], s["events_b"]), (3, 3))
        self.assertEqual((s["matched_pairs"], s["candidate_pairs"]), (2, 2))
        self.assertEqual((s["unmatched_a"], s["unmatched_b"]), (1, 1))
        self.assertEqual(s["total_midpoint_diff_ms"], 5050)
        self.assertEqual([e["id"] for e in r["unmatched"]["a"]], ["e5"])
        self.assertEqual([e["id"] for e in r["unmatched"]["b"]], ["e6"])
        # 容差小于间距时配对消失
        r2 = reconcile("s1", "s2", 4000)
        self.assertEqual(pair_keys(r2), [("e1", "e2")])

    def test_actor_must_be_nonempty_and_equal(self):
        reset_all()
        import_payload({
            "sources": [{"id": "s1", "uncertainty": 0},
                        {"id": "s2", "uncertainty": 0}],
            "events": [
                # 三种违规各占一对，类型互不相同以避免交叉配对
                {"id": "a1", "source": "s1", "time": 100, "type": "t1", "actor": ""},
                {"id": "b1", "source": "s2", "time": 100, "type": "t1", "actor": ""},
                {"id": "a2", "source": "s1", "time": 100, "type": "t2"},  # 无 actor
                {"id": "b2", "source": "s2", "time": 100, "type": "t2", "actor": "u"},
                {"id": "a3", "source": "s1", "time": 100, "type": "t3", "actor": "u"},
                {"id": "b3", "source": "s2", "time": 100, "type": "t3", "actor": "v"},
            ],
        })
        r = reconcile("s1", "s2", 1000)
        # 空 actor / 缺失 actor / actor 不一致：全部不可配对
        self.assertEqual(r["pairs"], [])
        self.assertEqual(r["summary"]["candidate_pairs"], 0)
        self.assertEqual(r["summary"]["unmatched_a"], 3)
        self.assertEqual(r["summary"]["unmatched_b"], 3)

    def test_event_type_must_match(self):
        reset_all()
        import_payload({
            "sources": [{"id": "s1", "uncertainty": 0},
                        {"id": "s2", "uncertainty": 0}],
            "events": [
                {"id": "a1", "source": "s1", "time": 100, "type": "login", "actor": "u"},
                {"id": "b1", "source": "s2", "time": 100, "type": "logout", "actor": "u"},
            ],
        })
        r = reconcile("s1", "s2", 1000)
        self.assertEqual(r["pairs"], [])

    def test_tolerance_boundary_inclusive_and_ms_rounding(self):
        reset_all()
        import_payload({
            "sources": [{"id": "s1", "uncertainty": 0},
                        {"id": "s2", "uncertainty": 0}],
            "events": [
                {"id": "a1", "source": "s1", "time": 100, "type": "x", "actor": "u"},
                # 间距 0.4ms → 四舍五入为 0ms：容差 0 也可配对
                {"id": "b1", "source": "s2", "time": 100.0004, "type": "x", "actor": "u"},
                {"id": "a2", "source": "s1", "time": 200, "type": "x", "actor": "u"},
                # 间距 0.6ms → 四舍五入为 1ms：容差 0 拒绝、容差 1 接受（闭区间判定）
                {"id": "b2", "source": "s2", "time": 200.0006, "type": "x", "actor": "u"},
                {"id": "a3", "source": "s1", "time": 300, "type": "x", "actor": "u"},
                # 间距恰好 100ms：容差 100 时边界可取
                {"id": "b3", "source": "s2", "time": 300.1, "type": "x", "actor": "u"},
            ],
        })
        r0 = reconcile("s1", "s2", 0)
        self.assertEqual(pair_keys(r0), [("a1", "b1")])
        self.assertEqual(r0["pairs"][0]["interval_distance_ms"], 0)
        r1 = reconcile("s1", "s2", 1)
        self.assertEqual(pair_keys(r1), [("a1", "b1"), ("a2", "b2")])
        self.assertEqual(r1["pairs"][1]["interval_distance_ms"], 1)
        r100 = reconcile("s1", "s2", 100)
        self.assertEqual(pair_keys(r100),
                         [("a1", "b1"), ("a2", "b2"), ("a3", "b3")])
        self.assertEqual(r100["pairs"][2]["interval_distance_ms"], 100)
        r99 = reconcile("s1", "s2", 99)
        self.assertEqual(pair_keys(r99), [("a1", "b1"), ("a2", "b2")])


class GlobalOptimum(unittest.TestCase):
    """全局最优而非逐条贪心：先最大化配对数，再最小化中点差之和。"""

    def test_max_cardinality_beats_greedy(self):
        # 贪心（按中点差从小到大逐条取）会先占 a1-b1(0ms)，导致 a2 无对可配 → 1 对；
        # 全局最优为 {a1-b2, a2-b1} → 2 对。
        reset_all()
        import_payload({
            "sources": [{"id": "s1", "uncertainty": 0},
                        {"id": "s2", "uncertainty": 0}],
            "events": [
                {"id": "a1", "source": "s1", "time": 100, "type": "x", "actor": "u"},
                {"id": "a2", "source": "s1", "time": 99.9, "type": "x", "actor": "u"},
                {"id": "b1", "source": "s2", "time": 100, "type": "x", "actor": "u"},
                {"id": "b2", "source": "s2", "time": 100.05, "type": "x", "actor": "u"},
            ],
        })
        # 容差 120ms：a2-b2 间距 150ms 不可配，其余三条边可配
        r = reconcile("s1", "s2", 120)
        self.assertEqual(r["summary"]["candidate_pairs"], 3)
        self.assertEqual(r["summary"]["matched_pairs"], 2)
        self.assertEqual(pair_keys(r), [("a1", "b2"), ("a2", "b1")])
        self.assertEqual(r["summary"]["total_midpoint_diff_ms"], 150)

    def test_min_cost_among_max_cardinality(self):
        # 两条最大匹配：{a1-b1, a2-b2} = 8+10 = 18ms，
        # {a1-b2, a2-b1} = 20+2 = 22ms；必须选中点差之和更小的前者。
        reset_all()
        import_payload({
            "sources": [{"id": "s1", "uncertainty": 0},
                        {"id": "s2", "uncertainty": 0}],
            "events": [
                {"id": "a1", "source": "s1", "time": 100, "type": "x", "actor": "u"},
                {"id": "a2", "source": "s1", "time": 100.01, "type": "x", "actor": "u"},
                {"id": "b1", "source": "s2", "time": 100.008, "type": "x", "actor": "u"},
                {"id": "b2", "source": "s2", "time": 100.02, "type": "x", "actor": "u"},
            ],
        })
        r = reconcile("s1", "s2", 1000)
        self.assertEqual(r["summary"]["matched_pairs"], 2)
        self.assertEqual(pair_keys(r), [("a1", "b1"), ("a2", "b2")])
        self.assertEqual(r["summary"]["total_midpoint_diff_ms"], 18)
        costs = {tuple(sorted([p["a"]["id"], p["b"]["id"]])): p["midpoint_diff_ms"]
                 for p in r["pairs"]}
        self.assertEqual(costs, {("a1", "b1"): 8, ("a2", "b2"): 10})

    def test_each_event_at_most_one_pair_and_stable_output(self):
        reset_all()
        events = []
        # 导入顺序与 ID 字典序故意不一致
        for i in range(6):
            events.append({"id": f"za{5 - i}", "source": "s1", "time": 100 + i * 10,
                           "type": "x", "actor": f"u{i % 3}"})
            events.append({"id": f"zb{5 - i}", "source": "s2", "time": 100 + i * 10 + 1,
                           "type": "x", "actor": f"u{i % 3}"})
        import_payload({
            "sources": [{"id": "s1", "uncertainty": 0.5},
                        {"id": "s2", "uncertainty": 0.5}],
            "events": events,
        })
        r1 = reconcile("s1", "s2", 5000)
        r2 = reconcile("s1", "s2", 5000)
        # 确定性：同一输入两次对账结果完全一致
        self.assertEqual(json.dumps(r1, sort_keys=True),
                         json.dumps(r2, sort_keys=True))
        # 每条事件最多参与一对
        used = [eid for pair in r1["pairs"] for eid in
                (pair["a"]["id"], pair["b"]["id"])]
        self.assertEqual(len(used), len(set(used)))
        # 输出稳定：配对按 (A 事件 ID, B 事件 ID) 排序，未匹配按事件 ID 排序
        self.assertEqual(pair_keys(r1), sorted(pair_keys(r1)))
        self.assertEqual([e["id"] for e in r1["unmatched"]["a"]],
                         sorted(e["id"] for e in r1["unmatched"]["a"]))
        self.assertEqual([e["id"] for e in r1["unmatched"]["b"]],
                         sorted(e["id"] for e in r1["unmatched"]["b"]))


class Validation(unittest.TestCase):
    """输入校验与每侧 200 条上限。"""

    def setUp(self):
        reset_all()
        import_payload({
            "sources": [{"id": "s1", "uncertainty": 0},
                        {"id": "s2", "uncertainty": 0}],
            "events": [{"id": "a1", "source": "s1", "time": 100, "type": "x",
                        "actor": "u"}],
        })

    def test_same_source_rejected(self):
        with self.assertRaises(ReconcileError) as ctx:
            reconcile("s1", "s1", 100)
        self.assertIn("不同", str(ctx.exception))

    def test_unknown_source_rejected(self):
        with self.assertRaises(ReconcileError) as ctx:
            reconcile("s1", "nope", 100)
        self.assertIn("不存在", str(ctx.exception))

    def test_negative_tolerance_rejected(self):
        with self.assertRaises(ReconcileError) as ctx:
            reconcile("s1", "s2", -1)
        self.assertIn("不能为负", str(ctx.exception))

    def test_non_numeric_tolerance_rejected(self):
        for bad in ("abc", None, float("nan"), float("inf"), True):
            with self.assertRaises(ReconcileError, msg=f"tolerance={bad!r}"):
                reconcile("s1", "s2", bad)

    def test_side_event_limit(self):
        reset_all()
        import_payload({
            "sources": [{"id": "big", "uncertainty": 0},
                        {"id": "small", "uncertainty": 0}],
            "events": (
                [{"id": f"e{i:03d}", "source": "big", "time": 1000 + i,
                  "type": "x", "actor": "u"}
                 for i in range(MAX_SIDE_EVENTS + 1)]
                + [{"id": "s0", "source": "small", "time": 1000,
                    "type": "x", "actor": "u"}]
            ),
        })
        with self.assertRaises(ReconcileError) as ctx:
            reconcile("big", "small", 100)
        self.assertIn("超过对账上限", str(ctx.exception))
        self.assertIn(str(MAX_SIDE_EVENTS), str(ctx.exception))
        # 对称：另一侧超限同样拒绝
        with self.assertRaises(ReconcileError):
            reconcile("small", "big", 100)
        # 恰好 200 条：允许
        reset_all()
        import_payload({
            "sources": [{"id": "big", "uncertainty": 0},
                        {"id": "small", "uncertainty": 0}],
            "events": (
                [{"id": f"e{i:03d}", "source": "big", "time": 1000 + i,
                  "type": "x", "actor": "u"}
                 for i in range(MAX_SIDE_EVENTS)]
                + [{"id": "s0", "source": "small", "time": 1000,
                    "type": "x", "actor": "u"}]
            ),
        })
        r = reconcile("big", "small", 100)
        self.assertEqual(r["summary"]["events_a"], MAX_SIDE_EVENTS)
        self.assertEqual(r["summary"]["matched_pairs"], 1)


class OverridesAndReadOnly(unittest.TestCase):
    """页面未保存假设参与对账；对账只读不改库。"""

    def test_unsaved_overrides_participate(self):
        reset_all()
        import_payload({
            "sources": [{"id": "s1", "uncertainty": 0},
                        {"id": "s2", "uncertainty": 0}],
            "events": [
                {"id": "a1", "source": "s1", "time": 100, "type": "x", "actor": "u"},
                {"id": "b1", "source": "s2", "time": 110, "type": "x", "actor": "u"},
            ],
        })
        # 默认假设：间距 10s 超出 5s 容差 → 无配对
        r0 = reconcile("s1", "s2", 5000)
        self.assertEqual(r0["pairs"], [])
        # 未保存假设 s2.offset=10：b1 校正到 100，区间重叠 → 配对成功
        r1 = reconcile("s1", "s2", 5000, {"s2": {"clock_offset": 10}})
        self.assertEqual(pair_keys(r1), [("a1", "b1")])
        self.assertEqual(r1["pairs"][0]["interval_distance_ms"], 0)

    def test_read_only(self):
        reset_all()
        import_payload({
            "sources": [{"id": "s1", "uncertainty": 0},
                        {"id": "s2", "uncertainty": 0}],
            "events": [
                {"id": "a1", "source": "s1", "time": 100, "type": "x", "actor": "u"},
                {"id": "b1", "source": "s2", "time": 100, "type": "x", "actor": "u"},
            ],
            "constraints": [{"from": "a1", "to": "b1", "kind": "claimed"}],
        })
        before = db_snapshot()
        # 未保存假设 s1.offset=3：a1 校正到 97，间距 3s 仍在 5s 容差内
        r = reconcile("s1", "s2", 5000, {"s1": {"clock_offset": 3}})
        self.assertEqual(len(r["pairs"]), 1)
        self.assertEqual(db_snapshot(), before)  # 不新增约束、不合并记录、不改假设


class SampleCase(unittest.TestCase):
    """内置示例案件：跨来源无相同 actor+类型组合 → 0 对，两侧全部未匹配。"""

    def setUp(self):
        load_sample()

    def test_sample_reconcile_deterministic(self):
        r = reconcile("gateway", "app-server", 60000)
        self.assertEqual(r["summary"]["events_a"], 3)
        self.assertEqual(r["summary"]["events_b"], 3)
        self.assertEqual(r["summary"]["matched_pairs"], 0)
        self.assertEqual(r["summary"]["unmatched_a"], 3)
        self.assertEqual(r["summary"]["unmatched_b"], 3)
        r2 = reconcile("gateway", "app-server", 60000)
        self.assertEqual(json.dumps(r, sort_keys=True),
                         json.dumps(r2, sort_keys=True))
        # 未保存假设参与：app-server offset +60s 后仍无相同 actor+类型，结果形态不变
        r3 = reconcile("gateway", "app-server", 60000,
                       {"app-server": {"clock_offset": 60}})
        self.assertEqual(r3["summary"]["matched_pairs"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
