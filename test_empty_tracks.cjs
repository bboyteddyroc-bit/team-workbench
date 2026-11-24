const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const s=fs.readFileSync('static/multitrack-view.js','utf8'),ctx={};vm.createContext(ctx);vm.runInContext(s.slice(s.indexOf('  function trackInfo'),s.indexOf('  function volumeChip'))+'\nthis.pending=pendingTracks;',ctx);
const b={tracks:[{id:'a'},{id:'b'},{id:'c'}],clips:[{track:'a'}],captions:[],audio_clips:[],stickers:[]};
const ids=()=>Array.from(ctx.orderedRows(b),r=>r.track.id);
assert.deepEqual(ids(),['a']);b.clips[0].track='b';assert.deepEqual(ids(),['b']);b.clips[0].track='a';assert.deepEqual(ids(),['a']);ctx.pending.add('c');assert.deepEqual(ids(),['a','c']);b.stickers.push({track:'c'});ids();b.stickers=[];assert.deepEqual(ids(),['a']);b.audio_clips.push({track:'b'});assert.deepEqual(ids(),['a','b']);
console.log('PASS empty track visibility: move, restore, explicit add, sticker removal, audio retention');
