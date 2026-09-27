/* 双来源事件对账抽屉 —— 复用 app.js 的 state / overrides / el / esc / toast /
   focusEvent / shortId 与 compare.js / sensitivity.js 的抽屉样式。 */
"use strict";

const reconState = {
  result: null,
  a: "",
  b: "",
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
    `<option value="${esc(s.id)}">${esc(s.name || s.id)} (${esc(s.id)})</option>`).join("");
  const selA = recon$("#recon-src-a"), selB = recon$("#recon-src-b");
  selA.innerHTML = opts;
  selB.innerHTML = opts;
  if (!reconState.a || !sources.some((s) => s.id === reconState.a)) {
    reconState.a = sources.length ? sources[0].id : "";
  }
  if (!reconState.b || !sources.some((s) => s.id === reconState.b)
      || reconState.b === reconState.a) {
    const other = sources.find((s) => s.id !== reconState.a);
    reconState.b = other ? other.id : "";
  }
  selA.value = reconState.a;
  selB.value = reconState.b;
}

/* --------------------------------------------------------------- 对账 */

async function reconRun() {
  if (!reconState.a || !reconState.b) return toast("请先选择两个来源", "error");
  if (reconState.a === reconState.b) return toast("对账需要两个不同的来源", "error");
  const tol = parseFloat(recon$("#recon-tol").value);
  const hint = recon$("#recon-hint");
  hint.textContent = "对账中…";
  const res = await fetch("/api/reconcile", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source_a: reconState.a,
      source_b: reconState.b,
      tolerance_ms: isNaN(tol) ? null : tol,
      // 页面当前（含未保存）的时钟假设参与区间计算
      overrides: state.overrides || {},
    }),
  });
  hint.textContent = "";
  if (!res.ok) {
    let msg = await res.text();
    try { msg = JSON.parse(msg).detail || msg; } catch { /* 保留原文 */ }
    reconState.result = null;
    recon$("#recon-result").innerHTML = "";
    return toast("对账失败: " + msg, "error");
  }
  reconState.result = await res.json();
  reconRender();
}

/* --------------------------------------------------------------- 渲染 */

function reconRender() {
  const d = reconState.result;
  const box = recon$("#recon-result");
  box.innerHTML = "";
  if (!d) return;
  box.appendChild(reconSummary(d));
  box.appendChild(reconPairsBlock(d));
  box.appendChild(reconUnmatchedBlock(d));
  if (d.notice) box.appendChild(el("div", "feas-note warn", esc(d.notice)));
}

function reconSummary(d) {
  const s = d.summary;
  const blk = el("div", "cmp-block");
  const dirty = Object.keys(state.overrides || {}).length > 0;
  blk.innerHTML = `<h3>对账概要
    <span class="cmp-count">${esc(d.source_a.name || d.source_a.id)} ⇄ ${esc(d.source_b.name || d.source_b.id)}
    · 容差 ${d.tolerance_ms} ms · 每侧上限 ${d.limits.max_side_events} 条
    ${dirty ? '<span class="tag amb">含未保存调整</span>' : ""}</span></h3>`;
  const meta = el("div", "sens-meta");
  meta.innerHTML = `
    <span class="stat">A 侧事件 <b>${s.events_a}</b></span>
    <span class="stat">B 侧事件 <b>${s.events_b}</b></span>
    <span class="stat">候选配对 <b>${s.candidate_pairs}</b></span>
    <span class="stat ${s.matched_pairs ? "" : "warn"}">已配对 <b>${s.matched_pairs}</b></span>
    <span class="stat ${s.unmatched_a ? "warn" : ""}">仅 A 有 <b>${s.unmatched_a}</b></span>
    <span class="stat ${s.unmatched_b ? "warn" : ""}">仅 B 有 <b>${s.unmatched_b}</b></span>
    <span class="stat">中点差合计 <b>${s.total_midpoint_diff_ms} ms</b></span>`;
  blk.appendChild(meta);
  return blk;
}

function reconPairsBlock(d) {
  const blk = el("div", "cmp-block");
  blk.innerHTML = `<h3>配对结果
    <span class="cmp-count">${d.pairs.length} 对 · 每条事件最多参与一对 · 点击事件 ID 在主时间线定位</span></h3>`;
  if (!d.pairs.length) {
    blk.appendChild(el("div", "cmp-empty",
      "当前容差与时钟假设下没有可配对的事件（要求 actor 相同且非空、类型相同、区间间距 ≤ 容差）。"));
    return blk;
  }
  const list = el("div", "recon-pairs");
  for (const p of d.pairs) {
    const row = el("div", "recon-pair");
    row.innerHTML = `
      <span class="recon-side">
        <span class="cmp-side-tag a">A</span>
        <span class="chain-node" data-eid="${esc(p.a.id)}" title="点击在主时间线定位">${esc(shortId(p.a.id))}</span>
        <span class="recon-mid" title="A 侧区间中点">${esc(p.a.midpoint_text.slice(11, 23))}</span>
      </span>
      <span class="recon-delta" title="配对双方区间中点差绝对值 / 两闭区间间距（均已四舍五入到整数毫秒）">
        Δ ${p.midpoint_diff_ms} ms · 间距 ${p.interval_distance_ms} ms</span>
      <span class="recon-side">
        <span class="cmp-side-tag b">B</span>
        <span class="chain-node" data-eid="${esc(p.b.id)}" title="点击在主时间线定位">${esc(shortId(p.b.id))}</span>
        <span class="recon-mid" title="B 侧区间中点">${esc(p.b.midpoint_text.slice(11, 23))}</span>
      </span>
      <span class="recon-tags">
        <span class="tag type">${esc(p.a.event_type)}</span>
        <span class="tag actor">👤 ${esc(p.a.actor)}</span>
      </span>`;
    row.querySelectorAll(".chain-node").forEach((n) =>
      n.addEventListener("click", () => { reconClose(); focusEvent(n.dataset.eid); }));
    list.appendChild(row);
  }
  blk.appendChild(list);
  return blk;
}

function reconUnmatchedBlock(d) {
  const blk = el("div", "cmp-block");
  blk.innerHTML = `<h3>未匹配事件
    <span class="cmp-count">只出现在单侧的记录：可能是一方漏采、actor/类型不一致，或间距超出容差</span></h3>`;
  const cols = el("div", "recon-unmatched");
  cols.appendChild(reconUnmatchedCol("a", d.source_a, d.unmatched.a));
  cols.appendChild(reconUnmatchedCol("b", d.source_b, d.unmatched.b));
  blk.appendChild(cols);
  return blk;
}

function reconUnmatchedCol(side, src, items) {
  const col = el("div", "recon-uncol");
  col.innerHTML = `<div class="recon-uncol-head ${side}">
    仅 ${side === "a" ? "A" : "B"} · ${esc(src.name || src.id)} 有
    <span class="cmp-badge ${items.length ? "added" : ""}">${items.length}</span></div>`;
  if (!items.length) {
    col.appendChild(el("div", "cmp-empty small", "该侧事件全部配对"));
    return col;
  }
  const list = el("div", "recon-unlist");
  for (const e of items) {
    const row = el("div", "recon-unrow");
    row.innerHTML = `
      <span class="chain-node" data-eid="${esc(e.id)}" title="点击在主时间线定位">${esc(shortId(e.id))}</span>
      <span class="recon-mid">${esc(e.midpoint_text.slice(11, 23))}</span>
      <span class="tag type">${esc(e.event_type)}</span>
      ${e.actor ? `<span class="tag actor">👤 ${esc(e.actor)}</span>` : '<span class="tag">无 actor</span>'}
      <span class="recon-unsummary" title="${esc(e.summary || "")}">${esc(e.summary || "")}</span>`;
    row.querySelector(".chain-node").addEventListener("click", () => {
      reconClose();
      focusEvent(e.id);
    });
    list.appendChild(row);
  }
  col.appendChild(list);
  return col;
}

/* --------------------------------------------------------------- 绑定 */

recon$("#btn-reconcile").addEventListener("click", reconOpen);
recon$("#recon-close").addEventListener("click", reconClose);
recon$("#recon-overlay").addEventListener("click", (e) => {
  if (e.target.id === "recon-overlay") reconClose();
});
recon$("#recon-run").addEventListener("click", reconRun);
recon$("#recon-src-a").addEventListener("change", (e) => { reconState.a = e.target.value; });
recon$("#recon-src-b").addEventListener("change", (e) => { reconState.b = e.target.value; });
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !recon$("#recon-overlay").classList.contains("hidden")) reconClose();
});
