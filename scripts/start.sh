#!/bin/bash
cd /Users/arnavmukherjee/Robo-Trader-Agent
export SSL_CERT_FILE=$(/Users/arnavmukherjee/Robo-Trader-Agent/.venv/bin/python -c "import certifi; print(certifi.where())")
exec /Users/arnavmukherjee/Robo-Trader-Agent/.venv/bin/python -m scripts.run_scalper
