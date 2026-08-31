/* Interface profissional do editor 3D.
 *
 * Este módulo só coordena interação e visibilidade. Geometria e modulação
 * continuam no script principal/servidor Python; nenhuma regra estrutural
 * vive aqui.
 */
(function () {
  'use strict';

  const state = {
    activeTool: 'select',
    realtime: true,
    isolatedWallId: null,
    connectedWallIds: null,
    hiddenWallIds: new Set(),
    hiddenOpeningIds: new Set(),
    wallDisplay: 'all',
    hoverObject: null,
    hoverColors: null,
    measureStart: null,
  };

  window.editorRealtimeEnabled = true;
  window.editorSnapCm = 1;

  const byId = id => document.getElementById(id);
  const asString = value => String(value == null ? '' : value);
  const wallIds = wall => {
    const values = [wall && wall.id, wall && wall.element_id, wall && wall.wall_group_id]
      .concat((wall && wall.source_wall_ids) || []);
    return new Set(values.map(asString).filter(Boolean));
  };
  const openingWallIds = opening => new Set([
    opening && opening.wall_id, opening && opening.wall_group_id, opening && opening.host_wall_id,
  ].map(asString).filter(Boolean));
  const candidateWallIds = candidate => new Set([
    candidate && candidate.wall_id,
    ...((candidate && candidate.primary_source_wall_ids) || []),
    ...((candidate && candidate.secondary_source_wall_ids) || []),
  ].map(asString).filter(Boolean));

  function intersects(left, right) {
    for (const value of left) if (right.has(value)) return true;
    return false;
  }

  function currentWall() {
    if (selectedWallId) {
      const direct = currentWalls.find(wall => wallIds(wall).has(asString(selectedWallId)));
      if (direct) return direct;
    }
    if (selectedOpeningId) {
      const opening = currentOpenings.find(item => asString(item.element_id) === asString(selectedOpeningId));
      if (opening) return currentWalls.find(wall => intersects(wallIds(wall), openingWallIds(opening))) || null;
    }
    if (state.isolatedWallId) return currentWalls.find(wall => wallIds(wall).has(state.isolatedWallId)) || null;
    return null;
  }

  function setPanelOpen(panel, open) {
    if (!panel) return;
    panel.classList.toggle('open', open);
  }

  function updateStatusSelection() {
    const wall = currentWall();
    let selected = 'Nada selecionado';
    if (selectedObject) {
      if (selectedObject.userData.kind === 'wall') selected = `Parede ${selectedObject.userData.wall.id}`;
      else if (selectedObject.userData.kind === 'opening') selected = `Abertura ${selectedObject.userData.opening.element_id}`;
      else if (selectedObject.userData.kind === 'block-instances') selected = 'Bloco estrutural';
      else selected = selectedObject.userData.kind || 'Elemento';
    }
    byId('status-selected').textContent = selected;
    byId('status-wall').textContent = `Parede: ${wall ? wall.id : '—'}`;
  }

  function wallMatchesFilter(wall) {
    const ids = wallIds(wall);
    if ([...ids].some(id => state.hiddenWallIds.has(id))) return false;
    if (state.isolatedWallId && !ids.has(state.isolatedWallId)) return false;
    if (state.connectedWallIds && !intersects(ids, state.connectedWallIds)) return false;
    return true;
  }

  function candidateMatchesFilter(candidate) {
    const ids = candidateWallIds(candidate);
    if (state.isolatedWallId && !ids.has(state.isolatedWallId)) return false;
    if (state.connectedWallIds && !intersects(ids, state.connectedWallIds)) return false;
    if ([...ids].some(id => state.hiddenWallIds.has(id))) return false;
    return true;
  }

  function openingMatchesFilter(opening) {
    if (state.hiddenOpeningIds.has(asString(opening.element_id))) return false;
    const ids = openingWallIds(opening);
    if (state.isolatedWallId && !ids.has(state.isolatedWallId)) return false;
    if (state.connectedWallIds && !intersects(ids, state.connectedWallIds)) return false;
    if ([...ids].some(id => state.hiddenWallIds.has(id))) return false;
    return true;
  }

  window.editorCandidateVisible = candidateMatchesFilter;

  function applyEditorVisibility() {
    const displayMode = byId('display-mode').value;
    const showWalls = state.wallDisplay !== 'blocks' && state.wallDisplay !== 'openings';
    const showBlocks = state.wallDisplay !== 'openings';
    const showOpenings = state.wallDisplay !== 'blocks';
    wallGroup.visible = displayMode !== 'blocks' && displayMode !== 'openings';
    blocksGroup.visible = displayMode !== 'walls' && displayMode !== 'openings';
    openingsGroup.visible = true;
    wallGroup.children.forEach(item => {
      const wall = item.userData.wall;
      if (wall) item.visible = showWalls && wallMatchesFilter(wall)
        && (item.userData.isError ? byId('mode-errors').checked : byId('mode-walls').checked);
    });
    axesGroup.children.forEach(item => {
      item.visible = !item.userData.wall || wallMatchesFilter(item.userData.wall);
    });
    blocksGroup.children.forEach(item => {
      const candidates = item.userData.candidates || [];
      const wall = item.userData.wall;
      const visibleForWall = candidates.length
        ? candidates.some(candidateMatchesFilter)
        : (!wall || wallMatchesFilter(wall));
      item.visible = showBlocks && byId('mode-blocks').checked && visibleForWall;
    });
    openingsGroup.children.forEach(item => {
      const opening = item.userData.opening;
      item.visible = showOpenings && byId('mode-openings').checked
        && (!opening || openingMatchesFilter(opening));
    });
    planGroup.visible = displayMode !== 'structural' && !state.isolatedWallId
      && !state.connectedWallIds && byId('mode-plan').checked;
    requestRender();
  }
  window.applyEditorVisibility = applyEditorVisibility;

  function connectedIdsFor(wall) {
    const result = wallIds(wall);
    const endpoints = [wall.start, wall.end];
    currentWalls.forEach(other => {
      if (other === wall) return;
      const tolerance = Math.max(Number(wall.thickness_cm) || 14, Number(other.thickness_cm) || 14) + 1;
      const touches = endpoints.some(a => [other.start, other.end].some(b => Math.hypot(a[0] - b[0], a[1] - b[1]) <= tolerance));
      if (touches) wallIds(other).forEach(id => result.add(id));
    });
    return result;
  }

  function isolateWall(wall, mode) {
    if (!wall) return;
    state.isolatedWallId = asString(wall.id);
    state.connectedWallIds = null;
    state.wallDisplay = mode || 'all';
    setPanelOpen(byId('wall-inspector'), true);
    updateWallInspector(wall);
    applyEditorVisibility();
    focusOnWallId(wall.id);
    byId('btn-wall-mode').classList.add('active');
    setStatus(`Parede ${wall.id} isolada para inspeção técnica.`);
  }

  function showConnected(wall) {
    if (!wall) return;
    state.isolatedWallId = null;
    state.connectedWallIds = connectedIdsFor(wall);
    state.wallDisplay = 'all';
    applyEditorVisibility();
    setStatus(`Parede ${wall.id} e encontros diretamente conectados visíveis.`);
  }

  function restoreVisibility() {
    state.isolatedWallId = null;
    state.connectedWallIds = null;
    state.hiddenWallIds.clear();
    state.hiddenOpeningIds.clear();
    state.wallDisplay = 'all';
    byId('btn-wall-mode').classList.remove('active');
    applyEditorVisibility();
    setStatus('Visibilidade geral restaurada.');
  }

  function viewWallElevation(wall) {
    if (!wall) return;
    const [x0, y0] = wall.start, [x1, y1] = wall.end;
    const dx = x1 - x0, dy = y1 - y0;
    const length = Math.max(1, Math.hypot(dx, dy));
    const nx = -dy / length, ny = dx / length;
    const height = Number(wall.height_cm) || 280;
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2, cz = (Number(wall.base_z_cm) || 0) + height / 2;
    controls.target.set(cx, cy, cz);
    camera.position.set(cx + nx * Math.max(length, height) * 1.35, cy + ny * Math.max(length, height) * 1.35, cz);
    camera.up.set(0, 0, 1);
    camera.lookAt(controls.target);
    controls.update();
  }

  function selectWallAt(index) {
    if (!currentWalls.length) return;
    const safe = ((index % currentWalls.length) + currentWalls.length) % currentWalls.length;
    const wall = currentWalls[safe];
    const mesh = wallGroup.children.find(item => item.userData.kind === 'wall' && item.userData.wall === wall);
    if (mesh) selectObject(mesh);
    selectedWallId = asString(wall.id);
    isolateWall(wall);
    syncSelectionPanel();
  }

  function navigateWall(delta) {
    const wall = currentWall();
    const index = wall ? currentWalls.indexOf(wall) : -1;
    selectWallAt(index + delta);
  }

  function updateWallInspector(wall) {
    if (!wall) return;
    const ids = wallIds(wall);
    const blocks = currentBlockCandidates.filter(candidate => intersects(candidateWallIds(candidate), ids));
    const openings = currentOpenings.filter(opening => intersects(openingWallIds(opening), ids));
    const courses = new Set(blocks.map(block => Number(block.course_index)).filter(Number.isFinite));
    const status = wall.modulation_status || {};
    byId('wall-inspector-title').textContent = `Parede ${wall.id} · inspeção técnica`;
    byId('wall-inspector-summary').textContent = [
      `Comprimento ${(Number(wall.length_cm) / 100).toFixed(2)} m · Espessura ${Number(wall.thickness_cm).toFixed(1)} cm · Altura ${(Number(wall.height_cm || 0) / 100).toFixed(2)} m`,
      `${blocks.length} blocos · ${courses.size || '—'} fiadas · ${openings.length} aberturas`,
      `Encontros: ${(wall.junctions || []).filter(Boolean).join(' / ') || 'ponta livre'} · Status: ${status.ok === false ? 'ERRO' : 'OK'}`,
      status.reason ? `Diagnóstico: ${status.reason}` : '',
    ].filter(Boolean).join('\n');
  }

  function appendNumericProperties() {
    const panel = byId('selection-panel');
    if (!panel || !selectedObject || panel.querySelector('[data-numeric-properties]')) return;
    if (selectedObject.userData.kind === 'opening') {
      const opening = selectedObject.userData.opening;
      const center = opening.center_cm || [0, 0];
      const height = Number(opening.height_cm) || (Number(opening.head_cm) - Number(opening.sill_cm));
      panel.insertAdjacentHTML('beforeend', `
        <div data-numeric-properties>
          <div class="property-grid">
            <label>X (m)<input id="prop-opening-x" type="number" step="0.01" value="${(center[0] / 100).toFixed(3)}"></label>
            <label>Y (m)<input id="prop-opening-y" type="number" step="0.01" value="${(center[1] / 100).toFixed(3)}"></label>
            <label>Largura (m)<input id="prop-opening-width" type="number" min="0.01" step="0.01" value="${(Number(opening.width_cm) / 100).toFixed(3)}"></label>
            <label>Altura (m)<input id="prop-opening-height" type="number" min="0.01" step="0.01" value="${(height / 100).toFixed(3)}"></label>
            <label>Peitoril (m)<input id="prop-opening-sill" type="number" step="0.01" value="${(Number(opening.sill_cm) / 100).toFixed(3)}"></label>
            <label>Mover no eixo (m)<input id="prop-opening-delta" type="number" step="0.01" value="0"></label>
          </div>
          <div class="property-actions"><button data-apply-opening>Aplicar valores</button><button class="secondary" data-duplicate-opening>Duplicar</button><button class="secondary" data-delete-opening>Excluir</button></div>
        </div>`);
    } else if (selectedObject.userData.kind === 'wall') {
      const wall = selectedObject.userData.wall;
      const dx = wall.end[0] - wall.start[0], dy = wall.end[1] - wall.start[1];
      panel.insertAdjacentHTML('beforeend', `
        <div data-numeric-properties>
          <div class="property-grid">
            <label>Início X (m)<input id="prop-wall-x0" type="number" step="0.01" value="${(wall.start[0] / 100).toFixed(3)}"></label>
            <label>Início Y (m)<input id="prop-wall-y0" type="number" step="0.01" value="${(wall.start[1] / 100).toFixed(3)}"></label>
            <label>Comprimento (m)<input id="prop-wall-length" type="number" min="0.01" step="0.01" value="${(Math.hypot(dx, dy) / 100).toFixed(3)}"></label>
            <label>Direção (°)<input id="prop-wall-angle" type="number" step="1" value="${(Math.atan2(dy, dx) * 180 / Math.PI).toFixed(2)}"></label>
            <label>Espessura (cm)<input id="prop-wall-thickness" type="number" min="1" step="0.1" value="${Number(wall.thickness_cm).toFixed(1)}"></label>
            <label>Altura (m)<input id="prop-wall-height" type="number" min="0.01" step="0.01" value="${(Number(wall.height_cm || 280) / 100).toFixed(3)}"></label>
          </div>
          <div class="property-actions"><button data-apply-wall>Aplicar geometria</button><button class="secondary" data-wall-view>Vista da parede</button></div>
        </div>`);
    }
  }

  async function postEditorAction(endpoint, body, successMessage) {
    if (!currentModelId) return setStatus('Carregue uma captura do Revit para editar.', true);
    const request = ++requestRevision;
    setStatus('Recalculando a região afetada…');
    try {
      const response = await fetch(endpoint, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(Object.assign({
          model_id: currentModelId, base_revision: modelRevision, revision: request,
        }, body)),
      });
      const data = await response.json();
      if (!response.ok) return setStatus((data.edit && data.edit.reason) || data.error || 'Alteração rejeitada.', true);
      renderModulationData(data, { edit: data.edit });
      setStatus(successMessage || 'Alteração aplicada e modulação validada.');
    } catch (error) {
      setStatus('Falha ao aplicar alteração: ' + error, true);
    }
  }

  function numberValue(id, multiplier) {
    return Number(byId(id).value.replace ? byId(id).value.replace(',', '.') : byId(id).value) * (multiplier || 1);
  }

  async function applyOpeningProperties() {
    const opening = selectedObject && selectedObject.userData.opening;
    if (!opening) return;
    const axis = opening.axis_cm || [Math.cos(opening.angle_rad || 0), Math.sin(opening.angle_rad || 0)];
    const delta = numberValue('prop-opening-delta', 100);
    const center = [numberValue('prop-opening-x', 100) + axis[0] * delta, numberValue('prop-opening-y', 100) + axis[1] * delta];
    await postEditorAction('/api/edit-opening', {
      opening_id: opening.element_id, center_cm: center,
      width_cm: numberValue('prop-opening-width', 100),
      height_cm: numberValue('prop-opening-height', 100),
      sill_cm: numberValue('prop-opening-sill', 100),
    }, `Abertura ${opening.element_id} atualizada; parede hospedeira recalculada.`);
  }

  async function applyWallProperties() {
    const wall = selectedObject && selectedObject.userData.wall;
    if (!wall) return;
    const start = [numberValue('prop-wall-x0', 100), numberValue('prop-wall-y0', 100)];
    const length = numberValue('prop-wall-length', 100);
    const angle = numberValue('prop-wall-angle', 1) * Math.PI / 180;
    const end = [start[0] + Math.cos(angle) * length, start[1] + Math.sin(angle) * length];
    await postEditorAction('/api/edit-wall', {
      wall_id: wall.id, start_cm: start, end_cm: end,
      thickness_cm: numberValue('prop-wall-thickness', 1),
      height_cm: numberValue('prop-wall-height', 100),
    }, `Parede ${wall.id} atualizada; dependências recalculadas.`);
  }

  function syncSelectionPanel() {
    updateStatusSelection();
    appendNumericProperties();
    const wall = currentWall();
    if (wall && byId('wall-inspector').classList.contains('open')) updateWallInspector(wall);
  }

  function setTool(tool) {
    state.activeTool = tool;
    document.querySelectorAll('[data-editor-tool]').forEach(button => button.classList.toggle('active', button.dataset.editorTool === tool));
    if (tool === 'move') {
      if (selectedObject && selectedObject.userData.kind === 'opening') beginOpeningEdit();
      else if (selectedObject && selectedObject.userData.kind === 'wall') beginWallEdit('move');
      else setStatus('Selecione uma parede ou abertura antes de mover.', true);
    } else if (tool === 'rotate') {
      if (selectedObject && selectedObject.userData.kind === 'wall') {
        appendNumericProperties();
        byId('prop-wall-angle') && byId('prop-wall-angle').focus();
        setStatus('Informe o ângulo exato da parede no painel de propriedades.');
      } else setStatus('A rotação numérica é aplicada a paredes selecionadas.', true);
    } else if (tool === 'section') {
      setPanelOpen(byId('sidebar'), true);
      byId('section-axis').focus();
      setStatus('Escolha o eixo e a posição do plano de corte.');
    } else if (tool === 'measure') {
      state.measureStart = null;
      setStatus('Medição: clique no primeiro ponto e depois no segundo.');
    }
  }

  function hideSelected() {
    if (!selectedObject) return;
    if (selectedObject.userData.kind === 'wall') wallIds(selectedObject.userData.wall).forEach(id => state.hiddenWallIds.add(id));
    if (selectedObject.userData.kind === 'opening') state.hiddenOpeningIds.add(asString(selectedObject.userData.opening.element_id));
    applyEditorVisibility();
    setStatus('Elemento ocultado temporariamente. Use “Mostrar tudo” para restaurar.');
  }

  function isolateSelected() {
    const wall = currentWall();
    if (wall) isolateWall(wall);
    else setStatus('Selecione uma parede, abertura ou bloco hospedado.', true);
  }

  function clearHover() {
    if (!state.hoverObject || !state.hoverColors) return;
    const materials = Array.isArray(state.hoverObject.material) ? state.hoverObject.material : [state.hoverObject.material];
    materials.forEach((material, index) => {
      if (material && material.color && state.hoverColors[index]) material.color.copy(state.hoverColors[index]);
    });
    state.hoverObject = null;
    state.hoverColors = null;
  }

  function updateHover(event) {
    if (editSession || state.activeTool === 'measure') return;
    const hit = pickObjectAt(event.clientX, event.clientY);
    const object = hit && hit.object;
    if (object === state.hoverObject || object === selectedObject) return;
    clearHover();
    if (!object || !object.material) return requestRender();
    state.hoverObject = object;
    const materials = Array.isArray(object.material) ? object.material : [object.material];
    state.hoverColors = materials.map(material => material.color ? material.color.clone() : null);
    materials.forEach(material => { if (material.color) material.color.lerp(new THREE.Color(0x7cc4ff), .42); });
    requestRender();
  }

  function makeDraggable(panel, handle) {
    let drag = null;
    (handle || panel).addEventListener('pointerdown', event => {
      if (event.button !== 0 || event.target.closest('button,input,select,textarea')) return;
      const rect = panel.getBoundingClientRect();
      drag = { dx: event.clientX - rect.left, dy: event.clientY - rect.top };
      panel.setPointerCapture && panel.setPointerCapture(event.pointerId);
    });
    (handle || panel).addEventListener('pointermove', event => {
      if (!drag) return;
      panel.style.left = Math.max(4, Math.min(window.innerWidth - 80, event.clientX - drag.dx)) + 'px';
      panel.style.top = Math.max(58, Math.min(window.innerHeight - 70, event.clientY - drag.dy)) + 'px';
      panel.style.right = 'auto'; panel.style.bottom = 'auto';
    });
    (handle || panel).addEventListener('pointerup', () => { drag = null; });
  }

  byId('btn-project-panel').addEventListener('click', () => setPanelOpen(byId('sidebar'), !byId('sidebar').classList.contains('open')));
  byId('close-project-panel').addEventListener('click', () => setPanelOpen(byId('sidebar'), false));
  byId('close-wall-inspector').addEventListener('click', () => setPanelOpen(byId('wall-inspector'), false));
  document.querySelectorAll('[data-editor-tool]').forEach(button => button.addEventListener('click', () => setTool(button.dataset.editorTool)));
  byId('btn-realtime').addEventListener('click', () => {
    state.realtime = !state.realtime;
    window.editorRealtimeEnabled = state.realtime;
    byId('btn-realtime').classList.toggle('active', state.realtime);
    setStatus(state.realtime ? 'Modulação em tempo real ativada.' : 'Prévia em tempo real pausada; o cálculo final continua ativo.');
  });
  byId('snap-step').addEventListener('change', event => {
    window.editorSnapCm = Number(event.target.value);
    const label = window.editorSnapCm === 0 ? 'desligado' : window.editorSnapCm < 1
      ? `${window.editorSnapCm * 10} mm` : `${window.editorSnapCm} cm`;
    byId('status-snap').textContent = `Snap: ${label}`;
    byId('status-scale').textContent = `Movimento: ${label}`;
  });
  byId('btn-isolate-selected').addEventListener('click', isolateSelected);
  byId('btn-hide-selected').addEventListener('click', hideSelected);
  byId('btn-show-all').addEventListener('click', restoreVisibility);
  byId('btn-wall-mode').addEventListener('click', () => {
    const wall = currentWall() || currentWalls[0];
    if (wall) isolateWall(wall); else setStatus('Carregue um modelo com paredes.', true);
  });
  byId('wall-previous').addEventListener('click', () => navigateWall(-1));
  byId('wall-next').addEventListener('click', () => navigateWall(1));
  byId('wall-isolate').addEventListener('click', () => isolateWall(currentWall()));
  byId('wall-connected').addEventListener('click', () => showConnected(currentWall()));
  byId('wall-only-blocks').addEventListener('click', () => isolateWall(currentWall(), 'blocks'));
  byId('wall-only-openings').addEventListener('click', () => isolateWall(currentWall(), 'openings'));
  byId('wall-elevation').addEventListener('click', () => viewWallElevation(currentWall()));
  byId('wall-3d').addEventListener('click', () => { isolateWall(currentWall()); setView('iso'); });
  byId('wall-restore').addEventListener('click', restoreVisibility);

  byId('selection-panel').addEventListener('click', event => {
    if (event.target.closest('[data-apply-opening]')) applyOpeningProperties();
    else if (event.target.closest('[data-apply-wall]')) applyWallProperties();
    else if (event.target.closest('[data-wall-view]')) isolateWall(currentWall());
    else if (event.target.closest('[data-duplicate-opening]')) {
      const opening = selectedObject && selectedObject.userData.opening;
      if (opening) postEditorAction('/api/duplicate-opening', { opening_id: opening.element_id, delta_cm: 10 }, 'Abertura duplicada e parede recalculada.');
    } else if (event.target.closest('[data-delete-opening]')) {
      const opening = selectedObject && selectedObject.userData.opening;
      if (opening) postEditorAction('/api/delete-opening', { opening_id: opening.element_id }, 'Abertura removida e parede recalculada.');
    }
  });

  canvasEl.addEventListener('click', event => {
    window.setTimeout(syncSelectionPanel, 0);
    if (state.activeTool === 'measure') {
      const point = worldPointAt(event.clientX, event.clientY);
      if (!point) return;
      if (!state.measureStart) {
        state.measureStart = point.clone();
        setStatus(`Primeiro ponto: X ${(point.x / 100).toFixed(2)} · Y ${(point.y / 100).toFixed(2)} m`);
      } else {
        const distance = point.distanceTo(state.measureStart);
        setStatus(`Medição: ${(distance / 100).toFixed(3)} m (${distance.toFixed(1)} cm).`);
        state.measureStart = null;
      }
    }
  });
  canvasEl.addEventListener('dblclick', event => {
    const hit = pickObjectAt(event.clientX, event.clientY);
    if (hit) { selectObject(hit.object, hit.instanceId); focusSelected(); syncSelectionPanel(); }
  });

  let hoverFrame = null;
  canvasEl.addEventListener('pointermove', event => {
    const point = worldPointAt(event.clientX, event.clientY);
    if (point) byId('status-coordinates').textContent = `X ${(point.x / 100).toFixed(2)} · Y ${(point.y / 100).toFixed(2)} · Z ${(point.z / 100).toFixed(2)} m`;
    if (!hoverFrame) hoverFrame = requestAnimationFrame(() => { hoverFrame = null; updateHover(event); });
  });
  canvasEl.addEventListener('pointerleave', () => { clearHover(); requestRender(); });

  canvasEl.addEventListener('contextmenu', event => {
    const hit = pickObjectAt(event.clientX, event.clientY);
    const menu = byId('element-context-menu');
    if (!hit || hit.object.userData.kind === 'opening') return menu.style.display = 'none';
    selectObject(hit.object, hit.instanceId);
    syncSelectionPanel();
    const rect = viewport.getBoundingClientRect();
    menu.style.left = Math.max(8, Math.min(rect.width - 230, event.clientX - rect.left)) + 'px';
    menu.style.top = Math.max(58, Math.min(rect.height - 240, event.clientY - rect.top)) + 'px';
    menu.style.display = 'block';
  });
  byId('element-context-menu').addEventListener('click', event => {
    const action = event.target.closest('[data-context-action]');
    if (!action) return;
    byId('element-context-menu').style.display = 'none';
    if (action.dataset.contextAction === 'move') setTool('move');
    else if (action.dataset.contextAction === 'isolate') isolateSelected();
    else if (action.dataset.contextAction === 'wall-view') isolateWall(currentWall());
    else if (action.dataset.contextAction === 'diagnostic') { byId('display-mode').value = 'diagnostic'; applyDisplayMode(); }
    else if (action.dataset.contextAction === 'hide') hideSelected();
  });

  document.addEventListener('click', event => {
    if (!event.target.closest('#element-context-menu') && !event.target.closest('canvas')) byId('element-context-menu').style.display = 'none';
  });
  byId('course-filter').addEventListener('change', event => {
    byId('status-course').textContent = event.target.value === '' ? 'Fiada: Todas' : `Fiada: ${Number(event.target.value) + 1}`;
    window.setTimeout(applyEditorVisibility, 0);
  });

  window.addEventListener('editor:model-rendered', () => {
    if (state.isolatedWallId || state.connectedWallIds || state.hiddenWallIds.size || state.hiddenOpeningIds.size) applyEditorVisibility();
    updateStatusSelection();
    const wall = currentWall();
    if (wall && byId('wall-inspector').classList.contains('open')) updateWallInspector(wall);
  });

  makeDraggable(byId('selection-panel'), byId('selection-panel'));
  makeDraggable(byId('wall-inspector'), byId('wall-inspector').querySelector('.panel-titlebar'));
  const toolbar = byId('top-toolbar');
  const syncToolbarHeight = () => {
    document.documentElement.style.setProperty('--topbar-height', `${toolbar.offsetHeight}px`);
  };
  new ResizeObserver(syncToolbarHeight).observe(toolbar);
  syncToolbarHeight();
  setPanelOpen(byId('sidebar'), false);
  updateStatusSelection();
})();
