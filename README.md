# UAE Climate Mobility Platform

A GPU-accelerated, climate-aware mobility platform for UAE cities. It fuses real
OSM geodata, accurate solar geometry, thermal-comfort science (UTCI/WBGT),
traffic-driven air-quality dispersion, and a multi-objective router into a
high-performance Deck.gl/MapLibre dashboard with three user modes:

- **Pedestrian** - heat-safety, shade, air-quality dose, hydration, cool refuges.
- **Driver** - eco-routing, CO2/fuel, congestion-aware travel.
- **Planner** - city heat-exposure + equity, comfort isochrones, what-if shading.

Everything runs locally. It uses your **RTX 4080 Super** via CuPy when available
and falls back transparently to NumPy on CPU. It works fully offline with a
deterministic synthetic city sector, and uses real free APIs when configured.

## Why it's useful (not gimmicks)

- **UTCI + WBGT heat-safety**, not just temperature - tells you when it is
  genuinely dangerous to walk.
- **Inhaled-dose air quality** (concentration x breathing rate x time) - the
  metric that matters for asthma/children, minimized by the router.
- **Cool-refuge routing** - hops between AC oases (metro, malls, mosques, parks)
  with suggested cooling breaks.
- **Best-departure optimizer** - "leave at 18:00 for the lowest heat stress."
- **Vulnerable-group profiles** - child / elderly / asthma / athlete / wheelchair
  reweight the route objectives.
- **Comfort isochrones** and **planner what-ifs** - shade hotspots and see the
  city-wide comfort gain instantly.

## Architecture

```
React Dashboard (Deck.gl + MapLibre)   <-- REST + WebSocket -->   FastAPI Gateway
                                                                      |
   geo_engine  ·  solar_comfort  ·  traffic_sim  ·  air_quality  ·  router  ·  analytics
                              (compute.xp = CuPy GPU / NumPy CPU)
```

Backend modules live in `backend/app/core/`:

| Module | Role |
|---|---|
| `geo_engine.py` | OSM networks + buildings + cool-refuge POIs, UTM 40N, height raster, caching, synthetic fallback |
| `solar_comfort.py` | pvlib solar position, GPU raster shadow casting, MRT -> UTCI/WBGT, full-day fields |
| `traffic_sim.py` | GPU-vectorized 20k+ agents, congestion -> emissions, binary WebSocket stream |
| `air_quality.py` | Gaussian-plume dispersion -> PM2.5/AQI raster + inhalation dose |
| `router.py` | Multi-objective, multimodal, profile-aware routes with rich metrics |
| `analytics.py` | Comfort isochrones, heat-exposure/equity, what-if scenarios |
| `data/adapters.py` | Hybrid weather/AQI (Open-Meteo + OpenWeather) with simulation fallback |

## Quick start (Windows PowerShell)

```powershell
# Backend (first run sets up the venv + installs deps)
./scripts/run_backend.ps1

# Frontend (in a second terminal)
./scripts/run_frontend.ps1
```

Then open http://localhost:5173.

### Manual setup

```powershell
cd backend
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt
# Optional GPU acceleration (RTX 4080 Super, CUDA 12.x):
./.venv/Scripts/python.exe -m pip install cupy-cuda12x==13.3.0
./.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000

cd ../frontend
npm install
npm run dev
```

### Docker

```bash
docker compose up --build
```

The backend image is CUDA-enabled; run with the NVIDIA Container Toolkit to use
the GPU (the compose file already requests it). Without a GPU it falls back to
CPU automatically.

## Configuration

Copy `.env.example` to `.env`. Key options:

- `PLACE` - any OSM-resolvable area (e.g. `"Dubai Marina, Dubai, UAE"`).
- `FORCE_SYNTHETIC=true` - skip OSM and use the offline synthetic sector (great
  for demos / no internet).
- `FORCE_CPU=true` - disable the GPU even if CuPy is installed.
- `OPENWEATHER_API_KEY` - enables real air-quality data (otherwise simulated).
- `AGENT_COUNT` - number of traffic agents (default 20000).

## Data sources (hybrid)

- **Weather/wind:** [Open-Meteo](https://open-meteo.com) (keyless).
- **Air quality:** OpenWeather Air Pollution (needs a free key).
- **Geodata:** OpenStreetMap via OSMnx.
- Falls back to a physics-based simulation when offline or unconfigured.

## Tests

```powershell
cd backend
./.venv/Scripts/python.exe -m pytest -q
```

Tests run against the offline synthetic sector on CPU and cover solar geometry,
shadow casting, UTCI banding, dispersion/dose, and routing/analytics behaviour.

## API surface

- `GET /api/health`, `/api/sector`, `/api/buildings`, `/api/refuges`
- `GET /api/environment?hour=`, `/api/comfort?hour=`, `/api/solar?hour=`, `/api/air`
- `POST /api/route`, `/api/best-departure`, `/api/isochrone`, `/api/whatif`
- `GET /api/heat-exposure?hour=`, `/api/traffic/stats`
- `WS /ws/traffic` - binary Float32 frames `[lon, lat, speed_norm, emission_norm] * N`

## Notes on performance

- Shadow casting and dispersion are CuPy kernels over rasters; the traffic sim
  updates all agents with a handful of vectorized array ops.
- The full day of comfort fields is computed on demand and cached.
- The traffic stream sends compact binary frames; the frontend renders agents
  with a binary-attribute ScatterplotLayer for 60fps with tens of thousands of
  points.
