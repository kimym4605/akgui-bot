// 👥 전술판 동기화 함수 테스트 (node scripts/test_tactics_sync.js)
// board.html의 "동기화(순수 함수)" 구간(clone·same·diffState·applyOps·rebase)만 떼어 돌려요. 화면(DOM)은 안 씀.
//
//   node scripts/test_tactics_sync.js          자체 검사 + 두 사람이 동시에 고치는 모의 실험
//   node scripts/test_tactics_sync.js --dump   연산 사례를 JSON으로 출력 → scripts/test_tactics.py가
//                                              서버(`utils/tactics.py` apply_op)와 결과가 같은지 맞춰 봐요
"use strict";
const fs = require("fs");
const path = require("path");
const html = fs.readFileSync(path.join(__dirname, "..", "config", "tactics", "board.html"), "utf8");
const a = html.indexOf("// ---------------------------------------------------------------- 동기화(순수 함수)");
const b = html.indexOf("// ---------------------------------------------------------------- 동기화 끝");
if (a < 0 || b < 0) { console.log("❌ 동기화 구간을 못 찾음"); process.exit(1); }
const { clone, same, diffState, applyOps, rebase } =
  new Function(html.slice(a, b) + "; return { clone, same, diffState, applyOps, rebase };")();

// 씨앗 고정 난수 (실패하면 다시 돌려 볼 수 있게)
let seed = 20261125;
const rnd = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
const pick = (arr) => arr[Math.floor(rnd() * arr.length)];
let idN = 0;
const nid = () => "i" + (idN++).toString(36);
const num = () => +rnd().toFixed(4);

function randItem() {
  const kind = pick(["agent", "ability", "arrow", "text"]);
  const it = { id: nid(), type: kind, team: pick(["ally", "enemy"]), u: num(), v: num() };
  if (kind === "agent") it.agent = pick(["o", "j"]);
  if (kind === "ability") { it.agent = pick(["o", "j"]); it.slot = pick(["Q", "E", "C", "X"]); }
  if (kind === "arrow") { it.u2 = num(); it.v2 = num(); }
  if (kind === "text") it.text = "글" + Math.floor(rnd() * 100);
  return it;
}
function randState() {
  const scenes = [];
  for (let i = 0, n = 1 + Math.floor(rnd() * 3); i < n; i++) {
    const items = [];
    for (let k = 0, m = Math.floor(rnd() * 4); k < m; k++) items.push(randItem());
    scenes.push({ sid: nid(), title: rnd() < 0.3 ? "장면" + i : "", items });
  }
  return { title: "제목", side: "atk", scenes };
}
// 편집기가 하는 일 하나를 흉내 내요(제자리 수정).
function mutate(st) {
  const sc = pick(st.scenes), r = rnd();
  if (r < 0.30) sc.items.push(randItem());
  else if (r < 0.50 && sc.items.length) { const it = pick(sc.items); it.u = num(); it.v = num(); }
  else if (r < 0.65 && sc.items.length) sc.items.splice(Math.floor(rnd() * sc.items.length), 1);
  else if (r < 0.72) sc.title = "t" + Math.floor(rnd() * 50);
  else if (r < 0.78) st.title = "제목" + Math.floor(rnd() * 50);
  else if (r < 0.83) st.side = st.side === "atk" ? "def" : "atk";
  else if (r < 0.92 && st.scenes.length < 6) {
    const i = st.scenes.indexOf(sc);
    st.scenes.splice(i + 1, 0, { sid: nid(), title: "", items: clone(sc.items).map((it) => ({ ...it, id: nid() })) });
  } else if (st.scenes.length > 1) st.scenes.splice(st.scenes.indexOf(sc), 1);
}
// 비교용: 항목 순서와 키 순서는 안 따져요(장면 순서는 따져요).
function canon(st) {
  const key = (o) => JSON.stringify(o, Object.keys(o).sort());
  return JSON.stringify({ title: st.title, side: st.side, scenes: st.scenes.map((s) => ({
    sid: s.sid, title: s.title || "", items: s.items.map(key).sort() })) });
}

if (process.argv.includes("--dump")) {
  // 서버와 맞춰 볼 사례: 시작 상태 + 연산 목록 + 이쪽(applyOps) 결과
  const cases = [];
  for (let n = 0; n < 60; n++) {
    const base = randState(), ops = [];
    let cur = clone(base);
    for (let k = 0; k < 6; k++) { const next = clone(cur); mutate(next); ops.push(...diffState(cur, next)); cur = next; }
    // 일부러 겹치게: 앞쪽 연산 몇 개를 한 번 더(다시 붙었을 때 재전송), 없는 것 지우기·고치기
    const extra = ops.slice(0, 3).concat([{ t: "del", sid: base.scenes[0].sid, id: "none" },
      { t: "upd", sid: base.scenes[0].sid, item: { id: "none", type: "agent", agent: "o", team: "ally", u: 0.5, v: 0.5 } },
      { t: "sdel", sid: "none" }, { t: "stitle", sid: "none", title: "x" }]);
    const all = ops.concat(extra);
    cases.push({ base, ops: all, result: JSON.parse(canon(applyOps(clone(base), all))) });
  }
  console.log(JSON.stringify(cases));
  process.exit(0);
}

let failed = 0;
const check = (name, ok, detail) => { console.log((ok ? "  ✅ " : "  ❌ ") + name + (!ok && detail ? " — " + detail : "")); if (!ok) failed++; };

console.log("[1] 차이 → 연산 → 적용");
const s0 = randState();
check("같으면 연산 없음", diffState(s0, clone(s0)).length === 0);
check("키 순서만 다르면 같은 항목", same({ id: "a", u: 1, v: 2 }, { v: 2, u: 1, id: "a" }) && !same({ id: "a", u: 1 }, { id: "a", u: 2 }));
let bad = 0, twice = 0, total = 0;
for (let n = 0; n < 400; n++) {
  const base = randState(), now = clone(base);
  for (let k = 0, m = 1 + Math.floor(rnd() * 6); k < m; k++) mutate(now);
  const ops = diffState(base, now);
  const got = applyOps(clone(base), ops);
  total++;
  if (canon(got) !== canon(now)) bad++;
  if (canon(applyOps(clone(got), ops)) !== canon(got)) twice++;
}
check(`차이를 적용하면 목표 상태가 됨 (${total}번)`, bad === 0, `${bad}번 다름`);
check("같은 연산을 두 번 적용해도 같음", twice === 0, `${twice}번 다름`);
const one = { title: "", side: "atk", scenes: [{ sid: "a", title: "", items: [] }] };
check("마지막 장면은 못 지움", applyOps(clone(one), [{ t: "sdel", sid: "a" }]).scenes.length === 1);
const swap = diffState(one, { title: "", side: "atk", scenes: [{ sid: "b", title: "", items: [] }] });
check("장면을 통째로 바꿀 땐 넣고 나서 지움", swap[0].t === "sadd" && swap[1].t === "sdel");
const ten = { title: "", side: "atk", scenes: [] };
for (let i = 0; i < 10; i++) ten.scenes.push({ sid: "s" + i, title: "", items: [] });
const ten2 = clone(ten); ten2.scenes.splice(9, 1, { sid: "new", title: "", items: [] });
const order = diffState(ten, ten2).map((o) => o.t);
check("장면 10개에서 하나를 바꿀 땐 지우고 나서 넣음(한도 안 넘김)", order[0] === "sdel" && order[1] === "sadd");
check("없는 장면·항목 연산은 조용히 건너뜀", canon(applyOps(clone(s0), [
  { t: "del", sid: "none", id: "x" }, { t: "upd", sid: s0.scenes[0].sid, item: { id: "none", type: "text", text: "x", u: 0, v: 0, team: "ally" } },
  { t: "stitle", sid: "none", title: "x" }, { t: "sdel", sid: "none" }])) === canon(s0));

console.log("[2] 두~세 사람이 동시에 고치는 모의 실험 (서버 순서대로 다시 쌓기)");
// 서버: 받은 순서대로 적용하고, 다른 사람에게는 연산을, 보낸 사람에게는 확인(ack)을 줘요.
function simulate(people, steps) {
  const start = randState();
  const server = clone(start);
  const toServer = [];                                   // [{from, n, ops}]
  const cs = [];
  for (let i = 0; i < people; i++)
    cs.push({ local: clone(start), synced: clone(start), confirmed: clone(start), unacked: [], inbox: [], seq: 0 });
  const flush = (c, i) => {
    const ops = diffState(c.synced, c.local);
    if (!ops.length) return;
    const batch = { n: ++c.seq, ops };
    c.unacked.push(batch); toServer.push({ from: i, ...batch }); c.synced = clone(c.local);
  };
  const serve = () => {
    const m = toServer.shift(); if (!m) return;
    applyOps(server, m.ops);
    cs.forEach((c, i) => c.inbox.push(i === m.from ? { t: "ack", n: m.n } : { t: "ops", ops: clone(m.ops) }));
  };
  const receive = (c) => {
    const m = c.inbox.shift(); if (!m) return;
    if (m.t === "ack") {
      const i = c.unacked.findIndex((x) => x.n === m.n);
      applyOps(c.confirmed, c.unacked[i].ops); c.unacked.splice(i, 1);
      return;
    }
    applyOps(c.confirmed, m.ops);
    const sent = []; for (const x of c.unacked) sent.push(...x.ops);
    const r = rebase(c.confirmed, sent, c.synced, c.local);
    c.synced = r.synced; c.local = r.local;
  };
  for (let s = 0; s < steps; s++) {
    const i = Math.floor(rnd() * people), c = cs[i], r = rnd();
    if (r < 0.35) mutate(c.local);
    else if (r < 0.55) flush(c, i);
    else if (r < 0.78) serve();
    else receive(c);
  }
  cs.forEach(flush);                                     // 남은 것 전부 흘려보내기
  while (toServer.length) serve();
  let moved = true;
  while (moved) {
    moved = false;
    for (const c of cs) while (c.inbox.length) { receive(c); moved = true; }
    cs.forEach(flush);
    while (toServer.length) { serve(); moved = true; }
  }
  const want = canon(server);
  return cs.every((c) => canon(c.local) === want && canon(c.confirmed) === want && !c.unacked.length);
}
let diverged = 0;
for (let n = 0; n < 300; n++) if (!simulate(2 + (n % 2), 60 + Math.floor(rnd() * 120))) diverged++;
check("300번 모두 서버와 모든 화면이 같아짐", diverged === 0, `${diverged}번 어긋남`);

console.log(failed ? `\n❌ 실패 ${failed}개` : "\n✅ 동기화 함수 테스트 전부 통과");
process.exit(failed ? 1 : 0);
