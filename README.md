# kfsi-seat-watcher

한국소방안전원 강습교육 **소방안전관리자 1급(혼용) 경기북부 운정 10.19~10.30** 일정에 결원이 생기면 카카오톡으로 알려 줍니다.
현재는 아래 **클라우드 실행**(GitHub Actions + cron-job.org)으로 돌고 있어 PC가 꺼져 있어도 동작합니다.
5분마다 확인하고, 교육 시작 전날(`deadline`, 10/18 23:59)이 되면 자동으로 종료합니다.
(참고: 사이트에 표시된 접수기간은 09.08 ~ 10.09 23:59 입니다.) Python 3.9 표준 라이브러리만 사용합니다.

## 1. 카카오 개발자 설정 (최초 1회, 약 5분) — 2025.12 개편된 콘솔 기준
1. https://developers.kakao.com 로그인 → **앱** → **앱 생성** (앱 이름 예: 결원알림, 회사명은 본인 이름)
2. **[앱] > [플랫폼 키] > [REST API 키]** 에서
   - REST API 키 값 → `config.json` 의 `kakao.rest_api_key`
   - **카카오 로그인 리다이렉트 URI** 에 `http://localhost:8765/callback` 등록
   - **클라이언트 시크릿** 코드 → `kakao.client_secret` (새 앱은 기본으로 켜져 있음)
3. **[카카오 로그인] > [사용 설정]** → 상태 **ON**
4. **[카카오 로그인] > [동의항목]** → 접근권한 목록의 **카카오톡 메시지 전송(talk_message)** → 설정 → "선택 동의" + 목적 입력 → 저장
5. **[앱] > [제품 링크 관리] > [웹 도메인]** 에 `https://safe.kfsi.or.kr` 등록 (메시지 [신청하러 가기] 버튼용)
6. (받는 사람이 앱 관리자가 아니고, 인증 시 권한 오류가 나면) 앱 **멤버** 메뉴에서 그 사람 카카오 계정을 초대
7. **알림 받을 사람**의 카카오 계정으로 인증합니다 (내 계정으로 하면 나에게 옵니다):
   ```
   python watcher.py --kakao-auth
   ```
   브라우저가 열리면 **알림 받을 사람이 자기 카카오 계정으로** 로그인/동의 → "인증 완료" 가 보이면 끝. 토큰은 `kakao_token.json` 에 저장되고 자동 갱신됩니다.

## 2. 테스트
```
python watcher.py --once           # 현재 상태 출력 (알림 X)
python watcher.py --test-notify    # 카톡 '나와의 채팅'으로 테스트 메시지
python watcher.py --simulate-open  # 결원 발생 알림 모양 + 버튼 링크 확인
```
> ⚠️ '나에게 보내기' 메시지는 휴대폰에서 **푸시 알림(소리/배너)이 안 울릴 수 있습니다.**
> 테스트 메시지에 알림이 오는지 꼭 확인하고, 안 오면 텔레그램을 함께 설정하세요 (`config.json` 의 `telegram`).

## 3. 실행
```
python watcher.py
```
- 터미널 창을 닫지 말고, **PC 절전 모드를 꺼 두세요** (설정 → 시스템 → 전원 → 절전 모드: 안 함).
- 알림 종류: 👀 감시 시작 / 🚨 결원 발생(최대 2회) / 🔒 다시 마감 / ⚠️ 3회 연속 확인 실패 / ⏹ 접수 마감 종료
- 기록은 `watcher.log` 에 남습니다.

## 텔레그램 (선택)
@BotFather 에서 `/newbot` → 토큰을 `telegram.bot_token` 에, 봇에게 아무 메시지 보낸 뒤
`https://api.telegram.org/bot<토큰>/getUpdates` 에서 `chat.id` 를 `telegram.chat_id` 에 입력.
설정된 채널 모두로 동시에 전송됩니다.

## 다른 사람이 알림을 받게 하려면
'나에게 보내기'는 `--kakao-auth` 로 로그인한 계정의 **나와의 채팅**으로 갑니다. 즉, 알림 받을 사람이 이 PC에서 `--kakao-auth` 를 실행해 자기 계정으로 로그인하면 그 사람만 받습니다.
- 로그인 화면은 항상 계정 입력부터 뜨도록(`prompt=login`) 해 두었습니다. 그래도 내 계정이 자동 선택되면 브라우저 주소를 시크릿 창에 붙여넣어 진행하세요.
- 동의 화면에서 "권한 없음" 류 오류가 나면: developers.kakao.com → 내 애플리케이션 → **팀 관리**에서 그 사람을 팀원으로 초대 → 수락 후 다시 시도.
- 받는 사람을 바꾸려면 `kakao_token.json` 을 지우고 `--kakao-auth` 를 다시 실행하면 됩니다.

## 친구에게 보내기 (받는 사람 폰에 일반 카톡처럼 알림)
'나에게 보내기'는 푸시 알림이 안 울릴 수 있어, 내 계정 → 받는 사람에게 보내는 방식을 지원합니다.
1. 콘솔 **[카카오 로그인] > [동의항목]** → 개인정보 **카카오 서비스 내 친구목록** → "선택 동의"로 저장 (메시지 전송 항목도 켜져 있어야 함)
2. 받는 사람: `python watcher.py --kakao-consent` → 자기 계정으로 로그인, **친구목록 + 메시지 전송 모두 동의**
3. 나: `python watcher.py --kakao-auth` → 내 계정으로 로그인, 모두 동의
4. `python watcher.py --kakao-friends` → 받는 사람의 uuid 를 `config.json` 의 `kakao.receiver_uuids` 에 `["uuid"]` 로 입력
5. `python watcher.py --test-notify`
- 두 사람은 카톡 친구여야 하고, 받는 사람 프로필이 비공개면 목록에 안 나옵니다.
- 권한 오류 시: 앱 멤버로 받는 사람 초대, 또는 비즈 앱 전환이 필요할 수 있습니다.
- `receiver_uuids` 를 비우면 다시 '나에게 보내기'로 동작합니다.

## 클라우드 실행 (GitHub Actions + cron-job.org)
PC 없이 돌리는 현재 운영 방식입니다.

```
cron-job.org (5분마다)
  → GitHub API: workflow_dispatch 호출
    → GitHub Actions: watcher.py --cron 한 번 실행
      → 소방안전원 일정 확인 → 상태가 바뀌었으면 카카오톡 알림
```

GitHub 자체 `schedule`(cron)도 워크플로에 넣어 두었습니다. 하지만 새 저장소에서는 1시간 넘게 시작되지 않았고, 시작되더라도 지연되거나 건너뛸 수 있습니다. 그래서 **정확한 5분 주기는 cron-job.org가 맡고**, `schedule`은 예비로만 둡니다. 둘이 겹쳐도 `concurrency` 설정으로 한 번에 하나씩 실행되므로 알림이 중복되지 않습니다.

### 구성 요소
| 구성 | 위치 | 내용 |
|---|---|---|
| 워크플로 | `.github/workflows/watch.yml` | `python3 watcher.py --cron --state-dir state --token-file $RUNNER_TEMP/kakao_token.json` |
| 비밀값 `CONFIG_JSON` | 저장소 Settings → Secrets → Actions | `config.json` 전체 (카카오 키·시크릿, 받는 사람 uuid, 감시 대상) |
| 비밀값 `KAKAO_TOKEN_JSON` | 〃 | **보내는 사람** `kakao_token.json` (refresh token 포함) |
| 상태 | Actions 캐시 `watcher-state-*` | `state/state.json`(마감/결원, 알림 횟수, 연속 실패), `state/watcher.log` |
| 외부 크론 | cron-job.org | 5분마다 `workflow_dispatch` 호출 |
| 호출용 토큰 | GitHub fine-grained PAT `kfsi-cron` | 이 저장소의 **Actions: Read and write** 권한만 있고 2026-10-20에 만료 |

### 처음부터 설정하는 순서
1. **비밀값 등록**: 로컬에서 `--kakao-auth`까지 끝낸 뒤 아래를 실행합니다.
   ```
   gh secret set CONFIG_JSON < config.json
   gh secret set KAKAO_TOKEN_JSON < kakao_token.json
   ```
2. **동작 확인**: `gh workflow run watch.yml`을 실행하고 Actions 탭에서 성공했는지, 로그에 `상태=마감 … 잔여 0명`이 찍혔는지 확인합니다.
3. **GitHub 토큰 발급**: https://github.com/settings/personal-access-tokens/new
   - Expiration: 감시 종료일 직후
   - Repository access: **Only select repositories** → 이 저장소
   - Permissions: **Actions → Read and write**. 목록에 없으면 **+ Add permissions**에서 `Actions`를 검색합니다. Metadata: Read-only는 자동으로 붙습니다.
4. **cron-job.org 작업 생성** (CREATE CRONJOB)
   - URL: `https://api.github.com/repos/Meow-Lee/kfsi-seat-watcher/actions/workflows/watch.yml/dispatches`
   - Schedule: Every 5 minutes
   - ADVANCED 탭
     - Request method: `POST`
     - Headers:
       - `Authorization: Bearer <github_pat_...>`
       - `Accept: application/vnd.github+json`
       - `X-GitHub-Api-Version: 2022-11-28`
     - Request body: `{"ref":"main"}`
   - **TEST RUN** 응답이 `204 No Content`면 성공입니다.
5. **자동 호출 확인**: `gh run list`에 `workflow_dispatch` 성공 실행이 5분 간격으로 쌓이면 PC 실행(`python watcher.py`)을 끕니다. 둘이 같이 돌면 알림이 중복됩니다.

### 확인 / 운영
- 실행 기록은 저장소 **Actions** 탭이나 `gh run list -R Meow-Lee/kfsi-seat-watcher`로 봅니다.
  - cron-job.org가 실행한 것은 `workflow_dispatch`, GitHub 자체 cron이 실행한 것은 `schedule`로 표시됩니다.
- 수동으로 한 번 실행하려면 `gh workflow run watch.yml -R Meow-Lee/kfsi-seat-watcher`를 씁니다.
- 실행이 안 쌓이면 cron-job.org의 작업 **History**에서 응답 코드를 봅니다.
  - `401`/`403`: 토큰 만료 또는 권한 부족
  - `404`: URL이나 워크플로 파일 이름이 틀림
- 카카오 access token은 실행할 때마다 refresh token으로 갱신해서 쓰고 버립니다. refresh token은 약 2개월 유효합니다. 다시 인증했다면 `KAKAO_TOKEN_JSON`도 다시 등록해야 합니다.
- 감시 대상이나 받는 사람을 바꿨다면 `config.json`을 고친 뒤 `CONFIG_JSON`을 다시 등록합니다.

### 보안
저장소는 **공개**입니다. 공개 저장소는 Actions 사용 시간이 무제한이라 공개로 두었습니다. 비공개 무료 한도(월 2,000분)로는 5분 주기를 끝까지 유지할 수 없습니다. 공개 상태에서 노출되지 않도록 다음과 같이 처리했습니다.
- `config.json`, `kakao_token*.json`, `state/`는 `.gitignore`에 들어 있어 **커밋 기록에 한 번도 들어간 적이 없습니다**. 비밀값은 Secrets(암호화)에만 있습니다.
- 카카오 토큰은 캐시가 아니라 `$RUNNER_TEMP`에 두므로 실행이 끝나면 사라집니다. 캐시에는 알림 상태만 남습니다.
- 로그에는 상태 문구만 찍히고, Secrets 값은 GitHub가 `***`로 가립니다.
- `GITHUB_TOKEN`은 읽기 전용입니다(`permissions: contents: read`, 저장소 기본값도 read).
- 외부 기여자의 PR 워크플로는 **승인해야만 실행**됩니다. fork PR에는 Secrets가 전달되지 않습니다.
- 커밋 작성자 이메일은 GitHub noreply 주소입니다.
- cron-job.org에 맡긴 PAT는 이 저장소의 Actions 실행·조회만 할 수 있습니다. Secrets를 읽거나 코드를 바꿀 수 없고, 만료일도 있습니다.

### 종료 / 정리 (감시 기한 이후)
`deadline`(2026-10-18 23:59)이 지나면 ⏹ 종료 알림을 한 번 보내고, 그 뒤 실행은 아무것도 하지 않습니다. 끝나면 다음을 정리합니다.
1. cron-job.org 작업을 끄거나 지웁니다.
2. `gh workflow disable watch.yml -R Meow-Lee/kfsi-seat-watcher`
3. GitHub PAT `kfsi-cron`을 지웁니다(10/20에 자동 만료되기도 합니다).
4. 필요 없으면 `Meow-Lee/kfsi-seat-watcher-old`(이전 비공개 저장소, 워크플로는 꺼 둠)를 지웁니다.
