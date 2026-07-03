"""
news.py — Economic Calendar News Filter
Pauses trading 30 minutes before/after high-impact events.
Get a free API key: https://site.financialmodelingprep.com/
"""
import requests
from datetime import datetime
import pytz

NY_TZ   = pytz.timezone('America/New_York')
FMP_KEY = ""   # Set your FMP API key here or via env var

def is_news_paused(symbol):
    """Returns True if within 30 min of a high-impact news event."""
    if not FMP_KEY:
        return False
    try:
        currency = 'USD'
        if 'GBP' in symbol: currency = 'GBP'
        elif 'EUR' in symbol: currency = 'EUR'
        elif 'JPY' in symbol: currency = 'JPY'
        elif 'AUD' in symbol: currency = 'AUD'
        elif 'CAD' in symbol: currency = 'CAD'
        elif 'XAU' in symbol: currency = 'USD'

        url   = f"https://financialmodelingprep.com/api/v3/economic_calendar?apikey={FMP_KEY}"
        items = requests.get(url, timeout=8).json()
        now   = datetime.now(NY_TZ)

        for item in items:
            if item.get('impact') == 'High' and item.get('currency') == currency:
                evt = datetime.fromisoformat(
                    item['date'].replace('Z', '+00:00')).astimezone(NY_TZ)
                if abs((evt - now).total_seconds() / 60) <= 30:
                    print(f"   📰 News pause: {item.get('event','?')} in {currency}")
                    return True
        return False
    except:
        return False

def get_upcoming_news():
    return []
