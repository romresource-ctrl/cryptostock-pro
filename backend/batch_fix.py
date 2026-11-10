@app.get('/api/dashboard/batch')
def dashboard_batch(markets: str = 'crypto', timeframe: str = '1h', sort: str = 'premium'):
    return [{'symbol': 'BTC', 'name': 'Bitcoin', 'price': 90000, 'change': 2.5}]
