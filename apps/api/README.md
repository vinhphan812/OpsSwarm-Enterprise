# API

Python FastAPI backend.

Initial endpoints:
- GET /health
- GET /store
- GET /inventory/{sku}
- POST /events
- POST /actions/submit
- POST /guard/validate

Live-state writes must flow through Decision Context Guard.
