def final_price(price: float, percent: float, coupon: float) -> float:
    discounted = (price - coupon) * (1 - percent / 100)
    return max(0.0, round(discounted, 2))
