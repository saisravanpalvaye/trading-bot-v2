import requests
from datetime import date
from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID


def send(text):
    url    = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    params = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        r = requests.post(url, params=params, timeout=10)
        if r.status_code == 200:
            print("Telegram alert sent.")
            return True
        print(f"Telegram error {r.status_code}: {r.text}")
        return False
    except Exception as e:
        print(f"Telegram failed: {e}")
        return False


def send_photo(image_bytes: bytes, caption: str) -> bool:
    """
    Send a PNG image to Telegram with a plain-text caption.
    Falls back to text message if photo send fails.
    """
    from config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    try:
        r = requests.post(url, data={
            "chat_id":    TELEGRAM_CHAT_ID,
            "caption":    caption,
            "parse_mode": "HTML",
        }, files={
            "photo": ("alert.png", image_bytes, "image/png"),
        }, timeout=30)
        if r.status_code == 200:
            print("Telegram photo sent.")
            return True
        print(f"Telegram photo error {r.status_code}: {r.text[:100]}")
        return False
    except Exception as e:
        print(f"Telegram photo failed: {e}")
        return False


def send_alert_with_image(picks, stale_exits, trailing_sls,
                          deployed, available,
                          nifty_rsi, vix_val, vix_label,
                          vix_action, regime, regime_desc,
                          **kwargs) -> bool:
    """
    Try to send image alert. Falls back to text if image fails.
    This is the main entry point called by run.py.
    """
    # Try image first
    try:
        from chart import build_alert_image, build_caption
        img_bytes = build_alert_image(
            picks        = picks,
            stale_exits  = stale_exits,
            trailing_sls = trailing_sls or [],
            deployed     = deployed,
            available    = available,
            nifty_rsi    = nifty_rsi,
            vix_val      = vix_val,
            vix_label    = vix_label,
            vix_action   = vix_action,
            regime       = regime,
            regime_desc  = regime_desc,
        )
        if img_bytes:
            caption = build_caption(picks, vix_val, vix_action)
            if send_photo(img_bytes, caption):
                return True
            print("  Photo send failed — falling back to text")
    except Exception as e:
        print(f"  Image generation error: {e} — falling back to text")

    # Fallback to text message
    print("  Sending text alert instead...")
    message = build_message(
        picks        = picks,
        stale_exits  = stale_exits,
        upgrades     = kwargs.get("upgrades", []),
        deployed     = deployed,
        available    = available,
        nifty_rsi    = nifty_rsi,
        vix_val      = vix_val,
        vix_label    = vix_label,
        vix_action   = vix_action,
        regime       = regime,
        regime_desc  = regime_desc,
        trailing_sls = trailing_sls,
    )
    return send(message)


def regime_line(regime, regime_desc, nifty_rsi, vix_val, vix_action):
    regime_colors = {
        "BULLISH":  "🟢", "BEARISH": "🔴",
        "SIDEWAYS": "🟡", "OVERSOLD": "🔵",
        "HIGH_VIX": "🔴", "NEUTRAL": "⚪", "UNKNOWN": "⚪",
    }
    vix_icon = "🟢" if vix_action == "normal" else ("🟡" if vix_action == "reduce" else "🔴")
    ricon        = regime_colors.get(regime, "⚪")
    regime_label = regime.replace("_", " ")
    rsi_str      = f"RSI {nifty_rsi}" if nifty_rsi else "RSI --"
    vix_str      = f"VIX {vix_val}" if vix_val else "VIX --"
    return (
        f"{ricon} <b>{regime_label}</b>  ·  {rsi_str}  {vix_icon} {vix_str}\n"
        f"<i>{regime_desc}</i>"
    )


def conf_dots(conf_factors):
    """6 emoji dots in one line — green/amber/red."""
    dot_map = {"green": "✅", "amber": "⚠️", "red": "❌"}
    dots    = "".join(dot_map.get(v[1], "⚪") for v in conf_factors.values())
    greens  = sum(1 for v in conf_factors.values() if v[1] == "green")
    return f"{dots}  <i>{greens}/6 green</i>"


def why_line(reasons):
    """Compact one-line reasons summary."""
    short = []
    for r in reasons[:4]:
        # shorten each reason to key phrase
        r = r.replace("recovering from oversold", "recov")
        r = r.replace("bullish crossover", "cross")
        r = r.replace("above signal — bullish trend active", "above sig")
        r = r.replace("above EMA20 and EMA50 — confirmed uptrend", "EMA bull")
        r = r.replace("above EMA20 — short-term bullish", "EMA20 bull")
        r = r.replace("bullish — trend confirmed", "bull")
        r = r.replace("spike — institutional buying detected", "spike")
        r = r.replace("— moderate trend", "mod")
        r = r.replace("— very strong trend", "strong")
        r = r.replace("buyers in control", "bulls lead")
        r = r.replace("momentum accelerating", "accel")
        r = r.replace("mild bullish bias", "mild bull")
        short.append(r.split("—")[0].strip().split("(")[0].strip())
    return "  ·  ".join(short[:3])


def opp_icon(opp_type):
    return {
        "BREAKOUT":        "📈",
        "OVERSOLD BOUNCE": "🔄",
        "MOMENTUM SURGE":  "⚡",
        "SECTOR PLAY":     "🔀",
        "TREND FOLLOW":    "📊",
    }.get(opp_type, "📊")

def confirmed_badge(pick):
    """Show ✔ if 2-candle confirmation passed."""
    if pick.get("two_candle_confirmed"):
        return " ✔ confirmed"
    return ""


def action_line(action, action_detail):
    icons = {
        "STRONG BUY": "🚀", "BUY": "✅",
        "WATCH": "👁",  "SKIP": "⏭", "AVOID": "🚫",
    }
    icon = icons.get(action, "➡️")
    return f"{icon} <b>ACTION : {action}</b>\n         <i>{action_detail}</i>"


def fmt_top_pick(pick):
    """Gold-bordered top pick box."""
    pct_g  = round((pick["target"] - pick["ltp"]) / pick["ltp"] * 100, 1)
    pct_l  = round((pick["ltp"]    - pick["sl"])  / pick["ltp"] * 100, 1)
    profit = round((pick["target"] - pick["ltp"]) * pick["qty"], 0)
    loss   = round((pick["ltp"]    - pick["sl"])  * pick["qty"], 0)
    stars  = "★" * min(5, pick["score"] // 20)
    size_n = "  ⚠️ 50% size" if pick.get("vix_reduced") else ""
    adx_s  = f"ADX {pick['adx']}" if pick.get("adx") else ""

    return (
        f"\n┌─── ★ TOP PICK  ·  HIGHEST CONVICTION ───┐\n"
        f"│\n"
        f"│ <b>{pick['ticker'].replace('.NS','').replace('&','&amp;')}</b>  <i>[NSE · {pick['sector_label']}]</i>  "
        f"{pick['score']}/100  {stars}\n"
        f"│ {opp_icon(pick['opp_type'])} {pick['opp_type']}  ·  Hold {pick['hold_days']} days{confirmed_badge(pick)}\n"
        f"│ {adx_s}\n"
        f"│ ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        f"│ ENTRY   <b>₹{pick['entry']:,.2f}</b>\n"
        f"│ TARGET  ₹{pick['target']:,.2f}  ▲ +{pct_g}%  <i>(+₹{profit:,.0f})</i>\n"
        f"│ SL      ₹{pick['sl']:,.2f}  ▼ -{pct_l}%  <i>(-₹{loss:,.0f})</i>\n"
        f"│ SIZE    {pick['qty']} shares  ·  ₹{pick['capital']:,.0f}  ·  R:R 1:{pick['rr']}{size_n}\n"
        f"│ ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        f"│ CONF    🔥 {pick['confidence']}  {conf_dots(pick['conf_factors'])}\n"
        f"│ WHY     <i>{why_line(pick['reasons'])}</i>\n"
        f"│ {action_line(pick['action'], pick['action_detail'])}\n"
        f"│\n"
        f"└──────────────────────────────────────┘"
    )


def fmt_other_pick(pick, rank):
    """Dimmer box for pick 2 and 3."""
    pct_g  = round((pick["target"] - pick["ltp"]) / pick["ltp"] * 100, 1)
    pct_l  = round((pick["ltp"]    - pick["sl"])  / pick["ltp"] * 100, 1)
    profit = round((pick["target"] - pick["ltp"]) * pick["qty"], 0)
    stars  = "★" * min(5, pick["score"] // 20)
    size_n = "  ⚠️ 50% size" if pick.get("vix_reduced") else ""

    return (
        f"\n┌─── #{rank} PICK ──────────────────────────┐\n"
        f"│ <b>{pick['ticker'].replace('.NS','').replace('&','&amp;')}</b>  "
        f"{pick['score']}/100  {stars}  "
        f"{opp_icon(pick['opp_type'])} {pick['opp_type']}\n"
        f"│ ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        f"│ ENTRY   <b>₹{pick['entry']:,.2f}</b>\n"
        f"│ TARGET  ₹{pick['target']:,.2f}  ▲ +{pct_g}%  <i>(+₹{profit:,.0f})</i>\n"
        f"│ SL      ₹{pick['sl']:,.2f}  ▼ -{pct_l}%\n"
        f"│ SIZE    {pick['qty']} shares  ·  ₹{pick['capital']:,.0f}  ·  R:R 1:{pick['rr']}{size_n}\n"
        f"│ ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        f"│ CONF    {pick['confidence']}  {conf_dots(pick['conf_factors'])}\n"
        f"│ WHY     <i>{why_line(pick['reasons'])}</i>\n"
        f"│ {action_line(pick['action'], pick['action_detail'])}\n"
        f"└──────────────────────────────────────┘"
    )


def build_message(picks, stale_exits, upgrades,
                  deployed, available,
                  nifty_rsi=None,
                  vix_val=None, vix_label="", vix_action="normal",
                  regime="NEUTRAL", regime_desc="",
                  trailing_sls=None):

    today = date.today().strftime("%d %b %Y, %a").upper()
    lines = []

    # ── header ──
    lines.append(
        f"<b>╔══════════════════════════════════╗</b>\n"
        f"<b>  TRADING BOT  ·  {today}</b>\n"
        f"<b>╚══════════════════════════════════╝</b>"
    )

    # ── market context ──
    lines.append(regime_line(regime, regime_desc, nifty_rsi, vix_val, vix_action))
    lines.append(f"<b>CAPITAL</b>  ₹{deployed:,.0f} deployed  ·  ₹{available:,.0f} free")
    lines.append("──────────────────────────────────")

    # ── VIX block ──
    if vix_action == "avoid":
        lines.append(
            "🔴 <b>HIGH VOLATILITY — NO TRADES TODAY</b>\n"
            "VIX above 22. All picks suppressed.\n"
            "Stay in cash. Wait for VIX below 18."
        )
        lines.append("──────────────────────────────────")
        lines.append("⚠️  2% risk max  ·  Set SL before entry\n    Not SEBI advice  ·  Your decision")
        return "\n".join(lines)

    if vix_action == "reduce":
        lines.append("🟡 <b>ELEVATED VIX — SIZES HALVED</b>")
        lines.append("──────────────────────────────────")

    # ── exits ──
    if stale_exits:
        lines.append("<b>EXIT ALERTS — 5-day cap reached</b>")
        for t in stale_exits:
            lines.append(f"  ⏹ Exit {t['ticker'].replace('.NS','')} — held {t['days_held']} trading days")
        lines.append("──────────────────────────────────")

    # ── trailing SL updates ──
    if trailing_sls:
        lines.append("<b>🔼 TRAIL YOUR STOP-LOSS</b>")
        for sl in trailing_sls:
            ticker = sl['ticker'].replace('.NS','')
            lines.append(
                f"  {ticker} up {sl['gain_pct']}% → "
                f"Move SL: Rs{sl['old_sl']} → <b>Rs{sl['new_sl']}</b>"
            )
            lines.append(f"  <i>{sl['reason']}</i>")
        lines.append("──────────────────────────────────")

    # ── upgrades ──
    if upgrades:
        lines.append("<b>UPGRADE OPPORTUNITY</b>")
        for u in upgrades:
            lines.append(
                f"  🔄 Exit {u['exit_ticker'].replace('.NS','')} "
                f"(score {u['exit_score']}) → "
                f"enter {u['enter_ticker'].replace('.NS','')} "
                f"(score {u['enter_score']}, +{u['score_gap']} pts)"
            )
        lines.append("──────────────────────────────────")

    # ── picks ──
    if picks:
        lines.append(f"<b>TODAY'S PICKS — {len(picks)} setup(s)</b>")
        for i, pick in enumerate(picks):
            if i == 0:
                lines.append(fmt_top_pick(pick))
            else:
                lines.append(fmt_other_pick(pick, i + 1))
    else:
        lines.append("<b>No qualifying setups today.</b>")
        lines.append("Scores below 65 or no regime fit.")
        lines.append("Stay in cash — better setups coming.")

    # ── footer ──
    lines.append("\n──────────────────────────────────")
    lines.append("⚠️  2% risk max  ·  Set SL before entry\n    Not SEBI advice  ·  Your decision")

    return "\n".join(lines)


def send_no_market(reason="Holiday or weekend"):
    """Send image alert for market closed days."""
    try:
        from chart import build_alert_image, build_caption
        img_bytes = build_alert_image(
            picks=[], stale_exits=[], trailing_sls=[],
            deployed=0, available=0,
            nifty_rsi=None, vix_val=None, vix_label="",
            vix_action="normal",
            regime="MARKET CLOSED",
            regime_desc=str(reason),
        )
        if img_bytes:
            caption = f"Market closed today - {reason}. See you next trading day."
            if send_photo(img_bytes, caption):
                return
    except Exception as e:
        print(f"  [send_no_market] Image failed: {e}")
    # fallback to text
    today = date.today().strftime("%d %b %Y, %a").upper()
    send(
        f"<b>TRADING BOT  -  {today}</b>\n\n"
        f"Market closed today\n"
        f"<i>{reason}</i>\n\n"
        f"See you next trading day."
    )


if __name__ == "__main__":
    send("Trading bot — dashboard style upgrade installed. Ready for Monday.")
