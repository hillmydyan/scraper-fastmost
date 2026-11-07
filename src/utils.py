"""Utility functions for FastMoss Scraper"""
import re
from typing import Union, Optional

def parse_revenue_value(val: Union[str, int, float, None]) -> float:
    """
    Mengonversi string nilai penjualan / omzet FastMoss atau input user
    ke angka float standar.
    
    Contoh:
    - 'RM952.2'       -> 952.2
    - 'RM 200'        -> 200.0
    - '50 rm'         -> 50.0
    - 'RM 4.54k'      -> 4540.0
    - 'RM 1.5m'       -> 1500000.0
    - 'Rp 150.000'    -> 150000.0
    - 'Rp 20.000.000' -> 20000000.0
    - '20jt' / '20 jt'-> 20000000.0
    - '20 juta'       -> 20000000.0
    - 'Rp 25,5 rb'    -> 25500.0
    - 'Rp 1.2 jt'     -> 1200000.0
    - '200'           -> 200.0
    - '-' / None      -> 0.0
    """
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
        
    s = str(val).strip().lower()
    if not s or s == '-' or s == 'none':
        return 0.0

    # Strip simbol mata uang dan kata mata uang dari seluruh string
    s = re.sub(r'\b(rm|rp|idr|myr|usd)\b', '', s)
    s = s.replace('$', '').strip()

    multiplier = 1.0
    if 'jt' in s or 'juta' in s:
        multiplier = 1_000_000.0
        s = re.sub(r'(jt|juta)', '', s).strip()
    elif 'rb' in s or 'ribu' in s:
        multiplier = 1_000.0
        s = re.sub(r'(rb|ribu)', '', s).strip()
    elif s.endswith('m'):
        multiplier = 1_000_000.0
        s = s[:-1].strip()
    elif s.endswith('b'):
        multiplier = 1_000_000_000.0
        s = s[:-1].strip()
    elif s.endswith('k'):
        multiplier = 1_000.0
        s = s[:-1].strip()

    # Normalisasi pemisah ribuan vs desimal
    if ',' in s and '.' in s:
        if s.find('.') < s.find(','):  # Format Eropa/ID: 1.250,50
            s = s.replace('.', '').replace(',', '.')
        else:  # Format US: 1,250.50
            s = s.replace(',', '')
    elif ',' in s:
        parts = s.split(',')
        if len(parts) == 2 and len(parts[1]) == 3 and multiplier == 1.0:
            s = s.replace(',', '')
        else:
            s = s.replace(',', '.')
    elif '.' in s:
        parts = s.split('.')
        if len(parts) > 2:
            s = s.replace('.', '')
        elif len(parts) == 2 and len(parts[1]) == 3 and multiplier == 1.0:
            s = s.replace('.', '')

    try:
        m = re.search(r'[-+]?\d*\.?\d+', s)
        if m:
            return float(m.group(0)) * multiplier
    except Exception:
        pass

    return 0.0

