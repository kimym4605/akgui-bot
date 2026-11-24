// 🗺️ 전술판 곡선 함수 테스트 (node scripts/test_tactics_curve.js)
// board.html에서 "곡선" 구간(smoothD·simplify·finishPts)만 떼어 돌려요. 화면(DOM)은 안 씀.
"use strict";
const fs = require("fs");
const path = require("path");
const html = fs.readFileSync(path.join(__dirname, "..", "config", "tactics", "board.html"), "utf8");
const a = html.indexOf("// ---------------------------------------------------------------- 곡선");
const b = html.indexOf("function midOf(");
if (a < 0 || b < 0) { console.log("❌ 곡선 구간을 못 찾음"); process.exit(1); }
const X = (u) => u * 1000, Y = (v) => v * 1000;
const dist = (p, q) => Math.hypot(p[0] - q[0], p[1] - q[1]);
const lib = new Function("X", "Y", "dist", html.slice(a, b) +
  "; return { smoothD, simplify, finishPts, clampPath, pathLen, fitLine };")(X, Y, dist);

let failed = 0;
const check = (name, ok) => { console.log((ok ? "  ✅ " : "  ❌ ") + name); if (!ok) failed++; };

// 손떨림 섞인 곧은 선 → 양 끝 두 점만
const shaky = [];
for (let i = 0; i <= 50; i++) shaky.push([0.1 + i * 0.006, 0.5 + (i % 2 ? 0.001 : -0.001)]);
check("손떨림 직선은 2점으로", lib.simplify(shaky).length === 2);

// 직각으로 꺾인 선 → 꺾인 점 유지
const corner = [];
for (let i = 0; i <= 20; i++) corner.push([0.1 + i * 0.01, 0.1]);
for (let i = 1; i <= 20; i++) corner.push([0.3, 0.1 + i * 0.01]);
const sc = lib.simplify(corner);
check("꺾인 선은 꺾인 점이 남음", sc.length === 3 && Math.abs(sc[1][0] - 0.3) < 1e-9 && Math.abs(sc[1][1] - 0.1) < 1e-9);

// 원호 → 점은 줄지만 2개보다 많음, 64개 이하
const arc = [];
for (let i = 0; i <= 300; i++) { const t = (Math.PI * i) / 300; arc.push([0.5 + 0.2 * Math.cos(t), 0.5 + 0.2 * Math.sin(t)]); }
const fa = lib.finishPts(arc);
check("곡선은 모양을 살려 줄임(3~64점)", fa.length > 3 && fa.length <= 64);
check("처음·끝 점 유지", fa[0][0] === +arc[0][0].toFixed(4) && fa[fa.length - 1][1] === +arc[300][1].toFixed(4));

const d = lib.smoothD([[0.1, 0.1], [0.2, 0.3], [0.4, 0.2]]);
check("곡선 경로는 M으로 시작해 C로 이어짐", d.startsWith("M100,100") && (d.match(/C/g) || []).length === 2);
check("두 점이면 직선 경로", lib.smoothD([[0.1, 0.1], [0.2, 0.2]]) === "M100,100 L200,200");

// 최대 길이 자르기 (만조 등)
const long = [[0, 0], [0.3, 0], [0.3, 0.3]];
const cut = lib.clampPath(long, 0.4);
check("최대 길이에서 자름(0.4)", Math.abs(lib.pathLen(cut) - 0.4) < 1e-9 && Math.abs(cut[cut.length - 1][1] - 0.1) < 1e-9);
check("짧으면 그대로", lib.clampPath(long, 5).length === 3);
check("최대 없음(0)이면 그대로", lib.clampPath(long, 0) === long);

// 곧은 벽: 고정 길이·최대 길이
const fixed = lib.fitLine([0.5, 0.5], [0.9, 0.5], { fixed: 0.05 });
check("고정 길이 벽은 그 길이", Math.abs(dist([0.5, 0.5], fixed) - 0.05) < 1e-9 && fixed[0] > 0.5);
const maxed = lib.fitLine([0.1, 0.1], [0.9, 0.1], { max: 0.3 });
check("최대 길이 넘으면 잘림", Math.abs(maxed[0] - 0.4) < 1e-9);
const short = lib.fitLine([0.1, 0.1], [0.2, 0.1], { max: 0.3 });
check("최대 안이면 끈 만큼", Math.abs(short[0] - 0.2) < 1e-9);
const same = lib.fitLine([0.1, 0.1], [0.1, 0.1], { fixed: 0.05 });
check("제자리 누름도 고정 길이(오른쪽)", Math.abs(same[0] - 0.15) < 1e-9);

console.log(failed ? `\n❌ 실패 ${failed}개` : "\n✅ 곡선 함수 테스트 전부 통과");
process.exit(failed ? 1 : 0);
