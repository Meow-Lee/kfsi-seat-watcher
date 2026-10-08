"""알림 채널: 카카오톡 '나에게 보내기' + (선택) 텔레그램."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import List, Optional

KAUTH = "https://kauth.kakao.com"
KAPI = "https://kapi.kakao.com"


def _post(url: str, data: dict, headers: Optional[dict] = None, timeout: int = 15) -> dict:
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers or {}, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded;charset=utf-8")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


class KakaoNotifier:
    name = "kakao"

    def __init__(self, cfg: dict, token_path: Path):
        self.client_id = cfg.get("rest_api_key", "").strip()
        self.client_secret = cfg.get("client_secret", "").strip()
        self.redirect_uri = cfg.get("redirect_uri", "http://localhost:8765/callback")
        self.token_path = token_path
        # 비어 있으면 '나에게 보내기', 있으면 해당 친구(들)에게 보내기
        self.receiver_uuids = [u for u in cfg.get("receiver_uuids", []) if u]
        self.token = json.loads(token_path.read_text("utf-8")) if token_path.exists() else {}

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.token.get("refresh_token"))

    # ---- 토큰 ----
    def _save_token(self, resp: dict) -> None:
        self.token["access_token"] = resp["access_token"]
        self.token["expires_at"] = time.time() + int(resp.get("expires_in", 0))
        if resp.get("refresh_token"):  # 갱신 응답에는 refresh_token이 없을 수도 있다
            self.token["refresh_token"] = resp["refresh_token"]
        self.token_path.write_text(json.dumps(self.token, indent=2), "utf-8")

    def _with_secret(self, data: dict) -> dict:
        if self.client_secret:
            data["client_secret"] = self.client_secret
        return data

    def refresh(self) -> None:
        resp = _post(f"{KAUTH}/oauth/token", self._with_secret({
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "refresh_token": self.token["refresh_token"],
        }))
        self._save_token(resp)

    def authorize(self, scope: str = "talk_message,friends") -> None:
        """브라우저로 카카오 로그인 → localhost 콜백에서 code를 받아 토큰 발급."""
        if not self.client_id:
            raise SystemExit("config.json 의 kakao.rest_api_key 를 먼저 입력하세요.")
        parsed = urllib.parse.urlparse(self.redirect_uri)
        auth_url = f"{KAUTH}/oauth/authorize?" + urllib.parse.urlencode({
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": scope,
            "prompt": "login",  # 브라우저에 이미 로그인된 계정 대신 원하는 계정으로 로그인
        })
        received = {}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                received.update({k: v[0] for k, v in qs.items()})
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                msg = "인증 완료! 이 창을 닫아도 됩니다." if "code" in received else f"인증 실패: {received}"
                self.wfile.write(f"<h2>{msg}</h2>".encode("utf-8"))

            def log_message(self, *args):
                pass

        server = HTTPServer((parsed.hostname, parsed.port or 80), Handler)
        print("브라우저에서 카카오 로그인/동의를 진행하세요. 자동으로 열리지 않으면 아래 주소를 여세요:\n" + auth_url)
        webbrowser.open(auth_url)
        while "code" not in received and "error" not in received:
            server.handle_request()
        server.server_close()
        if "code" not in received:
            raise SystemExit(f"카카오 인증 실패: {received}")

        resp = _post(f"{KAUTH}/oauth/token", self._with_secret({
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "code": received["code"],
        }))
        self._save_token(resp)
        print(f"토큰 저장 완료: {self.token_path}")

    def _auth_header(self) -> dict:
        return {"Authorization": f"Bearer {self.token.get('access_token', '')}"}

    def _ensure_fresh(self) -> None:
        if time.time() > self.token.get("expires_at", 0) - 300:
            self.refresh()

    def friends(self) -> list:
        """이 앱에 가입(동의)한 카카오톡 친구 목록."""
        self._ensure_fresh()
        req = urllib.request.Request(f"{KAPI}/v1/api/talk/friends?limit=100", headers=self._auth_header())
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8")).get("elements", [])

    # ---- 전송 ----
    def _send_once(self, text: str, link: Optional[str], button: str) -> None:
        # 버튼은 [제품 링크 관리 > 웹 도메인]에 등록된 도메인일 때만 보이므로, 본문에도 주소를 넣어 둔다
        # 텍스트 템플릿은 200자 제한 → 본문을 줄여서라도 링크는 끝까지 남긴다
        text = f"{text[:200 - len(link) - 1]}\n{link}" if link else text[:200]
        template = {"object_type": "text", "text": text,
                    "link": {"web_url": link or "", "mobile_web_url": link or ""}}
        if link:
            template["button_title"] = button
        data = {"template_object": json.dumps(template, ensure_ascii=False)}
        if self.receiver_uuids:
            data["receiver_uuids"] = json.dumps(self.receiver_uuids)
            resp = _post(f"{KAPI}/v1/api/talk/friends/message/default/send", data, headers=self._auth_header())
            if resp.get("failure_info") or not resp.get("successful_receiver_uuids"):
                raise RuntimeError(f"kakao friend send failed: {resp}")
        else:
            resp = _post(f"{KAPI}/v2/api/talk/memo/default/send", data, headers=self._auth_header())
            if resp.get("result_code") != 0:
                raise RuntimeError(f"kakao send failed: {resp}")

    def send(self, text: str, link: Optional[str] = None, button: str = "신청하러 가기") -> None:
        self._ensure_fresh()
        try:
            self._send_once(text, link, button)
        except urllib.error.HTTPError as e:
            if e.code != 401:
                raise RuntimeError(f"kakao HTTP {e.code}: {e.read().decode('utf-8', 'replace')}")
            self.refresh()  # 토큰이 서버 쪽에서 무효화된 경우
            self._send_once(text, link, button)


class TelegramNotifier:
    name = "telegram"

    def __init__(self, cfg: dict):
        self.bot_token = cfg.get("bot_token", "").strip()
        self.chat_id = str(cfg.get("chat_id", "")).strip()

    @property
    def configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def send(self, text: str, link: Optional[str] = None, button: str = "") -> None:
        if link:
            text = f"{text}\n{link}"
        resp = _post(f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                     {"chat_id": self.chat_id, "text": text, "disable_web_page_preview": "true"})
        if not resp.get("ok"):
            raise RuntimeError(f"telegram send failed: {resp}")


def notify_all(notifiers: List, text: str, link: Optional[str] = None, log=print) -> bool:
    """설정된 모든 채널로 전송. 하나라도 성공하면 True."""
    ok = False
    for n in notifiers:
        try:
            n.send(text, link)
            ok = True
            log(f"  -> {n.name} 전송 성공")
        except Exception as e:  # 한 채널 실패가 다른 채널을 막지 않도록
            log(f"  -> {n.name} 전송 실패: {e}")
    return ok
