const {spawn}=require('node:child_process');const path=require('node:path');
const child=spawn(path.join(__dirname,'.venv','Scripts','python.exe'),['-B',path.join(__dirname,'verify_mobile_flow_server.py')],{cwd:__dirname,stdio:'inherit'});
child.on('exit',c=>process.exit(c??1));
