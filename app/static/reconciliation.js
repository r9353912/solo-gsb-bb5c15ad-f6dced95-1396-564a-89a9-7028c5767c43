/* 双来源事件对账抽屉 —— 复用 app.js 的 state / overrides / el / esc / toast /
   focusEvent / shortId / colorFor 与 compare.js 的抽屉样式。
   只读：不新增约束、不合并记录；点击事件 ID 回主时间线定位。 */
"use strict";

const reconState = {
  result: null,
};
const recon$ = (sel) => document.querySelector(sel);

/* --------------------------------------------------------------- 开关 */

function reconOpen() {
  recon$("#recon-overlay").classList.remove("hidden");
  reconFillSources();
}
function reconClose() {
  recon$("#recon-overlay").classList.add("hidden");
}

function reconFillSources() {
  const sources = (state.result && state.result.sources) || [];
  const opts = sources.map((s) =>
    `<option value="${esc(s.id)}">${esc(s.name || s.id)} (${esc(s.id)} · ${s.event_count})</option>`).join("");
  const selA = recon$("#recon-source-a");
  const selB = recon$("#recon-source-b");
  const prevA = selA.value, prevB = selB.value;
  selA.innerHTML = opts;
  selB.innerHTML = opts;
  if (!sources.length) return;  // 首屏数据尚未载入：留空，等下次打开再填
  // 默认选两个不同来源（A 第一个、B 第二个）
  selA.value = prevA && sources.some((s) => s.id === prevA)
    ? prevA : (sources[0] && sources[0].id) || "";
  if (prevB && sources.some((s) => s.id === prevB) && prevB !== selA.value) {
    selB.value = prevB;
  } else {
    const other = sources.find((s) => s.id !== selA.value);
    selB.value = other ? other.id : (sources[0] && sources[0].id) || "";
  }
}

/* --------------------------------------------------------------- 对账 */

async function reconRun() {
  const sourceA = recon$("#recon-source-a").value;
  const sourceB = recon$("#recon-source-b").value;
  const tolRaw = recon$("#recon-tol").value;
  const toleranceMs = tolRaw === "" || tolRaw === null ? NaN : Number(tolRaw);
  const hint = recon$("#recon-hint");
  const box = recon$("#recon-result");

  if (!sourceA || !sourceB) { toast("请先在两侧各选择一个来源", "error"); return; }
  if (sourceA === sourceB) { toast("两侧必须选择不同来源", "error"); return; }
  if (!isFinite(toleranceMs) || toleranceMs < 0) {
    toast("容差必须是非负数值（毫秒）", "error"); return;
  }

  hint.textContent = "对账中…";
  box.innerHTML = "";
  box.appendChild(el("div", "cmp-empty", "全局最优配对求解中…"));

  const res = await fetch("/api/source-reconciliation", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    // 携带页面当前（含未保存）的时钟假设；只读，不改写任何数据
    body: JSON.stringify({
      source_a: sourceA,
      source_b: sourceB,
      tolerance_ms: toleranceMs,
      overrides: state.overrides || {},
    }),
  });
  hint.textContent = "";
  if (!res.ok) {
    let msg = await res.text();
    try { msg = JSON.parse(msg).detail || msg; } catch { /* 保留原文 */ }
    reconState.result = null;
    box.innerHTML = "";
    box.appendChild(el("div", "cmp-empty", "对账失败: " + esc(msg)));
    toast("对账失败: " + msg, "error");
    return;
  }
  reconState.result = await res.json();
  reconRender();
}

/* --------------------------------------------------------------- 渲染 */

function reconTime(ms) {
  // 整数毫秒 epoch → HH:MM:SS.mmm（UTC），与后端 fmt 对齐仅取时间片段
  const d = new Date(ms);
  const p = (n, l) => String(n).padStart(l, "0");
  return `${p(d.getUTCHours(), 2)}:${p(d.getUTCMinutes(), 2)}:${p(d.getUTCSeconds(), 2)}.${p(d.getUTCMilliseconds(), 3)}`;
}

function reconMsText(v) { return `${v >= 0 ? "+" : ""}${v} ms`; }

function reconRender() {
  const d = reconState.result;
  const box = recon$("#recon-result");
  box.innerHTML = "";
  if (!d) return;
  box.appendChild(reconSummary(d));
  box.appendChild(reconPairsBlock(d));
  box.appendChild(reconUnmatchedBlock(d, "a"));
  box.appendChild(reconUnmatchedBlock(d, "b"));
  // 点击任意事件 ID：关抽屉并在主时间线定位
  box.querySelectorAll("[data-eid]").forEach((n) =>
    n.addEventListener("click", () => { reconClose(); focusEvent(n.dataset.eid); }));
}

function reconSummary(d) {
  const s = d.stats;
  const side = d.sides;
  const dirty = Object.keys(state.overrides || {}).length > 0;
  const blk = el("div", "cmp-block");
  blk.innerHTML = `
    <h3>对账结果
      <span class="cmp-count">${esc(d.summary)}</span></h3>
    <div class="sens-meta">
      <span class="stat">A · ${esc(side.a.source_name || side.a.source_id)} <b>${s.events_a}</b></span>
      <span class="stat">B · ${esc(side.b.source_name || side.b.source_id)} <b>${s.events_b}</b></span>
      <span class="stat">容差 <b>±${d.tolerance_ms} ms</b></span>
      <span class="stat">候选边 <b>${s.candidate_edges}</b></span>
      <span class="stat ${s.matched_pairs ? "warn" : ""}">配对 <b>${s.matched_pairs}</b></span>
      <span class="stat">A 未匹配 <b>${s.unmatched_a}</b></span>
      <span class="stat">B 未匹配 <b>${s.unmatched_b}</b></span>
      <span class="stat">中点差绝对值之和 <b>${s.mid_delta_abs_sum_ms} ms</b></span>
      ${dirty ? '<span class="stat warn">含未保存假设</span>' : ""}
    </div>
    <div class="sens-notice" style="margin-top:8px">${esc(d.matching.rule)}；${esc(d.matching.rounding)}；每侧上限 ${d.matching.limit_per_side} 条。</div>`;
  return blk;
}

function reconEventCell(ev, cls) {
  const color = colorFor(ev.source_id);
  return `
    <div class="recon-cell ${cls}">
      <div class="recon-cell-id">
        <span class="chain-node" data-eid="${esc(ev.id)}" title="点击在主时间线定位">${esc(shortId(ev.id))}</span>
        <span class="tag actor">👤 ${esc(ev.actor || "")}</span>
      </div>
      <div class="recon-cell-summary" title="${esc(ev.summary)}">${esc(ev.summary || "")}</div>
      <div class="recon-cell-range" style="border-color:${color}55">
        <span title="闭区间 [lo, hi]（整数毫秒）">[${esc(reconTime(ev.lo_ms))} ~ ${esc(reconTime(ev.hi_ms))}]</span>
        <span class="recon-mid" title="区间中点">mid ${esc(reconTime(ev.mid_ms))}</span>
      </div>
    </div>`;
}

function reconPairsBlock(d) {
  const blk = el("div", "cmp-block");
  const n = d.pairs.length;
  blk.innerHTML = `<h3>已配对事件
    <span class="cmp-count">${n} 对 · 按 A 侧事件 ID 稳定排序；时间差为 B 中点 − A 中点</span></h3>`;
  if (!n) {
    blk.appendChild(el("div", "cmp-empty", "没有满足条件的配对（actor 相同 / 类型相同 / 闭区间间距 ≤ 容差）"));
    return blk;
  }
  const list = el("div", "recon-pairs");
  for (const p of d.pairs) {
    const row = el("div", "recon-pair");
    const gapCls = p.closed_gap_ms === 0 ? "touch" : "gap";
    row.innerHTML = `
      ${reconEventCell(p.a, "a")}
      <div class="recon-delta">
        <div class="recon-delta-main ${p.mid_delta_ms >= 0 ? "pos" : "neg"}"
             title="B 区间中点 − A 区间中点（整数毫秒）">${esc(reconMsText(p.mid_delta_ms))}</div>
        <div class="recon-delta-abs">|Δ| ${p.mid_delta_abs_ms} ms</div>
        <div class="recon-delta-gap ${gapCls}"
             title="两侧闭区间之间的间距（相接/重叠为 0）">闭区间间距 ${p.closed_gap_ms} ms</div>
        <div class="recon-delta-type">${esc(p.event_type)}</div>
      </div>
      ${reconEventCell(p.b, "b")}`;
    list.appendChild(row);
  }
  blk.appendChild(list);
  return blk;
}

function reconUnmatchedBlock(d, which) {
  const list = which === "a" ? d.unmatched_a : d.unmatched_b;
  const side = d.sides[which];
  const blk = el("div", "cmp-block");
  blk.innerHTML = `<h3>${which.toUpperCase()} 侧未匹配事件
    <span class="cmp-count">${esc(side.source_name || side.source_id)} · ${list.length} 条 · 按事件 ID 排序（含 actor 为空 / 类型无对应 / 未获最优配对）</span></h3>`;
  if (!list.length) {
    blk.appendChild(el("div", "cmp-empty", "✓ 全部配对"));
    return blk;
  }
  const wrap = el("div", "recon-unmatched");
  for (const ev of list) {
    const row = el("div", "recon-um-row");
    const noActor = !ev.actor;
    row.innerHTML = `
      <span class="chain-node" data-eid="${esc(ev.id)}" title="点击在主时间线定位">${esc(shortId(ev.id))}</span>
      <span class="recon-um-type">${esc(ev.event_type)}</span>
      <span class="tag actor">👤 ${esc(ev.actor || "（空）")}</span>
      <span class="recon-um-summary" title="${esc(ev.summary)}">${esc(ev.summary || "")}</span>
      <span class="recon-um-range" title="闭区间中点">[mid ${esc(reconTime(ev.mid_ms))}]</span>
      ${noActor ? '<span class="tag amb" title="actor 为空，不参与配对">actor 空</span>' : ""}`;
    wrap.appendChild(row);
  }
  blk.appendChild(wrap);
  return blk;
}

/* --------------------------------------------------------------- 绑定 */

recon$("#btn-reconcile").addEventListener("click", reconOpen);
recon$("#recon-close").addEventListener("click", reconClose);
recon$("#recon-run").addEventListener("click", reconRun);
recon$("#recon-rerun").addEventListener("click", reconRun);
recon$("#recon-source-a").addEventListener("change", () => {
  // 避免两侧相同：若撞了，自动切到另一个来源
  const a = recon$("#recon-source-a"), b = recon$("#recon-source-b");
  if (a.value === b.value) {
    const other = [...b.options].find((o) => o.value !== a.value);
    if (other) b.value = other.value;
  }
});
recon$("#recon-source-b").addEventListener("change", () => {
  const a = recon$("#recon-source-a"), b = recon$("#recon-source-b");
  if (a.value === b.value) {
    const other = [...a.options].find((o) => o.value !== b.value);
    if (other) a.value = other.value;
  }
});
recon$("#recon-tol").addEventListener("keydown", (e) => {
  if (e.key === "Enter") reconRun();
});
recon$("#recon-overlay").addEventListener("click", (e) => {
  if (e.target.id === "recon-overlay") reconClose();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !recon$("#recon-overlay").classList.contains("hidden")) reconClose();
});
