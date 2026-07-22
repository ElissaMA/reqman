#!/bin/bash
cd "$(dirname "$0")"
echo "================================================"
echo "  Reqman V3 - Inspection Demand System"
echo "  Architecture: Factory + Blueprint + Service"
echo "================================================"
export PYTHONPATH=src
python3 src/reqman/app.py
