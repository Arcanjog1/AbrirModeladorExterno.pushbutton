/* Shell BIM profissional do editor 3D.
 *
 * Este módulo cuida exclusivamente de apresentação e interação. A geometria
 * estrutural, a validação e a escolha dos blocos permanecem no solver Python.
 */
(function () {
  'use strict';

  const state = {
    activeTool: 'select',
    navigationTool: 'select',
    realtime: true,
    isolatedWallId: null,
    connectedWallIds: null,
    hiddenWallIds: new Set(),
    hiddenOpeningIds: new Set(),
    wallDisplay: 'all',
    highlightBlockCode: null,
    hoverObject: null,
    hoverInstanceId: null,
    hoverColors: null,
    measureStart: null,
    courseLabels: false,
    orthographicLike: false,
    shadows: false,
    activeEditorRequest: null,
    sectionDrag: null,
    sectionHover: null,
    sectionUndo: [],
    sectionRedo: [],
    sectionInverted: false,
    importStep: 1,
    multiSelection: [],
    additiveSelection: false,
    performance: {},
    dragFps: null,
    fpsActive: false,
    dependencyGraph: null,
    proposals: [],
    proposalPreviewId: null,
    proposalRequest: null,
  };

  window.editorRealtimeEnabled = true;
  window.editorSnapCm = 1;

  const byId = id => document.getElementById(id);
  const asString = value => String(value == null ? '' : value);
  const editorGizmoGroup = new THREE.Group();
  const hoverOverlayGroup = new THREE.Group();
  const courseLabelsGroup = new THREE.Group();
  const sectionVisualGroup = new THREE.Group();
  const previewFeedbackGroup = new THREE.Group();
  const diagnosticMarkersGroup = new THREE.Group();
  const directManipulationPreviewGroup = new THREE.Group();
  const multiSelectionGroup = new THREE.Group();
  [editorGizmoGroup, hoverOverlayGroup, courseLabelsGroup, sectionVisualGroup,
    previewFeedbackGroup, diagnosticMarkersGroup, directManipulationPreviewGroup, multiSelectionGroup].forEach(group => {
    group.userData.editorOverlay = true;
    scene.add(group);
  });

  const iconPaths = {
    project: '<path d="M3 6.5h7l2 2h9v9.5H3z"/><path d="M3 6.5V4h7l2 2.5"/>',
    select: '<path d="m5 3 12 10-6 .8-2.8 5.2z"/>',
    move: '<path d="M12 2v20M2 12h20"/><path d="m12 2-3 3m3-3 3 3M22 12l-3-3m3 3-3 3M12 22l-3-3m3 3 3-3M2 12l3-3m-3 3 3 3"/>',
    rotate: '<path d="M20 7v5h-5"/><path d="M18.5 16a8 8 0 1 1 .7-8.5L20 12"/>',
    measure: '<path d="m4 17 13-13 3 3L7 20z"/><path d="m10 11 3 3m0-6 3 3M7 14l3 3"/>',
    section: '<path d="M4 5h16v14H4z"/><path d="M2 12h20"/><path d="m9 9 3 3-3 3"/>',
    wall: '<path d="M3 5h18v14H3z"/><path d="M8 5v14m8-14v14"/>',
    isolate: '<path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z"/><circle cx="12" cy="12" r="2.5"/>',
    hide: '<path d="M3 3l18 18"/><path d="M10.6 6.2A11 11 0 0 1 12 6c6.5 0 10 6 10 6a17 17 0 0 1-3 3.8M6.2 6.2C3.5 8 2 12 2 12s3.5 6 10 6a10 10 0 0 0 3.8-.7"/>',
    show: '<path d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z"/>',
    diagnostic: '<path d="M12 3 2.5 20h19z"/><path d="M12 9v5m0 3h.01"/>',
    top: '<path d="m4 8 8-4 8 4-8 4z"/><path d="m4 12 8 4 8-4m-16 4 8 4 8-4"/>',
    front: '<path d="M4 4h16v16H4z"/><path d="M4 9h16m-8-5v16"/>',
    side: '<path d="m5 5 9-2 5 3v13l-9 2-5-3z"/><path d="m14 3v13l5 3"/>',
    iso: '<path d="m12 2 9 5v10l-9 5-9-5V7z"/><path d="m3 7 9 5 9-5m-9 5v10"/>',
    extents: '<path d="M8 3H3v5m13-5h5v5M8 21H3v-5m13 5h5v-5"/>',
    undo: '<path d="M9 7 4 12l5 5"/><path d="M5 12h8a6 6 0 0 1 6 6"/>',
    redo: '<path d="m15 7 5 5-5 5"/><path d="M19 12h-8a6 6 0 0 0-6 6"/>',
    focus: '<circle cx="12" cy="12" r="3"/><path d="M4 9V4h5m6 0h5v5m0 6v5h-5m-6 0H4v-5"/>',
    home: '<path d="m3 11 9-8 9 8"/><path d="M5 10v10h14V10m-9 10v-6h4v6"/>',
    cancel: '<path d="M5 5l14 14M19 5 5 19"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m16 16 5 5"/>',
    command: '<path d="m5 7 5 5-5 5m8 0h6"/>',
    theme: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5M17.5 17.5 19 19M19 5l-1.5 1.5M6.5 17.5 5 19"/>',
    orbit: '<circle cx="12" cy="12" r="3"/><path d="M4 12c0-5 3.6-9 8-9 3.3 0 6.2 2.2 7.4 5.2M20 12c0 5-3.6 9-8 9-3.3 0-6.2-2.2-7.4-5.2"/><path d="m18 4 2 4-4 .5M6 20l-2-4 4-.5"/>',
    pan: '<path d="M8 11V6a2 2 0 0 1 4 0v4-6a2 2 0 0 1 4 0v7-4a2 2 0 0 1 4 0v7c0 5-3 8-8 8-4 0-6-2-8-6l-2-4a2 2 0 0 1 3-2z"/>',
    zoom: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m15.5 15.5 5 5M7.5 10.5h6m-3-3v6"/>',
  };

  function svgIcon(name) {
    return `<svg class="tool-icon" viewBox="0 0 24 24" aria-hidden="true">${iconPaths[name] || iconPaths.command}</svg>`;
  }

  function decorateButton(button, icon) {
    if (!button || button.classList.contains('icon-button')) return;
    const label = button.textContent.trim();
    button.innerHTML = `${svgIcon(icon)}<span class="tool-label">${label}</span>`;
    button.classList.add('icon-button');
    if (!button.title) button.title = label;
    button.setAttribute('aria-label', button.title || label);
  }

  function decorateToolbars() {
    const idIcons = {
      'btn-project-panel': 'project', 'btn-wall-mode': 'wall', 'btn-proposals': 'diagnostic', 'btn-isolate-selected': 'isolate',
      'btn-hide-selected': 'hide', 'btn-show-all': 'show', 'btn-diagnostic-mode': 'diagnostic',
      'view-top': 'top', 'view-front': 'front', 'view-side': 'side', 'view-iso': 'iso',
      'view-extents': 'extents', 'btn-undo': 'undo', 'btn-redo': 'redo', 'view-selected': 'focus',
      'view-reset': 'home', 'btn-cancel-action': 'cancel', 'btn-search': 'search',
      'btn-command-palette': 'command', 'btn-theme': 'theme',
    };
    Object.entries(idIcons).forEach(([id, icon]) => decorateButton(byId(id), icon));
    document.querySelectorAll('[data-editor-tool]').forEach(button => decorateButton(button, {
      select: 'select', move: 'move', rotate: 'rotate', measure: 'measure', section: 'section',
    }[button.dataset.editorTool]));
    document.querySelectorAll('[data-nav-tool]').forEach(button => decorateButton(button, button.dataset.navTool));
    document.querySelectorAll('[data-nav-action]').forEach(button => decorateButton(button, {
      extents: 'extents', selection: 'focus', home: 'home',
    }[button.dataset.navAction]));
  }

  function wallIds(wall) {
    const values = [wall && wall.id, wall && wall.element_id, wall && wall.wall_group_id]
      .concat((wall && wall.source_wall_ids) || []);
    return new Set(values.map(asString).filter(Boolean));
  }

  function openingWallIds(opening) {
    return new Set([opening && opening.wall_id, opening && opening.wall_group_id,
      opening && opening.host_wall_id].map(asString).filter(Boolean));
  }

  function candidateWallIds(candidate) {
    return new Set([candidate && candidate.wall_id]
      .concat((candidate && candidate.source_wall_ids) || [])
      .concat((candidate && candidate.primary_source_wall_ids) || [])
      .concat((candidate && candidate.secondary_source_wall_ids) || [])
      .map(asString).filter(Boolean));
  }

  function intersects(left, right) {
    for (const value of left) if (right.has(value)) return true;
    return false;
  }

  function selectedBlock() {
    if (!selectedObject || selectedObject.userData.kind !== 'block-instances') return null;
    const index = selectedObject.userData.selectedInstanceId;
    const entry = selectedObject.userData.instances && selectedObject.userData.instances[index];
    return entry && entry.candidate || null;
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
    const block = selectedBlock();
    if (block) return currentWalls.find(wall => intersects(wallIds(wall), candidateWallIds(block))) || null;
    if (state.isolatedWallId) return currentWalls.find(wall => wallIds(wall).has(state.isolatedWallId)) || null;
    return null;
  }

  function clearThreeGroup(group) {
    while (group.children.length) {
      const child = group.children.pop();
      child.traverse(item => {
        if (item.geometry) item.geometry.dispose();
        const materials = Array.isArray(item.material) ? item.material : [item.material];
        materials.filter(Boolean).forEach(material => {
          if (material.map) material.map.dispose();
          material.dispose();
        });
      });
    }
  }

  function selectionKey(object, instanceId) {
    return `${object && object.uuid || 'none'}:${instanceId == null ? '-' : instanceId}`;
  }

  function renderMultiSelection() {
    clearThreeGroup(multiSelectionGroup);
    if (state.multiSelection.length < 2) return;
    state.multiSelection.forEach(item => {
      const object = item.object;
      if (!object || !object.parent) return;
      if (object.isInstancedMesh && item.instanceId != null) {
        const edges = new THREE.EdgesGeometry(object.geometry);
        const outline = new THREE.LineSegments(edges, new THREE.LineBasicMaterial({ color: 0x3b82f6, depthTest: false }));
        const matrix = new THREE.Matrix4();
        object.getMatrixAt(item.instanceId, matrix);
        matrix.decompose(outline.position, outline.quaternion, outline.scale);
        outline.renderOrder = 120;
        multiSelectionGroup.add(outline);
      } else {
        const outline = new THREE.BoxHelper(object, 0x3b82f6);
        outline.material.depthTest = false;
        outline.renderOrder = 120;
        multiSelectionGroup.add(outline);
      }
    });
  }

  function multiSelectionLabel(item) {
    const data = item.object && item.object.userData || {};
    if (data.kind === 'wall') return `Parede ${data.wall && data.wall.id || '—'}`;
    if (data.kind === 'opening') return `Abertura ${data.opening && data.opening.element_id || '—'}`;
    if (data.kind === 'block-instances') {
      const entry = data.instances && data.instances[item.instanceId];
      const block = entry && entry.candidate;
      return block && (block.type_name || `Bloco ${block.logical_code}`) || 'Bloco';
    }
    return data.kind === 'entity' ? 'Entidade DXF' : 'Elemento';
  }

  function renderMultiSelectionPanel() {
    if (state.multiSelection.length < 2) return;
    const panel = byId('selection-panel');
    panel.classList.remove('manual-hidden');
    panel.innerHTML = `<div class="sel-title">${state.multiSelection.length} elementos selecionados</div>`
      + '<div class="sel-row">Seleção múltipla · Ctrl+clique para adicionar ou remover.</div>'
      + state.multiSelection.slice(0, 12).map(item => `<div class="sel-row multi-selection-row">${multiSelectionLabel(item)}</div>`).join('')
      + (state.multiSelection.length > 12 ? `<div class="sel-row">+ ${state.multiSelection.length - 12} elemento(s)</div>` : '');
    decorateSelectionPanel();
    byId('selection-breadcrumb').textContent = `Projeto  ›  ${state.multiSelection.length} elementos`;
    byId('status-selected').textContent = `${state.multiSelection.length} elementos selecionados`;
  }

  function handleSelectionChanged(detail) {
    const object = detail && detail.object;
    if (!object) {
      window.setTimeout(() => {
        if (!selectedObject && !state.additiveSelection) {
          state.multiSelection = [];
          clearThreeGroup(multiSelectionGroup);
        }
      }, 0);
      return;
    }
    const item = { object, instanceId: detail.instanceId, key: selectionKey(object, detail.instanceId) };
    if (state.additiveSelection) {
      const index = state.multiSelection.findIndex(entry => entry.key === item.key);
      if (index >= 0) state.multiSelection.splice(index, 1);
      else state.multiSelection.push(item);
    } else state.multiSelection = [item];
    renderMultiSelection();
    window.setTimeout(() => {
      if (state.multiSelection.length > 1) renderMultiSelectionPanel();
      requestRender();
    }, 0);
  }

  function setPanelOpen(panel, open) {
    if (!panel) return;
    if (panel.id === 'selection-panel') {
      panel.classList.toggle('manual-hidden', !open);
      return;
    }
    panel.classList.toggle('open', open);
  }

  function closePopovers(except) {
    document.querySelectorAll('.editor-popover.open').forEach(popover => {
      if (!except || popover.id !== except) popover.classList.remove('open');
    });
  }

  function togglePopover(id) {
    const popover = byId(id);
    if (!popover) return;
    const open = !popover.classList.contains('open');
    closePopovers(id);
    popover.classList.toggle('open', open);
  }

  function setImportStep(step) {
    state.importStep = Math.max(1, Math.min(4, Number(step) || 1));
    document.querySelectorAll('[data-import-step]').forEach(item => item.classList.toggle('active', Number(item.dataset.importStep) === state.importStep));
    document.querySelectorAll('[data-import-progress]').forEach(item => {
      const itemStep = Number(item.dataset.importProgress);
      item.classList.toggle('active', itemStep === state.importStep);
      item.classList.toggle('done', itemStep < state.importStep);
    });
    byId('btn-import-back').disabled = state.importStep === 1;
    byId('btn-import-next').textContent = state.importStep === 4 ? 'Gerar modulação' : 'Continuar';
  }

  function openWorkspaceSection(name, options) {
    const sectionName = name || 'import';
    document.querySelectorAll('[data-workspace-tab]').forEach(tab => {
      const active = tab.dataset.workspaceTab === sectionName;
      tab.classList.toggle('active', active);
      tab.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    document.querySelectorAll('[data-workspace-section]').forEach(section => section.classList.toggle('active', section.dataset.workspaceSection === sectionName));
    setPanelOpen(byId('sidebar'), true);
    if (sectionName === 'import' && options && options.step) setImportStep(options.step);
  }

  function appendDiagnosticLog(message) {
    const log = byId('diagnostics-log');
    if (!log || !message) return;
    const stamp = new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    const lines = log.textContent === 'Aplicação iniciada. Aguardando modelo.' ? [] : log.textContent.split('\n');
    lines.push(`[${stamp}] ${message}`);
    log.textContent = lines.slice(-80).join('\n');
  }

  function metric(value, suffix) {
    return value != null && Number.isFinite(Number(value)) ? `${Number(value).toFixed(1)}${suffix || ''}` : '—';
  }

  function renderPerformance(data) {
    const performanceData = Object.assign({}, state.performance, (data && data.performance_ms) || {});
    state.performance = performanceData;
    const fps = state.dragFps;
    const status = byId('status-performance');
    if (status) {
      status.textContent = `Solver: ${metric(performanceData.solver, 'ms')} · Cena: ${metric(performanceData.scene_update, 'ms')} · FPS: ${metric(fps)}`;
      status.title = 'Medições da última atualização incremental';
    }
    const panel = byId('diagnostics-performance');
    if (!panel) return;
    const cacheState = performanceData.cache_hit ? 'reutilizado' : 'novo cálculo';
    panel.textContent = [
      `Detecção de dependências  ${metric(performanceData.detection, ' ms')}`,
      `Solver canônico          ${metric(performanceData.solver, ' ms')}`,
      `Montagem da resposta     ${metric(performanceData.payload, ' ms')}`,
      `Serialização             ${metric(performanceData.serialization, ' ms')}`,
      `Atualização da cena      ${metric(performanceData.scene_update, ' ms')}`,
      `Tempo total no servidor  ${metric(performanceData.total, ' ms')}`,
      `FPS durante o arraste    ${metric(fps)}`,
      '',
      `Paredes afetadas         ${performanceData.affected_walls ?? '—'}`,
      `Paredes processadas      ${performanceData.processed_walls ?? '—'}`,
      `Fiadas afetadas          ${performanceData.affected_courses ?? '—'}`,
      `Blocos removidos/adicionados  ${performanceData.blocks_removed ?? '—'} / ${performanceData.blocks_added ?? '—'}`,
      `Candidatos no delta      ${performanceData.response_candidates ?? '—'}`,
      `Resposta                 ${Number.isFinite(Number(performanceData.response_bytes)) ? `${(Number(performanceData.response_bytes) / 1024).toFixed(1)} KB` : '—'}`,
      `Cache                    ${cacheState}`,
      `geometryHash             ${performanceData.geometry_hash || '—'}`,
      `modulationHash           ${performanceData.modulation_hash || '—'}`,
    ].join('\n');
  }

  function beginFpsMeasurement() {
    if (state.fpsActive) return;
    state.fpsActive = true;
    let frames = 0;
    let started = performance.now();
    const sample = now => {
      if (!state.fpsActive) return;
      frames += 1;
      const elapsed = now - started;
      if (elapsed >= 400) {
        state.dragFps = Math.round((frames * 1000 / elapsed) * 10) / 10;
        frames = 0;
        started = now;
        renderPerformance();
      }
      requestAnimationFrame(sample);
    };
    requestAnimationFrame(sample);
  }

  function endFpsMeasurement() {
    state.fpsActive = false;
    renderPerformance();
  }

  function openDiagnosticTab(name) {
    const button = byId('diagnostics-panel').querySelector(`[data-diagnostic-tab="${name}"]`);
    if (button) button.click();
  }

  function proposalTarget() {
    const wall = currentWall();
    const opening = selectedObject && selectedObject.userData.kind === 'opening'
      ? selectedObject.userData.opening : null;
    return {
      opening_id: opening && opening.element_id,
      wall_id: wall && wall.id,
    };
  }

  function renderProposalDock() {
    const container = byId('diagnostics-proposals');
    const discard = byId('btn-discard-proposal');
    if (!container || !discard) return;
    discard.disabled = !state.proposalPreviewId;
    container.innerHTML = '';
    if (!state.proposals.length) {
      container.textContent = 'Selecione uma parede ou abertura e gere propostas. Nenhuma alteração é aplicada sem confirmação.';
      return;
    }
    state.proposals.forEach(proposal => {
      const card = document.createElement('article');
      card.className = `proposal-card${proposal.requires_manual_review ? ' manual-review' : ''}`;
      const copy = document.createElement('div');
      const title = document.createElement('strong'); title.textContent = proposal.title;
      const explanation = document.createElement('small'); explanation.textContent = proposal.explanation;
      const meta = document.createElement('div'); meta.className = 'proposal-meta';
      const courses = (proposal.affected_courses || []).map(item => Number(item) + 1).join(', ') || 'todas as fiadas necessárias';
      meta.textContent = `Impacto ${Number(proposal.impact_cm || 0).toFixed(1)} cm · conflitos ${proposal.conflicts_before} → ${proposal.conflicts_after} · fiadas ${courses}`;
      copy.append(title, explanation, meta);
      if (proposal.requires_manual_review) {
        const review = document.createElement('small');
        review.textContent = 'Revisão manual obrigatória: verifique cotas, ambiente e elementos hospedados.';
        copy.append(review);
      }
      const actions = document.createElement('div'); actions.className = 'proposal-actions';
      [['preview', state.proposalPreviewId === proposal.id ? 'Prévia ativa' : 'Ver prévia'], ['apply', 'Aplicar']].forEach(([action, label]) => {
        const button = document.createElement('button'); button.type = 'button';
        button.dataset.proposalAction = action; button.dataset.proposalId = proposal.id;
        button.textContent = label; button.disabled = action === 'preview' && state.proposalPreviewId === proposal.id;
        actions.appendChild(button);
      });
      card.append(copy, actions); container.appendChild(card);
    });
  }

  async function generateProposals(project) {
    if (!currentModelId) return setStatus('Carregue uma captura do Revit para gerar propostas.', true);
    if (state.proposalPreviewId) discardProposalPreview();
    const target = project ? {} : proposalTarget();
    if (!project && !target.wall_id && !target.opening_id) {
      return setStatus('Selecione uma parede, abertura ou bloco antes de gerar propostas.', true);
    }
    if (state.proposalRequest) state.proposalRequest.abort();
    const controller = new AbortController(); state.proposalRequest = controller;
    setPanelOpen(byId('diagnostics-panel'), true); openDiagnosticTab('proposals');
    setStatus(project ? 'Analisando alternativas do projeto…' : 'Simulando propostas para a seleção…');
    try {
      const response = await fetch('/api/proposals', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: controller.signal,
        body: JSON.stringify(Object.assign({ model_id: currentModelId, base_revision: modelRevision, project: Boolean(project) }, target)),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Não foi possível gerar propostas.');
      state.proposals = data.proposals || [];
      renderProposalDock();
      const message = state.proposals.length
        ? `${state.proposals.length} proposta(s) simulada(s); escolha uma prévia.`
        : 'Nenhuma alternativa segura melhorou ou preservou a modulação desta região.';
      setStatus(message, !state.proposals.length); showToast(message, state.proposals.length ? 'ok' : 'warning');
      appendDiagnosticLog(message);
    } catch (error) {
      if (error.name !== 'AbortError') { setStatus(`Falha ao gerar propostas: ${error.message || error}`, true); showToast('Falha ao simular propostas', 'error'); }
    } finally {
      if (state.proposalRequest === controller) state.proposalRequest = null;
    }
  }

  function discardProposalPreview() {
    if (!state.proposalPreviewId) return;
    if (committedViewData) renderModulationData(committedViewData);
    state.proposalPreviewId = null;
    renderProposalDock();
    setStatus('Prévia descartada; o modelo confirmado foi restaurado.');
  }

  async function previewProposal(proposalId) {
    if (!currentModelId) return;
    if (state.proposalPreviewId) discardProposalPreview();
    setStatus('Montando prévia comparativa da proposta…');
    try {
      const response = await fetch('/api/preview-proposal', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model_id: currentModelId, proposal_id: proposalId, base_revision: modelRevision }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Prévia indisponível.');
      renderModulationData(data, { preview: true, edit: data.edit });
      state.proposalPreviewId = proposalId; renderProposalDock();
      setStatus('Prévia ativa: compare os elementos realçados e confirme somente se fizer sentido.');
    } catch (error) {
      setStatus(`Falha na prévia: ${error.message || error}`, true); showToast('Não foi possível mostrar a prévia', 'error');
    }
  }

  async function applyProposal(proposalId) {
    if (!currentModelId) return;
    setStatus('Aplicando proposta e revalidando a modulação…');
    try {
      const response = await fetch('/api/apply-proposal', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model_id: currentModelId, proposal_id: proposalId, base_revision: modelRevision }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'A proposta não foi aplicada.');
      state.proposalPreviewId = null; state.proposals = [];
      renderModulationData(data, { edit: data.edit }); renderProposalDock();
      const message = 'Proposta aplicada e revalidada. Envie ao Revit quando estiver satisfeito com a revisão.';
      setStatus(message); showToast('Proposta aplicada', 'ok'); appendDiagnosticLog(message);
    } catch (error) {
      setStatus(`Falha ao aplicar proposta: ${error.message || error}`, true); showToast('A proposta não foi aplicada', 'error');
    }
  }

  function currentExportPayload() {
    return {
      schema: 'modulador-externo-3d/v1',
      exported_at: new Date().toISOString(),
      project_path: byId('dxf-path').value.trim(),
      model_id: typeof currentModelId === 'undefined' ? null : currentModelId,
      revision: typeof modelRevision === 'undefined' ? null : modelRevision,
      view_data: typeof committedViewData === 'undefined' ? null : committedViewData,
    };
  }

  function downloadExport(payload, suffix) {
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    const project = (byId('project-name').textContent || 'modelo').replace(/\.[^.]+$/, '').replace(/[^a-z0-9_-]+/gi, '-');
    link.href = url; link.download = `${project}-${suffix || 'modulacao'}.json`; link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  }

  function syncVisibilityPopover() {
    byId('quick-display-mode').value = byId('display-mode').value;
    document.querySelectorAll('[data-visibility-toggle]').forEach(button => {
      const source = byId(button.dataset.visibilityToggle);
      button.classList.toggle('active', Boolean(source && source.checked));
      button.setAttribute('aria-pressed', source && source.checked ? 'true' : 'false');
    });
  }

  function showToast(message, kind) {
    if (!message) return;
    const toast = document.createElement('div');
    toast.className = `editor-toast ${kind || ''}`;
    toast.textContent = message;
    byId('toast-stack').appendChild(toast);
    window.setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(3px)';
      window.setTimeout(() => toast.remove(), 150);
    }, kind === 'error' ? 4300 : 2600);
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
    if (state.highlightBlockCode && candidate.logical_code !== state.highlightBlockCode) return false;
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
      item.visible = showBlocks && byId('mode-blocks').checked
        && (!candidates.length || candidates.some(candidateMatchesFilter));
    });
    openingsGroup.children.forEach(item => {
      const opening = item.userData.opening;
      item.visible = showOpenings && byId('mode-openings').checked
        && (!opening || openingMatchesFilter(opening));
    });
    planGroup.visible = displayMode !== 'structural' && !state.isolatedWallId
      && !state.connectedWallIds && byId('mode-plan').checked;
    courseLabelsGroup.visible = state.courseLabels;
    requestRender();
  }
  window.applyEditorVisibility = applyEditorVisibility;

  function selectedCenter() {
    if (!selectedObject) return null;
    if (selectedObject.userData.kind === 'wall') {
      const wall = selectedObject.userData.wall;
      return new THREE.Vector3((wall.start[0] + wall.end[0]) / 2, (wall.start[1] + wall.end[1]) / 2,
        (Number(wall.base_z_cm) || 0) + (Number(wall.height_cm) || 280) / 2);
    }
    if (selectedObject.userData.kind === 'opening') {
      const opening = selectedObject.userData.opening;
      return new THREE.Vector3(opening.center_cm[0], opening.center_cm[1],
        (Number(opening.sill_cm) || 0) + ((Number(opening.head_cm) || 210) - (Number(opening.sill_cm) || 0)) / 2);
    }
    const block = selectedBlock();
    if (block) return new THREE.Vector3(block.origin_cm[0], block.origin_cm[1],
      Number(block.z_cm) + Number(block.height_cm) / 2);
    return selectedObject.position ? selectedObject.position.clone() : null;
  }

  function candidateOverlay(candidate, color, opacity) {
    const geometry = new THREE.BoxGeometry(Math.max(1, candidate.length_cm),
      Math.max(1, candidate.width_cm), Math.max(1, candidate.height_cm));
    const material = new THREE.MeshBasicMaterial({ color, transparent: true, opacity,
      depthWrite: false, wireframe: opacity < .2 });
    const mesh = new THREE.Mesh(geometry, material);
    const xDir = candidate.x_dir || [1, 0];
    mesh.position.set(candidate.origin_cm[0], candidate.origin_cm[1],
      Number(candidate.z_cm) + Number(candidate.height_cm) / 2);
    mesh.rotation.z = Math.atan2(xDir[1], xDir[0]);
    return mesh;
  }

  let queuedDirectPreview = null;
  let directPreviewFrame = null;

  function renderDirectPreview() {
    directPreviewFrame = null;
    const queued = queuedDirectPreview;
    if (!queued) return;
    clearThreeGroup(directManipulationPreviewGroup);
    const session = queued.session;
    const body = queued.computed.body || {};
    let mesh = null;
    if (session.kind === 'wall') {
      const start = body.start_cm || session.wall.start;
      const end = body.end_cm || session.wall.end;
      const dx = end[0] - start[0], dy = end[1] - start[1];
      const length = Math.max(1, Math.hypot(dx, dy));
      const height = Number(session.wall.height_cm || 280);
      mesh = new THREE.Mesh(new THREE.BoxGeometry(length, Number(session.wall.thickness_cm || 14), height),
        new THREE.MeshBasicMaterial({ color: 0x3b82f6, transparent: true, opacity: .28, depthWrite: false }));
      mesh.position.set((start[0] + end[0]) / 2, (start[1] + end[1]) / 2,
        Number(session.wall.base_z_cm || 0) + height / 2);
      mesh.rotation.z = Math.atan2(dy, dx);
    } else {
      const opening = session.opening;
      const center = body.center_cm || opening.center_cm;
      const width = Number(body.width_cm || opening.width_cm || 80);
      const height = Number(body.height_cm || opening.height_cm || (Number(opening.head_cm || 210) - Number(opening.sill_cm || 0)));
      const sill = Number(body.sill_cm == null ? opening.sill_cm || 0 : body.sill_cm);
      mesh = new THREE.Mesh(new THREE.BoxGeometry(width, Number(opening.wall_thickness_cm || 16) + 2, height),
        new THREE.MeshBasicMaterial({ color: 0x3b82f6, transparent: true, opacity: .34, depthWrite: false }));
      mesh.position.set(center[0], center[1], sill + height / 2);
      mesh.rotation.z = Number(opening.angle_rad || 0);
    }
    if (mesh) {
      mesh.userData.editorOverlay = true;
      mesh.renderOrder = 23;
      directManipulationPreviewGroup.add(mesh);
      const outline = new THREE.BoxHelper(mesh, 0x8fc5ff);
      outline.userData.editorOverlay = true;
      outline.material.depthTest = false;
      outline.renderOrder = 24;
      directManipulationPreviewGroup.add(outline);
    }
    const badge = byId('drag-value-badge');
    const rect = viewport.getBoundingClientRect();
    badge.textContent = `${queued.computed.label}${queued.free ? ' · livre' : ''}`;
    badge.style.left = Math.max(56, Math.min(rect.width - 210, queued.clientX - rect.left + 14)) + 'px';
    badge.style.top = Math.max(56, Math.min(rect.height - 68, queued.clientY - rect.top + 14)) + 'px';
    badge.classList.add('open');
    requestRender();
  }

  window.editorUpdateDirectPreview = function (session, computed, clientX, clientY, freeMovement) {
    queuedDirectPreview = { session, computed, clientX, clientY, free: Boolean(freeMovement) };
    if (!directPreviewFrame) directPreviewFrame = requestAnimationFrame(renderDirectPreview);
  };

  window.editorEndDirectPreview = function () {
    queuedDirectPreview = null;
    if (directPreviewFrame) cancelAnimationFrame(directPreviewFrame);
    directPreviewFrame = null;
    clearThreeGroup(directManipulationPreviewGroup);
    byId('drag-value-badge').classList.remove('open');
    requestRender();
  };

  function directHandle(position, color, data, size, geometry) {
    const mesh = new THREE.Mesh(geometry || new THREE.SphereGeometry(size || 6, 18, 12),
      new THREE.MeshBasicMaterial({ color, depthTest: false, transparent: true, opacity: .96 }));
    mesh.position.copy(position);
    mesh.renderOrder = 24;
    mesh.userData.editorDragHandle = data;
    editorGizmoGroup.add(mesh);
    return mesh;
  }

  function updateSelectionGizmo() {
    clearThreeGroup(editorGizmoGroup);
    const center = selectedCenter();
    if (!center || !selectedObject) return;
    const length = Math.max(28, Math.min(70, (lastBounds && lastBounds.span || 400) * .07));
    const kind = selectedObject.userData.kind;
    if (kind === 'wall' || kind === 'opening') {
      const outline = new THREE.BoxHelper(selectedObject, 0x3b82f6);
      outline.material.depthTest = false;
      outline.renderOrder = 20;
      editorGizmoGroup.add(outline);
    }
    if (kind === 'wall') {
      const wall = selectedObject.userData.wall;
      const dx = wall.end[0] - wall.start[0], dy = wall.end[1] - wall.start[1];
      const wallLength = Math.max(1, Math.hypot(dx, dy));
      const axis = new THREE.Vector3(dx / wallLength, dy / wallLength, 0);
      editorGizmoGroup.add(new THREE.ArrowHelper(axis, center, length, 0x3b82f6, 8, 5));
      editorGizmoGroup.add(new THREE.ArrowHelper(axis.clone().negate(), center, length, 0x3b82f6, 8, 5));
      [wall.start, wall.end].forEach((point, index) => {
        directHandle(new THREE.Vector3(point[0], point[1], center.z), 0x3b82f6, {
          kind: 'wall', mode: index ? 'end' : 'start', wallId: asString(wall.id), cursor: 'ew-resize',
        }, 7);
      });
    } else if (kind === 'opening') {
      const opening = selectedObject.userData.opening;
      const sourceAxis = opening.axis_cm || [Math.cos(opening.angle_rad || 0), Math.sin(opening.angle_rad || 0)];
      const axisLength = Math.max(1e-6, Math.hypot(sourceAxis[0], sourceAxis[1]));
      const axis = new THREE.Vector3(sourceAxis[0] / axisLength, sourceAxis[1] / axisLength, 0);
      editorGizmoGroup.add(new THREE.ArrowHelper(axis, center, length, 0x3b82f6, 8, 5));
      editorGizmoGroup.add(new THREE.ArrowHelper(axis.clone().negate(), center, length, 0x3b82f6, 8, 5));
      directHandle(center, 0x3b82f6, {
        kind: 'opening', mode: 'move', openingId: asString(opening.element_id), cursor: 'grab',
      }, 6);
      const halfWidth = Number(opening.width_cm || 80) / 2;
      ['resize-start', 'resize-end'].forEach((mode, index) => {
        const sign = index ? 1 : -1;
        const position = center.clone().add(axis.clone().multiplyScalar(halfWidth * sign));
        directHandle(position, 0xf0b44c, {
          kind: 'opening', mode, openingId: asString(opening.element_id), cursor: 'ew-resize',
        }, 6, new THREE.BoxGeometry(10, 10, 10));
      });
      const openingType = `${opening.type || ''} ${opening.family || ''}`.toLowerCase();
      if (Number(opening.sill_cm || 0) > 0 || /janela|window/.test(openingType)) {
        const zHandle = center.clone().add(new THREE.Vector3(0, 0, Number(opening.height_cm || 100) / 2 + 12));
        editorGizmoGroup.add(new THREE.ArrowHelper(new THREE.Vector3(0, 0, 1), center, length, 0x59bd76, 8, 5));
        directHandle(zHandle, 0x59bd76, {
          kind: 'opening', mode: 'sill', openingId: asString(opening.element_id), cursor: 'ns-resize',
        }, 6, new THREE.BoxGeometry(10, 10, 10));
      }
    } else {
      const block = selectedBlock();
      if (block) {
        const outline = candidateOverlay(block, 0x3b82f6, .12);
        outline.renderOrder = 20;
        editorGizmoGroup.add(outline);
      }
    }
    requestRender();
  }

  const gizmoRaycaster = new THREE.Raycaster();
  const gizmoMouse = new THREE.Vector2();
  window.editorPickDirectHandle = function (clientX, clientY) {
    const rect = canvasEl.getBoundingClientRect();
    gizmoMouse.x = ((clientX - rect.left) / rect.width) * 2 - 1;
    gizmoMouse.y = -((clientY - rect.top) / rect.height) * 2 + 1;
    gizmoRaycaster.setFromCamera(gizmoMouse, camera);
    const hit = gizmoRaycaster.intersectObjects(editorGizmoGroup.children, true)
      .find(item => item.object.userData && item.object.userData.editorDragHandle);
    return hit ? Object.assign({}, hit.object.userData.editorDragHandle) : null;
  };

  function updateQuickEdit() {
    const bar = byId('quick-edit-bar');
    if (!selectedObject || selectedObject.userData.kind !== 'opening') {
      bar.classList.remove('open');
      return;
    }
    const opening = selectedObject.userData.opening;
    const center = selectedCenter();
    const projected = center.clone().project(camera);
    const rect = viewport.getBoundingClientRect();
    const x = (projected.x * .5 + .5) * rect.width;
    const y = (-projected.y * .5 + .5) * rect.height;
    bar.style.left = Math.max(58, Math.min(rect.width - 250, x - 105)) + 'px';
    bar.style.top = Math.max(Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--topbar-height')) + 8,
      Math.min(rect.height - 74, y + 28)) + 'px';
    byId('quick-edit-title').textContent = opening.element_id || 'Abertura';
    byId('quick-edit-size').textContent = `${Number(opening.width_cm || 0).toFixed(0)} × ${Number(opening.height_cm || ((opening.head_cm || 0) - (opening.sill_cm || 0))).toFixed(0)} cm`;
    bar.classList.add('open');
  }

  function updateStatusSelection() {
    const wall = currentWall();
    const breadcrumb = ['Projeto'];
    let selected = 'Nada selecionado';
    let kind = '—';
    let metrics = '—';
    let modulation = '—';
    let alerts = currentWalls.filter(item => item.modulation_status && item.modulation_status.ok === false).length;
    if (selectedObject) {
      if (selectedObject.userData.kind === 'wall') {
        const item = selectedObject.userData.wall;
        selected = `Parede ${item.id}`; kind = item.name || item.layer || 'Parede';
        metrics = `${(Number(item.length_cm) / 100).toFixed(2)}m × ${Number(item.thickness_cm).toFixed(0)}cm`;
        modulation = item.modulation_status && item.modulation_status.ok === false ? 'Erro' : 'Correta';
        alerts = Math.max(alerts, item.modulation_status && item.modulation_status.ok === false ? 1 : 0);
        breadcrumb.push(item.level || 'Pavimento', `Parede ${item.id}`);
      } else if (selectedObject.userData.kind === 'opening') {
        const item = selectedObject.userData.opening;
        selected = `Abertura ${item.element_id}`; kind = item.type || item.family || 'Abertura';
        metrics = `${Number(item.width_cm || 0).toFixed(0)} × ${Number(item.height_cm || ((item.head_cm || 0) - (item.sill_cm || 0))).toFixed(0)}cm`;
        breadcrumb.push(item.level || 'Pavimento', `Parede ${wall ? wall.id : '—'}`, `Abertura ${item.element_id}`);
      } else if (selectedObject.userData.kind === 'block-instances') {
        const block = selectedBlock();
        if (block) {
          selected = block.id || block.logical_code; kind = block.type_name || `Bloco ${block.logical_code}`;
          metrics = `${Number(block.length_cm).toFixed(0)} × ${Number(block.width_cm).toFixed(0)} × ${Number(block.height_cm).toFixed(0)}cm`;
          modulation = `Fiada ${Number(block.course_index) + 1}`;
          alerts = Math.max(alerts, block.is_error ? 1 : 0);
          breadcrumb.push(block.level || 'Pavimento', `Parede ${wall ? wall.id : 'Encontro'}`, `Fiada ${Number(block.course_index) + 1}`, block.id || block.logical_code);
        }
      }
    }
    byId('status-selected').textContent = selected;
    byId('status-kind').textContent = `Tipo: ${kind}`;
    byId('status-wall').textContent = `Parede: ${wall ? wall.id : '—'}`;
    byId('status-metrics').textContent = `Dimensões: ${metrics}`;
    byId('status-modulation').textContent = `Modulação: ${modulation}`;
    byId('status-alerts').textContent = `Alertas: ${alerts}`;
    byId('selection-breadcrumb').textContent = breadcrumb.join('  ›  ');
    updateSelectionGizmo();
    updateQuickEdit();
  }

  function connectedIdsFor(wall) {
    const result = wallIds(wall);
    const endpoints = [wall.start, wall.end];
    currentWalls.forEach(other => {
      if (other === wall) return;
      const tolerance = Math.max(Number(wall.thickness_cm) || 14, Number(other.thickness_cm) || 14) + 1;
      const touches = endpoints.some(a => [other.start, other.end].some(b =>
        Math.hypot(a[0] - b[0], a[1] - b[1]) <= tolerance));
      if (touches) wallIds(other).forEach(id => result.add(id));
    });
    return result;
  }

  function setProjectionMode(orthographicLike) {
    if (state.orthographicLike === orthographicLike) return;
    const direction = camera.position.clone().sub(controls.target);
    const factor = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2))
      / Math.tan(THREE.MathUtils.degToRad((orthographicLike ? 5 : 50) / 2));
    camera.position.copy(controls.target).add(direction.multiplyScalar(factor));
    camera.fov = orthographicLike ? 5 : 50;
    camera.updateProjectionMatrix();
    state.orthographicLike = orthographicLike;
    byId('projection-mode').textContent = orthographicLike ? 'Ortográfica' : 'Perspectiva';
    requestRender();
  }

  function animateCamera(position, target, duration) {
    const fromPosition = camera.position.clone();
    const fromTarget = controls.target.clone();
    const started = performance.now();
    const total = duration || 180;
    function step(now) {
      const raw = Math.min(1, (now - started) / total);
      const t = 1 - Math.pow(1 - raw, 3);
      camera.position.lerpVectors(fromPosition, position, t);
      controls.target.lerpVectors(fromTarget, target, t);
      camera.lookAt(controls.target);
      controls.update();
      if (raw < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  function animateToView(kind) {
    const bounds = lastBounds || { cx: 0, cy: 0, cz: 140, span: 500 };
    const target = new THREE.Vector3(bounds.cx, bounds.cy, bounds.cz);
    const span = bounds.span;
    const positions = {
      top: [bounds.cx, bounds.cy + span * .001, bounds.cz + span * 1.6],
      bottom: [bounds.cx, bounds.cy + span * .001, bounds.cz - span * 1.6],
      front: [bounds.cx, bounds.cy - span * 1.6, bounds.cz],
      back: [bounds.cx, bounds.cy + span * 1.6, bounds.cz],
      side: [bounds.cx - span * 1.6, bounds.cy, bounds.cz],
      left: [bounds.cx - span * 1.6, bounds.cy, bounds.cz],
      right: [bounds.cx + span * 1.6, bounds.cy, bounds.cz],
      iso: [bounds.cx - span * 1.1, bounds.cy - span * 1.1, bounds.cz + span * 1.1],
    };
    const value = positions[kind] || positions.iso;
    camera.up.set(0, 0, 1);
    animateCamera(new THREE.Vector3(...value), target);
  }

  function viewWallElevation(wall, side) {
    if (!wall) return;
    const [x0, y0] = wall.start, [x1, y1] = wall.end;
    const dx = x1 - x0, dy = y1 - y0;
    const length = Math.max(1, Math.hypot(dx, dy));
    const height = Number(wall.height_cm) || 280;
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
    const target = new THREE.Vector3(cx, cy, (Number(wall.base_z_cm) || 0) + height / 2);
    setProjectionMode(true);
    const distance = Math.max(length, height) * 12;
    const direction = side ? new THREE.Vector3(dx / length, dy / length, 0)
      : new THREE.Vector3(-dy / length, dx / length, 0);
    animateCamera(target.clone().add(direction.multiplyScalar(distance)), target, 220);
  }

  function updateWallInspector(wall) {
    if (!wall) return;
    const ids = wallIds(wall);
    const blocks = currentBlockCandidates.filter(candidate => intersects(candidateWallIds(candidate), ids));
    const openings = currentOpenings.filter(opening => intersects(openingWallIds(opening), ids));
    const courses = new Set(blocks.map(block => Number(block.course_index)).filter(Number.isFinite));
    const special = blocks.filter(block => !['B39', 'B54'].includes(block.logical_code));
    const status = wall.modulation_status || {};
    byId('wall-inspector-title').textContent = `←  ${wall.id}  →`;
    byId('wall-inspector-summary').textContent = [
      `${wall.name || wall.layer || 'PAREDE'} ${wall.id}`,
      `Comprimento ${(Number(wall.length_cm) / 100).toFixed(2)}m  ·  Espessura ${Number(wall.thickness_cm).toFixed(1)}cm  ·  Altura ${(Number(wall.height_cm || 0) / 100).toFixed(2)}m`,
      `${courses.size || 0} fiadas  ·  ${blocks.length} blocos  ·  ${openings.length} aberturas  ·  ${special.length} peças especiais`,
      `Encontros ${(wall.junctions || []).filter(Boolean).join(' / ') || 'ponta livre'}  ·  ${status.ok === false ? 'ERRO' : 'MODULAÇÃO CORRETA'}`,
      status.reason || '',
    ].filter(Boolean).join('\n');
  }

  function isolateWall(wall, mode) {
    if (!wall) return;
    state.isolatedWallId = asString(wall.id);
    state.connectedWallIds = null;
    state.wallDisplay = mode || 'all';
    setPanelOpen(byId('wall-inspector'), true);
    updateWallInspector(wall);
    applyEditorVisibility();
    viewWallElevation(wall, false);
    byId('btn-wall-mode').classList.add('active');
    showToast(`Parede ${wall.id} pronta para inspeção`, 'ok');
  }

  function showConnected(wall) {
    if (!wall) return;
    state.isolatedWallId = null;
    state.connectedWallIds = connectedIdsFor(wall);
    state.wallDisplay = 'all';
    applyEditorVisibility();
    showToast(`Dependências da parede ${wall.id} visíveis`);
  }

  function restoreVisibility() {
    state.isolatedWallId = null;
    state.connectedWallIds = null;
    state.hiddenWallIds.clear();
    state.hiddenOpeningIds.clear();
    state.wallDisplay = 'all';
    state.highlightBlockCode = null;
    byId('btn-wall-mode').classList.remove('active');
    setPanelOpen(byId('wall-inspector'), false);
    applyEditorVisibility();
    setProjectionMode(false);
    showToast('Visualização geral restaurada', 'ok');
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
          <div class="property-actions"><button data-apply-opening>Aplicar</button><button data-generate-proposals>Propostas</button><button data-duplicate-opening>Duplicar</button><button data-delete-opening>Excluir</button></div>
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
          <div class="property-actions"><button data-apply-wall>Aplicar</button><button data-generate-proposals>Propostas</button><button data-wall-view>Vista da parede</button></div>
        </div>`);
    }
  }

  function decorateSelectionPanel() {
    const panel = byId('selection-panel');
    if (!panel || !panel.children.length) return;
    panel.classList.remove('manual-hidden');
    if (!panel.querySelector('.panel-window-controls')) {
      panel.insertAdjacentHTML('afterbegin', '<span class="panel-window-controls"><button type="button" data-panel-minimize="selection-panel" title="Recolher">—</button><button type="button" data-panel-dock="selection-panel" title="Encaixar">⇥</button><button type="button" data-panel-close="selection-panel" title="Fechar">×</button></span>');
    }
  }

  async function postEditorAction(endpoint, body, successMessage) {
    if (!currentModelId) return setStatus('Carregue uma captura do Revit para editar.', true);
    if (state.activeEditorRequest) state.activeEditorRequest.abort();
    const controller = new AbortController();
    state.activeEditorRequest = controller;
    const request = ++requestRevision;
    byId('btn-cancel-action').disabled = false;
    setStatus('Atualizando a região afetada…');
    try {
      const response = await fetch(endpoint, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: controller.signal,
        body: JSON.stringify(Object.assign({ model_id: currentModelId,
          base_revision: modelRevision, revision: request }, body)),
      });
      const data = await response.json();
      if (!response.ok) {
        const message = (data.edit && data.edit.reason) || data.error || 'Alteração rejeitada.';
        setStatus(message, true); showToast(message, 'error'); return;
      }
      renderModulationData(data, { edit: data.edit });
      setStatus(successMessage || 'Alteração aplicada.');
      showToast(successMessage || 'Região modulada', 'ok');
    } catch (error) {
      if (error.name !== 'AbortError') { setStatus('Falha ao aplicar alteração: ' + error, true); showToast('Falha ao atualizar o elemento', 'error'); }
    } finally {
      if (state.activeEditorRequest === controller) state.activeEditorRequest = null;
      byId('btn-cancel-action').disabled = !editSession;
    }
  }

  function numberValue(id, multiplier) {
    const input = byId(id);
    return Number(input.value.replace ? input.value.replace(',', '.') : input.value) * (multiplier || 1);
  }

  function shiftOpening(opening, deltaCm) {
    if (!opening) return;
    const axis = opening.axis_cm || [Math.cos(opening.angle_rad || 0), Math.sin(opening.angle_rad || 0)];
    const center = [opening.center_cm[0] + axis[0] * deltaCm, opening.center_cm[1] + axis[1] * deltaCm];
    return postEditorAction('/api/edit-opening', { opening_id: opening.element_id, center_cm: center },
      `Abertura ${opening.element_id} movida ${deltaCm > 0 ? '+' : ''}${deltaCm}cm`);
  }

  function applyOpeningProperties() {
    const opening = selectedObject && selectedObject.userData.opening;
    if (!opening) return;
    const axis = opening.axis_cm || [Math.cos(opening.angle_rad || 0), Math.sin(opening.angle_rad || 0)];
    const delta = numberValue('prop-opening-delta', 100);
    const center = [numberValue('prop-opening-x', 100) + axis[0] * delta,
      numberValue('prop-opening-y', 100) + axis[1] * delta];
    postEditorAction('/api/edit-opening', {
      opening_id: opening.element_id, center_cm: center,
      width_cm: numberValue('prop-opening-width', 100),
      height_cm: numberValue('prop-opening-height', 100), sill_cm: numberValue('prop-opening-sill', 100),
    }, `Abertura ${opening.element_id} atualizada · parede recalculada`);
  }

  function applyWallProperties() {
    const wall = selectedObject && selectedObject.userData.wall;
    if (!wall) return;
    const start = [numberValue('prop-wall-x0', 100), numberValue('prop-wall-y0', 100)];
    const length = numberValue('prop-wall-length', 100);
    const angle = numberValue('prop-wall-angle') * Math.PI / 180;
    const end = [start[0] + Math.cos(angle) * length, start[1] + Math.sin(angle) * length];
    postEditorAction('/api/edit-wall', { wall_id: wall.id, start_cm: start, end_cm: end,
      thickness_cm: numberValue('prop-wall-thickness'), height_cm: numberValue('prop-wall-height', 100) },
    `Parede ${wall.id} atualizada · dependências recalculadas`);
  }

  function recalculateSelectedRegion() {
    const wall = currentWall();
    if (!wall) return setStatus('Selecione uma parede ou elemento hospedado.', true);
    postEditorAction('/api/edit-wall', { wall_id: wall.id, start_cm: wall.start, end_cm: wall.end,
      thickness_cm: wall.thickness_cm, height_cm: wall.height_cm }, `Parede ${wall.id} modulada novamente`);
  }

  function syncSelectionPanel() {
    decorateSelectionPanel();
    appendNumericProperties();
    updateStatusSelection();
    const wall = currentWall();
    if (wall && byId('wall-inspector').classList.contains('open')) updateWallInspector(wall);
  }

  function setNavigationTool(tool) {
    state.navigationTool = tool;
    window.editorNavigationTool = tool;
    document.querySelectorAll('[data-nav-tool]').forEach(button => button.classList.toggle('active', button.dataset.navTool === tool));
    controls.mouseButtons.LEFT = tool === 'orbit' ? THREE.MOUSE.ROTATE : tool === 'pan'
      ? THREE.MOUSE.PAN : tool === 'zoom' ? THREE.MOUSE.DOLLY : null;
    if (tool === 'select') setTool('select');
    canvasEl.style.cursor = tool === 'pan' ? 'grab' : tool === 'zoom' ? 'ns-resize' : tool === 'orbit' ? 'grabbing' : 'default';
  }

  function setTool(tool) {
    state.activeTool = tool;
    window.editorActiveTool = tool;
    document.querySelectorAll('[data-editor-tool]').forEach(button => button.classList.toggle('active', button.dataset.editorTool === tool));
    if (tool === 'select') {
      state.navigationTool = 'select';
      controls.mouseButtons.LEFT = null;
      document.querySelectorAll('[data-nav-tool]').forEach(button => button.classList.toggle('active', button.dataset.navTool === 'select'));
    } else if (tool === 'move') {
      if (selectedObject && selectedObject.userData.kind === 'opening') beginOpeningEdit();
      else if (selectedObject && selectedObject.userData.kind === 'wall') beginWallEdit('move');
      else setStatus('Selecione uma parede ou abertura antes de mover.', true);
    } else if (tool === 'rotate') {
      if (selectedObject && selectedObject.userData.kind === 'wall') {
        appendNumericProperties();
        const field = byId('prop-wall-angle'); if (field) field.focus();
        setStatus('Informe o ângulo exato no painel de propriedades.');
      } else setStatus('A rotação numérica é aplicada a paredes selecionadas.', true);
    } else if (tool === 'section') {
      setPanelOpen(byId('section-panel'), true);
      byId('section-live-enabled').checked = true;
      applyLiveSection();
    } else if (tool === 'measure') {
      state.measureStart = null;
      setStatus('Medição: clique no primeiro ponto e depois no segundo.');
    }
    byId('btn-cancel-action').disabled = !(editSession || tool === 'measure' || tool === 'section');
  }

  function cancelActiveAction() {
    if (state.activeEditorRequest) state.activeEditorRequest.abort();
    state.activeEditorRequest = null;
    if (editPreviewTimer) window.clearTimeout(editPreviewTimer);
    if (state.sectionDrag) finishSectionDrag({ pointerId: state.sectionDrag.pointerId,
      preventDefault() {}, stopImmediatePropagation() {} }, true);
    if (editSession && window.cancelInteractiveEdit) window.cancelInteractiveEdit();
    state.measureStart = null;
    clearThreeGroup(previewFeedbackGroup);
    closeOverlays();
    setTool('select');
    byId('btn-cancel-action').disabled = true;
    setStatus('Operação cancelada.');
    showToast('Operação cancelada');
  }

  function hideSelected() {
    if (!selectedObject) return;
    if (selectedObject.userData.kind === 'wall') wallIds(selectedObject.userData.wall).forEach(id => state.hiddenWallIds.add(id));
    if (selectedObject.userData.kind === 'opening') state.hiddenOpeningIds.add(asString(selectedObject.userData.opening.element_id));
    const block = selectedBlock();
    if (block) candidateWallIds(block).forEach(id => state.hiddenWallIds.add(id));
    applyEditorVisibility();
    showToast('Elemento ocultado');
  }

  function isolateSelected() {
    const wall = currentWall();
    if (wall) isolateWall(wall);
    else setStatus('Selecione uma parede, abertura ou bloco hospedado.', true);
  }

  function clearHover() {
    if (state.hoverObject && state.hoverColors) {
      const materials = Array.isArray(state.hoverObject.material) ? state.hoverObject.material : [state.hoverObject.material];
      materials.forEach((material, index) => {
        if (material && material.color && state.hoverColors[index]) material.color.copy(state.hoverColors[index]);
      });
    }
    state.hoverObject = null;
    state.hoverInstanceId = null;
    state.hoverColors = null;
    clearThreeGroup(hoverOverlayGroup);
    byId('hover-tooltip').style.display = 'none';
  }

  function tooltipText(hit) {
    if (!hit || !hit.object) return '';
    const data = hit.object.userData;
    if (data.kind === 'wall') {
      const wall = data.wall;
      return `Parede ${wall.id}\n${Number(wall.thickness_cm).toFixed(0)} cm  ·  ${(Number(wall.length_cm) / 100).toFixed(2)} m`;
    }
    if (data.kind === 'opening') {
      const opening = data.opening;
      return `${opening.element_id || 'Abertura'}\n${Number(opening.width_cm || 0).toFixed(0)} × ${Number(opening.height_cm || ((opening.head_cm || 0) - (opening.sill_cm || 0))).toFixed(0)} cm`;
    }
    if (data.kind === 'block-instances') {
      const entry = data.instances && data.instances[hit.instanceId];
      const block = entry && entry.candidate;
      if (block) return `${block.type_name || `Bloco ${block.logical_code}`}\nFiada ${Number(block.course_index) + 1}  ·  Parede ${block.wall_id || 'encontro'}`;
    }
    return '';
  }

  function updateHover(event) {
    if (editSession || state.activeTool === 'measure') return;
    const directHandle = window.editorPickDirectHandle && window.editorPickDirectHandle(event.clientX, event.clientY);
    if (directHandle) {
      clearHover();
      canvasEl.style.cursor = directHandle.cursor || 'grab';
      const labels = { start: 'Arrastar início da parede', end: 'Arrastar fim da parede',
        move: 'Arrastar ao longo da parede', 'resize-start': 'Arrastar para alterar largura',
        'resize-end': 'Arrastar para alterar largura', sill: 'Arrastar peitoril verticalmente' };
      const tooltip = byId('hover-tooltip');
      tooltip.textContent = `${labels[directHandle.mode] || 'Arrastar elemento'}\nShift: movimento livre`;
      tooltip.style.left = Math.min(viewport.clientWidth - 220, event.clientX + 13) + 'px';
      tooltip.style.top = Math.min(viewport.clientHeight - 75, event.clientY + 13) + 'px';
      tooltip.style.display = 'block';
      return;
    }
    const hit = pickObjectAt(event.clientX, event.clientY);
    const object = hit && hit.object;
    canvasEl.style.cursor = object && currentModelId
      && (object.userData.kind === 'wall' || object.userData.kind === 'opening') ? 'grab'
        : state.navigationTool === 'select' ? 'default' : canvasEl.style.cursor;
    if (object !== state.hoverObject || (hit && hit.instanceId) !== state.hoverInstanceId) {
      clearHover();
      if (!object || object === selectedObject) return;
      state.hoverObject = object;
      state.hoverInstanceId = hit.instanceId;
      if (object.userData.kind !== 'block-instances' && object.material) {
        const materials = Array.isArray(object.material) ? object.material : [object.material];
        state.hoverColors = materials.map(material => material.color ? material.color.clone() : null);
        materials.forEach(material => { if (material.color) material.color.lerp(new THREE.Color(0x7bbcff), .22); });
        const outline = new THREE.BoxHelper(object, 0x79b7ff); outline.material.transparent = true; outline.material.opacity = .65;
        hoverOverlayGroup.add(outline);
      } else if (object.userData.kind === 'block-instances') {
        const entry = object.userData.instances && object.userData.instances[hit.instanceId];
        if (entry && entry.candidate) hoverOverlayGroup.add(candidateOverlay(entry.candidate, 0x79b7ff, .08));
      }
    }
    const text = tooltipText(hit);
    const tooltip = byId('hover-tooltip');
    if (text) {
      tooltip.textContent = text;
      tooltip.style.left = Math.min(viewport.clientWidth - 220, event.clientX + 13) + 'px';
      tooltip.style.top = Math.min(viewport.clientHeight - 75, event.clientY + 13) + 'px';
      tooltip.style.display = 'block';
    }
    requestRender();
  }

  function makeTextSprite(text, color) {
    const canvas = document.createElement('canvas');
    canvas.width = 96; canvas.height = 42;
    const context = canvas.getContext('2d');
    context.fillStyle = 'rgba(32,33,36,.82)'; context.fillRect(8, 5, 80, 32);
    context.strokeStyle = color; context.lineWidth = 2; context.strokeRect(8, 5, 80, 32);
    context.fillStyle = '#ffffff'; context.font = '600 20px Segoe UI'; context.textAlign = 'center'; context.textBaseline = 'middle';
    context.fillText(text, 48, 21);
    const texture = new THREE.CanvasTexture(canvas);
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: false }));
    sprite.scale.set(34, 15, 1);
    return sprite;
  }

  function rebuildCourseLabels() {
    clearThreeGroup(courseLabelsGroup);
    if (!state.courseLabels) return;
    const wall = currentWall();
    const candidates = wall ? currentBlockCandidates.filter(item => intersects(candidateWallIds(item), wallIds(wall)))
      : currentBlockCandidates;
    const grouped = new Map();
    candidates.forEach(candidate => {
      const key = Number(candidate.course_index);
      if (!grouped.has(key)) grouped.set(key, candidate);
    });
    [...grouped.entries()].sort((a, b) => a[0] - b[0]).slice(0, 80).forEach(([course, candidate]) => {
      const sprite = makeTextSprite(String(course + 1).padStart(2, '0'), '#3b82f6');
      if (wall) {
        const dx = wall.end[0] - wall.start[0], dy = wall.end[1] - wall.start[1];
        const length = Math.max(1, Math.hypot(dx, dy));
        sprite.position.set(wall.start[0] - dy / length * 22, wall.start[1] + dx / length * 22,
          Number(candidate.z_cm) + Number(candidate.height_cm) / 2);
      } else {
        sprite.position.set(candidate.origin_cm[0], candidate.origin_cm[1], Number(candidate.z_cm) + 12);
      }
      courseLabelsGroup.add(sprite);
    });
    requestRender();
  }

  function rebuildCourseFilter() {
    const toolbar = byId('toolbar-course-filter');
    const original = byId('course-filter');
    const courses = [...new Set(currentBlockCandidates.map(item => Number(item.course_index)).filter(Number.isFinite))].sort((a, b) => a - b);
    const value = original.value;
    toolbar.innerHTML = '<option value="">Fiada: Todas</option>' + courses.map(course =>
      `<option value="${course}">Fiada ${String(course + 1).padStart(2, '0')}</option>`).join('');
    toolbar.value = value;
  }

  function stepCourse(delta) {
    const select = byId('toolbar-course-filter');
    const values = [...select.options].map(option => option.value);
    let index = Math.max(0, values.indexOf(select.value));
    index = Math.max(0, Math.min(values.length - 1, index + delta));
    select.value = values[index];
    select.dispatchEvent(new Event('change'));
  }

  function diagnosticSuggestion(status) {
    const code = String(status.code || '').toUpperCase();
    if (code.includes('ALIGN')) return 'Revise o alinhamento dos encontros e o deslocamento entre fiadas.';
    if (code.includes('COVERAGE') || code.includes('NON_MODULAR')) return 'Revise dimensões da parede/abertura ou uma alternativa de fechamento permitida.';
    if (code.includes('OPENING')) return 'Confira posição, largura, verga, contraverga e o prisma da abertura.';
    return status.ok === false ? 'Abra a vista da parede para localizar a fiada e a regra reprovada.' : 'Nenhuma correção necessária.';
  }

  function showDiagnostics(wall) {
    const panel = byId('diagnostics-panel');
    const content = byId('diagnostics-content');
    setPanelOpen(panel, true);
    const elementTab = byId('diagnostics-panel').querySelector('[data-diagnostic-tab="element"]');
    if (elementTab) elementTab.click();
    if (!wall) {
      content.textContent = 'Selecione uma parede, abertura ou bloco para inspecionar.';
      return;
    }
    const status = wall.modulation_status || {};
    const blocks = currentBlockCandidates.filter(candidate => intersects(candidateWallIds(candidate), wallIds(wall)));
    const failed = blocks.filter(block => block.is_error);
    content.className = status.ok === false ? 'diagnostic-error' : failed.length ? 'diagnostic-warning' : 'diagnostic-ok';
    content.textContent = [
      `${status.ok === false ? '● ERRO' : failed.length ? '● ALERTA' : '● CORRETO'}  ·  Parede ${wall.id}`,
      `Fiadas: ${new Set(blocks.map(block => block.course_index)).size}  ·  Blocos: ${blocks.length}`,
      status.code ? `Regra/código: ${status.code}` : '',
      status.course_index != null ? `Fiada afetada: ${Number(status.course_index) + 1}` : '',
      status.reason ? `Motivo: ${status.reason}` : 'Nenhuma incompatibilidade registrada.',
      `Sugestão: ${diagnosticSuggestion(status)}`,
    ].filter(Boolean).join('\n');
  }

  function rebuildDiagnosticDock() {
    const conflicts = currentWalls.filter(wall => {
      const status = wall.modulation_status || {};
      return status.ok === false || currentBlockCandidates.some(candidate => candidate.is_error && intersects(candidateWallIds(candidate), wallIds(wall)));
    });
    const wallFilter = byId('diagnostic-filter-wall');
    const selectedFilter = wallFilter.value;
    wallFilter.innerHTML = '<option value="">Todas as paredes</option>';
    conflicts.forEach(wall => {
      const option = document.createElement('option');
      option.value = asString(wall.id); option.textContent = `Parede ${wall.id}`; wallFilter.appendChild(option);
    });
    wallFilter.value = selectedFilter;
    const container = byId('diagnostics-conflicts');
    container.innerHTML = '';
    conflicts.forEach(wall => {
      const status = wall.modulation_status || {};
      const severity = status.ok === false ? 'error' : 'warning';
      const row = document.createElement('div');
      row.className = `diagnostic-problem ${severity}`;
      row.dataset.wallId = asString(wall.id); row.dataset.severity = severity;
      const copy = document.createElement('div');
      const title = document.createElement('strong');
      title.textContent = `${severity === 'error' ? '● Erro' : '△ Alerta'} · Parede ${wall.id} · ${status.code || 'MODULAÇÃO'}`;
      const reason = document.createElement('small');
      reason.textContent = `${status.reason || 'Revisão necessária'} · ${diagnosticSuggestion(status)}`;
      copy.append(title, reason);
      const actions = document.createElement('div'); actions.className = 'problem-actions';
      [['locate', 'Localizar'], ['isolate', 'Isolar'], ['proposals', 'Propostas']].forEach(([action, label]) => {
        const button = document.createElement('button'); button.type = 'button'; button.dataset.diagnosticAction = action;
        button.dataset.wallId = asString(wall.id); button.textContent = label; actions.appendChild(button);
      });
      row.append(copy, actions); container.appendChild(row);
    });
    if (!conflicts.length) container.textContent = '✓ Nenhum conflito detectado no modelo atual.';
    byId('diagnostics-history').textContent = byId('history-list').textContent;
    const wall = currentWall();
    if (!wall && !state.dependencyGraph) byId('diagnostics-dependencies').textContent = 'Selecione uma parede, abertura ou bloco para ver suas dependências.';
    else if (!wall) {
      const graph = state.dependencyGraph;
      byId('diagnostics-dependencies').textContent = [
        'Última invalidação incremental',
        `Elemento alterado: ${(graph.changed_elements || []).filter(Boolean).join(', ') || '—'}`,
        `Paredes fonte: ${(graph.source_wall_ids || []).join(', ') || '—'}`,
        `Componente afetada: ${(graph.affected_wall_ids || []).join(', ') || '—'}`,
        `Contexto lido pelo solver: ${(graph.solver_context_wall_ids || []).join(', ') || '—'}`,
        `Fiadas recalculadas: ${(graph.affected_course_indices || []).map(index => Number(index) + 1).join(', ') || '—'}`,
        `Dependências invalidadas: ${(graph.invalidation || []).join(' → ') || '—'}`,
      ].join('\n');
    }
    else {
      const relatedOpenings = currentOpenings.filter(opening => intersects(openingWallIds(opening), wallIds(wall)));
      const relatedBlocks = currentBlockCandidates.filter(candidate => intersects(candidateWallIds(candidate), wallIds(wall)));
      const connected = currentWalls.filter(other => other !== wall && intersects(connectedIdsFor(wall), wallIds(other)));
      byId('diagnostics-dependencies').textContent = [
        `Parede ${wall.id}`,
        `Paredes conectadas: ${connected.map(item => item.id).join(', ') || 'nenhuma'}`,
        `Aberturas hospedadas: ${relatedOpenings.map(item => item.element_id).join(', ') || 'nenhuma'}`,
        `Blocos dependentes: ${relatedBlocks.length}`,
        `Fiadas afetadas: ${new Set(relatedBlocks.map(item => Number(item.course_index) + 1)).size}`,
      ].join('\n');
    }
    filterDiagnosticProblems();
  }

  function filterDiagnosticProblems() {
    const severity = byId('diagnostic-filter-severity').value;
    const wallId = byId('diagnostic-filter-wall').value;
    const textFilter = byId('diagnostic-filter-text').value.trim().toLowerCase();
    byId('diagnostics-conflicts').querySelectorAll('.diagnostic-problem').forEach(row => {
      row.hidden = Boolean((severity && row.dataset.severity !== severity)
        || (wallId && row.dataset.wallId !== wallId)
        || (textFilter && !row.textContent.toLowerCase().includes(textFilter)));
    });
  }

  function makeDiagnosticSprite(color, wall) {
    const sprite = makeTextSprite(wall.modulation_status && wall.modulation_status.ok === false ? '!' : '✓', color);
    sprite.scale.set(24, 11, 1);
    sprite.userData = { kind: 'diagnostic-marker', wall };
    sprite.position.set((wall.start[0] + wall.end[0]) / 2, (wall.start[1] + wall.end[1]) / 2,
      (Number(wall.base_z_cm) || 0) + (Number(wall.height_cm) || 280) + 22);
    return sprite;
  }

  function rebuildDiagnosticMarkers() {
    clearThreeGroup(diagnosticMarkersGroup);
    const diagnostic = byId('display-mode').value === 'diagnostic';
    diagnosticMarkersGroup.visible = diagnostic;
    if (!diagnostic) return;
    currentWalls.filter(wallMatchesFilter).forEach(wall => {
      const status = wall.modulation_status || {};
      diagnosticMarkersGroup.add(makeDiagnosticSprite(status.ok === false ? '#ef4444' : '#22c55e', wall));
    });
    requestRender();
  }

  function diagnosticHit(event) {
    if (!diagnosticMarkersGroup.visible) return null;
    const rect = canvasEl.getBoundingClientRect();
    mouseNdc.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    mouseNdc.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    raycaster.setFromCamera(mouseNdc, camera);
    const hits = raycaster.intersectObjects(diagnosticMarkersGroup.children, false);
    return hits[0] && hits[0].object.userData.wall || null;
  }

  function candidateKey(candidate) {
    return candidate.id || [candidate.wall_id, candidate.course_index, candidate.logical_code,
      ...(candidate.origin_cm || []), candidate.z_cm].join('|');
  }

  function showPreviewFeedback(data) {
    clearThreeGroup(previewFeedbackGroup);
    const edit = data.edit || {};
    const affected = new Set((edit.affected_wall_ids || []).map(asString));
    const previous = (committedViewData && committedViewData.block_candidates) || [];
    const next = data.block_candidates || [];
    const previousMap = new Map(previous.filter(item => !affected.size || intersects(candidateWallIds(item), affected))
      .map(item => [candidateKey(item), item]));
    const nextMap = new Map(next.filter(item => !affected.size || intersects(candidateWallIds(item), affected))
      .map(item => [candidateKey(item), item]));
    [...previousMap].filter(([key]) => !nextMap.has(key)).slice(0, 220)
      .forEach(([, candidate]) => previewFeedbackGroup.add(candidateOverlay(candidate, 0xef4444, .1)));
    [...nextMap].filter(([key]) => !previousMap.has(key)).slice(0, 220)
      .forEach(([, candidate]) => previewFeedbackGroup.add(candidateOverlay(candidate, 0x3b82f6, .16)));
    currentWalls.filter(wall => intersects(wallIds(wall), affected)).forEach(wall => {
      const mesh = wallGroup.children.find(item => item.userData.wall === wall);
      if (mesh) { const helper = new THREE.BoxHelper(mesh, 0x3b82f6); helper.material.transparent = true; helper.material.opacity = .35; previewFeedbackGroup.add(helper); }
    });
    requestRender();
  }

  function sectionSnapshot() {
    return { enabled: byId('section-live-enabled').checked, axis: byId('section-live-axis').value,
      positionCm: Number(byId('section-live-position').value || 0) * 100, inverted: state.sectionInverted };
  }

  function setSectionPositionCm(positionCm) {
    const value = Number.isFinite(positionCm) ? positionCm : 0;
    byId('section-live-position').value = (value / 100).toFixed(3);
    byId('section-live-slider').value = Math.round(value);
  }

  function applySectionSnapshot(snapshot) {
    byId('section-live-enabled').checked = snapshot.enabled;
    byId('section-live-axis').value = snapshot.axis;
    setSectionPositionCm(snapshot.positionCm);
    state.sectionInverted = Boolean(snapshot.inverted);
    byId('section-invert').classList.toggle('active', state.sectionInverted);
    applyLiveSection();
  }

  function sectionDescriptor() {
    const axis = byId('section-live-axis').value;
    const position = Number(byId('section-live-position').value || 0) * 100;
    const bounds = lastBounds || { cx: 0, cy: 0, cz: 140, span: 600 };
    let normal;
    let point;
    if (axis === 'wall') {
      const wall = currentWall();
      if (!wall) return null;
      const dx = wall.end[0] - wall.start[0], dy = wall.end[1] - wall.start[1];
      const length = Math.max(1, Math.hypot(dx, dy));
      normal = new THREE.Vector3(-dy / length, dx / length, 0);
      point = new THREE.Vector3((wall.start[0] + wall.end[0]) / 2,
        (wall.start[1] + wall.end[1]) / 2, bounds.cz).add(normal.clone().multiplyScalar(position));
    } else {
      normal = axis === 'x' ? new THREE.Vector3(-1, 0, 0) : axis === 'y'
        ? new THREE.Vector3(0, -1, 0) : new THREE.Vector3(0, 0, -1);
      point = axis === 'x' ? new THREE.Vector3(position, bounds.cy, bounds.cz)
        : axis === 'y' ? new THREE.Vector3(bounds.cx, position, bounds.cz)
          : new THREE.Vector3(bounds.cx, bounds.cy, position);
    }
    if (state.sectionInverted) normal.negate();
    return { axis, position, normal, point, plane: new THREE.Plane(normal, -normal.dot(point)), bounds };
  }

  function applyLiveSection(forceMaterials = false) {
    const enabled = byId('section-live-enabled').checked;
    clearThreeGroup(sectionVisualGroup);
    if (!enabled) {
      setSectionHover(null);
      sectionPlane = null;
      renderer.localClippingEnabled = false;
      scene.traverse(item => {
        if (!item.material || item.userData.editorOverlay) return;
        (Array.isArray(item.material) ? item.material : [item.material]).forEach(material => { material.clippingPlanes = null; material.needsUpdate = true; });
      });
      byId('footer-section').classList.remove('active');
      requestRender();
      return;
    }
    const descriptor = sectionDescriptor();
    if (!descriptor) { setStatus('Selecione uma parede para corte longitudinal.', true); return; }
    const plane = descriptor.plane;
    const size = Math.max(300, (descriptor.bounds.span || 600) * 1.3);
    const installClipping = !sectionPlane;
    if (sectionPlane) sectionPlane.copy(plane);
    else sectionPlane = plane;
    renderer.localClippingEnabled = true;
    if (installClipping || forceMaterials) {
      scene.traverse(item => {
        if (!item.material || item.userData.editorOverlay) return;
        (Array.isArray(item.material) ? item.material : [item.material]).forEach(material => {
          material.clippingPlanes = [sectionPlane]; material.needsUpdate = true;
        });
      });
    }
    const helper = new THREE.PlaneHelper(sectionPlane, size, 0x3b82f6);
    helper.userData.editorOverlay = true;
    helper.material.transparent = true; helper.material.opacity = .5; helper.renderOrder = 18;
    sectionVisualGroup.add(helper);

    const surface = new THREE.Mesh(new THREE.PlaneGeometry(size, size),
      new THREE.MeshBasicMaterial({ color: 0x3b82f6, transparent: true, opacity: .07,
        depthWrite: false, side: THREE.DoubleSide }));
    surface.position.copy(descriptor.point);
    surface.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), descriptor.normal);
    surface.userData = { editorOverlay: true, sectionDragHandle: true, sectionSurface: true, sectionAxis: descriptor.axis };
    surface.renderOrder = 17;
    sectionVisualGroup.add(surface);

    const arrowLength = Math.max(45, Math.min(110, size * .12));
    const positive = new THREE.ArrowHelper(descriptor.normal, descriptor.point, arrowLength, 0x72b4ff, 13, 8);
    const negative = new THREE.ArrowHelper(descriptor.normal.clone().negate(), descriptor.point, arrowLength, 0x72b4ff, 13, 8);
    [positive, negative].forEach(arrow => { arrow.userData.editorOverlay = true; sectionVisualGroup.add(arrow); });
    const handle = new THREE.Mesh(new THREE.SphereGeometry(11, 20, 14),
      new THREE.MeshBasicMaterial({ color: 0x72b4ff, depthTest: false }));
    handle.position.copy(descriptor.point);
    handle.userData = { editorOverlay: true, sectionDragHandle: true, sectionAxis: descriptor.axis };
    handle.renderOrder = 22;
    sectionVisualGroup.add(handle);

    const label = makeTextSprite(`${descriptor.axis.toUpperCase()} ${(descriptor.position / 100).toFixed(2)}m`, '#3b82f6');
    label.position.copy(descriptor.point).add(new THREE.Vector3(0, 0, 24));
    label.userData.editorOverlay = true;
    label.renderOrder = 23;
    sectionVisualGroup.add(label);
    byId('footer-section').classList.add('active');
    requestRender();
  }

  const sectionRaycaster = new THREE.Raycaster();
  const sectionMouse = new THREE.Vector2();

  function sectionHitAt(clientX, clientY) {
    if (!byId('section-live-enabled').checked) return null;
    const rect = canvasEl.getBoundingClientRect();
    sectionMouse.x = ((clientX - rect.left) / rect.width) * 2 - 1;
    sectionMouse.y = -((clientY - rect.top) / rect.height) * 2 + 1;
    sectionRaycaster.setFromCamera(sectionMouse, camera);
    const hits = sectionRaycaster.intersectObjects(sectionVisualGroup.children, true)
      .filter(hit => hit.object.userData && hit.object.userData.sectionDragHandle);
    return hits.find(hit => !hit.object.userData.sectionSurface)
      || ((state.activeTool === 'section') ? hits[0] : null);
  }

  function setSectionHover(hit) {
    if (state.sectionHover === (hit && hit.object)) return;
    if (state.sectionHover && state.sectionHover.material) {
      state.sectionHover.material.opacity = state.sectionHover.userData.sectionSurface ? .07 : 1;
      state.sectionHover.scale.setScalar(1);
    }
    state.sectionHover = hit && hit.object || null;
    canvasEl.classList.remove('section-hover-z', 'section-hover-xy');
    if (state.sectionHover) {
      if (state.sectionHover.material) state.sectionHover.material.opacity = state.sectionHover.userData.sectionSurface ? .15 : 1;
      if (!state.sectionHover.userData.sectionSurface) state.sectionHover.scale.setScalar(1.18);
      canvasEl.classList.add(state.sectionHover.userData.sectionAxis === 'z' ? 'section-hover-z' : 'section-hover-xy');
    }
    requestRender();
  }

  function showSectionDragBadge(positionCm, axis, event, freeMovement) {
    const badge = byId('drag-value-badge');
    const rect = viewport.getBoundingClientRect();
    badge.textContent = `Corte ${axis.toUpperCase()} = ${(positionCm / 100).toFixed(2)} m${freeMovement ? ' · livre' : ''}`;
    badge.style.left = Math.max(56, Math.min(rect.width - 220, event.clientX - rect.left + 14)) + 'px';
    badge.style.top = Math.max(56, Math.min(rect.height - 68, event.clientY - rect.top + 14)) + 'px';
    badge.classList.add('open');
  }

  function updateSectionHistoryButtons() {
    byId('btn-undo').disabled = !(state.sectionUndo.length || window.editorBackendCanUndo);
    byId('btn-redo').disabled = !(state.sectionRedo.length || window.editorBackendCanRedo);
  }

  function pushSectionHistory(before, after) {
    state.sectionUndo.push({ before, after });
    if (state.sectionUndo.length > 50) state.sectionUndo.shift();
    state.sectionRedo.length = 0;
    updateSectionHistoryButtons();
  }

  function undoSection() {
    const action = state.sectionUndo.pop();
    if (!action) return false;
    state.sectionRedo.push(action);
    applySectionSnapshot(action.before);
    updateSectionHistoryButtons();
    showToast('Movimento do plano de corte desfeito', 'ok');
    return true;
  }

  function redoSection() {
    const action = state.sectionRedo.pop();
    if (!action) return false;
    state.sectionUndo.push(action);
    applySectionSnapshot(action.after);
    updateSectionHistoryButtons();
    showToast('Movimento do plano de corte refeito', 'ok');
    return true;
  }

  function applyPendingSectionDrag() {
    const drag = state.sectionDrag;
    if (!drag || drag.pendingPosition == null) return;
    drag.frame = null;
    setSectionPositionCm(drag.pendingPosition);
    applyLiveSection();
    drag.pendingPosition = null;
  }

  canvasEl.addEventListener('pointerdown', event => {
    if (event.button !== 0 || state.sectionDrag) return;
    const hit = sectionHitAt(event.clientX, event.clientY);
    if (!hit) return;
    const descriptor = sectionDescriptor();
    if (!descriptor) return;
    const startPoint = worldPointAlongAxis(event.clientX, event.clientY,
      descriptor.point, descriptor.normal, event.shiftKey);
    if (!startPoint) return;
    state.sectionDrag = { pointerId: event.pointerId, descriptor, startPoint,
      startPosition: descriptor.position, before: sectionSnapshot(), clientStart: [event.clientX, event.clientY],
      moved: false, pendingPosition: null, frame: null };
    window.editorSectionDragging = true;
    controls.enabled = false;
    canvasEl.classList.add('direct-dragging');
    canvasEl.setPointerCapture(event.pointerId);
    event.preventDefault();
    event.stopImmediatePropagation();
  }, true);

  canvasEl.addEventListener('pointermove', event => {
    const drag = state.sectionDrag;
    if (!drag) {
      setSectionHover(sectionHitAt(event.clientX, event.clientY));
      return;
    }
    const point = worldPointAlongAxis(event.clientX, event.clientY,
      drag.descriptor.point, drag.descriptor.normal, event.shiftKey);
    if (!point) return;
    if (!drag.moved && Math.hypot(event.clientX - drag.clientStart[0], event.clientY - drag.clientStart[1]) < 2) return;
    drag.moved = true;
    const delta = point.clone().sub(drag.startPoint).dot(drag.descriptor.normal);
    drag.pendingPosition = snapScalar(drag.startPosition + delta, event.shiftKey);
    if (!drag.frame) drag.frame = requestAnimationFrame(applyPendingSectionDrag);
    showSectionDragBadge(drag.pendingPosition, drag.descriptor.axis, event, event.shiftKey);
    setStatus(`Corte ${drag.descriptor.axis.toUpperCase()} = ${(drag.pendingPosition / 100).toFixed(2)}m · atualização em tempo real`);
    event.preventDefault();
    event.stopImmediatePropagation();
  }, true);

  function finishSectionDrag(event, cancel) {
    const drag = state.sectionDrag;
    if (!drag) return;
    if (drag.frame) { cancelAnimationFrame(drag.frame); drag.frame = null; }
    if (drag.pendingPosition != null) applyPendingSectionDrag();
    if (cancel) applySectionSnapshot(drag.before);
    else if (drag.moved) pushSectionHistory(drag.before, sectionSnapshot());
    state.sectionDrag = null;
    window.editorSectionDragging = false;
    controls.enabled = true;
    canvasEl.classList.remove('direct-dragging');
    byId('drag-value-badge').classList.remove('open');
    if (event.pointerId != null && canvasEl.hasPointerCapture(event.pointerId)) canvasEl.releasePointerCapture(event.pointerId);
    if (!cancel && drag.moved) { setStatus('Plano de corte reposicionado.'); showToast('Plano de corte atualizado', 'ok'); }
    event.preventDefault();
    event.stopImmediatePropagation();
  }

  canvasEl.addEventListener('pointerup', event => finishSectionDrag(event, false), true);
  canvasEl.addEventListener('pointercancel', event => finishSectionDrag(event, true), true);

  function updateProjectName() {
    const path = byId('dxf-path').value.trim();
    const name = path ? path.split(/[\\/]/).pop() : 'Sem projeto';
    byId('project-name').textContent = name;
    byId('app-project-name').textContent = path ? name : 'Sem projeto aberto';
    byId('app-project-detail').textContent = path
      ? `${currentWalls.length} parede(s) · ${currentOpenings.length} abertura(s)`
      : 'Aguardando arquivo DWG ou captura do Revit';
    const sync = byId('app-sync-state');
    const fromRevit = /\.json$/i.test(path) || Boolean(currentWalls.some(wall => wall.element_id));
    sync.classList.toggle('sync-ok', Boolean(path && fromRevit));
    sync.classList.toggle('sync-waiting', !path || !fromRevit);
    sync.querySelector('span').textContent = path
      ? (fromRevit ? 'Revit sincronizado' : 'Projeto DWG carregado')
      : 'Revit aguardando captura';
    byId('status-revit').textContent = path && fromRevit ? 'Revit: sincronizado' : path ? 'Revit: arquivo local' : 'Revit: aguardando';
  }

  function updateProjectSnap(data) {
    const configured = Number(data && (data.project_module_cm
      || data.modulation_module_cm || data.setup && data.setup.module_cm));
    window.editorProjectModuleCm = Number.isFinite(configured) && configured > 0 ? configured : 20;
    const option = byId('snap-step').querySelector('option[value="project"]');
    if (option) option.textContent = `Snap módulo (${window.editorProjectModuleCm.toFixed(0)}cm)`;
    if (byId('snap-step').value === 'project') window.editorSnapCm = window.editorProjectModuleCm;
  }

  function setTheme(theme) {
    document.documentElement.dataset.theme = theme;
    scene.background = new THREE.Color(theme === 'light' ? 0xe7e9ec : 0x111318);
    const gridMaterials = Array.isArray(grid.material) ? grid.material : [grid.material];
    gridMaterials.forEach((material, index) => {
      material.color.set(theme === 'light' ? (index === 0 ? 0x8b9199 : 0xb4b9bf)
        : (index === 0 ? 0x45484d : 0x303338));
      material.transparent = true;
      material.opacity = theme === 'light' ? .48 : .62;
    });
    localStorage.setItem('modulation-editor-theme', theme);
    byId('btn-theme').title = theme === 'light' ? 'Usar tema escuro' : 'Usar tema claro';
    requestRender();
  }

  function setupPanel(panel) {
    if (!panel) return;
    const saved = localStorage.getItem(`editor-panel-${panel.id}`);
    if (saved) {
      try {
        const layout = JSON.parse(saved);
        ['left', 'top', 'right', 'bottom', 'width', 'height'].forEach(key => { if (layout[key]) panel.style[key] = layout[key]; });
        if (layout.dock) panel.classList.add(layout.dock);
      } catch (_error) { /* layout antigo inválido não bloqueia o editor */ }
    }
    let drag = null;
    panel.addEventListener('pointerdown', event => {
      const handle = event.target.closest('.panel-titlebar,.sel-title');
      if (!handle || event.button !== 0 || event.target.closest('button,input,select,textarea')) return;
      const rect = panel.getBoundingClientRect();
      drag = { dx: event.clientX - rect.left, dy: event.clientY - rect.top };
      panel.classList.remove('docked-left', 'docked-right');
      panel.setPointerCapture && panel.setPointerCapture(event.pointerId);
    });
    panel.addEventListener('pointermove', event => {
      if (!drag) return;
      panel.style.left = Math.max(4, Math.min(window.innerWidth - 80, event.clientX - drag.dx)) + 'px';
      panel.style.top = Math.max(52, Math.min(window.innerHeight - 65, event.clientY - drag.dy)) + 'px';
      panel.style.right = 'auto'; panel.style.bottom = 'auto';
    });
    panel.addEventListener('pointerup', () => {
      if (!drag) return;
      drag = null;
      localStorage.setItem(`editor-panel-${panel.id}`, JSON.stringify({ left: panel.style.left, top: panel.style.top,
        right: panel.style.right, bottom: panel.style.bottom, width: panel.style.width, height: panel.style.height }));
    });
  }

  function openOverlay(id) {
    closeOverlays();
    byId(id).classList.add('open');
    const input = byId(id).querySelector('input');
    if (input) { input.value = ''; input.focus(); input.dispatchEvent(new Event('input')); }
  }

  function closeOverlays() {
    document.querySelectorAll('.command-overlay.open').forEach(item => item.classList.remove('open'));
  }

  function searchableElements() {
    const items = [];
    currentWalls.forEach(wall => items.push({ label: `Parede ${wall.id}`, detail: `${(Number(wall.length_cm) / 100).toFixed(2)}m`,
      select: () => { const mesh = wallGroup.children.find(item => item.userData.wall === wall); if (mesh) selectObject(mesh); focusOnWallId(wall.id); } }));
    currentOpenings.forEach(opening => items.push({ label: `Abertura ${opening.element_id}`, detail: opening.type || opening.family || '',
      select: () => { const mesh = openingsGroup.children.find(item => item.userData.opening === opening && item.userData.kind === 'opening'); if (mesh) { selectObject(mesh); focusSelected(); } } }));
    currentBlockCandidates.forEach(candidate => items.push({ label: candidate.id || `${candidate.logical_code} · Fiada ${Number(candidate.course_index) + 1}`,
      detail: `${candidate.type_name || candidate.logical_code} · Parede ${candidate.wall_id || 'encontro'}`,
      select: () => {
        for (const mesh of blocksGroup.children) {
          const index = (mesh.userData.instances || []).findIndex(entry => entry.candidate === candidate || candidateKey(entry.candidate) === candidateKey(candidate));
          if (index >= 0) { selectObject(mesh, index); focusSelected(); break; }
        }
      } }));
    return items;
  }

  function renderResults(container, items) {
    container.innerHTML = '';
    items.slice(0, 60).forEach((item, index) => {
      const row = document.createElement('div');
      row.className = 'command-result' + (index === 0 ? ' active' : '');
      const label = document.createElement('span'); label.textContent = item.label;
      const detail = document.createElement('small'); detail.textContent = item.detail || '';
      row.append(label, detail);
      row.addEventListener('click', () => { closeOverlays(); item.select(); syncSelectionPanel(); });
      container.appendChild(row);
    });
    if (!items.length) {
      const row = document.createElement('div'); row.className = 'command-result'; row.textContent = 'Nenhum resultado.'; container.appendChild(row);
    }
  }

  function commandItems() {
    return [
      { label: 'Isolar parede selecionada', detail: 'Visibilidade', select: isolateSelected },
      { label: 'Mostrar projeto inteiro', detail: 'Visibilidade', select: restoreVisibility },
      { label: 'Vista superior', detail: 'Câmera', select: () => animateToView('top') },
      { label: 'Vista frontal', detail: 'Câmera', select: () => animateToView('front') },
      { label: 'Vista isométrica', detail: 'Câmera', select: () => animateToView('iso') },
      { label: 'Enquadrar seleção', detail: 'Câmera', select: focusSelected },
      { label: 'Abrir plano de corte', detail: 'Ferramentas', select: () => setPanelOpen(byId('section-panel'), true) },
      { label: 'Ativar diagnóstico', detail: 'Visualização', select: () => setVisualMode('diagnostic') },
      { label: 'Modo raio-X', detail: 'Visualização', select: () => setVisualMode('xray') },
      { label: 'Mostrar todas as fiadas', detail: 'Fiadas', select: () => { byId('toolbar-course-filter').value = ''; byId('toolbar-course-filter').dispatchEvent(new Event('change')); } },
      { label: 'Abrir projeto e configurações', detail: 'Painéis', select: () => setPanelOpen(byId('sidebar'), true) },
      { label: 'Alternar tema claro/escuro', detail: 'Aparência', select: () => setTheme(document.documentElement.dataset.theme === 'light' ? 'dark' : 'light') },
    ];
  }

  function setVisualMode(mode) {
    byId('display-mode').value = mode;
    byId('toolbar-display-mode').value = mode;
    applyDisplayMode();
    applyEditorVisibility();
    rebuildDiagnosticMarkers();
    byId('btn-diagnostic-mode').classList.toggle('active', mode === 'diagnostic');
    syncVisibilityPopover();
  }

  function centerOpeningInWall(opening, wall) {
    if (!opening || !wall) return;
    const center = [(wall.start[0] + wall.end[0]) / 2, (wall.start[1] + wall.end[1]) / 2];
    postEditorAction('/api/edit-opening', { opening_id: opening.element_id, center_cm: center },
      `Abertura ${opening.element_id} centralizada na parede`);
  }

  function handleOpeningMenu(action) {
    const opening = selectedObject && selectedObject.userData.opening;
    if (!opening) return;
    if (action === 'move') setTool('move');
    else if (action === 'properties') { syncSelectionPanel(); const panel = byId('selection-panel'); panel.classList.remove('minimized'); }
    else if (action.indexOf('shift-') === 0) shiftOpening(opening, Number(action.substring(6)));
    else if (action === 'center-wall') centerOpeningInWall(opening, currentWall());
    else if (action === 'duplicate') postEditorAction('/api/duplicate-opening', { opening_id: opening.element_id, delta_cm: 10 }, 'Abertura duplicada');
    else if (action === 'delete' && window.confirm(`Excluir a abertura ${opening.element_id}? Esta ação poderá ser desfeita pelo histórico.`)) {
      postEditorAction('/api/delete-opening', { opening_id: opening.element_id }, 'Abertura excluída');
    }
    else if (action === 'host-wall' || action === 'isolate') isolateWall(currentWall());
    else if (action === 'diagnostic') showDiagnostics(currentWall());
  }

  function handleContextAction(action) {
    if (action === 'move') setTool('move');
    else if (action === 'properties') { syncSelectionPanel(); byId('selection-panel').classList.remove('minimized'); }
    else if (action === 'center') focusSelected();
    else if (action === 'isolate' || action === 'host-wall' || action === 'wall-view') isolateSelected();
    else if (action === 'previous-wall') navigateWall(-1);
    else if (action === 'next-wall') navigateWall(1);
    else if (action === 'recalculate') recalculateSelectedRegion();
    else if (action === 'courses') { state.courseLabels = true; rebuildCourseLabels(); }
    else if (action === 'dependencies') showConnected(currentWall());
    else if (action === 'highlight-type') {
      const block = selectedBlock(); state.highlightBlockCode = block && block.logical_code; applyEditorVisibility();
    } else if (action === 'diagnostic') { setVisualMode('diagnostic'); showDiagnostics(currentWall()); }
    else if (action === 'proposals') generateProposals(false);
    else if (action === 'hide') hideSelected();
  }

  function updateThemeAndShadows() {
    const theme = localStorage.getItem('modulation-editor-theme') || 'dark';
    setTheme(theme);
    renderer.shadowMap.enabled = state.shadows;
    dirLight.castShadow = state.shadows;
    scene.traverse(item => { if (item.isMesh) { item.castShadow = state.shadows; item.receiveShadow = state.shadows; } });
    requestRender();
  }

  decorateToolbars();
  ['sidebar', 'selection-panel', 'section-panel', 'diagnostics-panel'].forEach(id => setupPanel(byId(id)));
  setPanelOpen(byId('sidebar'), false);
  updateThemeAndShadows();
  setImportStep(1);
  syncVisibilityPopover();

  document.querySelectorAll('[data-workspace-tab]').forEach(tab => tab.addEventListener('click', () => openWorkspaceSection(tab.dataset.workspaceTab)));
  byId('btn-import-back').addEventListener('click', () => setImportStep(state.importStep - 1));
  byId('btn-import-next').addEventListener('click', () => {
    if (state.importStep < 4) setImportStep(state.importStep + 1);
    else byId('btn-load').click();
  });

  byId('btn-app-import').addEventListener('click', () => openWorkspaceSection('import', { step: 1 }));
  byId('btn-app-revit').addEventListener('click', () => {
    openWorkspaceSection('import', { step: 1 });
    byId('btn-pick-json').focus();
    showToast('Selecione a captura JSON gerada pelo Revit.');
  });
  byId('btn-app-settings').addEventListener('click', () => openWorkspaceSection('visibility'));
  byId('btn-app-help').addEventListener('click', () => openOverlay('help-overlay'));
  byId('btn-app-fullscreen').addEventListener('click', async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await document.documentElement.requestFullscreen();
    } catch (error) { showToast(`Tela cheia indisponível: ${error.message || error}`, 'warning'); }
  });
  byId('btn-app-save').addEventListener('click', () => {
    try {
      localStorage.setItem('modulador-externo-3d-last-model', JSON.stringify(currentExportPayload()));
      showToast('Estado local salvo neste navegador.', 'ok');
      appendDiagnosticLog('Estado local salvo.');
    } catch (error) { showToast(`Não foi possível salvar: ${error.message || error}`, 'error'); }
  });
  byId('btn-app-export').addEventListener('click', () => {
    downloadExport(currentExportPayload(), 'modulacao');
    showToast('Arquivo de modulação exportado.', 'ok');
    appendDiagnosticLog('Modelo exportado em JSON.');
  });
  byId('btn-app-send-revit').addEventListener('click', () => {
    const payload = currentExportPayload();
    if (!payload.model_id) { showToast('Carregue e module um projeto antes de enviar ao Revit.', 'warning'); return; }
    if (window.chrome && window.chrome.webview && typeof window.chrome.webview.postMessage === 'function') {
      window.chrome.webview.postMessage({ type: 'modulador:apply-to-revit', payload });
      showToast('Alterações enviadas ao conector do Revit.', 'ok');
      appendDiagnosticLog('Pacote encaminhado ao WebView do Revit.');
    } else {
      downloadExport(payload, 'para-revit');
      showToast('Pacote para o Revit exportado; importe-o pelo comando pyRevit.', 'warning');
      appendDiagnosticLog('Conector WebView ausente; pacote para Revit exportado.');
    }
  });

  byId('btn-visibility-popover').addEventListener('click', () => { syncVisibilityPopover(); togglePopover('visibility-popover'); });
  byId('btn-more-tools').addEventListener('click', () => togglePopover('more-tools-popover'));
  document.querySelectorAll('[data-close-popover]').forEach(button => button.addEventListener('click', () => byId(button.dataset.closePopover).classList.remove('open')));
  byId('quick-display-mode').addEventListener('change', event => { setVisualMode(event.target.value); syncVisibilityPopover(); });
  document.querySelectorAll('[data-visibility-toggle]').forEach(button => button.addEventListener('click', () => {
    const source = byId(button.dataset.visibilityToggle);
    if (!source) return;
    source.checked = !source.checked;
    source.dispatchEvent(new Event('change'));
    syncVisibilityPopover();
  }));
  byId('btn-visibility-details').addEventListener('click', () => { closePopovers(); openWorkspaceSection('visibility'); });
  document.querySelectorAll('[data-more-action]').forEach(button => button.addEventListener('click', () => {
    closePopovers();
    const action = button.dataset.moreAction;
    if (action === 'calculator' || action === 'history') openWorkspaceSection(action);
    else if (action === 'diagnostics') showDiagnostics(currentWall());
    else if (action === 'commands') openOverlay('command-palette');
  }));
  document.querySelectorAll('[data-diagnostic-tab]').forEach(button => button.addEventListener('click', () => {
    document.querySelectorAll('[data-diagnostic-tab]').forEach(item => item.classList.toggle('active', item === button));
    document.querySelectorAll('[data-diagnostic-content]').forEach(item => item.classList.toggle('active', item.dataset.diagnosticContent === button.dataset.diagnosticTab));
  }));
  ['diagnostic-filter-severity', 'diagnostic-filter-wall'].forEach(id => byId(id).addEventListener('change', filterDiagnosticProblems));
  byId('diagnostic-filter-text').addEventListener('input', filterDiagnosticProblems);
  byId('diagnostics-conflicts').addEventListener('click', event => {
    const button = event.target.closest('[data-diagnostic-action]');
    if (!button) return;
    const wall = currentWalls.find(item => wallIds(item).has(asString(button.dataset.wallId)));
    if (!wall) return;
    if (button.dataset.diagnosticAction === 'locate') { focusOnWallId(wall.id); showDiagnostics(wall); }
    else if (button.dataset.diagnosticAction === 'isolate') isolateWall(wall);
    else if (button.dataset.diagnosticAction === 'proposals') {
      focusOnWallId(wall.id); generateProposals(false);
    }
  });
  document.querySelectorAll('[data-close-overlay]').forEach(button => button.addEventListener('click', () => byId(button.dataset.closeOverlay).classList.remove('open')));

  document.addEventListener('click', event => {
    const close = event.target.closest('[data-panel-close]');
    if (close) {
      setPanelOpen(byId(close.dataset.panelClose), false);
      if (close.dataset.panelClose === 'section-panel' && state.activeTool === 'section') setTool('select');
    }
    const minimize = event.target.closest('[data-panel-minimize]');
    if (minimize) byId(minimize.dataset.panelMinimize).classList.toggle('minimized');
    const dock = event.target.closest('[data-panel-dock]');
    if (dock) {
      const panel = byId(dock.dataset.panelDock);
      const next = panel.classList.contains('docked-right') ? '' : panel.classList.contains('docked-left') ? 'docked-right' : 'docked-left';
      panel.classList.remove('docked-left', 'docked-right'); if (next) panel.classList.add(next);
    }
    if (!event.target.closest('.editor-popover,#btn-visibility-popover,#btn-more-tools')) closePopovers();
  });

  byId('btn-project-panel').addEventListener('click', () => setPanelOpen(byId('sidebar'), !byId('sidebar').classList.contains('open')));
  byId('close-project-panel').addEventListener('click', () => setPanelOpen(byId('sidebar'), false));
  byId('close-wall-inspector').addEventListener('click', restoreVisibility);
  byId('wall-details').addEventListener('click', () => byId('wall-inspector').classList.toggle('details-open'));
  document.querySelectorAll('[data-editor-tool]').forEach(button => button.addEventListener('click', () => setTool(button.dataset.editorTool)));
  document.querySelectorAll('[data-nav-tool]').forEach(button => button.addEventListener('click', () => setNavigationTool(button.dataset.navTool)));
  document.querySelectorAll('[data-nav-action]').forEach(button => button.addEventListener('click', () => {
    if (button.dataset.navAction === 'extents') frameCamera(currentWalls, currentEntities);
    else if (button.dataset.navAction === 'selection') focusSelected();
    else animateToView('iso');
  }));

  byId('btn-realtime').addEventListener('click', () => {
    state.realtime = !state.realtime; window.editorRealtimeEnabled = state.realtime;
    byId('btn-realtime').classList.toggle('active', state.realtime);
    showToast(state.realtime ? 'Modulação em tempo real ativada' : 'Prévia em tempo real pausada', state.realtime ? 'ok' : 'warning');
  });
  byId('snap-step').addEventListener('change', event => {
    window.editorSnapCm = event.target.value === 'project' ? Number(window.editorProjectModuleCm || 20) : Number(event.target.value);
    const label = window.editorSnapCm === 0 ? 'desligado' : window.editorSnapCm < 1 ? `${window.editorSnapCm * 10}mm` : `${window.editorSnapCm * 10}mm`;
    byId('status-snap').textContent = `Snap: ${label}`; byId('status-scale').textContent = `Movimento: ${label}`;
  });
  byId('btn-isolate-selected').addEventListener('click', isolateSelected);
  byId('btn-hide-selected').addEventListener('click', hideSelected);
  byId('btn-show-all').addEventListener('click', restoreVisibility);
  byId('btn-wall-mode').addEventListener('click', () => {
    const wall = currentWall() || currentWalls[0];
    if (wall) isolateWall(wall); else setStatus('Carregue um modelo com paredes.', true);
  });
  byId('btn-proposals').addEventListener('click', () => generateProposals(false));
  byId('btn-generate-proposals').addEventListener('click', () => generateProposals(false));
  byId('btn-generate-project-proposals').addEventListener('click', () => generateProposals(true));
  byId('btn-discard-proposal').addEventListener('click', discardProposalPreview);
  byId('diagnostics-proposals').addEventListener('click', event => {
    const button = event.target.closest('[data-proposal-action]');
    if (!button) return;
    if (button.dataset.proposalAction === 'preview') previewProposal(button.dataset.proposalId);
    else if (button.dataset.proposalAction === 'apply') applyProposal(button.dataset.proposalId);
  });
  byId('btn-diagnostic-mode').addEventListener('click', () => setVisualMode(byId('display-mode').value === 'diagnostic' ? 'realistic' : 'diagnostic'));
  byId('wall-previous').addEventListener('click', () => navigateWall(-1));
  byId('wall-next').addEventListener('click', () => navigateWall(1));
  byId('wall-isolate').addEventListener('click', () => isolateWall(currentWall()));
  byId('wall-connected').addEventListener('click', () => showConnected(currentWall()));
  byId('wall-only-blocks').addEventListener('click', () => isolateWall(currentWall(), 'blocks'));
  byId('wall-only-openings').addEventListener('click', () => isolateWall(currentWall(), 'openings'));
  byId('wall-elevation').addEventListener('click', () => viewWallElevation(currentWall(), false));
  byId('wall-front').addEventListener('click', () => viewWallElevation(currentWall(), false));
  byId('wall-side').addEventListener('click', () => viewWallElevation(currentWall(), true));
  byId('wall-course').addEventListener('click', () => { state.courseLabels = true; rebuildCourseLabels(); byId('toolbar-course-filter').focus(); });
  byId('wall-diagnostic').addEventListener('click', () => { setVisualMode('diagnostic'); showDiagnostics(currentWall()); });
  byId('wall-3d').addEventListener('click', () => { setProjectionMode(false); animateToView('iso'); });
  byId('wall-restore').addEventListener('click', restoreVisibility);
  byId('btn-course-labels').addEventListener('click', () => { state.courseLabels = !state.courseLabels; byId('btn-course-labels').classList.toggle('active', state.courseLabels); rebuildCourseLabels(); });

  byId('selection-panel').addEventListener('click', event => {
    if (event.target.closest('[data-apply-opening]')) applyOpeningProperties();
    else if (event.target.closest('[data-apply-wall]')) applyWallProperties();
    else if (event.target.closest('[data-generate-proposals]')) generateProposals(false);
    else if (event.target.closest('[data-wall-view]')) isolateWall(currentWall());
    else if (event.target.closest('[data-duplicate-opening]')) {
      const opening = selectedObject && selectedObject.userData.opening;
      if (opening) postEditorAction('/api/duplicate-opening', { opening_id: opening.element_id, delta_cm: 10 }, 'Abertura duplicada');
    } else if (event.target.closest('[data-delete-opening]')) {
      const opening = selectedObject && selectedObject.userData.opening;
      if (opening && window.confirm(`Excluir a abertura ${opening.element_id}? Esta ação poderá ser desfeita pelo histórico.`)) {
        postEditorAction('/api/delete-opening', { opening_id: opening.element_id }, 'Abertura excluída');
      }
    }
  });
  byId('quick-edit-bar').addEventListener('click', event => {
    const opening = selectedObject && selectedObject.userData.opening;
    const shift = event.target.closest('[data-quick-shift]');
    if (shift) shiftOpening(opening, Number(shift.dataset.quickShift));
    if (event.target.closest('[data-quick-properties]')) { syncSelectionPanel(); byId('selection-panel').classList.remove('minimized'); }
  });

  let hoverFrame = null;
  canvasEl.addEventListener('pointerdown', event => {
    state.additiveSelection = Boolean(event.ctrlKey || event.metaKey);
  }, true);
  canvasEl.addEventListener('click', () => window.setTimeout(() => { state.additiveSelection = false; }, 0));
  canvasEl.addEventListener('pointermove', event => {
    const point = worldPointAt(event.clientX, event.clientY);
    if (point) byId('status-coordinates').textContent = `X ${(point.x / 100).toFixed(2)} · Y ${(point.y / 100).toFixed(2)} · Z ${(point.z / 100).toFixed(2)}m`;
    if (!hoverFrame) hoverFrame = requestAnimationFrame(() => { hoverFrame = null; updateHover(event); });
  });
  canvasEl.addEventListener('pointerleave', () => { clearHover(); setSectionHover(null); requestRender(); });
  canvasEl.addEventListener('click', event => {
    const markerWall = diagnosticHit(event);
    if (markerWall) { showDiagnostics(markerWall); focusOnWallId(markerWall.id); return; }
    window.setTimeout(syncSelectionPanel, 0);
    if (state.activeTool === 'measure') {
      const point = worldPointAt(event.clientX, event.clientY); if (!point) return;
      if (!state.measureStart) { state.measureStart = point.clone(); setStatus(`Primeiro ponto: X ${(point.x / 100).toFixed(2)} · Y ${(point.y / 100).toFixed(2)}m`); }
      else { const distance = point.distanceTo(state.measureStart); setStatus(`Medição: ${(distance / 100).toFixed(3)}m (${distance.toFixed(1)}cm)`); state.measureStart = null; showToast(`Medição ${(distance / 100).toFixed(3)}m`); }
    }
  });
  canvasEl.addEventListener('dblclick', event => {
    const hit = pickObjectAt(event.clientX, event.clientY);
    if (hit) { selectObject(hit.object, hit.instanceId); focusSelected(); syncSelectionPanel(); }
  });

  canvasEl.addEventListener('contextmenu', event => {
    const hit = pickObjectAt(event.clientX, event.clientY);
    const menu = byId('element-context-menu');
    if (!hit || hit.object.userData.kind === 'opening') { menu.style.display = 'none'; return; }
    selectObject(hit.object, hit.instanceId); syncSelectionPanel();
    const rect = viewport.getBoundingClientRect();
    menu.style.left = Math.max(8, Math.min(rect.width - 215, event.clientX - rect.left)) + 'px';
    menu.style.top = Math.max(52, Math.min(rect.height - 350, event.clientY - rect.top)) + 'px';
    menu.style.display = 'block';
  });
  byId('element-context-menu').addEventListener('click', event => {
    const action = event.target.closest('[data-context-action]'); if (!action) return;
    byId('element-context-menu').style.display = 'none'; handleContextAction(action.dataset.contextAction);
  });
  byId('opening-context-menu').addEventListener('click', event => {
    const action = event.target.closest('[data-opening-action]');
    if (action) { hideOpeningContextMenu(); handleOpeningMenu(action.dataset.openingAction); }
  });

  byId('toolbar-display-mode').addEventListener('change', event => setVisualMode(event.target.value));
  byId('display-mode').addEventListener('change', () => {
    byId('toolbar-display-mode').value = byId('display-mode').value; rebuildDiagnosticMarkers(); syncVisibilityPopover();
  });
  byId('toolbar-course-filter').addEventListener('change', event => {
    byId('course-filter').value = event.target.value;
    byId('course-filter').dispatchEvent(new Event('change'));
    byId('status-course').textContent = event.target.value === '' ? 'Fiada: Todas' : `Fiada: ${Number(event.target.value) + 1}`;
    rebuildCourseLabels();
  });
  byId('course-previous').addEventListener('click', () => stepCourse(-1));
  byId('course-next').addEventListener('click', () => stepCourse(1));
  byId('projection-mode').addEventListener('click', () => setProjectionMode(!state.orthographicLike));
  byId('toggle-shadows').addEventListener('click', () => { state.shadows = !state.shadows; byId('toggle-shadows').classList.toggle('active', state.shadows); updateThemeAndShadows(); });
  byId('footer-section').addEventListener('click', () => setPanelOpen(byId('section-panel'), !byId('section-panel').classList.contains('open')));
  byId('btn-theme').addEventListener('click', () => setTheme(document.documentElement.dataset.theme === 'light' ? 'dark' : 'light'));
  byId('view-reset').addEventListener('click', () => { setProjectionMode(false); animateToView('iso'); });
  byId('cube-home').addEventListener('click', () => { setProjectionMode(false); animateToView('iso'); });
  byId('btn-cancel-action').addEventListener('click', cancelActiveAction);

  byId('section-live-enabled').addEventListener('change', applyLiveSection);
  byId('section-live-axis').addEventListener('change', event => { if (event.target.value === 'wall') setSectionPositionCm(0); applyLiveSection(); });
  byId('section-live-slider').addEventListener('input', event => { byId('section-live-position').value = (Number(event.target.value) / 100).toFixed(2); applyLiveSection(); });
  byId('section-live-position').addEventListener('input', event => { byId('section-live-slider').value = Math.round(Number(event.target.value) * 100); applyLiveSection(); });
  byId('section-through-selection').addEventListener('click', () => {
    const center = selectedCenter(); if (!center) return;
    const axis = byId('section-live-axis').value;
    byId('section-live-position').value = ((axis === 'x' ? center.x : axis === 'y' ? center.y : center.z) / 100).toFixed(2);
    byId('section-live-slider').value = Math.round(Number(byId('section-live-position').value) * 100);
    byId('section-live-enabled').checked = true; applyLiveSection();
  });
  byId('section-invert').addEventListener('click', () => {
    const before = sectionSnapshot();
    state.sectionInverted = !state.sectionInverted;
    byId('section-invert').classList.toggle('active', state.sectionInverted);
    applyLiveSection();
    pushSectionHistory(before, sectionSnapshot());
    showToast('Lado visível do corte invertido.', 'ok');
  });
  byId('section-disable').addEventListener('click', () => { byId('section-live-enabled').checked = false; applyLiveSection(); });

  byId('btn-search').addEventListener('click', () => openOverlay('element-search'));
  byId('btn-command-palette').addEventListener('click', () => openOverlay('command-palette'));
  byId('element-search-input').addEventListener('input', event => {
    const query = event.target.value.trim().toLowerCase();
    renderResults(byId('element-search-results'), searchableElements().filter(item => !query || `${item.label} ${item.detail}`.toLowerCase().includes(query)));
  });
  byId('command-input').addEventListener('input', event => {
    const query = event.target.value.trim().replace(/^>/, '').toLowerCase();
    renderResults(byId('command-results'), commandItems().filter(item => !query || `${item.label} ${item.detail}`.toLowerCase().includes(query)));
  });
  document.querySelectorAll('.command-overlay').forEach(overlay => overlay.addEventListener('mousedown', event => { if (event.target === overlay) closeOverlays(); }));

  window.addEventListener('keydown', event => {
    const key = event.key.toLowerCase();
    const editingField = Boolean(event.target && event.target.closest && event.target.closest('input,textarea,select,[contenteditable="true"]'));
    if (state.sectionDrag && event.key === 'Escape') { finishSectionDrag(event, true); return; }
    if ((event.ctrlKey || event.metaKey) && key === 'z' && !event.shiftKey && state.sectionUndo.length) {
      event.preventDefault(); event.stopImmediatePropagation(); undoSection(); return;
    }
    if ((event.ctrlKey || event.metaKey) && (key === 'y' || (key === 'z' && event.shiftKey)) && state.sectionRedo.length) {
      event.preventDefault(); event.stopImmediatePropagation(); redoSection(); return;
    }
    if ((event.ctrlKey || event.metaKey) && key === 'f') { event.preventDefault(); event.stopImmediatePropagation(); openOverlay('element-search'); return; }
    if ((event.ctrlKey || event.metaKey) && (key === 'k' || key === 'p')) { event.preventDefault(); event.stopImmediatePropagation(); openOverlay('command-palette'); return; }
    if (!editingField && !event.ctrlKey && !event.metaKey && !event.altKey && !event.repeat) {
      if ((event.key === 'Delete' || event.key === 'Backspace') && selectedOpeningId) {
        const opening = currentOpenings.find(item => asString(item.element_id) === asString(selectedOpeningId));
        if (opening) {
          event.preventDefault();
          postEditorAction('/api/delete-opening', { opening_id: opening.element_id }, 'Abertura excluída');
          return;
        }
      }
      const shortcuts = {
        s: () => { setNavigationTool('select'); setTool('select'); },
        o: () => setNavigationTool('orbit'),
        p: () => setNavigationTool('pan'),
        z: () => setNavigationTool('zoom'),
        f: focusSelected,
        m: () => setTool('move'),
        r: () => setTool('rotate'),
        c: () => setTool('section'),
        i: isolateSelected,
        h: hideSelected,
        f1: () => openOverlay('help-overlay'),
      };
      if (shortcuts[key]) { event.preventDefault(); shortcuts[key](); return; }
    }
    if (event.key === 'Escape') { closeOverlays(); if (editSession || state.measureStart || state.activeEditorRequest) cancelActiveAction(); }
    if (event.shiftKey && event.key === 'ArrowLeft') { event.preventDefault(); navigateWall(-1); }
    if (event.shiftKey && event.key === 'ArrowRight') { event.preventDefault(); navigateWall(1); }
    if (event.key === 'Enter' && document.querySelector('.command-overlay.open')) {
      const row = document.querySelector('.command-overlay.open .command-result.active'); if (row) row.click();
    }
  }, true);

  byId('btn-undo').addEventListener('click', event => {
    if (!state.sectionUndo.length) return;
    event.preventDefault(); event.stopImmediatePropagation(); undoSection();
  }, true);
  byId('btn-redo').addEventListener('click', event => {
    if (!state.sectionRedo.length) return;
    event.preventDefault(); event.stopImmediatePropagation(); redoSection();
  }, true);

  ['view-top', 'view-front', 'view-side', 'view-iso'].forEach(id => byId(id).addEventListener('click', event => {
    event.stopImmediatePropagation(); animateToView({ 'view-top': 'top', 'view-front': 'front', 'view-side': 'side', 'view-iso': 'iso' }[id]);
  }, true));
  document.querySelectorAll('#view-cube [data-view]').forEach(button => button.addEventListener('click', event => {
    event.stopImmediatePropagation(); animateToView(button.dataset.view);
  }, true));

  controls.addEventListener('change', updateQuickEdit);
  window.addEventListener('editor:selection-changed', event => {
    handleSelectionChanged(event.detail || {});
    window.setTimeout(() => {
      syncSelectionPanel();
      if (state.multiSelection.length > 1) renderMultiSelectionPanel();
      rebuildDiagnosticDock();
    }, 0);
  });
  window.addEventListener('editor:model-rendered', event => {
    const detail = event.detail || {};
    if (detail.data && detail.data.dependency_graph) state.dependencyGraph = detail.data.dependency_graph;
    if (state.isolatedWallId || state.connectedWallIds || state.hiddenWallIds.size || state.hiddenOpeningIds.size || state.highlightBlockCode) applyEditorVisibility();
    updateProjectName(); updateProjectSnap(detail.data || {}); rebuildCourseFilter(); rebuildCourseLabels(); rebuildDiagnosticMarkers(); rebuildDiagnosticDock(); updateStatusSelection();
    appendDiagnosticLog(detail.options && detail.options.preview ? 'Prévia geométrica atualizada.' : `Modelo renderizado · ${currentWalls.length} parede(s) · ${currentBlockCandidates.length} bloco(s).`);
    if (detail.options && detail.options.preview) showPreviewFeedback(detail.data || {}); else clearThreeGroup(previewFeedbackGroup);
    if (byId('section-live-enabled').checked) applyLiveSection(true);
    const wall = currentWall(); if (wall && byId('wall-inspector').classList.contains('open')) updateWallInspector(wall);
    renderPerformance(detail.data || {});
  });
  window.addEventListener('editor:drag-state', event => {
    if (event.detail && event.detail.active) beginFpsMeasurement(); else endFpsMeasurement();
  });

  const statusObserver = new MutationObserver(() => {
    const message = byId('status-message').textContent.trim();
    const processing = /carregando|processando|recalculando|atualizando|analisando|convertendo|prévia calculad/i.test(message);
    byId('processing-indicator').classList.toggle('active', processing);
    const processLabel = byId('processing-indicator').querySelector('b');
    if (processLabel && processing) processLabel.textContent = message.split(/[.…]/)[0].slice(0, 28) || 'Processando';
    if (!message || message === 'Pronto' || /Prévia|Primeiro ponto|Recalculando|Atualizando/.test(message)) return;
    appendDiagnosticLog(message.split('\n')[0]);
    if (/conclu|atualiz|modulad|restaurad|desfeit|refeit/i.test(message)) showToast(message.split('\n')[0], 'ok');
    else if (byId('status-message').classList.contains('status-error')) showToast(message.split('\n')[0], 'error');
  });
  statusObserver.observe(byId('status-message'), { childList: true, characterData: true, subtree: true, attributes: true });

  const historyObserver = new MutationObserver(() => rebuildDiagnosticDock());
  historyObserver.observe(byId('history-list'), { childList: true, characterData: true, subtree: true });
  byId('dxf-path').addEventListener('input', updateProjectName);

  const toolbar = byId('top-toolbar');
  const appBar = byId('app-bar');
  const syncToolbarHeight = () => document.documentElement.style.setProperty('--topbar-height', `${appBar.offsetHeight + toolbar.offsetHeight}px`);
  const chromeObserver = new ResizeObserver(syncToolbarHeight);
  chromeObserver.observe(toolbar); chromeObserver.observe(appBar); syncToolbarHeight();
  setNavigationTool('select');
  updateProjectName();
  updateProjectSnap({});
  updateStatusSelection();
})();
