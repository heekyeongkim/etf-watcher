# -*- coding: utf-8 -*-
"""
TIME ETF 구성종목 변경 감지 → 텔레그램 알림
- 매 실행 시 현재 구성종목을 가져와 직전 스냅샷(holdings.json)과 비교
- 종목 추가/제외, 또는 비중 변화가 THRESHOLD(%p) 이상이면 텔레그램 발송
"""
import json
import os
import sys
import requests
from bs4 import BeautifulSoup

# ── 설정 ─────────────────────────────────────────────
ETF_URL = "https://timeetf.co.kr/m11_view.php?idx=22&cate=001"
ETF_NAME = "TIME 글로벌탑픽액티브"
SNAPSHOT_FILE = "holdings.json"
THRESHOLD = 0.5  # 비중 변화 알림 기준 (%p). 0으로 두면 모든 변화 알림

BOT_TOKEN = os.environ["TG_BOT_TOKEN"]
CHAT_ID = os.environ["TG_CHAT_ID"]
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def fetch_holdings() -> dict:
    """구성종목 테이블 파싱 → {종목명: {"code": 종목코드, "weight": 비중}}"""
    res = requests.get(ETF_URL, headers=HEADERS, timeout=30)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")

    holdings = {}
    # '구성종목' 섹션의 테이블: 종목코드 | 종목명 | 수량 | 평가금액 | 비중(%)
    for table in soup.find_all("table"):
        header = [th.get_text(strip=True) for th in table.find_all("th")]
        if "종목코드" in header and "비중(%)" in header:
            for tr in table.find_all("tr"):
                tds = [td.get_text(strip=True) for td in tr.find_all("td")]
                if len(tds) >= 5 and tds[1]:
                    try:
                        weight = float(tds[4].replace(",", ""))
                    except ValueError:
                        continue
                    holdings[tds[1]] = {"code": tds[0], "weight": weight}
            break

    if not holdings:
        raise RuntimeError("구성종목 테이블을 찾지 못했습니다 (사이트 구조 변경 가능성)")
    return holdings


def diff(old: dict, new: dict) -> list[str]:
    lines = []
    added = new.keys() - old.keys()
    removed = old.keys() - new.keys()

    for name in sorted(added):
        lines.append(f"🆕 신규 편입: {name} ({new[name]['weight']:.2f}%)")
    for name in sorted(removed):
        lines.append(f"❌ 편출: {name} (기존 {old[name]['weight']:.2f}%)")
    for name in sorted(old.keys() & new.keys()):
        delta = new[name]["weight"] - old[name]["weight"]
        if abs(delta) >= THRESHOLD:
            arrow = "🔺" if delta > 0 else "🔻"
            lines.append(
                f"{arrow} {name}: {old[name]['weight']:.2f}% → "
                f"{new[name]['weight']:.2f}% ({delta:+.2f}%p)"
            )
    return lines


def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    r = requests.post(url, data={"chat_id": CHAT_ID, "text": text}, timeout=30)
    r.raise_for_status()


def main():
    new = fetch_holdings()

    if not os.path.exists(SNAPSHOT_FILE):
        # 최초 실행: 스냅샷만 저장하고 알림 없이 종료
        with open(SNAPSHOT_FILE, "w", encoding="utf-8") as f:
            json.dump(new, f, ensure_ascii=False, indent=2)
        print("최초 스냅샷 저장 완료")
        return

    with open(SNAPSHOT_FILE, encoding="utf-8") as f:
        old = json.load(f)

    changes = diff(old, new)
    if changes:
        msg = f"📊 [{ETF_NAME}] 구성종목 변경 감지\n{ETF_URL}\n\n" + "\n".join(changes)
        send_telegram(msg)
        print("알림 발송:\n" + msg)
    else:
        print("변경 없음")

    with open(SNAPSHOT_FILE, "w", encoding="utf-8") as f:
        json.dump(new, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # 스크립트 자체 오류도 텔레그램으로 통지 (사이트 구조 변경 조기 발견용)
        try:
            send_telegram(f"⚠️ ETF 모니터링 스크립트 오류: {e}")
        finally:
            sys.exit(1)
