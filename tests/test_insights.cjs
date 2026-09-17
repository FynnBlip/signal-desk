const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const ctx = vm.createContext({document:{addEventListener(){}}, esc:s=>String(s)});
vm.runInContext(fs.readFileSync('app/insights.js','utf8'),ctx);
// Missing V2 must not move V3 into its place or connect across missing evidence.
const svg=vm.runInContext("insightPlot([5,null,6,7],{label:'test'})",ctx);
assert.match(svg,/v2 未测/);
assert.match(svg,/M 42 .* M 251/);
assert.doesNotMatch(svg,/NaN/);
assert.equal(vm.runInContext('insightNumber(null)',ctx),null);
assert.equal(vm.runInContext('insightNumber(Infinity)',ctx),null);
assert.match(vm.runInContext("insightPlot([null,null,null,null],{})",ctx),/尚无可比较/);
// A scene must be matched by name AND SNR, never by an arbitrary row position.
assert.equal(vm.runInContext(`JSON.stringify(insightScores({noise_label:'metro',snr_db:-10},{scenes:[{noise_label:'metro',snr_db:0,scores:{v1:9}},{noise_label:'metro',snr_db:-10,scores:{v1:4,v3:5}}]}))`,ctx),'[4,null,5,null]');
console.log('Chart evidence tests passed (missing data, fixed positions, scene identity).');
