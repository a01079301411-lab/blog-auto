# secrets/ (git에 올라가지 않음)

| 파일 | 내용 |
|---|---|
| `affiliate_links.json` | 제품 key → 제휴 링크(`sl=` 토큰 포함). 예시: `affiliate_links.example.json` |

만드는 법 (원본 zip의 `_catalog.json`에 링크가 그대로 있음):

```bash
python -m insaengtem links import "C:/Users/<나>/Downloads/insaengtem-auto/data/products/_catalog.json"
```
