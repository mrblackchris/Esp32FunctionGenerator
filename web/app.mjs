import {SerialTransport} from './serial.mjs';
import {HttpTransport} from './http.mjs';

const $ = id => document.getElementById(id);
const status = $('status'), channels = $('channels'), networkForm = $('networkForm');
let transport = null;
const hosted = window.FG_DEVICE_PAGE === true;
if (hosted) { $('connectionMode').value = 'http'; $('deviceAddress').value = location.origin; }
let connected = false, connecting = false, pending = 0, polling = false;
let connectionRevision = 0, networkRevision = 0, networkLoaded = false;
let lastNetwork = null, pollFailures = 0;
const supported = window.isSecureContext && 'serial' in navigator;

function applyBusyState() {
  const wifi = $('connectionMode').value === 'http';
  $('connect').disabled = (!wifi && !supported) || connected || connecting;
  $('connectionMode').disabled = connected || connecting;
  $('deviceAddress').disabled = connected || connecting;
  $('deviceAddressLabel').hidden = !wifi;
  $('disconnect').disabled = !connected;
  $('stopAll').disabled = !connected;
  $('networkRead').disabled = !connected || pending > 0;
  $('networkEdit').disabled = !connected || !networkLoaded;
  $('networkSave').disabled = !connected || !networkLoaded || pending > 0;
  networkSections();
  for (const form of channels.querySelectorAll('form')) {
    enableSections(form);
    if (!connected) for (const field of form.querySelectorAll('input,select')) field.disabled = true;
    for (const b of form.querySelectorAll('button')) {
      b.disabled = !connected || (!b.hasAttribute('data-stop') && (pending > 0 ||
        (b.hasAttribute('data-start') && (form.dataset.appliedMode !== 'burst' || form.dataset.dirty === '1'))));
    }
  }
  $('connectionBadge').textContent = connected ? ($('connectionMode').value === 'http' ? 'Wi-Fi connected' : 'USB connected') : connecting ? 'Connecting…' : 'Not connected';
  $('connectionBadge').classList.toggle('connected', connected);
}

function networkSections() {
  const f = networkForm.elements;
  f.password.disabled = !f.replacePassword.checked;
  f.password.type = $('showPassword').checked ? 'text' : 'password';
  for (const key of ['ip', 'gateway', 'subnet', 'dns']) {
    f[key].disabled = f.dhcp.checked;
    f[key].required = !f.dhcp.checked;
  }
}

function updateChannels(data, load = null) {
  if (!Array.isArray(data) || data.length !== 5) throw new Error('Unexpected channel response. Update the ESP32 firmware.');
  if (!channels.querySelector('form')) render(data);
  for (const c of data) {
    let form = channels.querySelector(`form[data-id="${c.id}"]`);
    if (!form) throw new Error('Unexpected channel ID.');
    if (load && load.id === String(c.id) && (form.dataset.revision || '0') === load.revision) {
      form.outerHTML = channelHTML(c);
      form = channels.querySelector(`form[data-id="${c.id}"]`);
      form.querySelector('.feedback').textContent = 'Channel settings applied.';
    }
    form.querySelector('.badge').textContent = c.enabled ? 'ON' : 'OFF';
    form.querySelector('.actual').innerHTML = summary(c);
    if (form.dataset.dirty !== '1') form.elements.enabled.checked = c.enabled;
    form.dataset.appliedMode = c.mode;
  }
  $('empty').hidden = true;
  applyBusyState();
}

function updateNetwork(data, load = false) {
  if (!data || typeof data.ssid !== 'string') throw new Error('Unexpected network response. Update the ESP32 firmware.');
  lastNetwork = data;
  $('networkStatus').textContent = `${data.connected ? 'Connected' : 'Not connected'} · ${data.ssid}\n` +
    `Current IP: ${data.currentIP} · ${data.dhcp ? 'DHCP' : 'Static IP'}\n` +
    `Gateway: ${data.currentGateway} · Subnet: ${data.currentSubnet} · DNS: ${data.currentDns}\n` +
    `Saved password: ${data.passwordSet ? 'set (hidden)' : 'none / open network'}`;
  if (load || !networkLoaded) {
    for (const key of ['ssid', 'ip', 'gateway', 'subnet', 'dns']) networkForm.elements[key].value = data[key];
    networkForm.elements.dhcp.checked = data.dhcp;
    networkForm.elements.password.value = '';
    networkForm.elements.replacePassword.checked = false;
    $('showPassword').checked = false;
    networkForm.dataset.dirty = '0';
    $('networkFeedback').textContent = 'Saved settings read from ESP32. The password is hidden.';
    networkLoaded = true;
  }
  applyBusyState();
}

async function connect() {
  if (connected || connecting) return;
  connecting = true;
  const revision = ++connectionRevision;
  applyBusyState();
  status.textContent = $('connectionMode').value === 'http' ? 'Connecting to the ESP32 over HTTP…' : 'Select your ESP32 in the browser USB serial dialog…';
  try {
    // The browser chooser must be called directly from a button click.
    if ($('connectionMode').value === 'http') {
      transport = new HttpTransport();
      await transport.open($('deviceAddress').value);
    } else {
      const port = await navigator.serial.requestPort();
      if (revision !== connectionRevision) return;
      transport = new SerialTransport();
      await transport.open(port);
    }
    transport.addEventListener('disconnect', () => {
      if (connected || connecting) disconnect('Connection lost. Reconnect to read device state.');
    });
    status.textContent = 'Reading ESP32 settings… Waiting for startup if the USB adapter reset the board.';
    let data;
    for (let attempt = 0; attempt < 4; ++attempt) {
      if (revision !== connectionRevision) return;
      try { data = await transport.request('/state', {}, 3000); break; }
      catch (error) {
        if (!error.message.includes('timed out') || attempt === 3) throw error;
      }
    }
    if (revision !== connectionRevision) return;
    const network = await transport.request('/network');
    if (revision !== connectionRevision) return;
    channels.replaceChildren();
    networkLoaded = false;
    connected = true;
    updateChannels(data);
    updateNetwork(network, true);
    pollFailures = 0;
    status.textContent = 'Connected. Displays show applied settings; press Apply after editing.';
  } catch (error) {
    if (revision === connectionRevision) {
      connected = false;
      status.textContent = error.name === 'NotFoundError' ? 'Connection cancelled. Click Connect USB to try again.' : 'Could not connect: ' + error.message;
      await transport?.close();
    }
  } finally {
    if (revision === connectionRevision) { connecting = false; applyBusyState(); }
  }
}

async function disconnect(message = 'Disconnected. Outputs retain their last applied state.') {
  const revision = ++connectionRevision;
  connected = false;
  connecting = true;
  status.textContent = message;
  applyBusyState();
  await transport?.close();
  if (revision === connectionRevision) {
    connecting = false;
    pending = 0;
    applyBusyState();
  }
}

async function action(path, params, options = {}) {
  if (!connected || (pending > 0 && path !== '/stop')) return;
  const revision = connectionRevision;
  pending++;
  applyBusyState();
  const form = options.form;
  const formRevision = form?.dataset.revision || '0';
  const netRevision = networkRevision;
  status.textContent = path === '/set' ? 'Applying channel…' : path === '/burst' ? 'Starting bursts…' :
    path === '/stop' ? 'Stopping outputs…' : path === '/network/set' ? 'Saving Wi-Fi settings…' : 'Reading saved Wi-Fi settings…';
  try {
    const data = await transport.request(path, params);
    if (revision !== connectionRevision) return;
    if (path.startsWith('/network')) {
      updateNetwork(data, netRevision === networkRevision);
      status.textContent = path === '/network/set' ? 'Network settings saved on ESP32. Wi-Fi reconnecting. If its address changes, reconnect using the new address. USB remains available.' : 'Saved Wi-Fi settings read from ESP32.';
      if (path === '/network/set' && netRevision === networkRevision) $('networkFeedback').textContent = 'Saved in ESP32 flash. Wi-Fi reconnecting…';
    } else {
      updateChannels(data, path === '/set' ? {id: form.dataset.id, revision: formRevision} : null);
      status.textContent = path === '/set' ? (params.mode === 'burst' ? 'Burst settings applied. Press Start bursts.' : 'Channel settings applied.') :
        path === '/burst' ? 'Burst sequence started.' : 'Stop confirmed. ' + (params.id === 'all' ? 'All outputs OFF.' : 'Channel OFF.');
    }
  } catch (error) {
    if (revision !== connectionRevision) return;
    status.textContent = 'Action not confirmed: ' + error.message;
    if (form?.isConnected) form.querySelector('.feedback').textContent = status.textContent;
    if (path === '/network/set') $('networkFeedback').textContent = status.textContent;
  } finally {
    if (revision === connectionRevision) pending = Math.max(0, pending - 1);
    applyBusyState();
  }
}

function changed(form) {
  form.dataset.dirty = '1';
  form.dataset.revision = String(Number(form.dataset.revision || 0) + 1);
  form.querySelector('.feedback').textContent = 'Changes not applied. Press Apply channel.';
  applyBusyState();
}
channels.addEventListener('input', e => { if (e.target.form) changed(e.target.form); });
channels.addEventListener('change', e => { if (e.target.form) changed(e.target.form); });
channels.addEventListener('invalid', e => {
  if (e.target.form) e.target.form.querySelector('.feedback').textContent = 'Check the highlighted field: ' + e.target.validationMessage;
}, true);
channels.addEventListener('submit', e => {
  e.preventDefault();
  const form = e.target;
  const params = Object.fromEntries(new FormData(form));
  params.id = form.dataset.id;
  params.enabled = form.elements.enabled.disabled ? '0' : form.elements.enabled.checked ? '1' : '0';
  action('/set', params, {form});
});
channels.addEventListener('click', e => {
  const button = e.target.closest('button');
  if (!button || button.disabled) return;
  if (button.dataset.stop !== undefined) action('/stop', {id: button.dataset.stop});
  if (button.dataset.start !== undefined) action('/burst', {id: button.dataset.start});
});
$('stopAll').onclick = () => action('/stop', {id: 'all'});
$('connect').onclick = connect;
$('disconnect').onclick = () => disconnect();
$('networkRead').onclick = () => action('/network', {});
networkForm.addEventListener('input', networkChanged);
networkForm.addEventListener('change', networkChanged);
function networkChanged() {
  networkRevision++;
  networkForm.dataset.dirty = '1';
  $('networkFeedback').textContent = 'Network changes not saved.';
  networkSections();
}
networkForm.addEventListener('submit', e => {
  e.preventDefault();
  const f = networkForm.elements;
  const params = {ssid: f.ssid.value, dhcp: f.dhcp.checked ? '1' : '0', replacePassword: f.replacePassword.checked ? '1' : '0'};
  if (new TextEncoder().encode(params.ssid).length > 32) {
    $('networkFeedback').textContent = 'SSID is limited to 32 UTF-8 bytes.'; f.ssid.focus(); return;
  }
  if (f.replacePassword.checked) params.password = f.password.value;
  if (!f.dhcp.checked) for (const key of ['ip', 'gateway', 'subnet', 'dns']) params[key] = f[key].value.trim();
  action('/network/set', params);
});

async function pollLoop() {
  if (connected && !pending && !polling) {
    polling = true;
    const revision = connectionRevision;
    try {
      const state = await transport.request('/state');
      if (revision !== connectionRevision) throw new Error('USB session changed.');
      updateChannels(state);
      if (!pending) {
        const network = await transport.request('/network');
        if (revision !== connectionRevision) throw new Error('USB session changed.');
        updateNetwork(network);
      }
      if (pollFailures) status.textContent = 'USB communication restored. Displays show applied settings.';
      pollFailures = 0;
    } catch (error) {
      if (revision === connectionRevision) {
        status.textContent = 'Device status unavailable: ' + error.message;
        if (++pollFailures >= 3) await disconnect('Device is not responding. Check the USB cable and reconnect.');
      }
    } finally { polling = false; }
  }
  setTimeout(pollLoop, 2000);
}
$('unsupported').hidden = supported;
$('connectionMode').onchange = applyBusyState;
applyBusyState();
pollLoop();

if (hosted) connect();
