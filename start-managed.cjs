const {spawn} = require('child_process');
const {existsSync} = require('fs');
const path = require('path');

const root = __dirname;
const python = path.join(root, '.venv', 'Scripts', 'python.exe');
const entry = path.join(root, 'run_service.py');
const [lane, replacePid, ...extra] = process.argv.slice(2);
if (!['local', 'lan'].includes(lane) || extra.length || (replacePid !== undefined && !/^[1-9]\d{0,9}$/.test(replacePid))) {
  throw new Error('Usage: start-managed.cjs local|lan [verified-old-listener-pid]');
}
if (![python, entry].every(existsSync)) throw new Error('Existing Hub runtime or start entry is missing');
if (lane === 'lan' && !['server.crt', 'server.key'].every(name => existsSync(path.join(root, 'state', 'tls', name)))) {
  throw new Error('Existing LAN TLS files are missing; no restart');
}
let child;
let stopping = false;
function run(script, args, onExit) {
  child = spawn(python, ['-B', path.join(root, script), ...args], {cwd: root, stdio: 'inherit'});
  child.on('error', error => { console.error(error.message); process.exitCode = 1; });
  child.on('exit', (code) => {
    if (code === 0 && !stopping && onExit) onExit();
    else process.exitCode = code ?? 1;
  });
}
process.on('SIGTERM', () => { stopping = true; child?.kill(); });
const start = () => run('run_service.py', [lane]);
// The same accepted managed job owns both the guarded stop and the new service.
// An approval refusal or a mismatched PID cannot leave a healthy lane stopped.
if (replacePid) run('deploy_case_data_lane_stop.py', [lane, replacePid], start);
else start();
