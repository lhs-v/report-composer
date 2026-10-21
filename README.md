# Report Composer (사내 PC용)

메일로 받은 주간 성과 패키지(zip 여러 통)를 **폴더에 넣기만 하면 자동으로 합쳐 풀고**, 그 안의 글 조각·캡처·영상·결과 페이지를 재료로 골라 **내 페이지를 조립**한 뒤 **Confluence**에 첨부까지 올리는 로컬 도구입니다. Python 표준 라이브러리만 쓰므로 설치할 패키지가 없습니다.

## 설치 (3단계)

1. 이 `composer` 폴더를 사내 PC 아무 곳에나 복사합니다 (예: `C:\Tools\composer`).
2. `composer.config.example.json`을 복사해 `composer.config.json`을 만들고 채웁니다.
   - `inbox_dir`: 메일 첨부 zip을 저장할 폴더 (기본 `~/Downloads/report-inbox`). 없으면 만들어집니다.
   - `confluence.base_url`: 사내 Confluence 주소 (예: `https://confluence.example.com`)
   - `confluence.pat`: Confluence 프로필 → **Personal Access Tokens**에서 만든 토큰
   - `confluence.default_space`: 스페이스 키, `confluence.default_parent_id`: 상위 페이지 URL의 `pageId` 숫자
   - 사내 인증서로 SSL 오류가 나면 `confluence.ca_bundle`에 사내 CA 인증서 파일(PEM) 경로를 넣습니다.
3. 실행: `python composer.py` → 브라우저가 `http://127.0.0.1:8790`을 엽니다. (창을 닫아도 서버는 터미널이 살아 있는 동안 유지됩니다.)

PowerShell에서 더블클릭 실행을 원하면 바로가기 대상에 `python C:\Tools\composer\composer.py`를 넣으면 됩니다.

## 사용 흐름

1. 메일의 zip 첨부(본문 메일의 `-light.zip`, 후속 메일의 `-part1of3.zip` …)를 전부 `inbox_dir`에 저장합니다. 조각이 다 모이면 3초 안에 자동으로 풀리고 zip은 `inbox_dir/done/`으로 옮겨집니다. 덜 모였으면 상단에 "자료 2/3 대기 중"이 보입니다.
2. 왼쪽에서 주차를 고르면 가운데에 재료가 흐름(stream) 단위로 나옵니다. 각 흐름은 제목·"무엇을 풀려고 했나"·"어떻게"·대표 결과·"지금 어디까지"·"다음"과 캡처·영상·결과 페이지·md 전문으로 쪼개져 있습니다.
3. 재료를 **클릭**하면 초안 끝에 붙고, **끌어 놓으면** 그 자리에 들어갑니다. "전체 추가"는 흐름의 글과 캡처를 한 번에 넣습니다. 이미 넣은 재료는 "사용됨"으로 표시됩니다. 여러 주차의 재료를 한 초안에 섞어도 됩니다.
4. 오른쪽 초안에서 글은 그 자리에서 고치고(`**굵게**`, `_기울임_`, `[링크](주소)`), 블록 왼쪽 손잡이(⋮⋮)를 끌거나 ↑↓ 버튼으로 순서를 바꿉니다. Enter로 문단 추가, 빈 문단에서 Backspace로 삭제, Ctrl+Z / Ctrl+Shift+Z로 되돌리기. 모든 변경은 즉시 저장됩니다. 초안은 여러 개 만들고 복제할 수 있습니다.
5. "미리보기"에서 올라갈 모습과 Confluence 저장 형식 원문(검증 결과 포함)을 봅니다.
6. **Confluence에 올리기**: 기본 스페이스·상위 페이지 아래 새 페이지를 만들고, 초안이 참조한 캡처·영상을 첨부한 뒤 본문을 씁니다. 상위 페이지는 제목으로 검색해 바꿀 수 있습니다. 같은 초안을 고쳐 다시 올리면 새 페이지가 아니라 **그 페이지가 갱신**됩니다.
7. API가 막혀 있을 때: "서식 복사"로 본문을 Confluence 편집기에 붙여넣고, "첨부 폴더"로 모아둔 파일을 편집기에 끌어 넣습니다.

## 데이터 위치

- 풀린 패키지: `workspace_dir/weeks/<주차>/`
- 초안: `workspace_dir/drafts/*.json` (텍스트라 백업·공유가 쉽습니다)
- 첨부 폴더 내보내기: `workspace_dir/export/<초안 id>/`

## 문제 해결

| 증상 | 확인할 것 |
|---|---|
| "Confluence가 설정되지 않았습니다" | `composer.config.json`의 `confluence.base_url`, `pat` |
| 401/403 | PAT 만료·권한. 프로필에서 토큰을 다시 발급 |
| SSL/CERTIFICATE 오류 | 사내 CA PEM 경로를 `confluence.ca_bundle`에 지정. 임시로 `verify_ssl: false`도 가능(권장하지 않음) |
| 포트 사용 중 | `python composer.py --port 8795` |
| 주차가 안 풀림 | `inbox_dir` 경로가 설정과 같은지, 조각이 모두 왔는지(`자료 i/N` 메일 전부) |

## 개발

```bash
cd composer
python -m unittest discover -s tests -t .
```
