/**
 * Interactive GIS Dispatch Board & Map Visualization
 * Supports Leaflet.js when online with an automatic interactive SVG Radar/Grid engine fallback.
 */

const MapEngine = {
  isLeafletAvailable: false,
  leafletMap: null,
  markers: [],
  selectedCoords: { lat: 12.9716, lng: 77.5946 },
  onPinSelectedCallback: null,

  // Bounding box for Metro area
  bounds: {
    minLat: 12.9000,
    maxLat: 13.0150,
    minLng: 77.5200,
    maxLng: 77.6600
  },

  init(containerId, onPinSelected) {
    this.container = document.getElementById(containerId);
    this.onPinSelectedCallback = onPinSelected;

    if (typeof L !== 'undefined') {
      try {
        this.initLeaflet(containerId);
        this.isLeafletAvailable = true;
        return;
      } catch (e) {
        console.warn("Leaflet init failed, falling back to SVG GIS Grid:", e);
      }
    }

    // Fallback to high-performance SVG GIS Grid
    this.initSvgGrid(containerId);
  },

  initLeaflet(containerId) {
    this.leafletMap = L.map(containerId).setView([12.9716, 77.5946], 12);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '© OpenStreetMap contributors'
    }).addTo(this.leafletMap);

    this.leafletMap.on('click', (e) => {
      this.selectedCoords = { lat: e.latlng.lat, lng: e.latlng.lng };
      if (this.onPinSelectedCallback) {
        this.onPinSelectedCallback(this.selectedCoords);
      }
      this.updateSelectionMarker(e.latlng.lat, e.latlng.lng);
    });
  },

  initSvgGrid(containerId) {
    this.container.innerHTML = `
      <div style="position: relative; width: 100%; height: 100%; background: #090e1a; overflow: hidden; user-select: none;">
        <!-- Municipal Grid Background -->
        <svg id="gis-svg-canvas" width="100%" height="100%" viewBox="0 0 1000 700" preserveAspectRatio="none" style="cursor: crosshair;">
          <defs>
            <pattern id="grid-pattern" width="50" height="50" patternUnits="userSpaceOnUse">
              <path d="M 50 0 L 0 0 0 50" fill="none" stroke="#1e293b" stroke-width="1" />
            </pattern>
            <radialGradient id="center-glow" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stop-color="#3b82f6" stop-opacity="0.15" />
              <stop offset="100%" stop-color="#090e1a" stop-opacity="0" />
            </radialGradient>
          </defs>
          <rect width="1000" height="700" fill="#090e1a" />
          <rect width="1000" height="700" fill="url(#grid-pattern)" />
          <circle cx="500" cy="350" r="300" fill="url(#center-glow)" />

          <!-- Sector Boundaries & Shading -->
          <!-- Central Sector -->
          <polygon points="350,230 650,230 650,470 350,470" fill="rgba(59, 130, 246, 0.08)" stroke="#3b82f6" stroke-width="1.5" stroke-dasharray="4,4" />
          <text x="500" y="260" text-anchor="middle" fill="#60a5fa" font-size="13" font-weight="bold" font-family="sans-serif">SEC-CENTRAL (Downtown Hub)</text>

          <!-- North Sector -->
          <polygon points="250,50 750,50 650,230 350,230" fill="rgba(16, 185, 129, 0.08)" stroke="#10b981" stroke-width="1.5" stroke-dasharray="4,4" />
          <text x="500" y="100" text-anchor="middle" fill="#34d399" font-size="13" font-weight="bold" font-family="sans-serif">SEC-NORTH (Riverfront & Transit)</text>

          <!-- East Sector -->
          <polygon points="650,230 950,230 950,550 650,470" fill="rgba(245, 158, 11, 0.08)" stroke="#f59e0b" stroke-width="1.5" stroke-dasharray="4,4" />
          <text x="800" y="320" text-anchor="middle" fill="#fbbf24" font-size="13" font-weight="bold" font-family="sans-serif">SEC-EAST (Industrial & Rail)</text>

          <!-- West Sector -->
          <polygon points="50,230 350,230 350,470 50,550" fill="rgba(139, 92, 246, 0.08)" stroke="#8b5cf6" stroke-width="1.5" stroke-dasharray="4,4" />
          <text x="200" y="320" text-anchor="middle" fill="#a78bfa" font-size="13" font-weight="bold" font-family="sans-serif">SEC-WEST (Residential & Univ)</text>

          <!-- South Sector -->
          <polygon points="250,650 750,650 650,470 350,470" fill="rgba(236, 72, 153, 0.08)" stroke="#ec4899" stroke-width="1.5" stroke-dasharray="4,4" />
          <text x="500" y="580" text-anchor="middle" fill="#f472b6" font-size="13" font-weight="bold" font-family="sans-serif">SEC-SOUTH (Lake Basin & Water)</text>

          <!-- Interactive Elements Layer -->
          <g id="svg-pins-layer"></g>
          <g id="svg-user-pin"></g>
        </svg>

        <!-- Click Helper Overlay -->
        <div style="position: absolute; top: 12px; left: 16px; background: rgba(15, 23, 42, 0.85); backdrop-filter: blur(6px); padding: 6px 12px; border-radius: 6px; border: 1px solid #334155; font-size: 0.78rem; color: #94a3b8; pointer-events: none;">
          📍 Click anywhere on the municipal grid to geotag location
        </div>
      </div>
    `;

    const svg = document.getElementById('gis-svg-canvas');
    svg.addEventListener('click', (e) => {
      const hit = e.target.closest && e.target.closest('[data-hid]');
      if (hit) { window.App.openTimeline(Number(hit.getAttribute('data-hid'))); return; }
      const rect = svg.getBoundingClientRect();
      const x = ((e.clientX - rect.left) / rect.width) * 1000;
      const y = ((e.clientY - rect.top) / rect.height) * 700;

      // Project SVG (x, y) back to lat/lng
      const lat = this.bounds.maxLat - (y / 700) * (this.bounds.maxLat - this.bounds.minLat);
      const lng = this.bounds.minLng + (x / 1000) * (this.bounds.maxLng - this.bounds.minLng);

      this.selectedCoords = { lat: parseFloat(lat.toFixed(5)), lng: parseFloat(lng.toFixed(5)) };
      this.drawSvgUserPin(x, y);

      if (this.onPinSelectedCallback) {
        this.onPinSelectedCallback(this.selectedCoords);
      }
    });
  },

  projectToSvg(lat, lng) {
    const x = ((lng - this.bounds.minLng) / (this.bounds.maxLng - this.bounds.minLng)) * 1000;
    const y = ((this.bounds.maxLat - lat) / (this.bounds.maxLat - this.bounds.minLat)) * 700;
    return { x: Math.max(20, Math.min(980, x)), y: Math.max(20, Math.min(680, y)) };
  },

  drawSvgUserPin(x, y) {
    const pinLayer = document.getElementById('svg-user-pin');
    if (!pinLayer) return;
    pinLayer.innerHTML = `
      <g transform="translate(${x}, ${y})">
        <circle r="18" fill="none" stroke="#3b82f6" stroke-width="2" opacity="0.6">
          <animate attributeName="r" values="10;26" dur="1.5s" repeatCount="indefinite" />
          <animate attributeName="opacity" values="0.8;0" dur="1.5s" repeatCount="indefinite" />
        </circle>
        <circle r="7" fill="#3b82f6" stroke="#fff" stroke-width="2" />
        <text y="-14" text-anchor="middle" fill="#fff" font-size="11" font-weight="bold" font-family="sans-serif">Selected Location</text>
      </g>
    `;
  },

  updateSelectionMarker(lat, lng) {
    if (this.isLeafletAvailable && this.leafletMap) {
      if (this.userMarker) {
        this.userMarker.setLatLng([lat, lng]);
      } else {
        this.userMarker = L.marker([lat, lng], {
          icon: L.divIcon({
            className: 'custom-user-marker',
            html: '<div style="background:#3b82f6; width:16px; height:16px; border-radius:50%; border:2px solid #fff; box-shadow:0 0 10px #3b82f6;"></div>',
            iconSize: [16, 16],
            iconAnchor: [8, 8]
          })
        }).addTo(this.leafletMap);
      }
    } else {
      const p = this.projectToSvg(lat, lng);
      this.drawSvgUserPin(p.x, p.y);
    }
  },

  focus(lat, lng) {
    if (this.leafletMap) this.leafletMap.setView([lat, lng], 16);
  },

  clearSelection() {
    if (this.userMarker && this.leafletMap) { this.leafletMap.removeLayer(this.userMarker); this.userMarker = null; }
    const pin = document.getElementById('svg-user-pin');
    if (pin) pin.innerHTML = '';
  },

  renderHazards(hazards, onSelectHazard) {
    if (this.isLeafletAvailable && this.leafletMap) {
      this.renderLeafletHazards(hazards, onSelectHazard);
    } else {
      this.renderSvgHazards(hazards, onSelectHazard);
    }
  },

  renderLeafletHazards(hazards, onSelectHazard) {
    // Clear old markers
    this.markers.forEach(m => this.leafletMap.removeLayer(m));
    this.markers = [];

    hazards.forEach(h => {
      const color = h.status === 'RESOLVED' ? '#10b981' :
                    h.urgency === 'Critical' ? '#ef4444' :
                    h.urgency === 'Medium' ? '#f59e0b' : '#3b82f6';

      const icon = L.divIcon({
        className: 'hazard-pin',
        html: `
          <div style="background:${color}; width:24px; height:24px; border-radius:50%; border:2px solid #fff; display:flex; align-items:center; justify-content:center; color:#fff; font-size:12px; box-shadow:0 0 12px ${color}; cursor:pointer;">
            ${h.urgency === 'Critical' ? '!' : '•'}
          </div>
        `,
        iconSize: [24, 24],
        iconAnchor: [12, 12]
      });

      const marker = L.marker([h.latitude, h.longitude], { icon }).addTo(this.leafletMap);
      const box = document.createElement('div');
      box.style.cssText = 'font-family:sans-serif; min-width:180px;';
      const title = document.createElement('b');
      title.textContent = '#' + h.ticket_code + ' - ' + h.urgency;
      const place = document.createElement('div');
      place.textContent = h.landmark;
      const state = document.createElement('small');
      state.textContent = 'Status: ' + h.status.replace(/_/g, ' ');
      const btn = document.createElement('button');
      btn.textContent = 'View audit log';
      btn.style.cssText = 'display:block; margin-top:6px; background:#3b82f6; color:#fff; border:none; padding:4px 8px; border-radius:4px; cursor:pointer; font-size:11px;';
      btn.addEventListener('click', () => window.App.openTimeline(h.id));
      box.append(title, place, state, btn);
      marker.bindPopup(box);
      this.markers.push(marker);
    });
  },

  renderSvgHazards(hazards, onSelectHazard) {
    const pinLayer = document.getElementById('svg-pins-layer');
    if (!pinLayer) return;

    let html = '';
    hazards.forEach(h => {
      const pos = this.projectToSvg(h.latitude, h.longitude);
      const color = h.status === 'RESOLVED' ? '#10b981' :
                    h.urgency === 'Critical' ? '#ef4444' :
                    h.urgency === 'Medium' ? '#f59e0b' : '#3b82f6';

      const isCritical = h.urgency === 'Critical' && h.status !== 'RESOLVED';

      html += `
        <g transform="translate(${pos.x}, ${pos.y})" style="cursor: pointer;" data-hid="${h.id}">
          ${isCritical ? `
            <circle r="16" fill="${color}" opacity="0.3">
              <animate attributeName="r" values="10;22" dur="1.2s" repeatCount="indefinite" />
              <animate attributeName="opacity" values="0.6;0" dur="1.2s" repeatCount="indefinite" />
            </circle>
          ` : ''}
          <circle r="9" fill="${color}" stroke="#ffffff" stroke-width="2" />
          <text y="3" text-anchor="middle" fill="#ffffff" font-size="9" font-weight="bold" font-family="sans-serif">
            ${h.urgency === 'Critical' ? '!' : '●'}
          </text>
          <text y="-14" text-anchor="middle" fill="#cbd5e1" font-size="10" font-weight="600" font-family="sans-serif">
            #${h.ticket_code.slice(-4)}
          </text>
        </g>
      `;
    });

    pinLayer.innerHTML = html;
  }
};
