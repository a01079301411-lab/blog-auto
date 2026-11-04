"""교육청 나이스(NEIS) 교육정보 개방 포털: 대구·경북 전체 학교 목록과 대표전화.
키 발급: https://open.neis.go.kr → 회원가입 → 인증키 신청 (무료, 바로 발급) → .env 의 NEIS_KEY
한 달에 한 번만 새로 받고 data/schools.json 에 저장해 둔다."""
import json
import logging
import os
import time

import requests

from config import DATA

log = logging.getLogger(__name__)
CACHE = DATA / "schools.json"
OFFICES = {"D10": "대구", "R10": "경북"}


def load(force=False):
    if CACHE.exists() and not force and time.time() - CACHE.stat().st_mtime < 30 * 86400:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    key = (os.getenv("NEIS_KEY") or "").strip()
    if not key:
        log.info("NEIS_KEY 없음: 학교 전체 목록은 건너뜀")
        return json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else []
    out = []
    for code, region in OFFICES.items():
        page = 1
        while True:
            try:
                r = requests.get("https://open.neis.go.kr/hub/schoolInfo", timeout=30, params={
                    "KEY": key, "Type": "json", "pIndex": page, "pSize": 1000, "ATPT_OFCDC_SC_CODE": code})
                js = r.json()
            except (requests.RequestException, ValueError) as e:
                log.warning("나이스 학교목록 실패: %s", e)
                break
            block = js.get("schoolInfo")
            if not block:
                log.warning("나이스 응답: %s", js.get("RESULT", js))
                break
            rows = block[1].get("row", []) if len(block) > 1 else []
            for s in rows:
                out.append({"학교명": s.get("SCHUL_NM", ""), "학교급": s.get("SCHUL_KND_SC_NM", ""),
                            "설립": s.get("FOND_SC_NM", ""), "시도": region,
                            "교육지원청": s.get("JU_ORG_NM", ""), "주소": s.get("ORG_RDNMA", ""),
                            "전화": s.get("ORG_TELNO", ""), "홈페이지": s.get("HMPG_ADRES", "")})
            total = block[0]["head"][0].get("list_total_count", 0)
            if page * 1000 >= total or not rows:
                break
            page += 1
    if out:
        CACHE.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out
