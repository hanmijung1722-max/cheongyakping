#!/usr/bin/env python3
"""청약핑 데이터 빌드 (표준 라이브러리만 사용)

청약홈 공공 API → docs/listings.json (웹앱용)
              → docs/all.ics        (전체 일정 구독용, 알림 없음)
              → docs/ics/<id>.ics   (단지별 일정 + 알림 포함, 탭 한 번으로 캘린더에 추가)

환경변수 APPLYHOME_SERVICE_KEY 가 없으면 샘플 데이터로 만듭니다.
"""
import json
import os
import re
import shutil
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
ENDPOINT = "https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1/getAPTLttotPblancDetail"
MODEL_ENDPOINT = "https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1/getAPTLttotPblancMdl"  # 주택형별 상세

# 종류: (제목, 짧은 이름, 쉬운 설명)
KINDS = {
    "announcement": ("모집공고", "공고", "분양 조건과 일정이 공개되는 날이에요."),
    "special": ("특별공급 접수", "특공", "신혼부부·생애최초 등 조건이 맞으면 먼저 신청할 수 있어요."),
    "first": ("1순위 접수", "1순위", "청약통장 요건을 갖춘 분들이 신청하는 일반공급 첫 번째 기회예요."),
    "second": ("2순위 접수", "2순위", "1순위에서 마감되지 않았을 때 이어지는 신청 기회예요."),
    "winner": ("당첨자 발표", "발표", "청약홈 등에서 당첨 여부를 확인할 수 있어요."),
    "contract": ("계약 체결", "계약", "당첨자가 서류를 내고 계약금을 납부하는 기간이에요."),
}
ORDER = list(KINDS)

DEFAULT_CONFIG = {
    "regions": ["서울", "경기"],
    "alarm_hour": 9,
    "alarms": {"day_before": True, "day_of": True, "deadline": True},
}


# ---------------------------------------------------------------- 설정 / 날짜

def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    path = ROOT / "config.json"
    if path.exists():
        user = json.loads(path.read_text(encoding="utf-8"))
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    cfg["alarm_hour"] = max(0, min(23, int(cfg["alarm_hour"])))
    return cfg


def today_kst():
    return datetime.now(KST).date()


def parse_date(raw):
    if not raw:
        return None
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) < 8:
        return None
    try:
        return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
    except ValueError:
        return None


# ---------------------------------------------------------------- API 호출 / 매핑

def fetch_region(key, region, since):
    rows, page = [], 1
    while page <= 5:
        query = urllib.parse.urlencode({
            "page": page,
            "perPage": 200,
            "cond[SUBSCRPT_AREA_CODE_NM::EQ]": region,
            "cond[RCRIT_PBLANC_DE::GTE]": since,
        })
        # Decoding 키는 +,/ 등을 포함할 수 있어 헤더로 전달합니다.
        req = urllib.request.Request(f"{ENDPOINT}?{query}", headers={"Authorization": f"Infuser {key}"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.load(resp)
        data = body.get("data", [])
        rows += data
        total = body.get("matchCount") or body.get("totalCount") or 0
        if not data or len(rows) >= total:
            break
        page += 1
    return rows


def flag(row, key):
    """'Y'/'N' 형태 필드를 True/False 로. 필드가 없으면 None(모름)."""
    if key not in row or row.get(key) is None:
        return None
    text = str(row.get(key)).strip().upper()
    if text in ("Y", "O", "TRUE", "해당", "1"):
        return True
    if text in ("N", "", "X", "FALSE", "미해당", "0"):
        return False
    return None


def house_kind(row):
    text = " ".join(str(row.get(k) or "") for k in ("HOUSE_DTL_SECD_NM", "HOUSE_SECD_NM"))
    if "국민" in text or "공공" in text:
        return "국민"
    if "민영" in text:
        return "민영"
    return None


def to_listing(row):
    def v(key):
        val = row.get(key)
        if val is None:
            return None
        val = str(val).strip()
        return val or None

    manage, name, region = v("HOUSE_MANAGE_NO"), v("HOUSE_NM"), v("SUBSCRPT_AREA_CODE_NM")
    if not (manage and name and region):
        return None

    def d(key):
        return parse_date(row.get(key))

    def span(starts, ends):
        s = [x for x in map(d, starts) if x]
        if not s:
            return None
        e = [x for x in map(d, ends) if x]
        start = min(s)
        return start, max(start, max(e) if e else start)

    events = {}
    if d("RCRIT_PBLANC_DE"):
        events["announcement"] = (d("RCRIT_PBLANC_DE"),) * 2
    events["special"] = span(["SPSPLY_RCEPT_BGNDE"], ["SPSPLY_RCEPT_ENDDE"])
    first = span(
        ["GNRL_RNK1_CRSPAREA_RCPTDE", "GNRL_RNK1_ETC_GG_RCPTDE", "GNRL_RNK1_ETC_AREA_RCPTDE"],
        ["GNRL_RNK1_CRSPAREA_ENDDE", "GNRL_RNK1_ETC_GG_ENDDE", "GNRL_RNK1_ETC_AREA_ENDDE"],
    )
    events["first"] = first or span(["RCEPT_BGNDE"], ["RCEPT_ENDDE"])  # 순위별 필드가 비면 전체 접수기간으로 대체
    events["second"] = span(
        ["GNRL_RNK2_CRSPAREA_RCPTDE", "GNRL_RNK2_ETC_GG_RCPTDE", "GNRL_RNK2_ETC_AREA_RCPTDE"],
        ["GNRL_RNK2_CRSPAREA_ENDDE", "GNRL_RNK2_ETC_GG_ENDDE", "GNRL_RNK2_ETC_AREA_ENDDE"],
    )
    events["winner"] = span(["PRZWNER_PRESNATN_DE"], [])
    events["contract"] = span(["CNTRCT_CNCLS_BGNDE"], ["CNTRCT_CNCLS_ENDDE"])
    events = {k: x for k, x in events.items() if x}
    if not any(k != "announcement" for k in events):
        return None

    units = v("TOT_SUPLY_HSHLDCO")
    try:
        units = int(float(units)) if units else None
    except ValueError:
        units = None

    return {
        "id": f"{manage}-{v('PBLANC_NO') or '0'}",
        "manage_no": manage,
        "pblanc_no": v("PBLANC_NO") or "0",
        "name": name,
        "region": region,
        "address": v("HSSPLY_ADRES") or "",
        "units": units,
        "builder": v("CNSTRCT_ENTRPS_NM"),
        "developer": v("BSNS_MBY_NM"),
        "move_in": v("MVN_PREARNGE_YM"),
        "phone": v("MDHS_TELNO"),
        "url": v("PBLANC_URL"),
        "kind": house_kind(row),                                  # 민영 / 국민(공공)
        "reg": {"spec": flag(row, "SPECLT_RDN_EARTH_AT"),         # 투기과열지구
                "adj": flag(row, "MDAT_TRGET_AREA_SECD")},        # 조정대상(청약과열)지역
        "events": [
            {"kind": k, "start": events[k][0].isoformat(), "end": events[k][1].isoformat()}
            for k in sorted(events, key=ORDER.index)
        ],
    }


def is_finished(listing, today):
    ends = [date.fromisoformat(e["end"]) for e in listing["events"] if e["kind"] != "announcement"]
    return not ends or max(ends) < today


RAW_SAMPLE = []   # 필드명 확인용으로 원본 응답 몇 줄만 보관


def fetch_all(key, regions, today):
    since = (today - timedelta(days=90)).isoformat()
    seen, out = set(), []
    for region in regions:
        for row in fetch_region(key, region, since):
            if len(RAW_SAMPLE) < 2:
                RAW_SAMPLE.append(row)
            item = to_listing(row)
            if item and item["id"] not in seen and not is_finished(item, today):
                seen.add(item["id"])
                out.append(item)
    return out


# ---------------------------------------------------------------- 주택형별 공급 유형 (싱글/신혼부부 구분용)

# 특별공급 유형 → 주택형별 API 필드
SUPPLY_FIELDS = {
    "newlywed": "NWWDS_HSHLDCO",             # 신혼부부
    "first_home": "LFE_FRST_HSHLDCO",        # 생애최초
    "multi_child": "MNYCH_HSHLDCO",          # 다자녀
    "parents": "OLD_PARNTS_SUPORT_HSHLDCO",  # 노부모부양
    "institution": "INSTT_RECOMEND_HSHLDCO", # 기관추천
    "newborn": "NWBB_HSHLDCO",               # 신생아
    "youth": "YGMN_HSHLDCO",                 # 청년
    "etc": "ETC_HSHLDCO",                    # 기타
}


def to_num(value):
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return 0


def fetch_models(key, manage_no, pblanc_no):
    query = urllib.parse.urlencode({
        "page": 1,
        "perPage": 200,
        "cond[HOUSE_MANAGE_NO::EQ]": manage_no,
        "cond[PBLANC_NO::EQ]": pblanc_no,
    })
    req = urllib.request.Request(f"{MODEL_ENDPOINT}?{query}", headers={"Authorization": f"Infuser {key}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp).get("data", [])


def summarize_models(rows):
    """주택형 행들을 → (공급유형별 합계, 주택형별 목록) 으로 요약"""
    totals = {"general": 0}
    totals.update({k: 0 for k in SUPPLY_FIELDS})
    types = []
    for row in rows:
        ty = str(row.get("HOUSE_TY") or "").strip()
        m = re.match(r"\s*([0-9]+(?:\.[0-9]+)?)", ty)
        area = round(float(m.group(1)), 2) if m else None
        item = {"ty": ty, "area": area, "general": to_num(row.get("SUPLY_HSHLDCO"))}
        price = to_num(row.get("LTTOT_TOP_AMOUNT"))   # 최고 분양가(만원)
        if price:
            item["price"] = price
        totals["general"] += item["general"]
        for name, field in SUPPLY_FIELDS.items():
            n = to_num(row.get(field))
            item[name] = n
            totals[name] += n
        types.append(item)
    return totals, types


def attach_supply(key, listings):
    """각 단지에 공급 유형 정보를 붙입니다. 실패해도 나머지 데이터는 그대로 둡니다."""
    debug = []
    for listing in listings:
        try:
            rows = fetch_models(key, listing["manage_no"], listing["pblanc_no"])
        except Exception as e:  # 네트워크/권한 오류는 건너뜀
            print(f"주택형 조회 실패 {listing['name']}: {e}", file=sys.stderr)
            continue
        if not rows:
            continue
        listing["supply"], listing["types"] = summarize_models(rows)
        if len(debug) < 3:
            debug.append({"name": listing["name"], "rows": rows[:2]})
    return debug


# ---------------------------------------------------------------- 샘플 데이터 (가상 단지)

def sample_listings(today):
    def ev(kind, a, b=None):
        return {"kind": kind, "start": (today + timedelta(days=a)).isoformat(),
                "end": (today + timedelta(days=b if b is not None else a)).isoformat()}

    def make(i, name, region, addr, units, evs, types, reg=None):
        reg = reg or {"spec": region == "서울", "adj": region == "서울"}
        keys = ["general"] + list(SUPPLY_FIELDS)
        totals = {k: sum(t.get(k, 0) for t in types) for k in keys}
        full = [{**{k: 0 for k in keys}, **t} for t in types]
        return {"id": f"sample-{i}", "name": f"{name} (샘플)", "region": region, "address": addr,
                "units": units, "builder": "샘플건설", "developer": "샘플디벨롭", "move_in": "202908",
                "phone": "02-000-0000", "url": None, "events": evs, "supply": totals, "types": full,
                "kind": "민영", "reg": reg}

    return [
        make(1, "한강 포레스트힐", "서울", "서울특별시 강동구 샘플동 100", 412,
             [ev("announcement", -8), ev("special", -1, 0), ev("first", 1, 2), ev("second", 3),
              ev("winner", 9), ev("contract", 15, 18)],
             [{"ty": "059.9800A", "area": 59.98, "general": 120, "newlywed": 40, "first_home": 30, "multi_child": 14, "parents": 8, "institution": 10, "youth": 0},
              {"ty": "084.9500B", "area": 84.95, "general": 140, "newlywed": 30, "first_home": 20, "multi_child": 12, "parents": 6, "institution": 8}]),
        make(2, "광교 에코파크", "경기", "경기도 수원시 영통구 샘플로 55", 860,
             [ev("announcement", -5), ev("special", 0, 1), ev("first", 2, 4), ev("second", 5),
              ev("winner", 11), ev("contract", 18, 21)],
             [{"ty": "084.9900A", "area": 84.99, "general": 520, "newlywed": 120, "first_home": 80, "multi_child": 50, "parents": 30, "institution": 60}]),
        make(3, "마포 리버뷰 센트럴", "서울", "서울특별시 마포구 샘플대로 12", 158,
             [ev("announcement", -2), ev("special", 4, 5), ev("first", 6, 7), ev("second", 8),
              ev("winner", 14), ev("contract", 21, 24)],
             [{"ty": "046.9700A", "area": 46.97, "general": 70, "newlywed": 30, "first_home": 20, "multi_child": 6, "parents": 4, "institution": 8},
              {"ty": "059.9000B", "area": 59.9, "general": 10, "newlywed": 6, "first_home": 4}]),
        make(4, "위례 스카이 테라스", "경기", "경기도 하남시 샘플길 77", 530,
             [ev("announcement", 0), ev("special", 9, 10), ev("first", 11, 12), ev("second", 13),
              ev("winner", 19), ev("contract", 26, 29)],
             [{"ty": "074.9900A", "area": 74.99, "general": 300, "newlywed": 90, "first_home": 60, "multi_child": 30, "parents": 20, "institution": 30}]),
        make(5, "성수 아뜰리에", "서울", "서울특별시 성동구 샘플로 8", 96,
             [ev("announcement", -14), ev("special", -9, -8), ev("first", -7, -6), ev("second", -5),
              ev("winner", 2), ev("contract", 9, 12)],
             [{"ty": "033.8000A", "area": 33.8, "general": 60, "youth": 0, "first_home": 12, "newlywed": 0, "institution": 4}]),
    ]


# ---------------------------------------------------------------- ICS 생성

def esc(text):
    return (str(text).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def fold(line):
    """RFC 5545: 한 줄은 75바이트 이내. 넘으면 CRLF + 공백으로 이어 씁니다."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts, cur = [], b""
    limit = 75
    for ch in line:
        b = ch.encode("utf-8")
        if len(cur) + len(b) > limit:
            parts.append(cur.decode("utf-8"))
            cur, limit = b, 74
        else:
            cur += b
    parts.append(cur.decode("utf-8"))
    return "\r\n ".join(parts)


def alarm_blocks(listing, event, cfg):
    """종일 일정은 시작일 00:00 기준이라 알림 시각을 '시작 대비 오프셋'으로 계산합니다."""
    h = cfg["alarm_hour"]
    start, end = date.fromisoformat(event["start"]), date.fromisoformat(event["end"])
    span = (end - start).days
    label = KINDS[event["kind"]][0]
    place = f"{listing['region']} · {listing['name']}"
    plans = []
    if cfg["alarms"].get("day_before"):
        plans.append((f"-PT{24 - h}H", f"내일 {label} · {place}"))
    if cfg["alarms"].get("day_of"):
        plans.append((f"PT{h}H" if h else "PT0S", f"오늘 {label} · {place}"))
    if cfg["alarms"].get("deadline") and span > 0:
        plans.append((f"P{span}DT{h}H", f"오늘 마감! {label} · {place}"))
    lines = []
    for trigger, text in plans:
        lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{esc(text)}", f"TRIGGER:{trigger}", "END:VALARM"]
    return lines


def vevents(listing, cfg, with_alarms, stamp):
    out = []
    for event in listing["events"]:
        if event["kind"] == "announcement":
            continue
        title, short, hint = KINDS[event["kind"]]
        start, end = date.fromisoformat(event["start"]), date.fromisoformat(event["end"])
        desc = f"{title}: {hint}\n{listing['address']}"
        if listing.get("url"):
            desc += f"\n공고문: {listing['url']}"
        desc += "\n※ 신청 전 입주자 모집공고문에서 자격과 일정을 꼭 확인하세요."
        summary = "[%s] %s" % (short, listing["name"])
        lines = [
            "BEGIN:VEVENT",
            f"UID:{listing['id']}-{event['kind']}@cheongyakping",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{start:%Y%m%d}",
            f"DTEND;VALUE=DATE:{(end + timedelta(days=1)):%Y%m%d}",
            f"SUMMARY:{esc(summary)}",
            f"LOCATION:{esc(listing['address'])}",
            f"DESCRIPTION:{esc(desc)}",
            "TRANSP:TRANSPARENT",
        ]
        if listing.get("url"):
            lines.append(f"URL:{listing['url']}")
        if with_alarms and end >= today_kst():
            lines += alarm_blocks(listing, event, cfg)
        lines.append("END:VEVENT")
        out += lines
    return out


def calendar(name, body_lines):
    head = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//CheongyakPing//KO", "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH", f"X-WR-CALNAME:{esc(name)}", "X-WR-TIMEZONE:Asia/Seoul",
        "REFRESH-INTERVAL;VALUE=DURATION:PT12H", "X-PUBLISHED-TTL:PT12H",
    ]
    lines = head + body_lines + ["END:VCALENDAR"]
    return "\r\n".join(fold(x) for x in lines) + "\r\n"


# ---------------------------------------------------------------- 메인

def main():
    cfg = load_config()
    today = today_kst()
    key = os.environ.get("APPLYHOME_SERVICE_KEY", "").strip()
    debug = []

    if key:
        listings = fetch_all(key, cfg["regions"], today)
        sample = False
        debug = attach_supply(key, listings)   # 싱글/신혼부부 구분용 주택형 정보
        got = sum(1 for x in listings if x.get("supply"))
        print(f"주택형 정보: {got}/{len(listings)}개 단지", file=sys.stderr)
    else:
        print("APPLYHOME_SERVICE_KEY 가 없어 샘플 데이터로 만듭니다.", file=sys.stderr)
        listings = [x for x in sample_listings(today) if x["region"] in cfg["regions"]]
        sample = True

    def first_day(x):
        return min(e["start"] for e in x["events"] if e["kind"] != "announcement")

    listings.sort(key=first_day)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    DOCS.mkdir(exist_ok=True)
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")
    if debug:  # API 응답 샘플 (필드명 확인용)
        (DOCS / "debug_models.json").write_text(json.dumps(debug, ensure_ascii=False, indent=1), encoding="utf-8")
    if RAW_SAMPLE:
        (DOCS / "debug_detail.json").write_text(json.dumps(RAW_SAMPLE, ensure_ascii=False, indent=1), encoding="utf-8")

    payload = {
        "updated": datetime.now(KST).isoformat(timespec="minutes"),
        "sample": sample,
        "alarm_hour": cfg["alarm_hour"],
        "alarms": cfg["alarms"],
        "kinds": {k: {"title": t, "short": s, "hint": h} for k, (t, s, h) in KINDS.items()},
        "listings": listings,
    }
    (DOCS / "listings.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    ics_dir = DOCS / "ics"
    if ics_dir.exists():
        shutil.rmtree(ics_dir)
    ics_dir.mkdir()

    all_lines = []
    for listing in listings:
        all_lines += vevents(listing, cfg, with_alarms=False, stamp=stamp)
        one = calendar(f"청약핑 · {listing['name']}", vevents(listing, cfg, with_alarms=True, stamp=stamp))
        (ics_dir / f"{listing['id']}.ics").write_text(one, encoding="utf-8", newline="")
    (DOCS / "all.ics").write_text(calendar("청약핑 · 서울·경기 청약", all_lines), encoding="utf-8", newline="")

    print(f"완료: 단지 {len(listings)}개 ({'샘플' if sample else '실데이터'})")


if __name__ == "__main__":
    main()
