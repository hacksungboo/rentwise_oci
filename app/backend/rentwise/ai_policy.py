"""Model-specific standard short-context prices, verified 2026-10-17.

Source: https://developers.openai.com/api/docs/models/gpt-5.6-terra
Keep the legacy Luna version so an in-flight call cannot be repriced by settings.
"""
from decimal import Decimal

DEFAULT_MODEL = 'gpt-5.6-terra'
PRICE_VERSION = 'openai-standard-2026-10-17-terra'
PRICES = {
    'gpt-5.6-luna': (Decimal('.20'), Decimal('.02'), Decimal('1.20')),
    'gpt-5.6-terra': (Decimal('2.00'), Decimal('.20'), Decimal('12.00')),
}
PRICE_VERSIONS = {
    'gpt-5.6-luna': 'openai-standard-2026-10-16',
    'gpt-5.6-terra': PRICE_VERSION,
}


def price_version(model_id):
    return PRICE_VERSIONS[model_id]


def rates_for_version(version):
    for model_id, known in PRICE_VERSIONS.items():
        if known == version:
            return PRICES[model_id]
    raise ValueError('Unregistered AI price version')
