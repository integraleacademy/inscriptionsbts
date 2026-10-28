/* Real regression: named action buttons mask form.action with a RadioNodeList. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/js/london-mobility.js', 'utf8');

async function submit(response) {
  let listener, sent, reloaded = false;
  const buttons = [{disabled:false}, {disabled:false}];
  const message = {hidden:true, textContent:'', scrollIntoView(){}};
  const form = {
    action: {toString:()=> '[object RadioNodeList]'},
    getAttribute: key => key === 'action' ? '/admin/candidat/example/londres/convention' : null,
    addEventListener: (event, fn) => { listener = fn; },
    querySelector: () => message, querySelectorAll: () => buttons,
    setAttribute(){}, removeAttribute(){}
  };
  vm.runInNewContext(source, {
    document:{querySelectorAll:()=>[form]},
    window:{location:{hash:'',reload(){reloaded=true;}}},
    FormData: class extends Map { constructor(){super();} },
    fetch: async (url, options) => { sent={url,options}; return response; }
  });
  await listener({preventDefault(){},submitter:{name:'action',value:'generate'}});
  return {sent,message,buttons,reloaded};
}

(async()=>{
  let result = await submit({ok:true,status:200,json:async()=>({ok:true})});
  assert.equal(result.sent.url, '/admin/candidat/example/londres/convention');
  assert.equal(result.sent.options.body.get('action'), 'generate');
  assert(result.reloaded);
  result = await submit({ok:false,status:400,json:async()=>({error:'Le SIRET doit comporter 14 chiffres.'})});
  assert.equal(result.message.textContent,'Le SIRET doit comporter 14 chiffres.');
  assert(!result.message.hidden && result.buttons.every(b=>!b.disabled) && !result.reloaded);
  result = await submit({ok:false,status:403,json:async()=>{throw Error('HTML');}});
  assert.match(result.message.textContent,/session a expiré/);
  console.log('London form: correct URL, submitted action, validation and expired session verified');
})().catch(error=>{console.error(error);process.exitCode=1;});
