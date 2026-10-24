(() => {
  const form=document.getElementById('application-form');
  if(!form) return;
  const normalize=v=>v.normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
  const nationalities=['Française','Belge','Suisse','Italienne','Espagnole','Portugaise','Allemande','Britannique','Irlandaise','Luxembourgeoise','Monégasque','Néerlandaise','Polonaise','Roumaine','Bulgare','Grecque','Ukrainienne','Russe','Algérienne','Marocaine','Tunisienne','Sénégalaise','Ivoirienne','Camerounaise','Congolaise','Malienne','Guinéenne','Malgache','Mauricienne','Comorienne','Canadienne','Américaine','Brésilienne','Chinoise','Japonaise','Indienne','Turque','Libanaise','Haïtienne','Cap-verdienne'];
  if(form.elements.nationalite) form.elements.nationalite.dataset.suggest='nationality';
  form.querySelectorAll('[data-suggest]').forEach(input=>{
    const wrapper=input.closest('label'); wrapper.classList.add('suggestion-field');
    const list=document.createElement('div');list.className='place-suggestions';list.id=`suggestions-${input.name}`;list.hidden=true;list.setAttribute('role','listbox');
    const hint=document.createElement('small');hint.className='suggestion-status';hint.setAttribute('aria-live','polite');
    wrapper.append(list,hint);input.setAttribute('role','combobox');input.setAttribute('aria-autocomplete','list');input.setAttribute('aria-expanded','false');input.setAttribute('aria-controls',list.id);input.autocomplete='off';
    let timer,controller,items=[],active=-1,version=0;
    const close=()=>{list.hidden=true;input.setAttribute('aria-expanded','false');input.removeAttribute('aria-activedescendant');active=-1;};
    const set=(name,val)=>{if(val&&form.elements[name]){form.elements[name].value=val;form.elements[name].dispatchEvent(new Event('change',{bubbles:true}));}};
    function select(item){
      const birth=input.name.includes('naissance');
      input.value=item.value;
      if(item.city){set(birth?'ville_naissance':'ville',item.city);set(birth?'cp_naissance':'cp',item.postcode);if(birth&&item.country)set('pays_naissance',item.country);}
      close();hint.textContent='Suggestion sélectionnée. Tu peux encore modifier ta réponse.';input.dispatchEvent(new Event('change',{bubbles:true}));input.focus();
    }
    async function search(){
      const own=++version,q=input.value.trim();controller?.abort();close();
      if(q.length<2)return;
      hint.textContent='Recherche de suggestions…';controller=new AbortController();
      try{
        if(input.dataset.suggest==='nationality')items=nationalities.filter(v=>normalize(v).includes(normalize(q))).map(v=>({label:v,value:v}));
        else{
          const params=new URLSearchParams({kind:input.dataset.suggest,q});
          if(input.name==='ville_naissance')params.set('country',form.elements.pays_naissance.value);
          const response=await fetch('/api/admission/suggestions?'+params,{signal:controller.signal});
          if(!response.ok)throw Error();const data=await response.json();if(own!==version)return;
          if(data.unavailable)throw Error();items=data.items||[];
        }
        if(own!==version||document.activeElement!==input)return;
        list.replaceChildren();items.forEach((item,i)=>{const option=document.createElement('div');option.role='option';option.id=`${list.id}-${i}`;option.textContent=item.label;option.setAttribute('aria-selected','false');option.addEventListener('mousedown',event=>{event.preventDefault();select(item);});list.append(option);});
        list.hidden=!items.length;input.setAttribute('aria-expanded',String(!!items.length));
        hint.textContent=items.length?'Choisis une proposition, ou conserve ta saisie.':'Aucune proposition. Tu peux conserver ta saisie manuelle.';
      }catch(error){if(error.name!=='AbortError'&&own===version)hint.textContent='Suggestions indisponibles. La saisie manuelle reste possible.';}
    }
    input.addEventListener('input',()=>{version++;controller?.abort();close();hint.textContent='';clearTimeout(timer);timer=setTimeout(search,350);});
    input.addEventListener('keydown',event=>{
      if(event.key==='Escape'){close();return;}
      if(list.hidden)return;
      if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();active=(active+(event.key==='ArrowDown'?1:-1)+items.length)%items.length;[...list.children].forEach((o,i)=>o.setAttribute('aria-selected',String(i===active)));input.setAttribute('aria-activedescendant',list.children[active].id);list.children[active].scrollIntoView({block:'nearest'});}
      if(event.key==='Enter'){event.preventDefault();event.stopPropagation();if(active>=0)select(items[active]);}
    });
    input.addEventListener('blur',()=>setTimeout(close,120));
  });
})();
