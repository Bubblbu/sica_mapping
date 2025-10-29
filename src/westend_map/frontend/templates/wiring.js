
<script>
(function() {
  const DATA_URLS = {
    filterConfig: '$filter_config_url',
    markerMetadata: '$marker_metadata_url',
    buildingData: '$building_records_url',
  };

  function fetchJson(url) {
    return fetch(url, { cache: 'no-cache' }).then(function(resp) {
      if (!resp.ok) {
        throw new Error('Failed to load ' + url + ': ' + resp.status);
      }
      return resp.json();
    });
  }

  let filterConfig = {};
  let markerMetadata = [];
  let buildingData = {};
  let buildingRecords = {};
  let buildingColumnOrder = [];

  function assignLoadedData(filters, metadata, buildings) {
    filterConfig = filters || {};
    markerMetadata = Array.isArray(metadata) ? metadata : [];
    buildingData = buildings || {};
    buildingRecords = (buildingData && buildingData.records) || {};
    buildingColumnOrder = (buildingData && Array.isArray(buildingData.columns)) ? buildingData.columns.slice() : [];
  }
  function wireUp() {
    try {
      const layerBlocks = window["$blocks_layer_var"] || null;
      const layerVTU = window["$layer_vtu_var"] || null;
      const layerNon = window["$layer_non_var"] || null;
      const mapInstance = (layerBlocks && layerBlocks._map) || (layerVTU && layerVTU._map) || (layerNon && layerNon._map) || null;

      if (!layerBlocks || typeof layerBlocks.eachLayer !== 'function') {
        throw new Error('Blocks layer not ready');
      }

      window.blocksIndex = {};
      window.blockBuildingIndex = {};
      window.buildingIndex = {};
      window.ownerIndex = {};
      window.membershipData = {};
      const BASE_ZOOM = 15;
      let currentZoomScale = 1;
      let colorScalingEnabled = true;
      let blockColorScalingEnabled = true;
      let blockColorMax = 0;

      function computeZoomScale(zoom) {
        if (!Number.isFinite(zoom)) return currentZoomScale;
        const scale = Math.pow(1.2, zoom - BASE_ZOOM);
        return Math.min(2.4, Math.max(0.35, scale));
      }

      function getScaledRadius(marker) {
        const base = marker && marker._baseRadius ? marker._baseRadius : 6;
        return base * currentZoomScale;
      }

      function resetBlockStyle(layer) {
        if (!layer) return;
        const rawUnits = Number(layer._blockUnits);
        const units = Number.isFinite(rawUnits) ? rawUnits : 0;
        let base;
        if (!blockColorScalingEnabled || blockColorMax <= 0) {
          base = { weight:1, color:'#b8b8b8', fillOpacity:0.20, fillColor:'#f0f0f0' };
        } else {
          const ratio = Math.max(0, Math.min(1, units / blockColorMax));
          const fill = (ratio <= 0.10) ? '#f7fcf5' :
                       (ratio <= 0.25) ? '#e5f5e0' :
                       (ratio <= 0.50) ? '#c7e9c0' :
                       (ratio <= 0.75) ? '#74c476' :
                       (ratio <  1.00) ? '#31a354' : '#006d2c';
          base = { weight:1, color:'#b8b8b8', fillOpacity:0.35, fillColor:fill };
        }
        layer._baseStyle = base;
        layer.setStyle(base);
      }

      function setBlockFiltered(blockId, filtered) {
        var layer = window.blocksIndex[blockId];
        if (!layer) return;
        layer._isFiltered = filtered;
        if (filtered) {
          layer._selectionRefs = 0;
          layer.setStyle({ weight:1, color:'#d0d0d0', fillOpacity:0.08, fillColor:'#f5f5f5' });
        } else {
          resetBlockStyle(layer);
        }
      }

      function highlightBlock(layer, on) {
        if (!layer || layer._isFiltered) return;
        if (on) {
          var base = layer._baseStyle || {};
          layer.setStyle({
            weight:4,
            color:'#ff1744',
            fillOpacity: Math.min(0.9, (base.fillOpacity || 0.35) + 0.1),
            fillColor: base.fillColor || (layer.options && layer.options.fillColor) || '#c7e9c0'
          });
          if (layer.bringToFront) layer.bringToFront();
        } else {
          resetBlockStyle(layer);
        }
      }

      function ensureMarkerBase(marker) {
        if (!marker) return;
        const opts = marker.options || {};
        if (marker._baseColor === undefined || marker._baseColor === null) {
          marker._baseColor = opts.base_color !== undefined ? opts.base_color : (opts.fillColor || '#9e9e9e');
        }
        if (marker._baseOpacity === undefined || marker._baseOpacity === null) {
          if (opts.base_opacity !== undefined && opts.base_opacity !== null) {
            marker._baseOpacity = opts.base_opacity;
          } else if (typeof opts.fillOpacity === 'number') {
            marker._baseOpacity = opts.fillOpacity;
          } else {
            marker._baseOpacity = 0.35;
          }
        }
        if (marker._baseRadius === undefined || marker._baseRadius === null) {
          const optRadius = (opts.base_radius !== undefined && opts.base_radius !== null)
            ? opts.base_radius
            : (opts.radius !== undefined ? opts.radius : 6);
          marker._baseRadius = typeof optRadius === 'number' ? optRadius : 6;
        }
        if (marker._selectionRefs === undefined) {
          marker._selectionRefs = 0;
        }
        if (marker._isFiltered === undefined) {
          marker._isFiltered = false;
        }
      }

      function highlightMarker(marker, on) {
        if (!marker) return;
        ensureMarkerBase(marker);
        if (marker._isFiltered) return;
        var baseOpacity = marker._baseOpacity || 0.35;
        var baseRadius = getScaledRadius(marker);
        var baseColor = marker._baseColor || (marker.options && marker.options.fillColor) || '#9e9e9e';
        if (typeof marker.setStyle === 'function') {
          marker.setStyle(on ? {
            weight:2,
            color:'#ff1744',
            fillOpacity: Math.min(0.95, baseOpacity + 0.20),
            fillColor: baseColor
          } : {
            weight:0,
            color:null,
            fillOpacity: baseOpacity,
            fillColor: baseColor
          });
        }
        if (typeof marker.setRadius === 'function') {
          const extra = Math.max(1.5, 1.5 * currentZoomScale);
          marker.setRadius(on ? baseRadius + extra : baseRadius);
        } else if (!on && typeof marker.setStyle === 'function') {
          marker.setStyle({ radius: baseRadius });
        }
        if (on && marker.bringToFront) marker.bringToFront();
      }

      function adjustMarkerSelection(marker, delta) {
        if (!marker) return;
        marker._selectionRefs = (marker._selectionRefs || 0) + delta;
        if (marker._selectionRefs < 0) marker._selectionRefs = 0;
        if (!marker._isFiltered) {
          highlightMarker(marker, marker._selectionRefs > 0);
        }
      }

      function adjustBlockSelection(layer, delta) {
        if (!layer) return;
        layer._selectionRefs = (layer._selectionRefs || 0) + delta;
        if (layer._selectionRefs < 0) layer._selectionRefs = 0;
        if (!layer._isFiltered) {
          highlightBlock(layer, layer._selectionRefs > 0);
        }
      }

      function setMarkerVisibility(marker, visible) {
        if (!marker) return;
        ensureMarkerBase(marker);
        marker._isFiltered = !visible;
        if (!visible) {
          marker._selectionRefs = 0;
          if (typeof marker.setStyle === 'function') {
            marker.setStyle({ weight:0, color:null, fillOpacity:0, fillColor: marker._baseColor });
          }
          if (typeof marker.setRadius === 'function') {
            marker.setRadius(0);
          }
        } else {
          var baseOpacity = marker._baseOpacity || 0.35;
          var baseRadius = getScaledRadius(marker);
          if (typeof marker.setStyle === 'function') {
            marker.setStyle({
              weight:0,
              color:null,
              fillOpacity: baseOpacity,
              fillColor: marker._baseColor
            });
          }
          if (typeof marker.setRadius === 'function') {
            marker.setRadius(baseRadius);
          }
          if ((marker._selectionRefs || 0) > 0) {
            highlightMarker(marker, true);
          }
        }
      }

      function setOwnerSelection(ownerKey, selected) {
        var arr = window.ownerIndex[ownerKey] || [];
        arr.forEach(function(marker) {
          adjustMarkerSelection(marker, selected ? +1 : -1);
        });
      }

      function setBlockSelectionMarkers(blockId, selected) {
        var ids = window.blockBuildingIndex[String(blockId)] || [];
        ids.forEach(function(bid) {
          var marker = window.buildingIndex[String(bid)];
          if (!marker) return;
          adjustMarkerSelection(marker, selected ? +1 : -1);
        });
      }

      function collectSelectedBuildingIds() {
        const ids = [];
        Object.keys(window.buildingIndex).forEach(function(key) {
          const marker = window.buildingIndex[key];
          if (marker && !marker._isFiltered && (marker._selectionRefs || 0) > 0) {
            ids.push(String(key));
          }
        });
        return ids;
      }

      function escapeCSV(value) {
        if (value === null || value === undefined) return '';
        let normalized = value;
        if (typeof normalized === 'object') {
          try {
            normalized = JSON.stringify(normalized);
          } catch (err) {
            normalized = String(normalized);
          }
        }
        let text = String(normalized);
        if (/[",\n\r]/.test(text)) {
          text = '"' + text.replace(/"/g, '""') + '"';
        }
        return text;
      }

      function applyMarkerMetadata() {
        if (!Array.isArray(markerMetadata)) return;
        markerMetadata.forEach(function(meta) {
          if (!meta) return;
          var markerVar = meta.marker_var;
          if (!markerVar) return;
          var marker = window[String(markerVar)];
          if (!marker) return;

          var key = String(meta.b_id);
          window.buildingIndex[key] = marker;

          const coloredColor = (typeof meta.base_color === 'string' && meta.base_color) || marker._baseColor || (marker.options && marker.options.fillColor) || '#9e9e9e';
          const neutralColor = (typeof meta.neutral_color === 'string' && meta.neutral_color) || '#9e9e9e';
          marker._colorizedColor = coloredColor;
          marker._neutralColor = neutralColor;
          marker._baseColor = coloredColor;
          marker._baseOpacity = (typeof meta.base_opacity === 'number') ? meta.base_opacity : (marker._baseOpacity || (marker.options && marker.options.fillOpacity) || 0.35);
          marker._baseRadius = (typeof meta.base_radius === 'number') ? meta.base_radius : (marker._baseRadius || (marker.options && marker.options.radius) || 6);
          marker._selectionRefs = 0;
          marker._isFiltered = false;
          marker._isVtu = !!meta.is_vtu;
          marker._passesMembership = true;
          const memberCount = Number(meta.member_count);
          marker._memberCount = Number.isFinite(memberCount) ? memberCount : 0;
          if (!marker.options) marker.options = {};
          marker.options.base_color = marker._baseColor;
          const unitsMeta = Number(meta.units);
          marker._units = Number.isFinite(unitsMeta) ? unitsMeta : 0;
          ensureMarkerBase(marker);
          updateMarkerColorAppearance(marker);

          var payload = Array.isArray(meta.members_payload) ? meta.members_payload : [];
          window.membershipData[key] = payload;

          var ownerKey = meta.owner_key;
          if (ownerKey) {
            if (!window.ownerIndex[ownerKey]) window.ownerIndex[ownerKey] = [];
            if (window.ownerIndex[ownerKey].indexOf(marker) === -1) {
              window.ownerIndex[ownerKey].push(marker);
            }
          }

          if (meta.block_id !== undefined && meta.block_id !== null) {
            var blockKey = String(meta.block_id);
            if (!window.blockBuildingIndex[blockKey]) window.blockBuildingIndex[blockKey] = [];
            if (window.blockBuildingIndex[blockKey].indexOf(key) === -1) {
              window.blockBuildingIndex[blockKey].push(key);
            }
          }
        });
      }

      function matchesFilters(records, opts) {
        const hasRecords = Array.isArray(records) && records.length > 0;
        if (!opts.requireMember && opts.minYear === null) {
          return true;
        }
        if (!hasRecords) {
          return false;
        }
        let filtered = records.slice();
        if (opts.requireMember) {
          filtered = filtered.filter(function(r) { return r.has_member_tag; });
        }
        if (opts.minYear !== null) {
          const yearThreshold = Number(opts.minYear);
          filtered = filtered.filter(function(r) {
            const yr = r.latest_membership_year;
            if (yr === undefined || yr === null) return false;
            const parsed = Number(yr);
            return Number.isFinite(parsed) && parsed >= yearThreshold;
          });
        }
        return filtered.length > 0;
      }

      function toggleLayerVisibility(layer, show) {
        if (!mapInstance || !layer) return;
        const hasLayer = mapInstance.hasLayer(layer);
        if (show && !hasLayer) {
          layer.addTo(mapInstance);
        } else if (!show && hasLayer) {
          mapInstance.removeLayer(layer);
        }
      }

      function buildingHover(bid, on) {
        var marker = window.buildingIndex[bid];
        if (!marker || marker._isFiltered) return;
        if (on) {
          highlightMarker(marker, true);
        } else if ((marker._selectionRefs || 0) === 0) {
          highlightMarker(marker, false);
        }
      }

      function blockHover(blockId, on) {
        var layer = window.blocksIndex[blockId];
        if (!layer || layer._isFiltered) return;
        if (on) {
          highlightBlock(layer, true);
        } else if ((layer._selectionRefs || 0) === 0) {
          highlightBlock(layer, false);
        }
      }

      function ownerHover(ownerKey, on) {
        var arr = window.ownerIndex[ownerKey] || [];
        arr.forEach(function(marker) {
          if (!marker || marker._isFiltered) return;
          if (on) {
            highlightMarker(marker, true);
          } else if ((marker._selectionRefs || 0) === 0) {
            highlightMarker(marker, false);
          }
        });
      }

      function handleSelectionChange(evt) {
        var cb = evt.target;
        if (!cb.classList.contains('row-select')) return;
        var row = cb.closest('tr');
        if (row) row.classList.toggle('selected', cb.checked);
        var typ = cb.dataset.type;
        var key = cb.dataset.target;
        if (typ === 'building') {
          adjustMarkerSelection(window.buildingIndex[key], cb.checked ? +1 : -1);
        } else if (typ === 'block') {
          adjustBlockSelection(window.blocksIndex[key], cb.checked ? +1 : -1);
          setBlockSelectionMarkers(key, cb.checked);
        } else if (typ === 'owner') {
          setOwnerSelection(key, cb.checked);
        }
        updateSummaryBar();
      }

      function getSortValue(row, index, type) {
        var cell = row.children[index];
        if (!cell) return type === 'number' ? NaN : '';
        var raw = cell.getAttribute('data-sort-value');
        if (raw === null) raw = cell.textContent || '';
        if (type === 'number') {
          var num = parseFloat(String(raw).replace(/[^0-9\\.-]/g, ''));
          return isNaN(num) ? NaN : num;
        }
        return String(raw).toLowerCase();
      }

      function sortByHeader(event) {
        var th = event.currentTarget;
        var sortType = th.dataset.sort || 'text';
        if (sortType === 'none') return;
        var table = th.closest('table');
        if (!table) return;
        var tbody = table.querySelector('tbody');
        if (!tbody) return;
        var headers = Array.from(th.parentNode.children);
        var columnIndex = headers.indexOf(th);
        var prev = th.dataset.sortDir || 'desc';
        var direction = prev === 'asc' ? 'desc' : 'asc';
        th.dataset.sortDir = direction;
        headers.forEach(function(header) {
          if (header !== th) header.removeAttribute('data-sort-dir');
        });
        var rows = Array.from(tbody.querySelectorAll('tr'));
        var rowsWithIndex = rows.map(function(row, idx) { return { row: row, idx: idx }; });
        rowsWithIndex.sort(function(a, b) {
          var va = getSortValue(a.row, columnIndex, sortType);
          var vb = getSortValue(b.row, columnIndex, sortType);
          var cmp;
          if (sortType === 'number') {
            var aNaN = isNaN(va);
            var bNaN = isNaN(vb);
            if (aNaN && bNaN) cmp = 0;
            else if (aNaN) cmp = 1;
            else if (bNaN) cmp = -1;
            else cmp = va - vb;
          } else {
            cmp = String(va).localeCompare(String(vb));
          }
          if (cmp === 0) cmp = a.idx - b.idx;
          return direction === 'asc' ? cmp : -cmp;
        });
        rowsWithIndex.forEach(function(item) {
          tbody.appendChild(item.row);
        });
      }

      const geo = layerBlocks;
      const blockLayers = [];
      geo.eachLayer(function(layer) {
        if (layer && layer.feature && layer.feature.properties) {
          var props = layer.feature.properties || {};
          var rawId = props.block_id;
          if (rawId === undefined || rawId === null) return;
          var id = String(rawId);
          window.blocksIndex[id] = layer;
          layer._selectionRefs = 0;
          layer._isFiltered = false;
          var unitTotal = Number(props.total_units);
          if (!Number.isFinite(unitTotal)) unitTotal = 0;
          layer._blockUnits = unitTotal;
          blockLayers.push(layer);
        }
      });
      blockColorMax = blockLayers.reduce(function(max, layer) {
        var units = Number(layer._blockUnits);
        return Number.isFinite(units) ? Math.max(max, units) : max;
      }, 0);
      if (!Number.isFinite(blockColorMax) || blockColorMax < 0) blockColorMax = 0;
      window.blockColorMax = blockColorMax;
      blockLayers.forEach(function(layer) { resetBlockStyle(layer); });

      applyMarkerMetadata();
      const markerCount = Object.keys(window.buildingIndex).length;
      if (!markerCount) {
        throw new Error('Building markers not ready');
      }
      applyZoomScaling();
      if (mapInstance && typeof mapInstance.on === 'function') {
        mapInstance.on('moveend', function() {
          updateMapStatus();
          applyZoomScaling();
        });
        mapInstance.on('zoomend', function() {
          updateMapStatus();
          applyZoomScaling();
        });
        mapInstance.on('layeradd', function() {
          updateMapStatus();
          applyZoomScaling();
        });
        mapInstance.on('layerremove', function() {
          updateMapStatus();
          applyZoomScaling();
        });
      }
      if (mapInstance && typeof mapInstance.invalidateSize === 'function') {
        setTimeout(function() {
          mapInstance.invalidateSize({ animate: false });
          applyZoomScaling();
          updateMapStatus();
        }, 50);
      }

      const tabB = document.getElementById('tab-buildings');
      const tabK = document.getElementById('tab-blocks');
      const tabL = document.getElementById('tab-landlords');
      const paneB = document.getElementById('pane-buildings');
      const paneK = document.getElementById('pane-blocks');
      const paneL = document.getElementById('pane-landlords');
      function activate(which) {
        [tabB, tabK, tabL].forEach(btn => btn && btn.classList.remove('active'));
        [paneB, paneK, paneL].forEach(pane => pane && pane.classList.remove('active'));
        if (which === 'buildings') { if (tabB) tabB.classList.add('active'); if (paneB) paneB.classList.add('active'); }
        else if (which === 'blocks') { if (tabK) tabK.classList.add('active'); if (paneK) paneK.classList.add('active'); }
        else { if (tabL) tabL.classList.add('active'); if (paneL) paneL.classList.add('active'); }
      }
      if (tabB) tabB.addEventListener('click', () => activate('buildings'));
      if (tabK) tabK.addEventListener('click', () => activate('blocks'));
      if (tabL) tabL.addEventListener('click', () => activate('landlords'));

      document.querySelectorAll('table.data thead th').forEach(function(th) {
        if ((th.dataset.sort || 'none') !== 'none') {
          th.addEventListener('click', sortByHeader);
        }
      });

      document.querySelectorAll('.row-select').forEach(function(cb) {
        cb.addEventListener('change', handleSelectionChange);
      });

      document.querySelectorAll('#blocks-table tbody tr').forEach(function(row) {
        var id = row.getAttribute('data-block');
        row.addEventListener('mouseenter', function() { blockHover(id, true); });
        row.addEventListener('mouseleave', function() { blockHover(id, false); });
      });

      document.querySelectorAll('#buildings-table tbody tr').forEach(function(row) {
        var bid = row.getAttribute('data-bid');
        row.addEventListener('mouseenter', function() { buildingHover(bid, true); });
        row.addEventListener('mouseleave', function() { buildingHover(bid, false); });
      });

      document.querySelectorAll('#landlords-table tbody tr').forEach(function(row) {
        var key = row.getAttribute('data-owner');
        row.addEventListener('mouseenter', function() { ownerHover(key, true); });
        row.addEventListener('mouseleave', function() { ownerHover(key, false); });
      });

      const requireMemberChk = document.getElementById('filter-require-member');
      const yearToggle = document.getElementById('filter-year-enabled');
      const yearSlider = document.getElementById('filter-updated-year');
      const yearLabel = document.getElementById('filter-updated-year-label');
      const hoodInputs = Array.from(document.querySelectorAll('.filter-neighbourhood-option'));
      const hoodSelectAllBtn = document.getElementById('hood-select-all');
      const hoodClearBtn = document.getElementById('hood-clear');
      const resetBtn = document.getElementById('filter-reset');
      const colorScaleChk = document.getElementById('viz-color-vtu');
      const colorBlocksChk = document.getElementById('viz-color-blocks');
      const hideNonChk = document.getElementById('viz-hide-non');
      const vizBlocksChk = document.getElementById('viz-show-blocks');
      const tableSearchInput = null;
      const statusCells = {
        total: {
          units: document.getElementById('status-total-units'),
          buildings: document.getElementById('status-total-buildings'),
          vtu: document.getElementById('status-total-vtu'),
          members: document.getElementById('status-total-members'),
        },
        view: {
          units: document.getElementById('status-view-units'),
          buildings: document.getElementById('status-view-buildings'),
          vtu: document.getElementById('status-view-vtu'),
          members: document.getElementById('status-view-members'),
        },
      };
      const summaryLabelEl = document.getElementById('summary-buildings-label');
      const summaryUnitsEl = document.getElementById('summary-buildings-units');
      const summaryMembersEl = document.getElementById('summary-buildings-members');
      const summaryRowsEl = document.getElementById('summary-buildings-rows');
      const legendContainerEl = document.getElementById('legend-map');
      const legendBlocksEl = document.getElementById('legend-blocks-section');
      const legendBuildingsEl = document.getElementById('legend-buildings-section');

      const metricControls = {};
      let metricKeys = [];

      const yearRangeMin = (filterConfig && typeof filterConfig.updated_year_min === 'number') ? filterConfig.updated_year_min : null;
      const yearRangeMax = (filterConfig && typeof filterConfig.updated_year_max === 'number') ? filterConfig.updated_year_max : null;
      const datasetTotals = (filterConfig && filterConfig.dataset_totals) || null;
      const totalBuildings = datasetTotals && typeof datasetTotals.buildings === 'number' ? datasetTotals.buildings : null;
      const totalMembers = datasetTotals && typeof datasetTotals.members === 'number' ? datasetTotals.members : null;
      const totalUnits = datasetTotals && typeof datasetTotals.units === 'number' ? datasetTotals.units : null;
      const totalVtuBuildings = datasetTotals && typeof datasetTotals.vtu_buildings === 'number' ? datasetTotals.vtu_buildings : null;

      function updateYearLabel() {
        if (!yearLabel) return;
        if (!yearSlider || !yearToggle || !yearToggle.checked) {
          yearLabel.textContent = 'Year: Any';
        } else {
          yearLabel.textContent = 'Year: ' + yearSlider.value;
        }
      }

      function setStatusCell(cell, value) {
        if (!cell) return;
        if (value === null || value === undefined || Number.isNaN(value)) {
          cell.textContent = '–';
          cell.setAttribute('data-value', 'none');
        } else {
          cell.textContent = Number(value).toLocaleString();
          cell.setAttribute('data-value', 'value');
        }
      }

      function updateDatasetStatus() {
        if (!statusCells) return;
        setStatusCell(statusCells.total.units, totalUnits);
        setStatusCell(statusCells.total.buildings, totalBuildings);
        setStatusCell(statusCells.total.vtu, totalVtuBuildings);
        setStatusCell(statusCells.total.members, totalMembers);
        setStatusCell(statusCells.view.units, null);
        setStatusCell(statusCells.view.buildings, null);
        setStatusCell(statusCells.view.vtu, null);
        setStatusCell(statusCells.view.members, null);
      }

      function computeMapSummary() {
        if (!mapInstance || typeof mapInstance.getBounds !== 'function') {
          return { buildings: null, members: null, units: null, vtu: null };
        }
        const bounds = mapInstance.getBounds();
        let buildingCount = 0;
        let memberTotal = 0;
        let unitTotal = 0;
        let vtuCount = 0;
        Object.keys(window.buildingIndex).forEach(function(key) {
          const marker = window.buildingIndex[key];
          if (!marker || marker._isFiltered) return;
          if (typeof mapInstance.hasLayer === 'function' && !mapInstance.hasLayer(marker)) return;
          if (typeof marker.getLatLng !== 'function') return;
          const latLng = marker.getLatLng();
          if (!latLng || typeof bounds.contains !== 'function' || !bounds.contains(latLng)) return;
          buildingCount += 1;
          const members = Number(marker._memberCount);
          if (Number.isFinite(members)) memberTotal += members;
          const unitsVal = Number(marker._units);
          if (Number.isFinite(unitsVal)) unitTotal += unitsVal;
          if (marker._isVtu) vtuCount += 1;
        });
        return {
          buildings: buildingCount,
          members: memberTotal,
          units: unitTotal,
          vtu: vtuCount,
        };
      }

      function updateMapStatus() {
        if (!statusCells) return;
        const summary = computeMapSummary();
        setStatusCell(statusCells.view.units, summary.units);
        setStatusCell(statusCells.view.buildings, summary.buildings);
        setStatusCell(statusCells.view.vtu, summary.vtu);
        setStatusCell(statusCells.view.members, summary.members);
      }

      function syncYearSliderState() {
        if (!yearSlider) return;
        const enabled = !!(yearToggle && yearToggle.checked);
        yearSlider.disabled = !enabled;
        if (enabled && yearRangeMin !== null && yearRangeMax !== null) {
          if (!yearSlider.value || Number.isNaN(Number(yearSlider.value))) {
            yearSlider.value = String(yearRangeMin);
          }
        }
        updateYearLabel();
      }

      function initializeYearControl() {
        if (!yearSlider) {
          return;
        }
        if (yearRangeMin === null || yearRangeMax === null || yearRangeMin > yearRangeMax) {
          yearSlider.disabled = true;
          if (yearToggle) {
            yearToggle.checked = false;
            yearToggle.disabled = true;
          }
          updateYearLabel();
          return;
        }
        yearSlider.min = String(yearRangeMin);
        yearSlider.max = String(yearRangeMax);
        yearSlider.step = 1;
        if (!yearSlider.value) {
          yearSlider.value = String(yearRangeMin);
        }
        if (yearToggle) {
          yearToggle.checked = false;
        }
        yearSlider.disabled = true;
        updateYearLabel();
      }

      function updateSummaryBar() {
        if (!summaryLabelEl || !summaryUnitsEl || !summaryMembersEl || !summaryRowsEl) return;
        const allRows = Array.from(document.querySelectorAll('#buildings-table tbody tr'));
        const selectedRows = allRows.filter(function(row) {
          const cb = row.querySelector('.row-select');
          return cb && cb.checked;
        });
        const targetRows = selectedRows.length ? selectedRows : allRows.filter(function(row) {
          return !row.classList.contains('hidden');
        });
        const label = selectedRows.length ? 'Totals (selected)' : 'Totals (visible)';
        let unitsSum = 0;
        let membersSum = 0;
        targetRows.forEach(function(row) {
          const units = Number(row.getAttribute('data-units'));
          const members = Number(row.getAttribute('data-member-total'));
          if (Number.isFinite(units)) unitsSum += units;
          if (Number.isFinite(members)) membersSum += members;
        });
        summaryLabelEl.textContent = label;
        summaryUnitsEl.textContent = unitsSum.toLocaleString();
        summaryMembersEl.textContent = membersSum.toLocaleString();
        summaryRowsEl.textContent = (targetRows.length || 0).toLocaleString() + (targetRows.length === 1 ? ' row' : ' rows');
      }

      function setLegendDisplay(el, show) {
        if (!el) return;
        el.style.display = show ? 'block' : 'none';
      }

      function updateLegendVisibility() {
        const blocksVisible = vizBlocksChk ? vizBlocksChk.checked !== false : true;
        const showBuildingLegend = colorScaleChk ? colorScaleChk.checked !== false : true;
        const showBlocksLegend = blocksVisible && blockColorScalingEnabled;
        if (legendContainerEl) {
          const sidebarEl = document.getElementById('sidebar-container');
          if (sidebarEl && sidebarEl.offsetWidth) {
            const leftPos = sidebarEl.offsetWidth + 30;
            legendContainerEl.style.left = leftPos + 'px';
          }
        }
        setLegendDisplay(legendBlocksEl, showBlocksLegend);
        setLegendDisplay(legendBuildingsEl, showBuildingLegend);
        if (legendContainerEl) {
          const shouldShow = (showBlocksLegend && legendBlocksEl) || (showBuildingLegend && legendBuildingsEl);
          legendContainerEl.style.display = shouldShow ? 'flex' : 'none';
        }
      }

      function updateMarkerColorAppearance(marker) {
        if (!marker) return;
        ensureMarkerBase(marker);
        if (marker._passesMembership === undefined) {
          marker._passesMembership = true;
        }
        const shouldColorize = colorScalingEnabled && marker._isVtu && marker._passesMembership;
        const coloredColor = marker._colorizedColor || marker._baseColor || '#9e9e9e';
        const neutralColor = marker._neutralColor || '#9e9e9e';
        const targetColor = shouldColorize ? coloredColor : neutralColor;
        marker._baseColor = targetColor;
        if (!marker.options) marker.options = {};
        marker.options.base_color = targetColor;
        if (marker._isFiltered) {
          return;
        }
        if ((marker._selectionRefs || 0) > 0) {
          highlightMarker(marker, true);
        } else {
          highlightMarker(marker, false);
        }
      }

      function applyVtuColorScaling(enabled) {
        colorScalingEnabled = enabled !== false;
        Object.keys(window.buildingIndex).forEach(function(key) {
          updateMarkerColorAppearance(window.buildingIndex[key]);
        });
        updateLegendVisibility();
      }

      function applyBlockColorScaling(enabled) {
        blockColorScalingEnabled = enabled !== false;
        Object.keys(window.blocksIndex).forEach(function(key) {
          const layer = window.blocksIndex[key];
          if (!layer) return;
          if (!layer._isFiltered) {
            resetBlockStyle(layer);
          }
        });
        updateLegendVisibility();
      }

      function applyZoomScaling() {
        if (!mapInstance || typeof mapInstance.getZoom !== 'function') return;
        currentZoomScale = computeZoomScale(mapInstance.getZoom());
        Object.keys(window.buildingIndex).forEach(function(key) {
          const marker = window.buildingIndex[key];
          if (!marker || marker._isFiltered) return;
          const baseOpacity = marker._baseOpacity || 0.35;
          const scaledRadius = getScaledRadius(marker);
          if (typeof marker.setRadius === 'function') {
            marker.setRadius(scaledRadius);
          }
          if (typeof marker.setStyle === 'function') {
            marker.setStyle({
              weight:0,
              color:null,
              fillOpacity: baseOpacity,
              fillColor: marker._baseColor || (marker.options && marker.options.fillColor) || '#9e9e9e'
            });
          }
          if ((marker._selectionRefs || 0) > 0) {
            highlightMarker(marker, true);
          }
        });
      }

      function initPaneResize() {
        const handles = document.querySelectorAll('.pane-resize-handle[data-target]');
        handles.forEach(function(handle) {
          const targetSelector = handle.getAttribute('data-target');
          if (!targetSelector) return;
          const target = document.querySelector(targetSelector);
          if (!target) return;
          const side = (handle.getAttribute('data-side') || 'right').toLowerCase();
          const minWidthAttr = Number(handle.getAttribute('data-min-width'));
          const maxWidthAttr = Number(handle.getAttribute('data-max-width'));
          const minWidth = Number.isFinite(minWidthAttr) ? minWidthAttr : (side === 'left' ? 240 : 300);
          const maxWidth = Number.isFinite(maxWidthAttr) ? maxWidthAttr : (side === 'left' ? 520 : 760);

          const startResize = function(startEvent) {
            if (startEvent.button !== undefined && startEvent.button !== 0) return;
            const isPointer = startEvent.type === 'pointerdown';
            if (isPointer && startEvent.pointerType === 'touch') {
              startEvent.preventDefault();
            } else {
              startEvent.preventDefault();
            }
            const pointerId = isPointer ? startEvent.pointerId : null;
            const startX = startEvent.clientX;
            const initialWidth = target.offsetWidth || parseFloat(getComputedStyle(target).width) || 0;

            const resizeTo = function(clientX) {
              if (typeof clientX !== 'number') return;
              let delta = clientX - startX;
              let newWidth = initialWidth;
              if (side === 'right') {
                newWidth = initialWidth + delta;
              } else {
                newWidth = initialWidth - delta;
              }
              if (Number.isFinite(minWidth)) newWidth = Math.max(minWidth, newWidth);
              if (Number.isFinite(maxWidth)) newWidth = Math.min(maxWidth, newWidth);
              target.style.width = newWidth + 'px';
              updateLegendVisibility();
              if (mapInstance && typeof mapInstance.invalidateSize === 'function') {
                mapInstance.invalidateSize({ animate: false });
              }
            };

            const onMove = function(moveEvent) {
              if (isPointer && moveEvent.pointerId !== pointerId) return;
              resizeTo(moveEvent.clientX);
            };

            const cleanup = function() {
              document.body.style.userSelect = '';
              document.body.style.cursor = '';
              if (isPointer) {
                window.removeEventListener('pointermove', onMove);
                window.removeEventListener('pointerup', onUp);
                window.removeEventListener('pointercancel', onCancel);
              } else {
                window.removeEventListener('mousemove', onMove);
                window.removeEventListener('mouseup', onUp);
              }
              updateLegendVisibility();
              if (mapInstance && typeof mapInstance.invalidateSize === 'function') {
                mapInstance.invalidateSize({ animate: false });
              }
            };

            const onUp = function(endEvent) {
              if (isPointer && endEvent.pointerId !== pointerId) return;
              cleanup();
            };

            const onCancel = function(cancelEvent) {
              if (isPointer && cancelEvent.pointerId !== pointerId) return;
              cleanup();
            };

            document.body.style.userSelect = 'none';
            document.body.style.cursor = 'col-resize';

            if (isPointer) {
              window.addEventListener('pointermove', onMove);
              window.addEventListener('pointerup', onUp);
              window.addEventListener('pointercancel', onCancel);
            } else {
              window.addEventListener('mousemove', onMove);
              window.addEventListener('mouseup', onUp);
            }
          };

          if (window.PointerEvent) {
            handle.addEventListener('pointerdown', startResize);
          } else {
            handle.addEventListener('mousedown', startResize);
          }
        });
      }

      function formatWithSummary(summary, value) {
        if (value === null || value === undefined || Number.isNaN(value)) return '–';
        if (summary.format === 'currency') {
          return '$$' + Math.round(value).toLocaleString();
        }
        if (summary.format === 'ratio') {
          const decimals = summary.decimals ?? 2;
          return Number(value).toLocaleString(undefined, {minimumFractionDigits: decimals, maximumFractionDigits: decimals});
        }
        if (summary.type === 'int') {
          return Math.round(value).toLocaleString();
        }
        const decimals = summary.decimals ?? 2;
        return Number(value).toLocaleString(undefined, {maximumFractionDigits: decimals});
      }

      function formatMetricValue(metric, value) {
        const ctrl = metricControls[metric];
        if (!ctrl) return String(value);
        return formatWithSummary(ctrl.summary, value);
      }

      function updateMetricLabels(metric) {
        const ctrl = metricControls[metric];
        if (!ctrl) return;
        const summary = ctrl.summary;
        const fromSlider = ctrl.fromSlider;
        const toSlider = ctrl.toSlider;
        const parseSlider = function(slider) {
          const raw = parseFloat(slider.value);
          if (!Number.isFinite(raw)) return null;
          const value = fromSlider(raw);
          return Number.isFinite(value) ? value : null;
        };
        let minVal = parseSlider(ctrl.minSlider);
        let maxVal = parseSlider(ctrl.maxSlider);
        if (minVal === null) minVal = summary.min;
        if (maxVal === null) maxVal = summary.max;
        minVal = Math.max(summary.min, Math.min(summary.max, minVal));
        maxVal = Math.max(summary.min, Math.min(summary.max, maxVal));
        if (minVal > maxVal) {
          if (ctrl.useLog) {
            maxVal = minVal;
          } else {
            minVal = maxVal;
          }
        }
        if (summary.type === 'int') {
          minVal = Math.round(minVal);
          maxVal = Math.round(maxVal);
        }
        ctrl.currentMin = minVal;
        ctrl.currentMax = maxVal;
        ctrl.minLabel.textContent = formatWithSummary(summary, minVal);
        ctrl.maxLabel.textContent = formatWithSummary(summary, maxVal);
        if (ctrl.bars && ctrl.bars.length) {
          const low = Math.min(minVal, maxVal);
          const high = Math.max(minVal, maxVal);
          ctrl.bars.forEach(function(bar) {
            const start = parseFloat(bar.dataset.start);
            const end = parseFloat(bar.dataset.end);
            const active = !(end < low || start > high);
            bar.classList.toggle('active', active);
          });
        }
        ctrl.minSlider.value = String(toSlider(minVal));
        ctrl.maxSlider.value = String(toSlider(maxVal));
      }

      function makeSliderHandler(metric, role) {
        return function() {
          const ctrl = metricControls[metric];
          if (!ctrl) return;
          const fromSlider = ctrl.fromSlider;
          const toSlider = ctrl.toSlider;
          const minVal = fromSlider(parseFloat(ctrl.minSlider.value));
          const maxVal = fromSlider(parseFloat(ctrl.maxSlider.value));
          if (role === 'min') {
            if (Number.isFinite(minVal) && Number.isFinite(maxVal) && minVal > maxVal) {
              ctrl.maxSlider.value = String(toSlider(minVal));
            }
          } else if (role === 'max') {
            if (Number.isFinite(minVal) && Number.isFinite(maxVal) && maxVal < minVal) {
              ctrl.minSlider.value = String(toSlider(maxVal));
            }
          }
          updateMetricLabels(metric);
          applyFilters();
        };
      }

      function buildMetricControls() {
        const container = document.getElementById('filter-building-section');
        Object.keys(metricControls).forEach(function(key) { delete metricControls[key]; });
        metricKeys = [];
        if (!container || !filterConfig.building_metrics) {
          return;
        }
        container.innerHTML = '';
        const order = filterConfig.building_metric_order || Object.keys(filterConfig.building_metrics);
        order.forEach(function(metric) {
          const summary = filterConfig.building_metrics[metric];
          if (!summary) return;
          const control = document.createElement('div');
          control.className = 'metric-control';

          const hasSpread = summary.max > summary.min;
          const positiveMin = (typeof summary.min_positive === 'number' && summary.min_positive > 0) ? summary.min_positive : null;
          let useLog = false;
          if (summary.use_log !== undefined) {
            useLog = !!summary.use_log;
          } else {
            useLog = !!(summary.type !== 'int' && positiveMin !== null && hasSpread && (
              summary.format === 'currency' || (summary.max / positiveMin) >= 25
            ));
          }
          useLog = useLog && positiveMin !== null && hasSpread;

          const header = document.createElement('div');
          header.className = 'metric-header';
          header.textContent = summary.label || metric;
          control.appendChild(header);

          const hist = document.createElement('div');
          hist.className = 'metric-histogram';
          const bars = [];
          const bins = summary.bins || [];
          const maxCount = summary.max_count || 1;
          bins.forEach(function(bin) {
            const bar = document.createElement('div');
            bar.className = 'metric-hist-bar';
            const height = maxCount ? Math.max(2, (bin.count / maxCount) * 100) : 2;
            bar.style.height = height + '%';
            bar.dataset.start = bin.start;
            bar.dataset.end = bin.end;
            const rangeLabel = formatWithSummary(summary, bin.start) + ' – ' + formatWithSummary(summary, bin.end);
            const countLabel = ' (' + bin.count.toLocaleString() + ')';
            bar.title = useLog ? rangeLabel + countLabel + ' [log bin]' : rangeLabel + countLabel;
            hist.appendChild(bar);
            bars.push(bar);
          });
          control.appendChild(hist);

          const sliders = document.createElement('div');
          sliders.className = 'metric-sliders';
          const minSlider = document.createElement('input');
          minSlider.type = 'range';
          const maxSlider = document.createElement('input');
          maxSlider.type = 'range';

          const logMin = useLog ? Math.log(positiveMin) : 0;
          const logMax = useLog ? Math.log(Math.max(summary.max, positiveMin)) : 1;
          const toSlider = useLog && logMax !== logMin
            ? function(value) {
                if (!Number.isFinite(value)) return 0;
                if (value <= 0) return 0;
                const clamped = Math.max(positiveMin, Math.min(Number(value), summary.max));
                return ((Math.log(clamped) - logMin) / (logMax - logMin)) * 100;
              }
            : function(value) { return Number(value); };
          const fromSlider = useLog && logMax !== logMin
            ? function(pos) {
                const ratio = Math.min(1, Math.max(0, Number(pos) / 100));
                if (ratio === 0 && summary.min <= 0) {
                  return summary.min;
                }
                return Math.exp(logMin + ratio * (logMax - logMin));
              }
            : function(pos) { return Number(pos); };

          const sliderStep = useLog ? 0.5 : (summary.step || ((summary.max - summary.min) / 200) || 1);

          if (useLog && logMax !== logMin) {
            minSlider.min = 0;
            minSlider.max = 100;
            maxSlider.min = 0;
            maxSlider.max = 100;
            minSlider.value = String(toSlider(summary.min));
            maxSlider.value = String(toSlider(summary.max));
          } else {
            minSlider.min = summary.min;
            minSlider.max = summary.max;
            maxSlider.min = summary.min;
            maxSlider.max = summary.max;
            minSlider.value = String(summary.min);
            maxSlider.value = String(summary.max);
          }
          minSlider.step = sliderStep;
          maxSlider.step = sliderStep;

          sliders.appendChild(minSlider);
          sliders.appendChild(maxSlider);
          control.appendChild(sliders);

          const values = document.createElement('div');
          values.className = 'metric-values';
          const minLabel = document.createElement('span');
          const maxLabel = document.createElement('span');
          values.appendChild(minLabel);
          values.appendChild(maxLabel);
          control.appendChild(values);

          container.appendChild(control);

          metricControls[metric] = {
            summary: summary,
            minSlider: minSlider,
            maxSlider: maxSlider,
            minLabel: minLabel,
            maxLabel: maxLabel,
            bars: bars,
            useLog: useLog && logMax !== logMin,
            toSlider: useLog && logMax !== logMin ? toSlider : function(value) { return Number(value); },
            fromSlider: useLog && logMax !== logMin ? fromSlider : function(value) { return Number(value); },
            currentMin: summary.min,
            currentMax: summary.max,
          };

          minSlider.addEventListener('input', makeSliderHandler(metric, 'min'));
          maxSlider.addEventListener('input', makeSliderHandler(metric, 'max'));
        });
        metricKeys = Object.keys(metricControls);
        metricKeys.forEach(updateMetricLabels);
      }

      initializeYearControl();
      buildMetricControls();
      syncYearSliderState();
      updateDatasetStatus();
      updateLegendVisibility();

      function applyFilters() {
        metricKeys.forEach(updateMetricLabels);
        const searchTerm = '';
        const selectedHoods = hoodInputs
          .filter(function(inp) { return inp.checked; })
          .map(function(inp) { return (inp.value || '').toLowerCase().trim(); });
        const hasHoodFilter = hoodInputs.length > 0;
        const restrictHoods = hasHoodFilter && selectedHoods.length > 0;
        const hideWhenNone = hasHoodFilter && selectedHoods.length === 0;
        const thresholds = {};
        metricKeys.forEach(function(metric) {
          const ctrl = metricControls[metric];
          const summary = ctrl.summary;
          let minVal = ctrl.currentMin;
          let maxVal = ctrl.currentMax;
          const tolerance = summary.step ? summary.step * 0.5 : 0;
          thresholds[metric] = {
            min: (minVal <= summary.min + tolerance) ? null : minVal,
            max: (maxVal >= summary.max - tolerance) ? null : maxVal,
            summary: summary,
          };
        });
        const opts = {
          requireMember: requireMemberChk ? requireMemberChk.checked : false,
          minYear: (yearToggle && yearToggle.checked && yearSlider) ? Number.parseInt(yearSlider.value, 10) : null,
        };
        if (opts.minYear !== null && Number.isNaN(opts.minYear)) {
          opts.minYear = null;
        }
        const visibleBids = new Set();
        document.querySelectorAll('#buildings-table tbody tr').forEach(function(row) {
          const bid = row.getAttribute('data-bid');
          const marker = window.buildingIndex[bid];
          const records = window.membershipData[bid] || [];
          const membershipMatch = matchesFilters(records, opts);
          if (marker) {
            marker._passesMembership = membershipMatch;
          }

          let matches = true;
          const rowArea = (row.getAttribute('data-area') || '').toLowerCase().trim();
          if (restrictHoods) {
            matches = selectedHoods.includes(rowArea);
          } else if (hideWhenNone) {
            matches = false;
          }

          if (matches && metricKeys.length) {
            for (let i = 0; i < metricKeys.length; i += 1) {
              const metric = metricKeys[i];
              const threshold = thresholds[metric];
              const attrName = 'data-' + threshold.summary.attr;
              const rawValue = row.getAttribute(attrName);
              const value = rawValue === null || rawValue === '' ? NaN : parseFloat(rawValue);
              if (Number.isNaN(value)) {
                continue;
              }
              if (threshold.min !== null && value < threshold.min) { matches = false; break; }
              if (threshold.max !== null && value > threshold.max) { matches = false; break; }
            }
          }

          if (matches && searchTerm) {
            const haystack = row.getAttribute('data-search') || '';
            matches = haystack.indexOf(searchTerm) !== -1;
          }

          row.classList.toggle('hidden', !matches);
          const checkbox = row.querySelector('.row-select');
          if (!matches) {
            if (checkbox && checkbox.checked) {
              const current = marker ? (marker._selectionRefs || 0) : 0;
              checkbox.checked = false;
              if (marker && current > 0) adjustMarkerSelection(marker, -current);
            }
          }

          setMarkerVisibility(marker, matches);
          if (marker) {
            updateMarkerColorAppearance(marker);
          }

          if (matches) {
            visibleBids.add(String(bid));
          }
        });

        Object.keys(window.blockBuildingIndex).forEach(function(blockId) {
          var ids = window.blockBuildingIndex[blockId] || [];
          var hasVisible = ids.some(function(id) { return visibleBids.has(String(id)); });
          var row = document.querySelector('#blocks-table tbody tr[data-block="' + blockId + '"]');
          var layer = window.blocksIndex[blockId];
          if (row) {
            row.classList.toggle('hidden', !hasVisible);
            const checkbox = row.querySelector('.row-select');
            if (!hasVisible && checkbox && checkbox.checked) {
              checkbox.checked = false;
              if (layer) layer._selectionRefs = 0;
              setBlockSelectionMarkers(blockId, false);
            }
          }
          setBlockFiltered(blockId, !hasVisible);
        });

        document.querySelectorAll('#landlords-table tbody tr').forEach(function(row) {
          var owner = row.getAttribute('data-owner');
          var hasVisible = !!document.querySelector('#buildings-table tbody tr[data-owner="' + owner + '"]:not(.hidden)');
          row.classList.toggle('hidden', !hasVisible);
          const checkbox = row.querySelector('.row-select');
          if (!hasVisible && checkbox && checkbox.checked) {
            checkbox.checked = false;
            setOwnerSelection(owner, false);
          }
        });

        updateDatasetStatus();
        updateMapStatus();
        updateSummaryBar();
      }

      if (requireMemberChk) requireMemberChk.addEventListener('change', applyFilters);
      if (yearToggle) yearToggle.addEventListener('change', function() {
        syncYearSliderState();
        applyFilters();
      });
      if (yearSlider) yearSlider.addEventListener('input', function() {
        updateYearLabel();
        if (yearToggle && yearToggle.checked) {
          applyFilters();
        }
      });
      hoodInputs.forEach(function(inp) { inp.addEventListener('change', applyFilters); });

      if (hoodSelectAllBtn) {
        hoodSelectAllBtn.addEventListener('click', function() {
          hoodInputs.forEach(function(inp) { inp.checked = true; });
          applyFilters();
        });
      }
      if (hoodClearBtn) {
        hoodClearBtn.addEventListener('click', function() {
          hoodInputs.forEach(function(inp) { inp.checked = false; });
          applyFilters();
        });
      }

      let searchDebounce = null;

      initPaneResize();

      toggleLayerVisibility(layerVTU, true);
      if (colorScaleChk) {
        applyVtuColorScaling(colorScaleChk.checked !== false);
        colorScaleChk.addEventListener('change', function() {
          applyVtuColorScaling(colorScaleChk.checked !== false);
        });
      } else {
        applyVtuColorScaling(true);
      }
      if (colorBlocksChk) {
        applyBlockColorScaling(colorBlocksChk.checked !== false);
        colorBlocksChk.addEventListener('change', function() {
          applyBlockColorScaling(colorBlocksChk.checked !== false);
        });
      } else {
        applyBlockColorScaling(true);
      }
      if (hideNonChk) {
        toggleLayerVisibility(layerNon, !hideNonChk.checked);
        hideNonChk.addEventListener('change', function() {
          toggleLayerVisibility(layerNon, !hideNonChk.checked);
          updateMapStatus();
        });
      } else {
        toggleLayerVisibility(layerNon, true);
      }
      if (vizBlocksChk) {
        toggleLayerVisibility(layerBlocks, vizBlocksChk.checked !== false);
        vizBlocksChk.addEventListener('change', function() {
          toggleLayerVisibility(layerBlocks, vizBlocksChk.checked);
          updateLegendVisibility();
        });
      } else {
        toggleLayerVisibility(layerBlocks, true);
      }

      if (resetBtn) {
        resetBtn.addEventListener('click', function() {
          if (requireMemberChk) requireMemberChk.checked = false;
          if (yearToggle) yearToggle.checked = false;
          if (yearSlider) {
            yearSlider.value = yearRangeMin !== null ? String(yearRangeMin) : yearSlider.value;
          }
          syncYearSliderState();
          hoodInputs.forEach(function(inp) { inp.checked = true; });
          if (colorScaleChk) {
            colorScaleChk.checked = true;
            applyVtuColorScaling(true);
          }
          if (colorBlocksChk) {
            colorBlocksChk.checked = true;
            applyBlockColorScaling(true);
          }
          if (hideNonChk) {
            hideNonChk.checked = false;
            toggleLayerVisibility(layerNon, true);
          }
          if (vizBlocksChk) {
            vizBlocksChk.checked = true;
            toggleLayerVisibility(layerBlocks, true);
          }
          if (tableSearchInput) {
            tableSearchInput.value = '';
          }
          document.querySelectorAll('.row-select').forEach(function(cb) {
            if (cb.checked) {
              cb.checked = false;
              cb.dispatchEvent(new Event('change', { bubbles: true }));
            }
          });
          metricKeys.forEach(function(metric) {
            const ctrl = metricControls[metric];
            if (!ctrl) return;
            ctrl.minSlider.value = ctrl.summary.min;
            ctrl.maxSlider.value = ctrl.summary.max;
            updateMetricLabels(metric);
          });
          applyFilters();
          updateLegendVisibility();
        });
      }

      metricKeys.forEach(updateMetricLabels);
      updateLegendVisibility();
      applyFilters();
    } catch (e) {
      setTimeout(wireUp, 120);
    }
  }

  function loadInitialData() {
    return Promise.all([
      fetchJson(DATA_URLS.filterConfig),
      fetchJson(DATA_URLS.markerMetadata),
      fetchJson(DATA_URLS.buildingData),
    ]).then(function(results) {
      assignLoadedData(results[0], results[1], results[2]);
    });
  }

  loadInitialData()
    .then(function() {
      if (document.readyState === 'complete') {
        wireUp();
      } else {
        window.addEventListener('load', wireUp);
      }
    })
    .catch(function(err) {
      console.error('Failed to initialise map data', err);
    });
})();
</script>
