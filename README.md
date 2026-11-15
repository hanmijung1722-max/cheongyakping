# 청약핑 웹 버전 (Mac 없이 · 무료 · 혼자 쓰기용)

서울·경기 청약 일정을 아이폰에서 앱처럼 보고, **아이폰 캘린더 알림**으로 받는 방식이에요.
Xcode도, 유료 개발자 계정도, 서버도 필요 없어요.

## 어떻게 동작하나요?

```
[GitHub Actions: 매일 오전 7시(KST) 자동 실행]
   build.py ─ 청약홈 공공 API 호출
      ├─ docs/listings.json   ← 웹앱이 읽는 데이터
      ├─ docs/ics/<단지>.ics   ← 단지별 일정 + 알림(하루 전·당일·마감일 오전 9시)
      └─ docs/all.ics         ← 전체 일정 구독용(알림 없음)
[GitHub Pages: docs/ 폴더를 무료 웹사이트로 공개]
   docs/index.html ← 아이폰 Safari에서 열고 "홈 화면에 추가"
```

- **보기:** 웹앱(홈 · 캘린더 · 가이드 · 알림 설정)
- **알림:** 단지 상세의 “알림 포함해서 캘린더에 추가” 버튼 → 아이폰 캘린더가 알림을 울려요

## 설정 (약 15분, 한 번만)

1. **GitHub 가입** → 새 저장소(Repository) 만들기 → 이름 예: `cheongyakping`, **Public**
   (무료 계정은 Public 저장소만 Pages를 쓸 수 있어요. 공개 데이터라 괜찮고, 인증키는 아래 Secrets에 숨겨져요.)
2. 이 폴더의 파일 전체(`build.py`, `config.json`, `docs/`, `.github/`)를 저장소에 업로드
   - 웹에서 “Add file → Upload files”로 폴더째 끌어다 놓으면 돼요. `.github` 폴더가 숨김 폴더라 안 보이면 터미널/GitHub Desktop을 쓰거나, 저장소에서 `Add file → Create new file`로 `.github/workflows/update.yml` 이름을 직접 입력해 내용을 붙여넣으세요.
3. **공공데이터포털 인증키 발급**
   - data.go.kr 가입 → “한국부동산원_청약홈 분양정보 조회 서비스” 활용신청(개발계정 자동승인)
   - 마이페이지의 **일반 인증키(Decoding)** 복사
4. 저장소 **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `APPLYHOME_SERVICE_KEY` / Secret: 복사한 키
5. 저장소 **Settings → Pages** → Source: *Deploy from a branch* → Branch: `main`, 폴더 `/docs` → Save
6. 저장소 **Actions** 탭 → `update-data` → **Run workflow** (처음 한 번 수동 실행)
7. 1~2분 뒤 `https://<내아이디>.github.io/<저장소이름>/` 이 내 웹앱 주소예요.

## 아이폰에서 쓰기

1. Safari로 웹앱 주소 열기 → 공유 버튼 → **홈 화면에 추가**
2. 마음에 드는 단지 탭 → **📅 알림 포함해서 캘린더에 추가** → “모두 추가”
3. (선택) 설정 탭의 주소로 **전체 일정 구독**: 설정 → 캘린더 → 계정 → 계정 추가 → 기타 → 구독 캘린더 추가

## 설정 바꾸기 (`config.json`)

| 항목 | 의미 |
|---|---|
| `regions` | 가져올 지역. 기본 `["서울","경기"]` |
| `alarm_hour` | 알림 시각(0~23시). 기본 9 |
| `alarms.day_before / day_of / deadline` | 하루 전 / 시작일 당일 / 마감일 알림 켜기·끄기 |

## 꼭 알아두세요

- **인증키를 넣기 전에는 샘플(가상) 데이터가 보여요.** 먼저 화면만 확인하고 싶으면 4~6번 없이도 열려요.
- 필드명은 공개된 청약홈 API 명세 기준이에요. 첫 실제 실행 후 **2순위 같은 일정이 비어 있으면** `build.py`의 `to_listing()` 필드명을 실제 응답에 맞춰 주세요.
- 캘린더에 한 번 추가한 알림은 **자동으로 갱신되지 않아요.** 공고 일정이 바뀌면 캘린더에서 기존 일정을 지운 뒤 다시 추가해 주세요.
- 캘린더 **구독**(all.ics)의 알림은 아이폰 설정에 따라 표시되지 않을 수 있어서, 알림이 필요한 단지는 위의 단지별 “캘린더에 추가”를 쓰는 걸 권장해요.
- GitHub은 저장소에 오래 활동이 없으면(약 60일) 예약 실행을 멈출 수 있어요. 그럴 땐 Actions 탭에서 다시 켜 주세요.
- 청약핑은 청약홈의 **비공식** 도구예요. 신청 전에는 입주자 모집공고문을 꼭 확인하세요.

## 로컬에서 미리 보기 (선택)

```bash
python3 build.py            # 키 없이 실행하면 샘플 데이터 생성
cd docs && python3 -m http.server 8000   # http://localhost:8000
```
