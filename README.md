# delta-trader

Production trading daemon for Delta Exchange India API v2.

Features:
- Cryptographic HMAC-SHA256 request signing (`METHOD + TIMESTAMP + PATH + QUERY + BODY`)
- Strict testnet safety locks (`https://cdn-ind.testnet.deltaex.org`)
- Live order lifecycle management & paper trading engine
- Automated stop loss, take profit (TP1, TP2, Final), and trailing stops
- Real-time outbound webhook and Telegram event telemetry
- Pre-trade risk manager (leverage limits, daily drawdown circuit breakers, slippage bounds)
- Command-line interface for manual interventions and operational queries

## Architecture

```
delta-trader/
├── config/
│   └── settings.py
├── src/
│   ├── client.py
│   ├── paper_engine.py
│   ├── risk_manager.py
│   ├── daemon.py
│   ├── reconciliation.py
│   └── cli.py
├── requirements.txt
└── README.md
```

## Quick Start

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Configure environment:
```bash
cp .env.example .env
```

3. Run the trading daemon:
```bash
python -m src.daemon --mode paper
```

4. Launch interactive CLI:
```bash
python -m src.cli --help
```
