// Channel markup, mode controls and applied-value summaries reused from the ESP32 web page.
const analog=m=>['sine','triangle','rectangle'].includes(m);
function enableSections(form){if(!form.elements.mode)return;const mode=form.elements.mode.value;
for(const section of form.querySelectorAll('[data-section]')){const kind=section.dataset.section;const visible=kind==='timing'?(mode==='pulse'||mode==='burst'):kind==='analog'?analog(mode):mode===kind;section.hidden=!visible;for(const input of section.querySelectorAll('input'))input.disabled=!visible;}
const enable=form.querySelector('[data-enable]');enable.hidden=mode==='burst';form.elements.enabled.disabled=mode==='burst';
const start=form.querySelector('[data-start]');start.hidden=mode!=='burst';start.disabled=form.dataset.appliedMode!=='burst'||form.dataset.dirty==='1';}
function summary(c){if(c.id<3)return (c.duty===0||c.duty===100?'Constant output when enabled':'Applied frequency: '+c.actualHz.toFixed(3)+' Hz')+'<br>Applied duty (before dead time): '+c.actualDuty.toFixed(3)+'%<br>High / low on-time: '+c.highDuty.toFixed(3)+'% / '+c.lowDuty.toFixed(3)+'%<br>Actual dead time: '+c.actualDeadUs.toFixed(3)+' µs';
if(analog(c.mode))return 'Applied mode: '+c.mode+'<br>Nominal actual frequency: '+c.actualWaveHz.toFixed(3)+' Hz<br>Amplitude: '+c.amplitude+'%';
if(c.mode==='burst')return 'Burst frequency: '+c.actualHz.toFixed(3)+' Hz<br>'+c.pulseCount+' pulses × '+c.burstCount+' bursts<br>Completed bursts: '+c.completedBursts;
return 'Actual frequency: '+c.actualHz.toFixed(3)+' Hz<br>Actual duty: '+c.actualDuty.toFixed(3)+'%';}
function channelHTML(c){
const pair=c.id<3;
return `<form data-id="${c.id}" data-applied-mode="${c.mode}"><h2>${pair?'Pair '+(c.id+1):'Waveform '+(c.id-2)} <span class="badge">${c.enabled?'ON':'OFF'}</span></h2><p class="pins">${pair?'High-side: GPIO'+c.highPin+'<br>Low-side: GPIO'+c.lowPin:'Output: GPIO'+c.highPin}</p>
${pair?`<label>Frequency (Hz)<input name="frequency" type="number" min="0" max="100000" step="any" value="${c.frequency}" required></label><small>1–100000 Hz, or 0 to disable</small>
<label>Duty (%)<input name="duty" type="number" min="0" max="100" step="any" value="${c.duty}" required></label><label>Dead time (µs)<input name="deadUs" type="number" min="0" max="1000" step="any" value="${c.deadUs}" required></label>`:
`<label>Output mode<select name="mode">${[['pulse','Continuous pulse'],['burst','Pulse burst'],['sine','Sine (analog)'],['triangle','Triangle (analog)'],['rectangle','Rectangle (analog)']].map(([v,label])=>'<option value="'+v+'" '+(c.mode===v?'selected':'')+'>'+label+'</option>').join('')}</select></label>
<section data-section="timing"><label>On time (µs)<input name="onUs" type="number" min="1" max="30000" step="1" value="${c.onUs}" required></label><label>Off time (µs)<input name="offUs" type="number" min="1" max="30000" step="1" value="${c.offUs}" required></label></section>
<section data-section="burst"><label>Pulses per burst<input name="pulseCount" type="number" min="1" max="255" step="1" value="${c.pulseCount}" required></label><label>Number of bursts<input name="burstCount" type="number" min="1" max="1000" step="1" value="${c.burstCount}" required></label><label>Pause between bursts (ms)<input name="gapMs" type="number" min="0" max="60000" step="1" value="${c.gapMs}" required></label><small>Apply settings, then press Start bursts. Each burst has an exact pulse count; the extra pause is approximate. Example: 10 pulses × 3 bursts = 30 pulses total.</small></section>
<section data-section="analog"><label>Waveform frequency (Hz)<input name="waveHz" type="number" min="10" max="5000" step="any" value="${c.waveHz}" required></label><label>Amplitude (%)<input name="amplitude" type="number" min="0" max="100" step="any" value="${c.amplitude}" required></label></section>`}
<label data-enable>Enable output<input name="enabled" type="checkbox" ${c.enabled?'checked':''}></label><p class="actual">${summary(c)}</p><p class="feedback" role="status"></p><button type="submit">Apply channel</button>
${pair?'':'<button type="button" data-start="'+c.id+'">Start bursts</button>'} <button type="button" class="stop" data-stop="${c.id}">Stop</button></form>`;
}
function render(data){const channels=document.getElementById('channels');channels.innerHTML=data.map(channelHTML).join('');for(const form of channels.querySelectorAll('form'))enableSections(form);}
