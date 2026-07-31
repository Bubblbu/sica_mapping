
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
      const layerNeighbourhoods = window["$layer_neighbourhoods_var"] || null;
      const mapInstance = (layerBlocks && layerBlocks._map) || (layerVTU && layerVTU._map) || (layerNon && layerNon._map) || null;

      if (!layerBlocks || typeof layerBlocks.eachLayer !== 'function') {
        throw new Error('Blocks layer not ready');
      }

      window.blocksIndex = {};
      window.blockBuildingIndex = {};
      window.buildingIndex = {};
      window.ownerIndex = {};
      window.hoodIndex = {};
      const BASE_ZOOM = 14;
      // Thin light stroke so overlapping markers read as distinct dots instead
      // of blurring into solid blobs at dense blocks (option 1).
      const MARKER_STROKE_COLOR = '#ffffff';
      const MARKER_STROKE_WEIGHT = 0.6;
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
        const buildingCount = Number(layer._blockBuildings) || 0;
        let base;
        if (buildingCount <= 0) {
          // Empty blocks (no buildings) carry no meaningful data — leave them
          // transparent rather than painting them into the color scale.
          base = { weight:1, color:'#b8b8b8', fillOpacity:0, fillColor:'transparent' };
        } else if (!blockColorScalingEnabled || blockColorMax <= 0) {
          base = { weight:1, color:'#b8b8b8', fillOpacity:0.35, fillColor:'#f0f0f0' };
        } else {
          const ratio = Math.max(0, Math.min(1, units / blockColorMax));
          const fill = (ratio <= 0.10) ? '#c7e9c0' :
                       (ratio <= 0.25) ? '#a1d99b' :
                       (ratio <= 0.50) ? '#74c476' :
                       (ratio <= 0.75) ? '#41ab5d' :
                       (ratio <  1.00) ? '#238b45' : '#005a32';
          base = { weight:1, color:'#b8b8b8', fillOpacity:0.7, fillColor:fill };
        }
        layer._baseStyle = base;
        layer.setStyle(base);
      }

      function setBlockFiltered(blockId, filtered) {
        var layer = window.blocksIndex[blockId];
        if (!layer) return;
        // Called for every one of ~4,600 blocks on every filter tick; skip the
        // setStyle work when the filtered state isn't actually changing (same
        // reasoning as setMarkerVisibility above).
        if (layer._isFiltered === filtered) return;
        layer._isFiltered = filtered;
        if (filtered) {
          layer._selectionRefs = 0;
          // Fully hidden, matching setMarkerVisibility()'s treatment of filtered
          // buildings (weight:0/fillOpacity:0) rather than just dimming to a
          // faint grey outline.
          layer.setStyle({ weight:0, color:null, fillOpacity:0, fillColor:'#f5f5f5' });
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
            weight: MARKER_STROKE_WEIGHT,
            color: MARKER_STROKE_COLOR,
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
        // Called for every one of ~5,000 buildings on every filter/slider tick;
        // most buildings' visibility doesn't flip on a given tick, so skip the
        // setStyle/setRadius work (real canvas redraw cost) entirely when the
        // state isn't actually changing — this was the main source of slider-
        // drag jank.
        if (marker._isFiltered === !visible) return;
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
              weight: MARKER_STROKE_WEIGHT,
              color: MARKER_STROKE_COLOR,
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

      function setHoodSelection(hoodKey, selected) {
        var arr = window.hoodIndex[hoodKey] || [];
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
          const memberCount = Number(meta.member_count);
          marker._memberCount = Number.isFinite(memberCount) ? memberCount : 0;
          if (!marker.options) marker.options = {};
          marker.options.base_color = marker._baseColor;
          const unitsMeta = Number(meta.units);
          marker._units = Number.isFinite(unitsMeta) ? unitsMeta : 0;
          const yearMeta = Number(meta.year_built);
          marker._yearBuilt = Number.isFinite(yearMeta) ? yearMeta : null;
          ensureMarkerBase(marker);
          updateMarkerColorAppearance(marker);

          var ownerKey = meta.owner_key;
          if (ownerKey) {
            if (!window.ownerIndex[ownerKey]) window.ownerIndex[ownerKey] = [];
            if (window.ownerIndex[ownerKey].indexOf(marker) === -1) {
              window.ownerIndex[ownerKey].push(marker);
            }
          }

          var hoodKey = String(meta.local_area || '').toLowerCase().trim();
          if (hoodKey) {
            if (!window.hoodIndex[hoodKey]) window.hoodIndex[hoodKey] = [];
            if (window.hoodIndex[hoodKey].indexOf(marker) === -1) {
              window.hoodIndex[hoodKey].push(marker);
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

      function neighbourhoodHover(hoodKey, on) {
        var arr = window.hoodIndex[hoodKey] || [];
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
        } else if (typ === 'neighbourhood') {
          setHoodSelection(key.toLowerCase().trim(), cb.checked);
        }
        updateSummaryBar();
        updateGroupTableSummaries();
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
          var buildingCount = Number(props.buildings);
          layer._blockBuildings = Number.isFinite(buildingCount) ? buildingCount : 0;
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

      // Blocks and building markers share one canvas renderer (prefer_canvas=True
      // on the map, neither layer sets a custom pane/renderer), so paint order is
      // just insertion order into that shared canvas — not tied to which was added
      // to the map first. Toggling a layer off/on re-inserts it at the end (drawn
      // on top), so re-showing blocks after hiding them can push them in front of
      // buildings. Pin blocks behind buildings every time blocks become visible.
      function sendBlocksToBack() {
        blockLayers.forEach(function(layer) {
          if (layer && typeof layer.bringToBack === 'function') layer.bringToBack();
        });
      }
      sendBlocksToBack();

      applyMarkerMetadata();
      const markerCount = Object.keys(window.buildingIndex).length;
      if (!markerCount) {
        throw new Error('Building markers not ready');
      }
      applyZoomScaling();
      // Toggling a FeatureGroup/GeoJSON layer on/off (e.g. "Show buildings",
      // "Show blocks") fires 'layeradd'/'layerremove' on the map once PER CHILD
      // layer — thousands of times for ~5,000 building markers or ~4,600 block
      // features — not once for the group. Running updateMapStatus()/
      // applyZoomScaling() (each an O(buildings) scan) synchronously on every one
      // of those events is what froze the page on toggle. Coalesce to at most
      // once per animation frame, same pattern as scheduleApplyFilters() below.
      let mapStatusScheduled = false;
      function scheduleMapStatusUpdate() {
        if (mapStatusScheduled) return;
        mapStatusScheduled = true;
        window.requestAnimationFrame(function() {
          mapStatusScheduled = false;
          updateMapStatus();
          applyZoomScaling();
        });
      }
      if (mapInstance && typeof mapInstance.on === 'function') {
        mapInstance.on('moveend', scheduleMapStatusUpdate);
        mapInstance.on('zoomend', scheduleMapStatusUpdate);
        mapInstance.on('layeradd', scheduleMapStatusUpdate);
        mapInstance.on('layerremove', scheduleMapStatusUpdate);
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
      const tabN = document.getElementById('tab-neighbourhoods');
      const paneB = document.getElementById('pane-buildings');
      const paneK = document.getElementById('pane-blocks');
      const paneL = document.getElementById('pane-landlords');
      const paneN = document.getElementById('pane-neighbourhoods');
      function activate(which) {
        [tabB, tabK, tabL, tabN].forEach(btn => btn && btn.classList.remove('active'));
        [paneB, paneK, paneL, paneN].forEach(pane => pane && pane.classList.remove('active'));
        if (which === 'buildings') { if (tabB) tabB.classList.add('active'); if (paneB) paneB.classList.add('active'); }
        else if (which === 'blocks') { if (tabK) tabK.classList.add('active'); if (paneK) paneK.classList.add('active'); }
        else if (which === 'neighbourhoods') { if (tabN) tabN.classList.add('active'); if (paneN) paneN.classList.add('active'); }
        else { if (tabL) tabL.classList.add('active'); if (paneL) paneL.classList.add('active'); }
      }
      if (tabB) tabB.addEventListener('click', () => activate('buildings'));
      if (tabK) tabK.addEventListener('click', () => activate('blocks'));
      if (tabL) tabL.addEventListener('click', () => activate('landlords'));
      if (tabN) tabN.addEventListener('click', () => activate('neighbourhoods'));

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

      document.querySelectorAll('#neighbourhoods-table tbody tr').forEach(function(row) {
        var hoodKey = (row.getAttribute('data-area') || '').toLowerCase().trim();
        row.addEventListener('mouseenter', function() { neighbourhoodHover(hoodKey, true); });
        row.addEventListener('mouseleave', function() { neighbourhoodHover(hoodKey, false); });
      });

      const hoodInputs = Array.from(document.querySelectorAll('.filter-neighbourhood-option'));

      // Cached once: applyFilters() runs on every slider tick, so re-querying the DOM
      // (and re-resolving each row's checkbox) on every call is the difference between
      // a smooth drag and a janky one at ~5,000 building rows. Row sets never change
      // after initial render — only their hidden/visible state does.
      const buildingRows = Array.from(document.querySelectorAll('#buildings-table tbody tr'));
      buildingRows.forEach(function(row) { row.__checkbox = row.querySelector('.row-select'); });

      // Column indices of the aggregate cells that get recomputed live from
      // currently-visible buildings on every applyFilters() pass (see
      // updateGroupRowValues below) — must match the <thead> order in sidebar.html.
      function cacheRowCells(rows, colMap) {
        rows.forEach(function(row) {
          row.__cells = {};
          Object.keys(colMap).forEach(function(key) {
            row.__cells[key] = row.children[colMap[key]] || null;
          });
        });
      }

      const landlordRows = Array.from(document.querySelectorAll('#landlords-table tbody tr'));
      landlordRows.forEach(function(row) { row.__checkbox = row.querySelector('.row-select'); });
      cacheRowCells(landlordRows, { bldgs: 2, units: 3, avg: 4, vtu: 5 });

      const neighbourhoodRows = Array.from(document.querySelectorAll('#neighbourhoods-table tbody tr'));
      neighbourhoodRows.forEach(function(row) { row.__checkbox = row.querySelector('.row-select'); });
      cacheRowCells(neighbourhoodRows, { bldgs: 2, units: 3, avg: 4, vtu: 5 });

      const blockRowById = {};
      const blockRows = Array.from(document.querySelectorAll('#blocks-table tbody tr'));
      cacheRowCells(blockRows, { bldgs: 2, units: 3, avg: 4, year: 5, vtu: 6 });
      blockRows.forEach(function(row) {
        row.__checkbox = row.querySelector('.row-select');
        blockRowById[row.getAttribute('data-block')] = row;
      });
      const hoodSelectAllBtn = document.getElementById('hood-select-all');
      const hoodClearBtn = document.getElementById('hood-clear');
      const resetBtn = document.getElementById('filter-reset');
      const colorScaleChk = document.getElementById('viz-color-vtu');
      const colorBlocksChk = document.getElementById('viz-color-blocks');
      const showBuildingsChk = document.getElementById('viz-show-buildings');
      const vizBlocksChk = document.getElementById('viz-show-blocks');
      const hideEmptyBlocksChk = document.getElementById('viz-hide-empty-blocks');
      const vizNeighbourhoodsChk = document.getElementById('viz-show-neighbourhoods');
      const tableSearchInput = document.getElementById('owner-search');
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

      const datasetTotals = (filterConfig && filterConfig.dataset_totals) || null;
      const totalBuildings = datasetTotals && typeof datasetTotals.buildings === 'number' ? datasetTotals.buildings : null;
      const totalMembers = datasetTotals && typeof datasetTotals.members === 'number' ? datasetTotals.members : null;
      const totalUnits = datasetTotals && typeof datasetTotals.units === 'number' ? datasetTotals.units : null;
      const totalVtuBuildings = datasetTotals && typeof datasetTotals.vtu_buildings === 'number' ? datasetTotals.vtu_buildings : null;

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

      function updateSummaryBar() {
        if (!summaryLabelEl || !summaryUnitsEl || !summaryMembersEl || !summaryRowsEl) return;
        const allRows = buildingRows;
        const selectedRows = allRows.filter(function(row) {
          const cb = row.__checkbox;
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

      // Recomputes one Blocks/Landlords/Neighbourhoods row's Bldgs/Units/Avg/VTU
      // (and, for blocks, Median year) cells from only the buildings currently
      // passing the active filters — the row's own columns were previously baked
      // in at build time from the full dataset and never changed when a filter
      // (e.g. the unit-size slider) hid some of its buildings.
      // `items` is either an array of markers (landlords/neighbourhoods, via
      // window.ownerIndex/hoodIndex) or an array of building-id strings
      // (blocks, via window.blockBuildingIndex) — `resolveMarker` resolves the
      // latter without allocating an intermediate array on every call.
      // `includeYear` skips the years array/sort entirely for landlord and
      // neighbourhood rows, which never display a median-year column — with
      // ~1,500 landlord rows re-evaluated per slider-drag frame, that sort was
      // pure waste for a value nothing ever reads.
      function computeLiveGroupMetrics(items, resolveMarker, includeYear) {
        let bldgs = 0;
        let units = 0;
        let vtu = 0;
        const years = includeYear ? [] : null;
        items.forEach(function(item) {
          const marker = resolveMarker ? resolveMarker(item) : item;
          if (!marker || marker._isFiltered) return;
          bldgs += 1;
          const u = Number(marker._units);
          if (Number.isFinite(u)) units += u;
          if (marker._isVtu) vtu += 1;
          if (includeYear && marker._yearBuilt !== null && marker._yearBuilt !== undefined) {
            years.push(marker._yearBuilt);
          }
        });
        let medianYear = null;
        if (includeYear && years.length) {
          years.sort(function(a, b) { return a - b; });
          const mid = Math.floor(years.length / 2);
          medianYear = years.length % 2 ? years[mid] : Math.round((years[mid - 1] + years[mid]) / 2);
        }
        return { bldgs: bldgs, units: units, vtu: vtu, avg: bldgs > 0 ? units / bldgs : 0, medianYear: medianYear };
      }

      function setCellValue(cell, sortValue, text) {
        if (!cell) return;
        cell.setAttribute('data-sort-value', String(sortValue));
        cell.textContent = text;
      }

      // Skips all DOM writes when nothing actually changed since the last call —
      // during a slider drag, most blocks/landlords/neighbourhoods are unaffected
      // by a given threshold nudge, and writing textContent/attributes on ~6,000
      // rows every animation frame (whether or not the numbers moved) was the
      // main cause of the drag feeling sluggish.
      function updateGroupRowValues(row, items, resolveMarker) {
        if (!row || !row.__cells) return;
        const includeYear = !!row.__cells.year;
        const m = computeLiveGroupMetrics(items, resolveMarker, includeYear);
        const prev = row.__lastMetrics;
        if (prev && prev.bldgs === m.bldgs && prev.units === m.units && prev.vtu === m.vtu && prev.medianYear === m.medianYear) {
          return;
        }
        row.__lastMetrics = m;
        setCellValue(row.__cells.bldgs, m.bldgs, m.bldgs.toLocaleString());
        setCellValue(row.__cells.units, m.units, m.units.toLocaleString());
        setCellValue(row.__cells.avg, m.avg, m.avg.toFixed(1));
        setCellValue(row.__cells.vtu, m.vtu, m.vtu.toLocaleString());
        if (includeYear) {
          setCellValue(row.__cells.year, m.medianYear === null ? '' : m.medianYear, m.medianYear === null ? '' : String(m.medianYear));
        }
        // Keep the row's own data attributes in sync too, since
        // updateGroupTableSummary()'s footer totals sum from these.
        row.setAttribute('data-bldgs', String(m.bldgs));
        row.setAttribute('data-units', String(m.units));
        row.setAttribute('data-vtu-bldgs', String(m.vtu));
      }

      // Shared footer-summary logic for the Blocks/Landlords/Neighbourhoods tabs,
      // which all use the same Bldgs/Units/Avg Units per Bldg/VTU bldgs column
      // shape (unlike Buildings, whose footer tracks Units/Members per building
      // row rather than a per-group aggregate).
      function updateGroupTableSummary(rows, ids) {
        const labelEl = document.getElementById(ids.label);
        if (!labelEl) return;
        const selectedRows = rows.filter(function(row) {
          const cb = row.__checkbox;
          return cb && cb.checked;
        });
        const targetRows = selectedRows.length ? selectedRows : rows.filter(function(row) {
          return !row.classList.contains('hidden');
        });
        const label = selectedRows.length ? 'Totals (selected)' : 'Totals (visible)';
        let bldgsSum = 0;
        let unitsSum = 0;
        let vtuSum = 0;
        targetRows.forEach(function(row) {
          const bldgs = Number(row.getAttribute('data-bldgs'));
          const units = Number(row.getAttribute('data-units'));
          const vtu = Number(row.getAttribute('data-vtu-bldgs'));
          if (Number.isFinite(bldgs)) bldgsSum += bldgs;
          if (Number.isFinite(units)) unitsSum += units;
          if (Number.isFinite(vtu)) vtuSum += vtu;
        });
        const avg = bldgsSum > 0 ? unitsSum / bldgsSum : 0;
        const rowCount = targetRows.length || 0;
        labelEl.textContent = label + ' — ' + rowCount.toLocaleString() + (rowCount === 1 ? ' row' : ' rows');
        const bldgsEl = document.getElementById(ids.bldgs);
        const unitsEl = document.getElementById(ids.units);
        const avgEl = document.getElementById(ids.avg);
        const vtuEl = document.getElementById(ids.vtu);
        if (bldgsEl) bldgsEl.textContent = bldgsSum.toLocaleString();
        if (unitsEl) unitsEl.textContent = unitsSum.toLocaleString();
        if (avgEl) avgEl.textContent = avg.toFixed(1);
        if (vtuEl) vtuEl.textContent = vtuSum.toLocaleString();
      }

      function updateGroupTableSummaries() {
        updateGroupTableSummary(blockRows, {
          label: 'summary-blocks-label', bldgs: 'summary-blocks-bldgs',
          units: 'summary-blocks-units', avg: 'summary-blocks-avg', vtu: 'summary-blocks-vtu',
        });
        updateGroupTableSummary(landlordRows, {
          label: 'summary-landlords-label', bldgs: 'summary-landlords-bldgs',
          units: 'summary-landlords-units', avg: 'summary-landlords-avg', vtu: 'summary-landlords-vtu',
        });
        updateGroupTableSummary(neighbourhoodRows, {
          label: 'summary-neighbourhoods-label', bldgs: 'summary-neighbourhoods-bldgs',
          units: 'summary-neighbourhoods-units', avg: 'summary-neighbourhoods-avg', vtu: 'summary-neighbourhoods-vtu',
        });
      }

      function setLegendDisplay(el, show) {
        if (!el) return;
        el.style.display = show ? 'block' : 'none';
      }

      function updateLegendVisibility() {
        const blocksVisible = vizBlocksChk ? vizBlocksChk.checked !== false : true;
        const buildingsVisible = showBuildingsChk ? showBuildingsChk.checked !== false : true;
        const showBuildingLegend = buildingsVisible && (colorScaleChk ? colorScaleChk.checked !== false : true);
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
        const shouldColorize = colorScalingEnabled && marker._isVtu;
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
              weight: MARKER_STROKE_WEIGHT,
              color: MARKER_STROKE_COLOR,
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

      // Sliders fire 'input' many times per second while dragging. applyFilters() walks
      // every building/block/landlord row, so calling it synchronously per event is what
      // makes dragging a filter slider feel sluggish. Coalesce to at most once per
      // animation frame instead — the label text still updates immediately below, only
      // the expensive full-row-scan pass gets throttled.
      let applyFiltersScheduled = false;
      function scheduleApplyFilters() {
        if (applyFiltersScheduled) return;
        applyFiltersScheduled = true;
        window.requestAnimationFrame(function() {
          applyFiltersScheduled = false;
          applyFilters();
        });
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
          scheduleApplyFilters();
        };
      }

      // Renders one Craigslist-style histogram + dual-handle range slider control
      // into `container` and returns its bookkeeping object for metricControls[metric].
      // Shared by the Buildings section's metrics and the Membership section's
      // membership-year metric — same look and threshold-filtering behavior,
      // just rendered into different containers so they show up in different
      // parts of the sidebar.
      function renderMetricControl(container, metric, summary) {
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

          const ctrl = {
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
          return ctrl;
      }

      function buildMetricControls() {
        Object.keys(metricControls).forEach(function(key) { delete metricControls[key]; });
        metricKeys = [];

        const buildingContainer = document.getElementById('filter-building-section');
        if (buildingContainer && filterConfig.building_metrics) {
          buildingContainer.innerHTML = '';
          const order = filterConfig.building_metric_order || Object.keys(filterConfig.building_metrics);
          order.forEach(function(metric) {
            const summary = filterConfig.building_metrics[metric];
            if (!summary) return;
            metricControls[metric] = renderMetricControl(buildingContainer, metric, summary);
          });
        }

        const membershipContainer = document.getElementById('filter-membership-year-section');
        if (membershipContainer && filterConfig.membership_year_metric) {
          membershipContainer.innerHTML = '';
          metricControls['latest_membership_year'] = renderMetricControl(
            membershipContainer, 'latest_membership_year', filterConfig.membership_year_metric
          );
        }

        metricKeys = Object.keys(metricControls);
        metricKeys.forEach(updateMetricLabels);
      }

      buildMetricControls();
      updateDatasetStatus();
      updateLegendVisibility();

      function applyFilters() {
        metricKeys.forEach(updateMetricLabels);
        const searchTerm = tableSearchInput ? tableSearchInput.value.trim().toLowerCase() : '';
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
        const visibleBids = new Set();
        buildingRows.forEach(function(row) {
          const bid = row.getAttribute('data-bid');
          const marker = window.buildingIndex[bid];

          let matches = true;
          const rowArea = (row.getAttribute('data-area') || '').toLowerCase().trim();
          if (restrictHoods) {
            matches = matches && selectedHoods.includes(rowArea);
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
          const checkbox = row.__checkbox;
          if (!matches) {
            if (checkbox && checkbox.checked) {
              const current = marker ? (marker._selectionRefs || 0) : 0;
              checkbox.checked = false;
              if (marker && current > 0) adjustMarkerSelection(marker, -current);
            }
          }

          const wasFiltered = marker ? marker._isFiltered : null;
          setMarkerVisibility(marker, matches);
          // updateMarkerColorAppearance() re-applies color via another setStyle
          // call — only worth doing when this tick actually flipped the marker's
          // filtered state (global color-scaling toggles are handled separately
          // by applyVtuColorScaling(), which loops explicitly).
          if (marker && wasFiltered !== marker._isFiltered) {
            updateMarkerColorAppearance(marker);
          }

          if (matches) {
            visibleBids.add(String(bid));
          }
        });

        const hideEmptyBlocks = hideEmptyBlocksChk ? hideEmptyBlocksChk.checked : false;
        Object.keys(window.blocksIndex).forEach(function(blockId) {
          var ids = window.blockBuildingIndex[blockId] || [];
          var isEmpty = ids.length === 0;
          var row = blockRowById[blockId];
          var shouldHide;
          if (isEmpty) {
            // Empty blocks have no buildings to derive visibility from, so the
            // neighbourhood filter has to be checked against the block's own
            // local_area (data-area) directly, not via visibleBids.
            var blockArea = row ? (row.getAttribute('data-area') || '').toLowerCase().trim() : '';
            var hoodMatch = true;
            if (restrictHoods) {
              hoodMatch = selectedHoods.includes(blockArea);
            } else if (hideWhenNone) {
              hoodMatch = false;
            }
            shouldHide = hideEmptyBlocks || !hoodMatch;
          } else {
            var hasVisible = ids.some(function(id) { return visibleBids.has(String(id)); });
            shouldHide = !hasVisible;
          }
          var layer = window.blocksIndex[blockId];
          if (row) {
            row.classList.toggle('hidden', shouldHide);
            const checkbox = row.__checkbox;
            if (shouldHide && checkbox && checkbox.checked) {
              checkbox.checked = false;
              if (layer) layer._selectionRefs = 0;
              setBlockSelectionMarkers(blockId, false);
            }
            updateGroupRowValues(row, ids, function(id) { return window.buildingIndex[id]; });
          }
          setBlockFiltered(blockId, shouldHide);
        });

        // Was a per-row `document.querySelector('...:not(.hidden)')` CSS scan over all
        // building rows for every one of ~1,500 landlords — O(landlords x buildings) via
        // the selector engine, on every slider tick. window.ownerIndex (built once at
        // load) plus the marker._isFiltered flag set just above give the same answer as
        // a plain array check with no DOM/CSS involved.
        landlordRows.forEach(function(row) {
          var owner = row.getAttribute('data-owner');
          var markers = window.ownerIndex[owner] || [];
          var hasVisible = markers.some(function(m) { return !m._isFiltered; });
          row.classList.toggle('hidden', !hasVisible);
          const checkbox = row.__checkbox;
          if (!hasVisible && checkbox && checkbox.checked) {
            checkbox.checked = false;
            setOwnerSelection(owner, false);
          }
          updateGroupRowValues(row, markers);
        });

        neighbourhoodRows.forEach(function(row) {
          var hoodKey = (row.getAttribute('data-area') || '').toLowerCase().trim();
          var markers = window.hoodIndex[hoodKey] || [];
          var hasVisible = markers.some(function(m) { return !m._isFiltered; });
          row.classList.toggle('hidden', !hasVisible);
          const checkbox = row.__checkbox;
          if (!hasVisible && checkbox && checkbox.checked) {
            checkbox.checked = false;
            setHoodSelection(hoodKey, false);
          }
          updateGroupRowValues(row, markers);
        });

        updateDatasetStatus();
        updateMapStatus();
        updateSummaryBar();
        updateGroupTableSummaries();
      }

      if (hideEmptyBlocksChk) hideEmptyBlocksChk.addEventListener('change', applyFilters);
      if (tableSearchInput) tableSearchInput.addEventListener('input', scheduleApplyFilters);
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

      if (showBuildingsChk) {
        toggleLayerVisibility(layerVTU, showBuildingsChk.checked !== false);
        toggleLayerVisibility(layerNon, showBuildingsChk.checked !== false);
        showBuildingsChk.addEventListener('change', function() {
          toggleLayerVisibility(layerVTU, showBuildingsChk.checked !== false);
          toggleLayerVisibility(layerNon, showBuildingsChk.checked !== false);
          updateLegendVisibility();
        });
      } else {
        toggleLayerVisibility(layerVTU, true);
        toggleLayerVisibility(layerNon, true);
      }
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
      if (vizBlocksChk) {
        toggleLayerVisibility(layerBlocks, vizBlocksChk.checked !== false);
        vizBlocksChk.addEventListener('change', function() {
          toggleLayerVisibility(layerBlocks, vizBlocksChk.checked);
          if (vizBlocksChk.checked) sendBlocksToBack();
          updateLegendVisibility();
        });
      } else {
        toggleLayerVisibility(layerBlocks, true);
      }
      if (vizNeighbourhoodsChk) {
        toggleLayerVisibility(layerNeighbourhoods, vizNeighbourhoodsChk.checked !== false);
        vizNeighbourhoodsChk.addEventListener('change', function() {
          toggleLayerVisibility(layerNeighbourhoods, vizNeighbourhoodsChk.checked);
        });
      } else {
        toggleLayerVisibility(layerNeighbourhoods, true);
      }

      if (resetBtn) {
        resetBtn.addEventListener('click', function() {
          if (hideEmptyBlocksChk) hideEmptyBlocksChk.checked = false;
          hoodInputs.forEach(function(inp) { inp.checked = true; });
          if (colorScaleChk) {
            colorScaleChk.checked = true;
            applyVtuColorScaling(true);
          }
          if (colorBlocksChk) {
            colorBlocksChk.checked = true;
            applyBlockColorScaling(true);
          }
          if (showBuildingsChk) {
            showBuildingsChk.checked = true;
            toggleLayerVisibility(layerVTU, true);
            toggleLayerVisibility(layerNon, true);
          }
          if (vizBlocksChk) {
            vizBlocksChk.checked = true;
            toggleLayerVisibility(layerBlocks, true);
            sendBlocksToBack();
          }
          if (vizNeighbourhoodsChk) {
            vizNeighbourhoodsChk.checked = true;
            toggleLayerVisibility(layerNeighbourhoods, true);
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

      // "Currently visible" matches exactly what computeMapSummary() already counts
      // for the sidebar's "In view" stats row: passes the active filters, on the map
      // layer, and within the current pan/zoom bounds — not just the filter state.
      function collectVisibleBuildingIds() {
        const ids = [];
        if (!mapInstance || typeof mapInstance.getBounds !== 'function') return ids;
        const bounds = mapInstance.getBounds();
        Object.keys(window.buildingIndex).forEach(function(key) {
          const marker = window.buildingIndex[key];
          if (!marker || marker._isFiltered) return;
          if (typeof mapInstance.hasLayer === 'function' && !mapInstance.hasLayer(marker)) return;
          if (typeof marker.getLatLng !== 'function') return;
          const latLng = marker.getLatLng();
          if (!latLng || typeof bounds.contains !== 'function' || !bounds.contains(latLng)) return;
          ids.push(key);
        });
        return ids;
      }

      function exportVisibleBuildingsCsv() {
        const ids = collectVisibleBuildingIds();
        if (!ids.length) {
          window.alert('No buildings are currently visible to export.');
          return;
        }
        const columns = buildingColumnOrder.length
          ? buildingColumnOrder
          : Object.keys(buildingRecords[ids[0]] || {});
        const lines = [columns.map(escapeCSV).join(',')];
        ids.forEach(function(id) {
          const record = buildingRecords[id] || {};
          lines.push(columns.map(function(col) { return escapeCSV(record[col]); }).join(','));
        });
        const blob = new Blob([lines.join('\r\n')], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        const timestamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
        link.href = url;
        link.download = 'buildings-visible-' + timestamp + '.csv';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
      }

      const exportVisibleBtn = document.getElementById('export-visible-csv');
      if (exportVisibleBtn) {
        exportVisibleBtn.addEventListener('click', exportVisibleBuildingsCsv);
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
