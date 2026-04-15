"""
Windows PC에서 실행: 동행복권에서 1~265회 로또 번호를 CSV로 저장.
사용법:
  pip install requests
  python lotto_fetch_from_pc.py
  scp lotto_1_265.csv jayeondeule@lockers7.iptime.org:/workspace/jayeondeule/
"""
import csv
import time

try:
    import requests
except ImportError:
    print("requests 설치 필요: pip install requests")
    exit(1)

API_URL = "https://www.dhlottery.co.kr/common.do?method=getLottoNumber&drwNo={}"
OUTPUT = "lotto_1_265.csv"

session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/javascript, */*',
    'Referer': 'https://www.dhlottery.co.kr/gameResult.do?method=byWin',
})

rows = []
fail_count = 0

for draw_no in range(1, 266):
    try:
        resp = session.get(API_URL.format(draw_no), timeout=10)
        text = resp.text.strip()

        # HTML 응답인지 확인
        if text.startswith('<') or 'DOCTYPE' in text[:100]:
            fail_count += 1
            if fail_count <= 3:
                print(f"  {draw_no}회: HTML 응답 (API 차단)")
            if fail_count == 4:
                print("  ... (이하 동일 에러 생략)")
            continue

        data = resp.json()
        if data.get("returnValue") == "success":
            rows.append([
                draw_no,
                data["drwNoDate"],
                data["drwtNo1"], data["drwtNo2"], data["drwtNo3"],
                data["drwtNo4"], data["drwtNo5"], data["drwtNo6"],
                data["bnusNo"],
            ])
            if draw_no % 50 == 0:
                print(f"  {draw_no}회 수집 완료... ({len(rows)}건)")
        else:
            print(f"  {draw_no}회: returnValue={data.get('returnValue')}")

    except Exception as e:
        fail_count += 1
        if fail_count <= 5:
            print(f"  {draw_no}회 에러: {e}")
        continue

    time.sleep(0.3)

if rows:
    with open(OUTPUT, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['draw_no', 'draw_date', 'num1', 'num2', 'num3', 'num4', 'num5', 'num6', 'bonus'])
        writer.writerows(rows)
    print(f"\n성공! {len(rows)}건 → {OUTPUT}")
    print(f"서버 업로드: scp {OUTPUT} jayeondeule@lockers7.iptime.org:/workspace/jayeondeule/")
else:
    print(f"\n수집 실패: {fail_count}건 에러")
    print("동행복권 API가 차단된 것 같습니다.")
    print("브라우저에서 https://www.dhlottery.co.kr/common.do?method=getLottoNumber&drwNo=1 접속해 보세요.")
    print("JSON이 보이면 VPN/프록시 문제, HTML이 보이면 API 자체 변경입니다.")
