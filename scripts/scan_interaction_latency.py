"""🚨 "첫 응답보다 앞에 왕복(네트워크·DB)이 있는" 상호작용 핸들러를 전수로 찾아요.

## 왜 스크립트로 두나

상호작용 토큰은 **첫 응답까지 3초**다. 넘기면 `404 Unknown interaction`이고, 유저에게는
"앱이 응답하지 않았습니다"만 남는다. 더 나쁜 건 그 순서다 — DB를 먼저 건드리고 응답을
나중에 하면 **일은 벌어졌는데 화면만 안 뜬다**(2026-10-17 🎣 다시던지기, 🛒 상점이 그랬다).

이름 목록으로 훑으면 또 빠뜨린다. 그래서 AST로 전수 검사한다.
2026-10-18에 이 스크립트로 team.py 4곳 · notify.py 1곳 · onboarding.py 11곳을 고쳤다.

## 판정 규칙 — **분기(경로)별로** 본다

핸들러(인자에 `interaction`/`inter`를 받는 async 함수)의 본문을 **실행 순서대로** 따라가며
"아직 응답 안 한 상태에서 왕복 await를 했고, 그 뒤에 응답한다"를 찾는다.

🚨 **여기서 두 번 틀렸으니 적어둔다**(2026-10-18):
  1. `ast.walk`은 소스 순서가 아니라 **너비 우선**이다. 줄번호로 정렬해야 한다.
  2. "첫 응답에서 멈추기"도 "안 멈추기"도 둘 다 틀렸다. 권한 검사처럼 **앞에서 먼저 답하고
     돌아가는 길**이 있으면 그 응답에서 멈추면 뒤쪽 위험을 놓치고(위음성 11건), 반대로 안
     멈추면 `ack` 뒤의 followup까지 전부 걸린다(오탐 70건). 그래서 `if`/`try`의 **갈래마다
     상태를 따로 들고 가다가 합친다**(`return`한 갈래는 죽은 길로 빼고).

왕복으로 세지 않는 것:
  - `interaction.response.*` / `followup.*` / `edit_original_response` / `send_modal` — 응답이다.
  - `ack(...)` — `utils/interaction_ack.py`. defer라서 **이게 곧 첫 응답**이다.
  - 같은 파일의 **응답 전용 헬퍼**(자기 몸통에 응답 말고 다른 await가 없는 함수, 예:
    `team._fresh`·`vp._reply`) — 위임받아 응답만 하므로 왕복이 아니다. 단 조건부로만
    응답할 수 있으니 **"받아둔 것"으로는 쳐주지 않는다.**
  - 같은 파일의 **먼저 받아두는 함수**(첫 await가 `ack`/응답인 함수, 예: `casino.take_bet`)
    — 위임하면 그쪽에서 이미 받았으므로 그 call을 응답으로 센다.

이 스크립트가 **놓치는 구멍**(= 손으로 따라가야 하는 자리):
  - 다른 파일/모듈로 위임해서 그쪽이 받아두는 경우는 판정하지 못한다(파일 단위로 본다).
  - `asyncio.create_task`로 떼어낸 왕복은 안 걸린다(그게 맞다).

## 쓰는 법

    python scripts/scan_interaction_latency.py          # 걸린 게 있으면 종료코드 1
    python scripts/scan_interaction_latency.py --all    # 파일별 핸들러 수까지

-> reference_discord_interaction_3s_token (메모리)
"""
import argparse
import ast
import pathlib
import sys

COGS = pathlib.Path(__file__).resolve().parent.parent / "cogs"

# 🚨 **첫 응답**이에요. 3초 안에 여기까지 와야 해요.
FIRST_RESPONSE_MARKERS = (".response.",)
# ⭐ 이건 "이미 누가 받아둔 뒤"에만 쓸 수 있는 것들이에요(안 받아뒀으면 아예 터져요).
#    그래서 함수가 이것만 쓰면 **부르는 쪽이 이미 받아둔** 증거예요 — 안 걸려야 해요.
#    (예: `card_gacha.do_pull`·`fishing.finish_cast`는 버튼 핸들러가 ack한 뒤에 불려요)
POST_ACK_MARKERS = ("followup.", "edit_original_response")
# defer를 감싼 공용 헬퍼(utils/interaction_ack.py). 이게 곧 첫 응답이에요.
ACK_NAMES = ("ack",)

RESPONSE_MARKERS = FIRST_RESPONSE_MARKERS + POST_ACK_MARKERS

RESP, SKIP, RISKY = "resp", "skip", "risky"


def _is_response_expr(text: str) -> bool:
    return any(marker in text for marker in RESPONSE_MARKERS)


def _call_name(node: ast.AST) -> str:
    """`await self._fresh(it)` → `_fresh`, `await ack(it)` → `ack`."""
    if not isinstance(node, ast.Call):
        return ""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _awaits_in(node: ast.AST, *, shallow: bool = False) -> list[ast.Await]:
    """이 노드 안의 await들을 줄번호 순으로. 중첩 함수는 빼요.

    `shallow=True`면 **복합문의 몸통은 보지 않아요**(if/for/try는 갈래별로 따로 보니까요)."""
    out = []
    for child in ast.walk(node):
        if isinstance(child, (ast.AsyncFunctionDef, ast.FunctionDef, ast.Lambda)):
            continue
        if isinstance(child, ast.Await):
            out.append(child)
    out.sort(key=lambda n: (n.lineno, n.col_offset))
    return out


# ── 함수별 성격 판정 ────────────────────────────────────────────────
def _own_await_texts(func: ast.AST) -> list[tuple[int, str, str]]:
    out = []
    for node in _awaits_in(func):
        try:
            out.append((node.lineno, ast.unparse(node.value), _call_name(node.value)))
        except Exception:  # noqa: BLE001
            continue
    return out


def _responder_only(func: ast.AST) -> bool:
    """응답만 await하는 헬퍼인가요? (왕복이 아니지만 '받아둔 것'으로는 안 쳐요)"""
    awaits = _own_await_texts(func)
    return bool(awaits) and all(
        _is_response_expr(t) or n in ACK_NAMES for _, t, n in awaits
    )


def _secures_first(func: ast.AST) -> bool:
    """**첫 await가 응답/ack**인가요? 그러면 이 함수에 맡기면 이미 받아둔 셈이에요."""
    awaits = _own_await_texts(func)
    if not awaits:
        return False
    _, text, name = awaits[0]
    return _is_response_expr(text) or name in ACK_NAMES


# ── 경로를 따라가는 본체 ─────────────────────────────────────────────
class _State:
    __slots__ = ("secured", "risky", "dead")

    def __init__(self, secured=False, risky=None, dead=False):
        self.secured = secured
        self.risky = risky      # (lineno, text) — 아직 응답 전에 한 왕복
        self.dead = dead        # return/raise로 끝난 길

    def copy(self) -> "_State":
        return _State(self.secured, self.risky, self.dead)


def _merge(states: list[_State]) -> _State:
    live = [s for s in states if not s.dead]
    if not live:
        return _State(dead=True)
    secured = all(s.secured for s in live)
    risky = None if secured else next((s.risky for s in live if s.risky), None)
    return _State(secured, risky)


class _Scanner:
    def __init__(self, filename: str, responder: set[str], securing: set[str]):
        self.filename = filename
        self.responder = responder
        self.securing = securing
        self.findings: list[str] = []
        self._double: list[str] = []      # 받아둔 뒤 또 response.*를 쓴 자리
        self._func: ast.AST | None = None
        self._reported: set[tuple[str, int]] = set()

    def classify(self, node: ast.Await) -> tuple[str, int, str]:
        try:
            text = ast.unparse(node.value)
        except Exception:  # noqa: BLE001
            return SKIP, node.lineno, "?"
        name = _call_name(node.value)
        if _is_response_expr(text) or name in ACK_NAMES:
            return RESP, node.lineno, text
        if name in self.responder:
            return SKIP, node.lineno, text
        if name in self.securing:
            return RESP, node.lineno, text
        return RISKY, node.lineno, text

    def _report(self, state: _State, lineno: int):
        # 갈래마다 또 알려주면 시끄러워요. 함수당 한 번만.
        # 🚨 이름만으로 세면 안 돼요 — onboarding엔 `confirm_button`이 **셋**이라
        #    하나만 보고하고 둘을 삼켰어요. 줄번호까지 넣어서 구분해요.
        key = (self._func.name, self._func.lineno)
        if key in self._reported:
            return
        self._reported.add(key)
        risky_line, risky_text = state.risky
        self.findings.append(
            f"{self.filename}:{self._func.lineno} {self._func.name}() — "
            f"L{risky_line} `{risky_text[:70]}` 가 L{lineno} 응답보다 앞에 있어요"
        )

    def exprs(self, nodes: list[ast.AST], state: _State):
        """단순문(또는 복합문의 조건식)에 들어 있는 await들을 순서대로 처리해요."""
        awaits = []
        for node in nodes:
            awaits.extend(_awaits_in(node))
        awaits.sort(key=lambda n: (n.lineno, n.col_offset))
        for node in awaits:
            kind, lineno, _text = self.classify(node)
            if kind == RESP:
                first_kind = any(m in _text for m in FIRST_RESPONSE_MARKERS)
                if state.secured and first_kind:
                    # 🚨 반대 방향 사고예요. 받아둔 뒤에 `interaction.response.*`를 또
                    #    쓰면 `InteractionResponded`로 터져요(followup/edit_original을
                    #    써야 해요). ack를 넣다가 치환을 빠뜨리면 여기서 걸려요.
                    self._double.append(
                        f"{self.filename}:{self._func.lineno} {self._func.name}() — "
                        f"L{lineno} `{_text[:70]}` 는 이미 받아둔 뒤라 터져요"
                    )
                if not state.secured and state.risky is not None:
                    self._report(state, lineno)
                    state.risky = None      # 같은 함수에서 한 번만 알려줘요
                state.secured = True
            elif kind == RISKY and not state.secured and state.risky is None:
                state.risky = (lineno, _text)

    def block(self, stmts: list[ast.stmt], state: _State) -> _State:
        for stmt in stmts:
            if state.dead:
                break
            if isinstance(stmt, (ast.AsyncFunctionDef, ast.FunctionDef, ast.ClassDef)):
                continue
            if isinstance(stmt, ast.If):
                self.exprs([stmt.test], state)
                a = self.block(stmt.body, state.copy())
                b = self.block(stmt.orelse, state.copy()) if stmt.orelse else state.copy()
                state = _merge([a, b])
            elif isinstance(stmt, ast.Try):
                self.exprs([], state)
                entry = state.copy()
                body = self.block(stmt.body, entry.copy())
                # 🚨 `except`는 **그 왕복이 이미 시작된 뒤**에 돌아요. 그래서 핸들러의
                #    시작 상태에 body에서 생긴 왕복을 물려줘요(안 그러면 `except
                #    Forbidden`에서 답하는 자리를 놓쳐요 — onboarding 2곳이 그랬어요).
                caught = _State(entry.secured, entry.risky or body.risky)
                branches = [body] + [
                    self.block(h.body, caught.copy()) for h in stmt.handlers
                ]
                if stmt.orelse:
                    branches.append(self.block(stmt.orelse, body.copy()))
                state = _merge(branches)
                if stmt.finalbody:
                    state = self.block(stmt.finalbody, state)
            elif isinstance(stmt, (ast.For, ast.AsyncFor)):
                self.exprs([stmt.iter], state)
                body = self.block(stmt.body, state.copy())
                state = _merge([state.copy(), body])   # 한 번도 안 돌 수 있어요
            elif isinstance(stmt, ast.While):
                self.exprs([stmt.test], state)
                body = self.block(stmt.body, state.copy())
                state = _merge([state.copy(), body])
            elif isinstance(stmt, (ast.With, ast.AsyncWith)):
                self.exprs([item.context_expr for item in stmt.items], state)
                state = self.block(stmt.body, state)
            elif isinstance(stmt, ast.Match):
                self.exprs([stmt.subject], state)
                branches = [self.block(c.body, state.copy()) for c in stmt.cases]
                branches.append(state.copy())          # 아무 case도 안 맞을 수 있어요
                state = _merge(branches)
            elif isinstance(stmt, (ast.Return, ast.Raise)):
                self.exprs([stmt], state)
                state.dead = True
            elif isinstance(stmt, (ast.Break, ast.Continue)):
                state.dead = True
            else:
                self.exprs([stmt], state)
        return state

    def run(self, func: ast.AST):
        self._func = func
        # ⭐ 자기 몸통에 `interaction.response.*`도 `ack`도 없고 followup만 쓰면,
        #    **부르는 쪽이 이미 받아둔 핸들러**예요(안 받아뒀으면 followup이 터져요).
        own = _own_await_texts(func)
        secures_here = any(
            any(m in t for m in FIRST_RESPONSE_MARKERS) or n in ACK_NAMES for _, t, n in own
        )
        uses_followup = any(any(m in t for m in POST_ACK_MARKERS) for _, t, _ in own)
        self.block(func.body, _State(secured=uses_followup and not secures_here))


def _handlers(tree: ast.AST) -> list[ast.AST]:
    return [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
        and any(a.arg in ("interaction", "inter") for a in node.args.args)
    ]


def scan_file(path: pathlib.Path) -> tuple[list[str], int]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    funcs = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
    ]
    responder = {f.name for f in funcs if _responder_only(f)}
    securing = {f.name for f in funcs if _secures_first(f)} - responder

    handlers = _handlers(tree)
    scanner = _Scanner(path.name, responder, securing)
    for func in handlers:
        scanner.run(func)
    return scanner.findings + scanner._double, len(handlers)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="파일별 핸들러 수도 보여줘요")
    args = parser.parse_args()

    total_handlers = 0
    all_findings = []
    for path in sorted(COGS.glob("*.py")):
        findings, handlers = scan_file(path)
        total_handlers += handlers
        all_findings.extend(findings)
        if args.all:
            mark = "⚠️" if findings else "✅"
            print(f"{mark} {path.name}: 핸들러 {handlers}개 / 걸린 것 {len(findings)}개")

    print()
    print(f"상호작용 핸들러 {total_handlers}개를 훑었어요 — 걸린 것 {len(all_findings)}개")
    for line in all_findings:
        print(f"  🚨 {line}")
    if not all_findings:
        print("  ✅ 첫 응답 앞에 왕복이 있는 핸들러가 없어요.")
    return 1 if all_findings else 0


if __name__ == "__main__":
    sys.exit(main())
