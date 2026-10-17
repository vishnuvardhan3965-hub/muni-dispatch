"""
Configuration and domain constants for the Municipal Hazard & Outage Dispatcher.
"""
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATABASE_URL = os.environ.get("DATABASE_URL", "")
CREW_PIN = os.environ.get("CREW_PIN", "")
PORT = int(os.environ.get("PORT", "8080"))

# Proximity radius in meters for spatial duplicate detection
DUPLICATE_RADIUS_METERS = float(os.environ.get("DUPLICATE_RADIUS_METERS", "350"))

# Standard Municipal Sectors with depot coordinates and dispatch zones
MUNICIPAL_SECTORS = {
    "SEC-CENTRAL": {
        "id": "SEC-CENTRAL",
        "name": "Central Civic & Commercial District",
        "zone": "District 1",
        "depot": "Depot 1 - Civic Center Hub",
        "center": {"lat": 12.9716, "lng": 77.5946},
        "color": "#3B82F6"
    },
    "SEC-NORTH": {
        "id": "SEC-NORTH",
        "name": "North Riverfront & Transit Corridor",
        "zone": "District 2",
        "depot": "Depot 2 - Riverfront Substation",
        "center": {"lat": 12.9980, "lng": 77.5920},
        "color": "#10B981"
    },
    "SEC-EAST": {
        "id": "SEC-EAST",
        "name": "East Industrial & Rail Logistics Zone",
        "zone": "District 3",
        "depot": "Depot 3 - East Industrial Yard",
        "center": {"lat": 12.9780, "lng": 77.6400},
        "color": "#F59E0B"
    },
    "SEC-WEST": {
        "id": "SEC-WEST",
        "name": "West Residential & University Sector",
        "zone": "District 4",
        "depot": "Depot 4 - West Heights Operations",
        "center": {"lat": 12.9550, "lng": 77.5400},
        "color": "#8B5CF6"
    },
    "SEC-SOUTH": {
        "id": "SEC-SOUTH",
        "name": "South Lake Basin & Water Works Sector",
        "zone": "District 5",
        "depot": "Depot 5 - South Water Filtration Base",
        "center": {"lat": 12.9180, "lng": 77.5850},
        "color": "#EC4899"
    }
}

HAZARD_CATEGORIES = [
    {
        "id": "ELECTRICAL",
        "label": "Electrical & Power Grid",
        "icon": "⚡",
        "description": "Downed electrical cables, sparking transformers, exposed street wiring"
    },
    {
        "id": "WATER_DRAINAGE",
        "label": "Water Main & Drainage",
        "icon": "💧",
        "description": "Burst water mains, pressurized pipe burst, street flooding, broken fire hydrant"
    },
    {
        "id": "SEWAGE_MANHOLE",
        "label": "Open Sewer & Sanitation",
        "icon": "⚠️",
        "description": "Missing manhole cover, collapsed storm drain, raw sewage backflow"
    },
    {
        "id": "GAS_PIPELINE",
        "label": "Gas & Utility Pipeline",
        "icon": "🔥",
        "description": "Suspected gas line leak, pipeline rupture, chemical / mercaptan odor"
    },
    {
        "id": "ROADWAY_STRUCTURE",
        "label": "Roadway & Structural Hazard",
        "icon": "🚧",
        "description": "Sinkhole, bridge deck fissure, damaged guardrail, municipal barrier collapse"
    }
]

URGENCY_LEVELS = ["Low", "Medium", "Critical"]

INCIDENT_STATUSES = [
    "REPORTED",          # Newly submitted by citizen
    "ACKNOWLEDGED",      # Registered by dispatch operator
    "DISPATCHED",        # Field crew assigned and en-route
    "ON_SITE_VERIFIED",   # Field crew on location, verified conditions & perimeter
    "IN_PROGRESS",       # Active repair work
    "RESOLVED"           # Fixed, verified safe, ticket closed
]

CREW_UNITS = [
    "CREW-ELEC-09",
    "WATER-SQUAD-04",
    "SANITATION-UNIT-12",
    "GAS-EMERGENCY-03",
    "CIVIL-UNIT-07",
]
