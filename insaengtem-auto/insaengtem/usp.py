"""USP 계산 (순수 함수). 영상에 계산식이 그대로 노출되므로 반올림 규칙을 엄격히 지킨다.

규칙
- 원 단위 정수. 나눠떨어지지 않으면 반올림하고 '약'을 붙인다.
- 배송비가 있고 무료배송 조건 미달이면 '배송비 넣어도 한 개 N원' 문구 생성.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal


def won(n: int | float) -> str:
    return f"{int(n):,}원"


def round_won(x: Decimal | float) -> int:
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@dataclass
class Option:
    label: str          # "60구"
    price: int          # 총 결제가(옵션 추가금 포함)
    qty: int            # 60
    unit: str = "개"    # "알" / "포" / "팩"


@dataclass
class UnitPrice:
    option: Option
    exact: bool                 # 나눠떨어지는가
    per_unit: int               # 반올림된 1단위 가격
    shipping: int               # 이 옵션 1회 구매 시 배송비
    per_unit_with_ship: int
    exact_with_ship: bool

    @property
    def formula(self) -> str:
        return f"{self.option.label} {won(self.option.price)} ÷ {self.option.qty}"

    @property
    def text(self) -> str:
        return f"1{self.option.unit} {'' if self.exact else '약 '}{won(self.per_unit)}"

    @property
    def text_with_ship(self) -> str:
        return f"1{self.option.unit} {'' if self.exact_with_ship else '약 '}{won(self.per_unit_with_ship)}"


@dataclass
class UspResult:
    rows: list[UnitPrice]
    best: UnitPrice
    worst: UnitPrice
    saving_per_unit: int            # 최저단가 vs 최고단가 1단위 차이(반올림)
    saving_exact: bool
    shipping_fee: int
    free_over: int | None
    discount_rate: int | None = None  # 정가 대비 할인율(%) 반올림
    lines: dict = field(default_factory=dict)


def shipping_for(price: int, shipping_fee: int, free_over: int | None) -> int:
    if shipping_fee <= 0:
        return 0
    if free_over is not None and price >= free_over:
        return 0
    return shipping_fee


def unit_prices(options: list[Option | dict], shipping_fee: int = 0, free_over: int | None = None,
                list_price: int | None = None, sale_price: int | None = None) -> UspResult:
    opts = [o if isinstance(o, Option) else Option(**o) for o in options]
    if not opts:
        raise ValueError("옵션이 비어 있습니다")
    rows: list[UnitPrice] = []
    for o in opts:
        if o.qty <= 0:
            raise ValueError(f"수량이 0 이하: {o}")
        q = Decimal(o.price) / Decimal(o.qty)
        ship = shipping_for(o.price, shipping_fee, free_over)
        qs = (Decimal(o.price) + ship) / Decimal(o.qty)
        rows.append(UnitPrice(o, q == q.to_integral_value(), round_won(q), ship, round_won(qs),
                              qs == qs.to_integral_value()))
    best = min(rows, key=lambda r: Decimal(r.option.price) / r.option.qty)
    worst = max(rows, key=lambda r: Decimal(r.option.price) / r.option.qty)
    diff = Decimal(worst.option.price) / worst.option.qty - Decimal(best.option.price) / best.option.qty
    res = UspResult(rows, best, worst, round_won(diff), diff == diff.to_integral_value(), shipping_fee, free_over)
    if list_price and sale_price and list_price > sale_price:
        res.discount_rate = round_won(Decimal(list_price - sale_price) * 100 / Decimal(list_price))
    res.lines = summary_lines(res)
    return res


def summary_lines(r: UspResult) -> dict:
    """영상·캡션에 그대로 쓰는 문구 묶음."""
    b = r.best
    out = {
        "formula": b.formula,
        "value": b.per_unit,
        "fmt": f"1{b.option.unit} {'' if b.exact else '약 '}{{}}원",
        "best_text": b.text,
    }
    if b.shipping:
        out["ship_line"] = f"배송비 {won(b.shipping)}까지 넣어도 {b.text_with_ship}"
    elif r.shipping_fee and r.free_over:
        out["ship_line"] = f"{won(r.free_over)} 이상 무료배송"
    else:
        out["ship_line"] = "무료배송이라 추가 비용 0원"
    if len(r.rows) > 1 and r.saving_per_unit > 0:
        u = b.option.unit
        approx = "" if r.saving_exact else "약 "
        lab = b.option.label
        last = lab[-1]
        has = ("가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 != 0) or last in "0136781"
        out["saving_line"] = f"{lab}{'이' if has else '가'} {r.worst.option.label}보다 1{u} {approx}{won(r.saving_per_unit)} 저렴"
    if r.discount_rate:
        out["discount_line"] = f"{r.discount_rate}% 할인 중"
    out["table"] = [[x.option.label, won(x.option.price), x.text] for x in r.rows]
    return out


def allowed_amounts(r: UspResult, extra: list[int] | None = None) -> set[int]:
    """검수용: 콘텐츠에 등장해도 되는 금액 집합."""
    s: set[int] = set(extra or [])
    for x in r.rows:
        s |= {x.option.price, x.per_unit, x.per_unit_with_ship, x.shipping}
    s |= {r.shipping_fee, r.saving_per_unit}
    if r.free_over:
        s.add(r.free_over)
    s.discard(0)
    return s
