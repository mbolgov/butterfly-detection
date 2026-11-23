/* Butterfly pilot interface. No external dependencies. Normalized original-image coordinates. */
(function (global) {
  'use strict';
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const clone = value => JSON.parse(JSON.stringify(value));
  const clamp = (value, low = 0, high = 1) => Math.max(low, Math.min(high, value));
  function validBox(box) {
    return box && ['left','top','width','height'].every(k => typeof box[k] === 'number' && Number.isFinite(box[k])) &&
      box.left >= 0 && box.top >= 0 && box.width > 0 && box.height > 0 &&
      box.left + box.width <= 1 + 1e-9 && box.top + box.height <= 1 + 1e-9;
  }
  function boxFromPoints(a, b) {
    return {left: Math.min(a.x,b.x), top: Math.min(a.y,b.y), width: Math.abs(b.x-a.x), height: Math.abs(b.y-a.y)};
  }
  function moveBox(box, dx, dy) {
    return {...box, left: clamp(box.left + dx, 0, 1-box.width), top: clamp(box.top + dy, 0, 1-box.height)};
  }
  function resizeBox(box, handle, p) {
    let x1 = box.left, y1 = box.top, x2 = x1+box.width, y2 = y1+box.height;
    if (handle.includes('w')) x1 = clamp(p.x);
    if (handle.includes('e')) x2 = clamp(p.x);
    if (handle.includes('n')) y1 = clamp(p.y);
    if (handle.includes('s')) y2 = clamp(p.y);
    return boxFromPoints({x:x1,y:y1},{x:x2,y:y2});
  }
  function validateState(state, mode, imageState, inputError) {
    if (inputError) return 'Не удалось прочитать задание. Пропустите его и сообщите заказчику.';
    if (imageState === 'error') {
      const decision = state && (mode === 'annotation' ? state.status : state.verdict);
      const values = state && (mode === 'annotation' ? state.boxes : state.reasons);
      return decision === 'image_error' && Array.isArray(values) && !values.length ? null : 'Повторите загрузку или выберите «Фото не загрузилось».';
    }
    if (imageState !== 'ready') return 'Дождитесь загрузки фото.';
    if (mode === 'annotation') {
      if (!state || !['objects','empty'].includes(state.status)) return 'Нарисуйте рамку или выберите «Бабочек нет».';
      if (!Array.isArray(state.boxes) || !state.boxes.every(validBox)) return 'Проверьте границы рамок.';
      if (state.status === 'objects' && state.boxes.length === 0) return 'Нарисуйте рамку или выберите «Бабочек нет».';
      if (state.status === 'empty' && state.boxes.length > 0) return 'В ответе «Бабочек нет» не должно быть рамок.';
    } else {
      if (!state || !['approve','reject'].includes(state.verdict)) return 'Выберите «Всё верно» или «Есть ошибки».';
      if (!Array.isArray(state.reasons) || !state.reasons.every(r => ['missed','extra','bounds'].includes(r))) return 'Проверьте причины ошибок.';
      if (state.verdict === 'reject' && !state.reasons.length) return 'Укажите хотя бы одну ошибку.';
      if (state.verdict !== 'reject' && state.reasons.length) return 'Причины ошибок должны быть отмечены только для ответа «Есть ошибки».';
    }
    return null;
  }
  function create(root, options) {
    const mode = options.mode === 'review' ? 'review' : 'annotation';
    const input = options.input || {};
    let state = mode === 'annotation' ? {status:'',boxes:[],comment:''} :
      {verdict:'',reasons:[],comment:''};
    if (options.value && typeof options.value === 'object') state = {...state,...clone(options.value)};
    state.comment = String(state.comment || '');
    let inputError = false;
    let reviewBoxes = [];
    try {
      if (mode === 'review') {
        reviewBoxes = typeof input.boxes === 'string' ? JSON.parse(input.boxes) : input.boxes;
        if (!Array.isArray(reviewBoxes) || !reviewBoxes.every(validBox)) throw Error('invalid boxes');
        if (!['objects','empty','uncertain'].includes(input.annotation_status)) throw Error('invalid status');
        if (input.annotation_status === 'empty' && reviewBoxes.length) throw Error('inconsistent empty');
        if (input.annotation_status === 'objects' && !reviewBoxes.length) throw Error('inconsistent objects');
      } else if (!Array.isArray(state.boxes) || !state.boxes.every(validBox)) {
        state = {status:'',boxes:[],comment:''};
      }
    } catch (_) { inputError = true; }
    if (mode === 'review') state.reasons = Array.isArray(state.reasons) ? state.reasons.filter(r => ['missed','extra','bounds'].includes(r)) : [];
    let selected = -1, tool = 'draw', zoom = 1, hidden = false, imageState = 'loading';
    let naturalWidth = 1, naturalHeight = 1, drag = null, destroyed = false;
    const history = [], cleanups = [];
    const editable = mode === 'annotation' && !options.readOnly;
    function on(el, type, handler, opts) {
      el.addEventListener(type, handler, opts);
      cleanups.push(() => el.removeEventListener(type, handler, opts));
    }
    root.classList.add('bf'); root.tabIndex = 0;
    root.innerHTML = `
      <header class="bf-header"><div><h2>${mode === 'annotation' ? 'Выделите всех взрослых бабочек' : 'Проверьте разметку бабочек'}</h2>
      </div><span class="bf-count" aria-live="polite"></span></header>
      <div class="bf-rule">${mode === 'annotation' ? 'Одна бабочка — одна плотная рамка. Включите видимые крылья, тело, усики и лапки.' : 'Проверьте весь кадр: нет ли пропусков, лишних рамок или неточных границ.'}</div>
      <div class="bf-toolbar" role="toolbar" aria-label="Работа с фотографией">
        ${mode === 'annotation' ? '<button type="button" data-action="draw" class="bf-tool">＋ Новая рамка</button><button type="button" data-action="select" class="bf-tool">Выбрать</button><button type="button" data-action="delete">Удалить</button><button type="button" data-action="undo" title="Ctrl+Z">Отменить</button>' : '<button type="button" data-action="toggle">Скрыть рамки</button>'}
        <span class="bf-toolbar-gap"></span><button type="button" data-action="zoom-out" aria-label="Уменьшить">−</button><span class="bf-zoom">100%</span><button type="button" data-action="zoom-in" aria-label="Увеличить">＋</button><button type="button" data-action="fit">Весь кадр</button>
      </div>
      <div class="bf-view" aria-label="Фотография"><div class="bf-stage"><img class="bf-image" draggable="false" alt="Фотография для разметки бабочек"><svg class="bf-svg" xmlns="${SVG_NS}" role="img" aria-label="Рамки на фотографии"></svg></div><div class="bf-loading" role="status">Загружаем фото…</div></div>
      <div class="bf-load-failure" hidden><p>Фото не открылось.</p><button type="button" data-action="retry">Повторить загрузку</button> <button type="button" data-action="image_error">Фото не загрузилось</button></div>
      <p class="bf-help">${mode === 'annotation' ? 'Протяните рамку мышью. Для исправления нажмите «Выбрать»: рамку можно передвинуть или потянуть за край.' : 'Можно скрыть рамки, чтобы заметить пропущенных бабочек. Саму разметку здесь менять не нужно.'}</p>
      ${mode === 'annotation' ? '<div class="bf-box-list" aria-label="Список рамок"></div>' : '<p class="bf-author-status"></p>'}
      <div class="bf-answer" role="group" aria-label="Ответ">${mode === 'annotation' ? '<button type="button" data-action="empty">Бабочек нет</button>' : '<button type="button" data-action="approve">Всё верно</button><button type="button" data-action="reject">Есть ошибки</button>'}</div>
      ${mode === 'review' ? '<fieldset class="bf-reasons" hidden><legend>Что нужно исправить?</legend><label><input type="checkbox" value="missed"> Пропущена бабочка</label><label><input type="checkbox" value="extra"> Лишняя рамка</label><label><input type="checkbox" value="bounds"> Неточные границы</label></fieldset>' : ''}
      <p class="bf-error" role="alert" hidden></p>`;
    const $ = selector => root.querySelector(selector);
    const $$ = selector => [...root.querySelectorAll(selector)];
    const view = $('.bf-view'), stage = $('.bf-stage'), img = $('.bf-image'), svg = $('.bf-svg');
    const error = $('.bf-error');
    function value() {
      // Existing training keys require confirmed for a completed answer.
      const confirmed = validateState(state, mode, imageState, inputError) === null;
      if (mode === 'annotation') return {status:state.status, boxes:clone(state.boxes), confirmed, comment:state.comment};
      return {verdict:state.verdict,reasons:clone(state.reasons),confirmed,comment:state.comment};
    }
    function notify() { if (!destroyed && !options.readOnly && options.onChange) options.onChange(value()); }
    function update(mutator, remember = false) {
      if (options.readOnly) return;
      if (remember) {history.push(clone(state)); if (history.length > 50) history.shift();}
      mutator(); error.hidden = true; render(); notify();
    }
    function svgEl(tag, attrs) {
      const el = document.createElementNS(SVG_NS,tag);
      Object.entries(attrs).forEach(([k,v]) => el.setAttribute(k,String(v)));
      return el;
    }
    function drawOverlay() {
      svg.replaceChildren();
      if (hidden || imageState !== 'ready') return;
      const boxes = mode === 'annotation' ? clone(state.boxes) : reviewBoxes;
      if (drag && drag.draft) {
        if (drag.kind === 'new') boxes.push(drag.draft); else boxes[drag.index] = drag.draft;
      }
      const cssWidth = Math.max(1, stage.getBoundingClientRect().width);
      const px = naturalWidth / cssWidth;
      boxes.forEach((b,i) => {
        const attrs = {x:b.left*naturalWidth,y:b.top*naturalHeight,width:b.width*naturalWidth,height:b.height*naturalHeight};
        const group = svgEl('g', {'data-box':i});
        const color = selected === i && editable ? '#00e4ca' : '#ffe24a';
        const shadow = svgEl('rect',{...attrs,fill:'none',stroke:'#172b36','stroke-width':5,'vector-effect':'non-scaling-stroke','pointer-events':'none'});
        group.append(shadow);
        const rect = svgEl('rect',{...attrs,fill:'transparent',stroke:color,'stroke-width':2.5,'vector-effect':'non-scaling-stroke','data-box':i});
        rect.style.pointerEvents = editable && tool === 'select' ? 'all' : 'none';
        rect.style.cursor = 'move'; group.append(rect);
        const tx = clamp(attrs.x+5*px,0,Math.max(0,naturalWidth-25*px));
        const ty = Math.max(17*px,attrs.y+17*px);
        const text = svgEl('text',{x:tx,y:ty,fill:'#fff',stroke:'#172b36','stroke-width':3*px,'paint-order':'stroke','font-size':14*px,'font-family':'Arial,sans-serif','font-weight':700,'pointer-events':'none'});
        text.textContent = String(i+1); group.append(text);
        if (editable && tool === 'select' && selected === i) {
          const x=[attrs.x,attrs.x+attrs.width/2,attrs.x+attrs.width], y=[attrs.y,attrs.y+attrs.height/2,attrs.y+attrs.height];
          [['nw',0,0],['n',1,0],['ne',2,0],['e',2,1],['se',2,2],['s',1,2],['sw',0,2],['w',0,1]].forEach(([name,ix,iy])=>{
            const h=svgEl('rect',{x:x[ix]-5*px,y:y[iy]-5*px,width:10*px,height:10*px,fill:'#fff',stroke:'#005d58','stroke-width':1.5,'vector-effect':'non-scaling-stroke','data-box':i,'data-handle':name});
            h.style.cursor=name+'-resize'; group.append(h);
          });
        }
        svg.append(group);
      });
    }
    function layout() {
      if (destroyed || imageState !== 'ready') return;
      const available = Math.max(240,view.clientWidth-2);
      const base = Math.min(available/naturalWidth,520/naturalHeight,1);
      const width = naturalWidth*base*zoom, height = naturalHeight*base*zoom;
      stage.style.width = width+'px'; stage.style.height=height+'px';
      view.style.height=Math.min(522,Math.max(220,height+2))+'px';
      $('.bf-zoom').textContent=Math.round(zoom*100)+'%'; drawOverlay();
    }
    function render() {
      const current = mode === 'annotation' ? state.status : state.verdict;
      $('.bf-load-failure p').textContent = current === 'image_error' ? 'Отмечено: фото не загрузилось.' : 'Фото не открылось.';
      $('.bf-count').textContent = 'Рамок: '+(mode === 'annotation' ? state.boxes.length : reviewBoxes.length);
      $$('[data-action]').forEach(button => {
        const a=button.dataset.action;
        const active=(a==='draw' && tool==='draw' && editable)||(a==='select' && tool==='select' && editable)||
          a===current;
        button.classList.toggle('is-active',active);
        button.setAttribute('aria-pressed',String(active));
        button.disabled=!!options.readOnly || (a==='delete' && selected < 0) || (a==='undo' && history.length===0) ||
          (['draw','select','delete','undo','zoom-in','zoom-out','fit','toggle','approve','reject','empty'].includes(a) && (imageState!=='ready'||inputError));
        if (options.readOnly && ['zoom-in','zoom-out','fit','toggle'].includes(a)) button.disabled=imageState!=='ready';
      });
      if (mode==='annotation') {
        const list=$('.bf-box-list'); list.replaceChildren();
        state.boxes.forEach((b,i)=> {const button=document.createElement('button');button.type='button';button.dataset.boxSelect=String(i);button.textContent='Рамка '+(i+1);button.className=selected===i?'is-active':'';button.disabled=!!options.readOnly;list.append(button);});
      } else {
        $('.bf-author-status').textContent = reviewBoxes.length === 0 ? 'Рамок нет. Проверьте, действительно ли на фото нет бабочек.' : 'Проверьте каждую рамку и объекты за их пределами.';
        $('.bf-reasons').hidden=current!=='reject';
        $$('.bf-reasons input').forEach(el=>{el.checked=state.reasons.includes(el.value);el.disabled=!!options.readOnly;});
      }
      svg.style.cursor=editable&&tool==='draw'?'crosshair':'default';
      if (mode==='review') $('[data-action="toggle"]').textContent=hidden?'Показать рамки':'Скрыть рамки';
      drawOverlay();
    }
    function point(e) {const r=svg.getBoundingClientRect();return {x:clamp((e.clientX-r.left)/r.width),y:clamp((e.clientY-r.top)/r.height)};}
    function start(e) {
      if (!editable||imageState!=='ready'||e.button!==0||inputError) return;
      e.preventDefault(); root.focus({preventScroll:true});
      const p=point(e), handle=e.target.dataset.handle, index=Number(e.target.dataset.box);
      if (tool==='select') {
        if (!Number.isInteger(index)||index<0||index>=state.boxes.length) {selected=-1;render();return;}
        selected=index;drag={kind:handle?'resize':'move',index,handle,start:p,original:clone(state.boxes[index]),draft:clone(state.boxes[index])};
      } else {drag={kind:'new',start:p,draft:boxFromPoints(p,p)};selected=-1;}
      svg.setPointerCapture(e.pointerId);drawOverlay();
    }
    function move(e) {
      if (!drag) return;
      const p=point(e);
      if (drag.kind==='new') drag.draft=boxFromPoints(drag.start,p);
      else if(drag.kind==='move') drag.draft=moveBox(drag.original,p.x-drag.start.x,p.y-drag.start.y);
      else drag.draft=resizeBox(drag.original,drag.handle,p);
      drawOverlay();
    }
    function finish(e) {
      if(!drag)return;
      const d=drag;drag=null;
      if(svg.hasPointerCapture(e.pointerId))svg.releasePointerCapture(e.pointerId);
      const r=svg.getBoundingClientRect();
      if(!validBox(d.draft) || (d.kind==='new' && (d.draft.width*r.width<3||d.draft.height*r.height<3))) {render();return;}
      if(d.kind!=='new'&&JSON.stringify(d.original)===JSON.stringify(d.draft)){render();return;}
      update(()=>{
        if(d.kind==='new'){state.boxes.push(d.draft);selected=state.boxes.length-1;}
        else state.boxes[d.index]=d.draft;
        state.status='objects';
      },true);
    }
    on(svg,'pointerdown',start);on(svg,'pointermove',move);on(svg,'pointerup',finish);
    on(svg,'pointercancel',()=>{drag=null;render();});
    on(root,'click',e=>{
      const button=e.target.closest('button');if(!button||!root.contains(button)||button.disabled)return;
      if(button.dataset.boxSelect!==undefined){selected=Number(button.dataset.boxSelect);tool='select';render();return;}
      const action=button.dataset.action;
      if(action==='draw'||action==='select'){tool=action;render();return;}
      if(action==='delete'){if(selected>=0)update(()=>{state.boxes.splice(selected,1);selected=-1;},true);return;}
      if(action==='undo'){if(history.length){state=history.pop();selected=-1;render();notify();}return;}
      if(action==='zoom-in'||action==='zoom-out'||action==='fit'){
        zoom=action==='fit'?1:clamp(zoom*(action==='zoom-in'?1.5:1/1.5),1,6);
        layout();if(action==='fit'){view.scrollLeft=0;view.scrollTop=0;}return;
      }
      if(action==='toggle'){hidden=!hidden;render();return;}
      if(action==='retry'){load();return;}
      if(action==='image_error' && imageState==='error' && !inputError){
        update(()=>{state=mode==='annotation' ? {status:'image_error',boxes:[],comment:''} : {verdict:'image_error',reasons:[],comment:''}; selected=-1; history.length=0;});
        return;
      }
      if(action==='empty'){
        if(state.boxes.length && !global.confirm('Удалить рамки и отметить, что бабочек нет? Можно вернуть ответ кнопкой «Отменить».'))return;
        update(()=>{state.status=state.status==='empty'?'':'empty';state.boxes=[];state.comment='';selected=-1;},true);return;
      }
      if(action==='approve'||action==='reject'){update(()=>{state.verdict=action;state.reasons=[];state.comment='';});}
    });
    if(mode==='review') $$('.bf-reasons input').forEach(el=>on(el,'change',()=>update(()=>{state.reasons=$$('.bf-reasons input:checked').map(x=>x.value);})));
    on(root,'keydown',e=>{
      if(!editable||/INPUT|TEXTAREA|SELECT/.test(e.target.tagName))return;
      if(e.key==='Escape'){drag=null;selected=-1;render();}
      if((e.key==='Delete'||e.key==='Backspace')&&selected>=0){e.preventDefault();$('[data-action="delete"]').click();}
      if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'){e.preventDefault();$('[data-action="undo"]').click();}
    });
    let loadTimer;
    function failed(){if(destroyed)return;imageState='error';$('.bf-loading').hidden=true;$('.bf-load-failure').hidden=false;stage.hidden=true;render();}
    function load(){
      clearTimeout(loadTimer);imageState='loading';stage.hidden=true;$('.bf-loading').hidden=false;$('.bf-loading').textContent='Загружаем фото…';$('.bf-load-failure').hidden=true;
      render();loadTimer=setTimeout(failed,25000);
      img.removeAttribute('src');img.src=String(input.image||input.photo_url||'');
    }
    on(img,'load',()=>{
      clearTimeout(loadTimer);if(!img.naturalWidth||!img.naturalHeight){failed();return;}
      imageState='ready';naturalWidth=img.naturalWidth;naturalHeight=img.naturalHeight;
      const key = mode === 'annotation' ? 'status' : 'verdict';
      const recovered = !options.readOnly && state[key] === 'image_error';
      if (recovered) state[key] = '';
      svg.setAttribute('viewBox',`0 0 ${naturalWidth} ${naturalHeight}`);stage.hidden=false;$('.bf-loading').hidden=true;$('.bf-load-failure').hidden=true;layout();render();
      if (recovered || state.status || state.verdict) notify();
    });
    on(img,'error',()=>{clearTimeout(loadTimer);failed();});
    const observer=typeof ResizeObserver!=='undefined'?new ResizeObserver(layout):null;
    if(observer)observer.observe(view);else on(global,'resize',layout);
    if(inputError){imageState='error';$('.bf-loading').textContent='Не удалось прочитать разметку. Пропустите задание и сообщите заказчику.';render();}
    else load();
    return {
      value,
      validate(candidate){const message=validateState(candidate||state,mode,imageState,inputError);error.textContent=message||'';error.hidden=!message;return message;},
      setValue(saved){state={...state,...clone(saved)};state.comment=String(state.comment||'');render();},
      destroy(){destroyed=true;clearTimeout(loadTimer);if(observer)observer.disconnect();cleanups.forEach(fn=>fn());root.replaceChildren();},
      debug(){return {imageState,zoom,selected,mode,inputError};}
    };
  }
  const api={create,validBox,boxFromPoints,moveBox,resizeBox,validateState};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  global.ButterflyUI=api;
})(typeof window!=='undefined'?window:globalThis);

/* Platform adapter uses documented Yandex Tasks lifecycle and persistence methods. */
(function () {
  'use strict';
  function boxesMatch(boxes, reference, threshold) {
    if (!Array.isArray(boxes) || boxes.length !== reference.length) return false;
    function iou(a, b) {
      const w = Math.max(0, Math.min(a.left + a.width, b.left + b.width) - Math.max(a.left, b.left));
      const h = Math.max(0, Math.min(a.top + a.height, b.top + b.height) - Math.max(a.top, b.top));
      const intersection = w * h;
      return intersection / (a.width * a.height + b.width * b.height - intersection);
    }
    const owner = Array(reference.length).fill(-1);
    function match(index, seen) {
      for (let j = 0; j < reference.length; j++) {
        if (seen.has(j) || !(iou(boxes[index], reference[j]) >= threshold - 1e-12)) continue;
        seen.add(j);
        if (owner[j] === -1 || match(owner[j], seen)) { owner[j] = index; return true; }
      }
      return false;
    }
    return boxes.every((box, index) => match(index, new Set()));
  }
  function extend(Parent, ctor, methods) {ctor.prototype=Object.create(Parent.prototype);Object.assign(ctor.prototype,methods);return ctor;}
  exports.Task = extend(TolokaHandlebarsTask, function (options) {
    TolokaHandlebarsTask.call(this, options);
  }, {
    onRender: function () {
      if(this.butterfly)this.butterfly.destroy();
      const task=this;
      const host=this.getDOMElement().querySelector('.butterfly-task');
      const saved=this.getSolution();
      this.butterfly=window.ButterflyUI.create(host,{
        mode:'annotation',input:this.getTask().input_values,
        value:saved&&saved.output_values,
        readOnly:!!this.getWorkspaceOptions().isReviewMode,
        onChange:function(value){
          const input = task.getTask().input_values;
          if (Array.isArray(input.control_boxes)) {
            const reference = input.control_boxes;
            const expectedStatus = reference.length ? 'objects' : 'empty';
            const correct = value.confirmed && value.status === expectedStatus && boxesMatch(value.boxes, reference, 0.60);
            task.setSolutionOutputValues(Object.assign({}, value, {bbox_ok: Boolean(correct)}));
            return;
          }
          const refs = input.training_boxes;
          if (Array.isArray(refs) && value.status !== 'image_error' && value.confirmed && boxesMatch(value.boxes, refs, 0.70)) {
            // Native training compares JSON exactly. Canonicalize only successful training answers.
            task.setSolutionOutputValues(Object.assign({}, value, {boxes: refs}));
          } else {
            task.setSolutionOutputValues(value);
          }
        }
      });
    },
    validate: function (solution) {
      const values=solution&&solution.output_values;
      const message=this.butterfly?this.butterfly.validate(values):'Дождитесь загрузки интерфейса.';
      if(message)return {task_id:this.getTask().id,errors:{'__TASK__':{code:'VALIDATION_ERROR',message:message}}};
      return TolokaHandlebarsTask.prototype.validate.call(this,solution);
    },
    onResume: function () {
      const solution=this.getSolution();
      if(this.butterfly&&solution)this.butterfly.setValue(solution.output_values);
    },
    onDestroy: function () {if(this.butterfly)this.butterfly.destroy();}
  });
})();
