"""Sprachverständnis: Normalisierung, Tippfehler-Toleranz, Erkennen von Märkten, Strategien, Status, Einstellungen und Zahlen."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import get_close_matches

UMLAUT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def norm(text: str) -> str:
    t = text.lower().translate(UMLAUT).replace("\u00ad", "")
    t = re.sub(r"(\d),(\d)", r"\1.\2", t)
    t = re.sub(r"[^a-z0-9%./+\- ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def tokens(t: str) -> list[str]:
    return [w.strip(".-/") for w in t.split() if w.strip(".-/")]


# --- Vokabular -------------------------------------------------------------
MARKET_WORDS = {
    "BTC/EUR": ["btc", "bitcoin", "bitcoins", "xbt"], "ETH/EUR": ["eth", "ethereum", "ether"], "SOL/EUR": ["sol", "solana"],
    "XRP/EUR": ["xrp", "ripple"], "ADA/EUR": ["ada", "cardano"], "DOT/EUR": ["dot", "polkadot"], "LINK/EUR": ["link", "chainlink"],
    "LTC/EUR": ["ltc", "litecoin"], "AVAX/EUR": ["avax", "avalanche"], "DOGE/EUR": ["doge", "dogecoin", "dogecoins"],
    "AAPL": ["aapl", "apple"], "MSFT": ["msft", "microsoft"], "NVDA": ["nvda", "nvidia"], "AMZN": ["amzn", "amazon"],
    "GOOGL": ["googl", "google", "alphabet"], "META": ["meta", "facebook"], "TSLA": ["tsla", "tesla"], "AMD": ["amd"],
    "NFLX": ["nflx", "netflix"], "SPY": ["spy", "s&p", "sp500", "s+p"], "QQQ": ["qqq", "nasdaq"],
}
GROUP_WORDS = {"krypto": ["kryptos", "krypto", "kryptowaehrungen", "kryptowaehrung", "coins", "crypto", "cryptos"],
               "aktie": ["aktien", "aktie", "etfs", "etf", "stocks"]}
STRATEGY_WORDS = {
    "trendfolge": ["trendfolge", "trend", "trendfolger", "trendfolgestrategie"], "momentum": ["momentum"],
    "mean_reversion": ["mean", "reversion", "meanreversion", "mittelwert"], "ausbruch": ["ausbruch", "breakout", "ausbruchs"],
    "ruecksetzer": ["ruecksetzer", "swing", "pullback", "ruecksetzern"], "range": ["range", "seitwaerts-strategie"],
}
STATUS_WORDS = {
    "live_klein": [["live", "klein"], ["live-klein"], ["liveklein"], ["klein"]], "live": [["live"], ["echtgeld"], ["echt"]],
    "paper": [["paper"], ["papier"], ["spielgeld"], ["demo"], ["test"]], "backtest": [["backtest"]], "entwurf": [["entwurf"]],
    "pausiert": [["pausiert"], ["pausieren"], ["pause"]], "ausgemustert": [["ausgemustert"], ["ausmustern"]],
}
SETTING_WORDS = {
    "risk_per_trade_pct": [["risiko", "pro", "trade"], ["risiko", "je", "trade"], ["risiko", "pro", "kauf"], ["einsatz", "pro", "trade"],
                           ["risiko", "pro", "handel"], ["risiko", "trade"]],
    "daily_loss_limit_pct": [["tagesverlust"], ["verlust", "pro", "tag"], ["taeglich", "verlust"], ["verlustlimit"], ["tageslimit"]],
    "max_drawdown_pct": [["drawdown"], ["rueckgang"]],
    "max_positions": [["positionen"], ["anzahl", "positionen"], ["gleichzeitig"]],
    "max_position_pct": [["groesse", "position"], ["positionsgroesse"], ["anteil", "position"], ["groesse", "je", "position"]],
    "liquidity_reserve_pct": [["reserve"], ["liquiditaetsreserve"]],
    "loss_streak_limit": [["verlustserie"], ["verluste", "in", "folge"]],
    "max_spread_pct": [["spread"]], "min_order_risk_pct": [["mindestorder"], ["kleines", "konto"]],
    "max_total_risk_pct": [["gesamtrisiko"]], "strategy_budget_pct": [["strategie", "budget"], ["strategiebudget"]],
}
AUTOMATION_WORDS = {"halbautomatisch": [["halbautomatisch"], ["halb", "automatisch"], ["bestaetigen", "jeden"]],
                    "signale": [["nur", "signale"], ["nur", "melden"]],
                    "automatisch": [["vollautomatisch"], ["automatisch"], ["selbststaendig"], ["alleine"]]}

ON_WORDS = {"an", "ein", "einschalten", "anschalten", "aktivieren", "aktiviere", "hinzufuegen", "dazu", "dazunehmen", "aufnehmen",
            "freischalten", "handeln", "handle", "schalte_an", "rein", "mit"}
OFF_WORDS = {"aus", "ausschalten", "abschalten", "deaktivieren", "deaktiviere", "entfernen", "entferne", "raus", "weg", "nicht",
             "streichen", "rausnehmen", "nimm"}

VOCAB: set[str] = set()
for _d in (MARKET_WORDS, GROUP_WORDS, STRATEGY_WORDS):
    for ws in _d.values():
        VOCAB.update(w for w in ws if len(w) >= 4)
for _d in (STATUS_WORDS, SETTING_WORDS, AUTOMATION_WORDS):
    for seqs in _d.values():
        for seq in seqs:
            VOCAB.update(w for w in seq if len(w) >= 5)
VOCAB.update(["strategie", "strategien", "starten", "stoppen", "pausieren", "verkaufen", "verkaufe", "uebergeben", "uebergib", "gewinn",
              "verlust", "guthaben", "kontostand", "kontowert", "position", "positionen", "einstellungen", "warum", "kaufen", "kauft",
              "notaus", "freigeben", "kraken", "alpaca", "meldungen", "markt", "maerkte", "risiko", "zustand", "status", "hilfe",
              "strategieauswahl", "vorschlag", "uebernehmen", "einschalten", "ausschalten", "aktivieren", "deaktivieren"])
SYNONYM = {"kranken": "kraken", "krake": "kraken", "alpaka": "alpaca", "bitcion": "bitcoin", "etherium": "ethereum",
           "stratgie": "strategie", "stategie": "strategie", "strategy": "strategie", "papertrading": "paper", "spielgeldkonto": "spielgeld",
           "lifeklein": "liveklein", "life": "live", "echtheit": "echtgeld", "doch": "doch"}


def fix(words: list[str]) -> list[str]:
    out = []
    for w in words:
        w = SYNONYM.get(w, w)
        if len(w) >= 5 and w not in VOCAB and not w.replace(".", "").isdigit():
            m = get_close_matches(w, VOCAB, n=1, cutoff=0.84)
            if m:
                w = m[0]
        out.append(w)
    return out


def has_seq(words: list[str], seq: list[str]) -> bool:
    """Alle Wörter der Folge kommen (in Reihenfolge, Lücken erlaubt) vor; Wortanfang genügt ab 5 Zeichen."""
    i = 0
    for w in words:
        s = seq[i]
        if w == s or (len(s) >= 5 and w.startswith(s)):
            i += 1
            if i == len(seq):
                return True
    return False


def any_word(words: list[str], options) -> bool:
    return any(w in options for w in words)


def stem_in(words: list[str], *stems: str) -> bool:
    return any(w.startswith(s) for w in words for s in stems)


@dataclass
class Parsed:
    text: str
    words: list[str]
    markets: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    strategies: list[str] = field(default_factory=list)
    all_strategies: bool = False
    status: str | None = None
    setting: str | None = None
    automation: str | None = None
    number: float | None = None
    assets: list[str] = field(default_factory=list)


def parse(text: str) -> Parsed:
    t = norm(text)
    words = fix(tokens(t))
    p = Parsed(t, words)
    for sym, ws in MARKET_WORDS.items():
        if any_word(words, ws):
            p.markets.append(sym)
    if "link" in words and stem_in(words, "http"):
        p.markets.remove("LINK/EUR")
    for g, ws in GROUP_WORDS.items():
        if any_word(words, ws):
            p.groups.append(g)
    for sid, ws in STRATEGY_WORDS.items():
        if any_word(words, ws) and sid not in p.strategies:
            if sid == "trendfolge" and "trend" in words and not stem_in(words, "strateg", "trendfolg") and p.markets:
                continue  # „wie ist der Trend bei Bitcoin“ meint die Marktlage
            p.strategies.append(sid)
    p.all_strategies = stem_in(words, "strategien") and any_word(words, {"alle", "allen", "jede", "saemtliche"})
    # „von Live auf Paper“: das Ziel steht hinter dem letzten „auf“
    tail = words[len(words) - 1 - words[::-1].index("auf"):] if "auf" in words else words
    for st in ("live_klein", "paper", "backtest", "entwurf", "ausgemustert", "pausiert", "live"):
        if any(has_seq(tail, seq) for seq in STATUS_WORDS[st]):
            if st == "live_klein" and not has_seq(tail, ["live"]) and "liveklein" not in tail and "live-klein" not in tail:
                continue
            p.status = st
            break
    if p.status is None and "aus" in words and any_word(words, {"mustere", "muster", "mustern"}):
        p.status = "ausgemustert"  # „Mustere Range aus“
    for key, seqs in SETTING_WORDS.items():
        if any(has_seq(words, seq) for seq in seqs):
            p.setting = key
            break
    for mode in ("halbautomatisch", "signale", "automatisch"):
        if any(has_seq(words, seq) for seq in AUTOMATION_WORDS[mode]):
            p.automation = mode
            break
    m = re.search(r"(-?\d+(?:\.\d+)?)", t)
    if m:
        p.number = float(m.group(1))
    p.assets = [s.split("/")[0] for s in p.markets]
    return p
