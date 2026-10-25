const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const code=fs.readFileSync('static/js/planning-sync.js','utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function setup({dirty=false,cancel=false,status=200,revision='b'.repeat(64)}={}){
 const dl={},wl={},added=[];let reloads=0,calls=0;
 const document={body:{dataset:{planningSyncUrl:'/planning/sync?scope=student&view=today',planningSyncRevision:'a'.repeat(64)},append:n=>added.push(n)},hidden:false,querySelector:()=>null,addEventListener:(n,fn)=>dl[n]=fn,createElement:tag=>({tag,children:[],setAttribute(){},addEventListener(n,fn){this[n]=fn},append(...items){this.children.push(...items)}})};
 const window={location:{reload(){reloads++}},addEventListener:(n,fn)=>wl[n]=fn,dispatchEvent:e=>!cancel};
 const sandbox={document,window,fetch:async()=>{calls++;return{status,ok:status===200,headers:{get:()=> 'application/json'},json:async()=>({revision})}},CustomEvent:class{constructor(type,opts){this.type=type;Object.assign(this,opts)}},setInterval:fn=>wl.interval=fn};
 if(dirty){sandbox.fetch=()=>new Promise(resolve=>{calls++;wl.resolve=()=>resolve({status,ok:true,headers:{get:()=> 'application/json'},json:async()=>({revision})})});}
 vm.runInNewContext(code,sandbox);
 return {document,dl,wl,added,get reloads(){return reloads},get calls(){return calls}};
}
(async()=>{
 let c=setup();await tick();assert.equal(c.reloads,1);
 c=setup({revision:'a'.repeat(64)});await tick();assert.equal(c.reloads,0);
 c=setup({cancel:true});await tick();assert.equal(c.reloads,0);assert.equal(c.added.length,0);
 c=setup({status:401});await tick();c.wl.interval();await tick();assert.equal(c.calls,1);assert.equal(c.reloads,0);
 c=setup({dirty:true});c.dl.input({target:{matches:()=>true}});c.wl.resolve();await tick();assert.equal(c.reloads,0);assert.equal(c.added.length,1);assert.match(c.added[0].children[0].textContent,/Terminez votre saisie/);c.added[0].children[1].click();assert.equal(c.reloads,1);
 c=setup({revision:'bad'});await tick();assert.equal(c.reloads,0);
 c=setup({revision:'a'.repeat(64)});await tick();c.document.hidden=true;c.wl.interval();await tick();assert.equal(c.calls,1);c.document.hidden=false;c.dl.visibilitychange();await tick();assert.equal(c.calls,2);
 console.log('Planning synchronization: 14 assertions passed.');
})().catch(error=>{console.error(error);process.exitCode=1});
