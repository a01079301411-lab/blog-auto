"""표준 라이브러리만 쓰는 HTTP 도우미. 재시도와 타임아웃을 담당한다."""
import json
import time
import urllib.error
import urllib.request

UA = "Mozilla/5.0 (compatible; sports-data-collector/1.0)"


def get_json(url, retries=3, timeout=20):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500:  # 잘못된 요청은 재시도해도 같다
                raise
            last = e
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ConnectionError) as e:
            last = e
        time.sleep(2 ** attempt)
    raise last
