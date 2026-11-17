'use strict';
const $ = id => document.getElementById(id);
const token = location.hash.slice(1);
history.replaceState(null, '', location.pathname);
let selected = '', detail = null, polling = false, connected = false, acting = false, refreshing = null;
const labels = {http:'HTTP foundation', events:'Stage log', llm:'Language model', research:'Web research', geocoding:'Place lookup', java:'Java routes', sessions:'Conversation state'};
function node(tag, value, cls) { const el = document.createElement(tag); el.textContent = value; if (cls) el.className = cls; return el; }
function notice(value, error = false) { $('notice').textContent = value; $('notice').className = error ? 'error' : ''; }
async function api(path, method = 'GET', data) {
  const response = await fetch('/lab/' + path, {method, headers:{'X-Lab-Token':token, 'Content-Type':'application/json'}, body:data === undefined ? undefined : JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Invalid lab request.');
  return result;
}
async function action(callback) { if (acting) return; acting = true; try { if (refreshing) await refreshing; await callback(); await refresh(); } catch (error) { notice(error.message, true); } finally { acting = false; } }
function buildKeys() {
  for (const provider of ['groq', 'anthropic', 'exa']) {
    const card = node('div', '', 'connection'); card.append(node('b', provider));
    const status = node('p', '', 'hint'); status.id = 'key_status_' + provider; card.append(status);
    const input = document.createElement('input'); input.type = 'password'; input.autocomplete = 'new-password'; input.placeholder = 'Personal API key'; input.setAttribute('aria-label', provider + ' key'); card.append(input);
    const label = node('label', 'Remember in Windows', 'check'); const remember = document.createElement('input'); remember.type = 'checkbox'; label.prepend(remember); card.append(label);
    const row = node('div', '', 'keyrow');
    for (const [caption, callback] of [
      ['Save', async () => { await api('keys', 'POST', {provider, value:input.value, remember:remember.checked}); input.value = ''; notice('Key accepted. Its value is not returned or used by this diagnostic.'); }],
      ['Remove', async () => { await api('keys/' + provider, 'DELETE'); input.value = ''; notice('Key removed.'); }],
    ]) { const button = node('button', caption, 'secondary'); button.addEventListener('click', () => action(callback)); row.append(button); }
    card.append(row); $('keys').append(card);
  }
}
function renderEvents() {
  $('events').replaceChildren();
  const events = (detail?.events || []).filter(event => $('level').value === 'ALL' || event.level === $('level').value);
  if (!events.length) $('events').append(node('p', 'No matching events.', 'hint'));
  for (const event of events) {
    const box = node('details', '', 'event ' + (['INFO','WARNING','ERROR'].includes(event.level) ? event.level : 'INFO'));
    box.append(node('summary', `${event.level || 'INFO'} · ${event.stage || 'lab'} · ${(event.message || 'Event').slice(0,180)}`), node('pre', JSON.stringify(event, null, 2)));
    $('events').append(box);
  }
}
function showRecord() {
  const hidden = 'Input/output values were not captured. Enable the inspection checkbox before the next run.';
  $('inputData').textContent = detail ? (detail.request === null ? hidden : JSON.stringify(detail.request, null, 2)) : 'No run selected.';
  $('outputData').textContent = detail ? (detail.response === null ? hidden : JSON.stringify(detail.response, null, 2)) : 'No run selected.';
  $('resultStatus').textContent = detail ? `${detail.status.toUpperCase()}${detail.httpStatus ? ' · HTTP ' + detail.httpStatus : ''}` : 'NO RUN YET';
  $('resultStatus').className = 'badge' + (detail?.status === 'failed' ? ' failed' : detail?.status === 'completed' ? ' ready' : '');
  $('runInfo').textContent = detail ? `${detail.options.mode} diagnostic · ${detail.options.timeout_seconds}s limit · ${detail.elapsedMs ?? '…'} ms · trace ${detail.traceId || 'pending / cancelled'} · ${detail.events.length} events` : '';
  $('export').disabled = !detail || detail.status === 'running'; renderEvents();
}
function refresh() {
  if (!refreshing) refreshing = loadState().finally(() => { refreshing = null; });
  return refreshing;
}
async function loadState() {
  const state = await api('status'); connected = true;
  $('capabilities').replaceChildren();
  for (const capability of state.capabilities) {
    const row = node('div', '', 'capability'); row.append(node('span', labels[capability.id]), node('span', capability.available ? 'READY' : 'NOT BUILT YET', 'badge' + (capability.available ? ' ready' : ''))); $('capabilities').append(row);
  }
  for (const [provider, key] of Object.entries(state.keys)) $('key_status_' + provider).textContent = key.present ? (key.saved ? 'Stored in Windows' : 'Process-only key') : 'No key stored';
  $('vault').textContent = state.vaultError ? 'Windows storage could not be read. Process-only storage is available.' : state.vaultAvailable ? 'Remembered keys use a separate Windows vault for this v2 lab.' : 'Windows storage is unavailable. Use process-only keys.';
  for (const checkbox of $('keys').querySelectorAll('input[type=checkbox]')) checkbox.disabled = state.busy || !state.vaultAvailable;
  for (const control of $('keys').querySelectorAll('button, input[type=password]')) control.disabled = state.busy;
  $('run').disabled = state.busy; $('reset').disabled = state.busy; $('cancel').disabled = !state.busy;
  $('busy').textContent = state.busy ? 'Running · no external calls' : 'Ready · diagnostic only';
  $('selectedRun').replaceChildren();
  for (const record of [...state.runs].reverse()) { const option = node('option', `${record.created.slice(11,19)} · ${record.mode} · ${record.status}`); option.value = record.id; $('selectedRun').append(option); }
  if (!state.runs.some(r => r.id === selected)) selected = state.runs.at(-1)?.id || '';
  $('selectedRun').value = selected; detail = selected ? await api('runs/' + selected) : null; showRecord();
}
$('run').addEventListener('click', () => action(async () => {
  const timeout = Number($('timeout').value); if (!(timeout > 0 && timeout <= 60)) throw new Error('Time limit must be above 0 and at most 60 seconds.');
  const result = await api('run', 'POST', {request:{sessionId:$('session').value, message:$('message').value}, mode:$('mode').value, timeout_seconds:timeout, inspect:$('inspect').checked});
  selected = result.runId; notice('Request started. Only the new core is being called.');
}));
$('cancel').addEventListener('click', () => action(async () => { await api('cancel','POST',{}); notice('Cancellation requested.'); }));
$('reset').addEventListener('click', () => action(async () => { await api('reset','POST',{}); selected = ''; detail = null; $('message').value = ''; $('session').value = crypto.randomUUID(); notice('Local reports cleared. Stored keys are unchanged.'); }));
$('selectedRun').addEventListener('change', () => { const value = $('selectedRun').value; action(async () => { selected = value; }); });
$('level').addEventListener('change', renderEvents);
$('export').addEventListener('click', () => action(async () => {
  if (!detail || !confirm('Have you reviewed the input and output? Exported JSON may contain personal text or locations.')) return;
  const report = await api('export/' + detail.id); const url = URL.createObjectURL(new Blob([JSON.stringify(report,null,2)], {type:'application/json'}));
  const link = document.createElement('a'); link.href = url; link.download = 'trego-run-' + detail.id + '.json'; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}));
$('stop').addEventListener('click', async () => { if (acting) return; acting = true; try { if (refreshing) await refreshing; await api('stop','POST',{}); connected = false; for (const button of document.querySelectorAll('button')) button.disabled = true; notice('Lab is stopping. Use the launcher to open it again.'); } catch (error) { notice(error.message, true); } finally { acting = false; } });
$('session').value = crypto.randomUUID(); buildKeys();
if (token) action(async () => { await refresh(); notice('Connected to the local v2 lab. Start with any message.'); });
else { $('run').disabled = true; $('reset').disabled = true; $('stop').disabled = true; }
setInterval(async () => { if (!connected || polling || acting) return; polling = true; try { await refresh(); } catch { connected = false; notice('Lab disconnected. Reopen it with Start-Agent-Lab.cmd.', true); } finally { polling = false; } }, 1000);
