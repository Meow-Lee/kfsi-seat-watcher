"""한국소방안전원 강습교육 결원 감시 → 카카오톡/텔레그램 알림.

사용법:
  python watcher.py                # 감시 시작 (interval_sec 마다 확인, deadline 에 자동 종료)
  python watcher.py --kakao-auth   # 보내는 사람(나) 카카오 인증 → 토큰 발급
  python watcher.py --kakao-consent  # 받는 사람 카카오 동의 (친구에게 보내기용, 토큰은 따로 보관)
  python watcher.py --kakao-friends  # 메시지 보낼 수 있는 친구 목록(uuid) 출력
  python watcher.py --cron --state-dir state  # 한 번 확인 후 종료 (GitHub Actions 용, 상태는 state-dir 에 유지)
  python watcher.py --once         # 한 번만 확인하고 결과 출력 (알림 없음)
  python watcher.py --test-notify  # 설정된 모든 채널로 테스트 메시지
  python watcher.py --simulate-open  # 결원 발생을 가정하고 실제 알림 전송
"""
import argparse
import json
import re
import sys
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from notifiers import KakaoNotifier, TelegramNotifier, notify_all

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
STATE_PATH = BASE_DIR / "state.json"
TOKEN_PATH = BASE_DIR / "kakao_token.json"
RECEIVER_TOKEN_PATH = BASE_DIR / "kakao_token_receiver.json"
LOG_PATH = BASE_DIR / "watcher.log"

SITE = "https://safe.kfsi.or.kr"
GRID_URL = SITE + "/edu/training/ajax/TrainingApplyGridList.do?tcd={tcd}&eduTask=ALL&viewName=common/schdule/gridBody/trainingGridBody"
APPLY_URL = SITE + "/edu/training/trainingApplyList.do?tcd={tcd}"

FAIL_ALERT_THRESHOLD = 3
OPEN_ALERT_MAX = 2  # 결원 상태가 유지되면 다음 확인 때 한 번 더 알림

ROW_RE = re.compile(r"<tr\b([^>]*)>(.*?)</tr>", re.S)
TD_RE = re.compile(r"<td\b[^>]*>(.*?)</td>", re.S)
TAG_RE = re.compile(r"<[^>]+>")


def log(msg: str) -> None:
    line = f"[{datetime.now():%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def text_of(fragment: str) -> str:
    return " ".join(TAG_RE.sub(" ", fragment).split())


@dataclass
class Slot:
    date: str
    place: str
    status_cd: str
    label: str
    seats: Optional[int]

    @property
    def is_open(self) -> bool:
        # 사이트의 "신청 가능한 교육만 보기" 필터와 같은 기준. 잔여 인원만으로 판단하면
        # 접수기간이 끝난 뒤 자리가 남아 있어도 신청 불가인 경우 오알림이 난다.
        return self.status_cd == "1"

    def describe(self) -> str:
        seats = "?" if self.seats is None else f"{self.seats}명"
        return f"{self.place} {self.date} / 상태={self.label}(코드 {self.status_cd}) / 잔여 {seats}"

    def short(self) -> str:
        return f"{self.label}, 잔여 {'?' if self.seats is None else self.seats}명"


def fetch(tcd: str) -> str:
    req = urllib.request.Request(GRID_URL.format(tcd=tcd), headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Referer": APPLY_URL.format(tcd=tcd),
        "X-Requested-With": "XMLHttpRequest",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", "replace")


def find_target(html: str, target: dict) -> Optional[Slot]:
    """지부코드 + 교육장소 + 시작일이 모두 일치하는 일정 행을 찾는다."""
    for m in ROW_RE.finditer(html):
        attrs, body = m.group(1), m.group(2)
        if f'data-jibu-cd="{target["jibu_cd"]}"' not in attrs:
            continue
        cells = [text_of(td) for td in TD_RE.findall(body)]
        if not cells or not cells[0].startswith(target["start_date"]) or target["place"] not in cells:
            continue

        status = re.search(r'data-kfsi-rcpt-stts-cd="(\d+)"', attrs)
        # 바로 다음 collapse 행(다음 일정 행 전까지)에 '교육접수 가능한 인원 : N명' 이 있다
        rest = html[m.end():]
        nxt = rest.find("data-jibu-cd=")
        seats = re.search(r"가능한 인원\s*:\s*(\d+)\s*명", rest if nxt < 0 else rest[:nxt])
        return Slot(
            date=re.sub(r"\s*\[\d+\]", "", cells[0]),
            place=target["place"],
            status_cd=status.group(1) if status else "?",
            label=cells[-1] or "?",
            seats=int(seats.group(1)) if seats else None,
        )
    return None


def check(target: dict) -> Slot:
    slot = find_target(fetch(target["tcd"]), target)
    if slot is None:
        raise LookupError("대상 일정 행을 찾지 못함 (사이트 구조 변경 또는 일정 삭제)")
    return slot


def load_json(path: Path, default: dict) -> dict:
    return json.loads(path.read_text("utf-8")) if path.exists() else default


def build_notifiers(cfg: dict) -> list:
    candidates = [KakaoNotifier(cfg.get("kakao", {}), TOKEN_PATH), TelegramNotifier(cfg.get("telegram", {}))]
    return [n for n in candidates if n.configured]


def open_message(slot: Slot, target: dict) -> str:
    seats = "" if slot.seats is None else f" 잔여 {slot.seats}명"
    # 사이트가 지역 필터를 URL 로 받지 않으므로 화면에서 고를 지역을 안내한다
    return (f"🚨 결원 발생!{seats}\n{target['label']}\n{slot.date} ({slot.place})\n"
            f"지금 바로 신청하세요. (지역: {target.get('region', '')} 선택)")


def tick(cfg: dict, notifiers: list, state: dict) -> bool:
    """한 번 확인하고 필요한 알림을 보낸 뒤 state 를 저장한다. 감시 기한이 지났으면 False."""
    target = cfg["target"]
    apply_url = APPLY_URL.format(tcd=target["tcd"])
    deadline = datetime.fromisoformat(cfg["deadline"])
    interval = int(cfg.get("interval_sec", 300))

    def send(text: str, link: Optional[str] = apply_url) -> None:
        # 링크가 없으면 카카오가 등록 도메인 첫 화면(사이트 메인)으로 보내므로 모든 메시지에 신청 페이지를 건다
        if not notify_all(notifiers, text, link, log=log):
            log("  !! 모든 알림 채널 전송 실패")

    if datetime.now() >= deadline:
        if not state.get("ended"):
            log("감시 기한 도달 → 종료")
            send(f"⏹ 감시 기한({deadline:%m/%d %H:%M})이 지나 결원 감시를 종료합니다.")
            state["ended"] = True
            STATE_PATH.write_text(json.dumps(state), "utf-8")
        return False

    try:
        slot = check(target)
        log(slot.describe())
        if state["fails"] >= FAIL_ALERT_THRESHOLD:
            send("✅ 사이트 확인이 다시 정상화되었습니다.")
        state["fails"] = 0
        status = "OPEN" if slot.is_open else "CLOSED"

        if not state["started"]:
            state["started"] = True
            send(f"👀 결원 감시 시작 ({interval // 60}분 간격, {deadline:%m/%d %H:%M}까지)\n"
                 f"{target['label']}\n현재: {slot.short()}")
        if status == "OPEN":
            if state["status"] != "OPEN":
                state["open_alerts"] = 0
            if state["open_alerts"] < OPEN_ALERT_MAX:
                send(open_message(slot, target))
                state["open_alerts"] += 1
        elif state["status"] == "OPEN":
            send(f"🔒 다시 마감되었습니다. ({slot.short()})")
        state["status"] = status
    except Exception as e:
        state["fails"] += 1
        log(f"확인 실패 ({state['fails']}회 연속): {e}")
        if state["fails"] == FAIL_ALERT_THRESHOLD:
            send(f"⚠️ 사이트 확인이 {state['fails']}회 연속 실패했습니다.\n{e}\n직접 확인해 주세요.")
    STATE_PATH.write_text(json.dumps(state), "utf-8")
    return True


def load_state(fresh: bool) -> dict:
    """fresh=True(PC 상시 실행)면 시작 알림과 실패 횟수를 새로 시작한다."""
    state = {"status": None, "open_alerts": 0, "fails": 0, "started": False, "ended": False}
    if STATE_PATH.exists():
        state.update(json.loads(STATE_PATH.read_text("utf-8")))
    if fresh:
        state.update(fails=0, started=False, ended=False)
    return state


def run(cfg: dict, notifiers: list) -> None:
    state = load_state(fresh=True)
    while tick(cfg, notifiers, state):
        time.sleep(int(cfg.get("interval_sec", 300)))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--kakao-auth", action="store_true")
    g.add_argument("--kakao-consent", action="store_true")
    g.add_argument("--kakao-friends", action="store_true")
    g.add_argument("--once", action="store_true")
    g.add_argument("--test-notify", action="store_true")
    g.add_argument("--simulate-open", action="store_true")
    g.add_argument("--cron", action="store_true")
    parser.add_argument("--state-dir", help="state.json / kakao_token.json / watcher.log 위치")
    parser.add_argument("--token-file", help="카카오 토큰 파일 위치 (state-dir 보다 우선)")
    args = parser.parse_args()

    global STATE_PATH, TOKEN_PATH, LOG_PATH
    if args.state_dir:
        state_dir = Path(args.state_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        STATE_PATH, TOKEN_PATH, LOG_PATH = (state_dir / "state.json", state_dir / "kakao_token.json",
                                            state_dir / "watcher.log")
    if args.token_file:
        # Actions 에서는 토큰을 캐시 대상(state-dir) 밖에 둬서 캐시에 남지 않게 한다
        TOKEN_PATH = Path(args.token_file)

    if not CONFIG_PATH.exists():
        raise SystemExit("config.json 이 없습니다. config.example.json 을 복사해 값을 채우세요.")
    cfg = json.loads(CONFIG_PATH.read_text("utf-8"))
    target = cfg["target"]

    if args.kakao_auth:
        KakaoNotifier(cfg.get("kakao", {}), TOKEN_PATH).authorize()
        return
    if args.kakao_consent:
        KakaoNotifier(cfg.get("kakao", {}), RECEIVER_TOKEN_PATH).authorize()
        return
    if args.kakao_friends:
        friends = KakaoNotifier(cfg.get("kakao", {}), TOKEN_PATH).friends()
        if not friends:
            print("목록이 비어 있습니다. 받는 사람이 --kakao-consent 로 동의했는지, 카톡 친구인지 확인하세요.")
        for f in friends:
            print(f"{f.get('profile_nickname', '?')}  {f['uuid']}")
        print()
        print('→ 받을 사람의 uuid 를 config.json 의 kakao.receiver_uuids 에 ["..."] 형태로 넣으세요.')
        return
    if args.once:
        print(check(target).describe())
        return

    notifiers = build_notifiers(cfg)
    if not notifiers:
        raise SystemExit("설정된 알림 채널이 없습니다. --kakao-auth 를 먼저 실행하거나 telegram 설정을 채우세요.")
    log("알림 채널: " + ", ".join(n.name for n in notifiers))

    if args.test_notify:
        notify_all(notifiers, "🔔 결원 알림 봇 테스트 메시지입니다.", APPLY_URL.format(tcd=target["tcd"]), log=log)
    elif args.simulate_open:
        slot = check(target)
        slot.status_cd, slot.label, slot.seats = "1", "접수가능(시뮬레이션)", 1
        notify_all(notifiers, "[테스트] " + open_message(slot, target), APPLY_URL.format(tcd=target["tcd"]), log=log)
    elif args.cron:
        tick(cfg, notifiers, load_state(fresh=False))
    else:
        run(cfg, notifiers)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n중단됨")
