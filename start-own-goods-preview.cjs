// Isolated preview with the app's existing Python environment; no team service restart.
const {spawn}=require('node:child_process');
const path=require('node:path');
const child=spawn(path.join(__dirname,'.venv','Scripts','python.exe'),['-B',path.join(__dirname,'preview_own_goods.py')],{cwd:__dirname,stdio:'inherit'});
child.on('error',e=>{console.error(e);process.exitCode=1;});
child.on('exit',code=>{process.exitCode=code??1;});
process.on('SIGTERM',()=>child.kill());
