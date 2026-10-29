import {api,el,root,state,heading,field,button,check,select,types,notice,statuses,time} from './core.js';

const key=()=>crypto.randomUUID().replaceAll('-','');
function show(...nodes){root.replaceChildren(...nodes);window.scrollTo(0,0);}
const short=id=>id?String(id).slice(-8):'无';
const payload=q=>Object.fromEntries(['title','type','required','options','constraints'].map(k=>[k,structuredClone(q[k])]));
const privacyNames={AVAILABLE:'可展示',INSUFFICIENT_SAMPLE:'样本不足，已隐藏',PRIVACY_SUPPRESSED:'存在稀有分组，已隐藏',NO_FOREIGN_SOURCES:'无他人采用'};
function pager(skip,total,load){return el('div',{class:'toolbar'},skip?button('上一页',()=>load(Math.max(0,skip-20))):el('span'),skip+20<total?button('下一页',()=>load(skip+20)):null);}
function versionBody(v){
  const q=v.payload;
  return el('div',{},el('h3',{},q.title),el('p',{class:'muted'},`${types[q.type]} · ${q.required?'必答':'可选'} · 版本 v${v.versionNo}`),
    ...q.options.map(o=>el('p',{},`${o.label} [${o.optionId}]`)),
    el('p',{class:'muted'},'约束：'+Object.entries(q.constraints).filter(([k,val])=>val!==null&&val!==false).map(([k,val])=>`${k}=${val}`).join('；')),
    q.type==='NUMBER'?el('p',{class:'muted'},'固定统计切点：'+(v.summaryPolicy.numericCuts.join('，')||'单一分组')):null);
}

function questionForm(initial, initialPolicy, submit, name=''){
  let q=structuredClone(initial||{title:'',type:'SINGLE',required:false,options:[{optionId:key(),label:''},{optionId:key(),label:''}],constraints:{}});
  let cuts=initialPolicy?.numericCuts?.join(',')??'';
  const container=el('section',{class:'panel'});
  function render(){
    container.replaceChildren(field('管理名称',el('input',{value:name,maxlength:200,onInput:e=>name=e.target.value})),
      field('题干',el('input',{value:q.title,maxlength:1000,onInput:e=>q.title=e.target.value})),
      field('题型',select(Object.entries(types),q.type,v=>{q.type=v;q.constraints={};q.options=['SINGLE','MULTI'].includes(v)?[{optionId:key(),label:''},{optionId:key(),label:''}]:[];cuts='';render();})),
      check('必答',q.required,v=>q.required=v));
    if(['SINGLE','MULTI'].includes(q.type)){
      for(const [i,o]of q.options.entries())container.append(el('div',{class:'option-editor'},
        field('选项 '+(i+1),el('input',{value:o.label,onInput:e=>o.label=e.target.value})),button('移除',()=>{q.options.splice(i,1);render();})));
      container.append(button('添加选项',()=>{q.options.push({optionId:key(),label:''});render();}));
    }
    const fields={MULTI:[['minSelections','最少选择'],['maxSelections','最多选择']],TEXT:[['minLength','最短长度'],['maxLength','最长长度']],NUMBER:[['minValue','最小值'],['maxValue','最大值']]}[q.type]||[];
    for(const [k,label]of fields)container.append(field(label,el('input',{value:q.constraints[k]??'',type:q.type==='NUMBER'?'text':'number',onInput:e=>{
      if(e.target.value==='')q.constraints[k]=null;else q.constraints[k]=q.type==='NUMBER'?e.target.value:Number(e.target.value);
    }})));
    if(q.type==='NUMBER')container.append(check('只允许整数',q.constraints.integerOnly||false,v=>q.constraints.integerOnly=v),
      field('固定数字切点（逗号分隔）',el('input',{value:cuts,onInput:e=>cuts=e.target.value}),'最多19个递增值。留空时由有限上下界生成候选切点；无上下界时必须填写。保存版本后不可改动。'));
    container.append(button('保存',()=>submit({name,payload:q,summaryPolicy:q.type==='NUMBER'&&cuts.trim()?{policyVersion:1,numericCuts:cuts.split(/[,，]/).map(s=>s.trim())}:null}),'primary'));
  }
  render();return container;
}

export async function libraryHome(back,skip=0,shared=false){
  const data=await api((shared?'/library/shared-with-me':'/library/questions')+`?skip=${skip}&limit=20`);
  show(heading(shared?'收到的共享':'我的题目','保存题目、管理不可变版本，并在多份问卷中复用。'));
  root.append(el('div',{class:'toolbar'},button('返回问卷',back),el('div',{class:'actions'},
    button(shared?'我的题目':'收到的共享',()=>libraryHome(back,0,!shared)),button('我的题库',()=>bankHome(back)),
    !shared?button('新建题目',()=>{
      show(heading('新建题目','保存后生成独立题目和第一个正式版本。'),questionForm(null,null,async data=>{
        const result=await api('/library/questions','POST',data);await itemDetail(result.item.id,()=>libraryHome(back));
      }),button('返回题目列表',()=>libraryHome(back)));
    },'primary'):null)));
  const grid=el('div',{class:'grid'});
  for(const entry of data.items){
    const item=shared?entry.version:entry;
    grid.append(el('article',{class:'survey-card'},el('h2',{},entry.name),
      el('p',{class:'muted'},shared?`共享版本 v${item.versionNo}`:entry.status==='ACTIVE'?'可使用':'已归档'),
      button('查看题目',()=>shared?versionView(item,()=>libraryHome(back,skip,true),false):itemDetail(item.id,()=>libraryHome(back,skip)))));
  }
  if(!data.items.length)grid.append(el('p',{class:'muted'},'暂无题目。'));
  root.append(grid,pager(skip,data.total,n=>libraryHome(back,n,shared)));
}

async function itemDetail(itemId,back,skip=0){
  const [item,history]=await Promise.all([api('/library/questions/'+itemId),api(`/library/questions/${itemId}/versions?skip=${skip}&limit=20`)]);
  show(heading(item.name,'正式版本不覆盖；从旧版修改形成分支，恢复也会生成新版本。'),
    el('div',{class:'toolbar'},button('返回题目列表',back),el('div',{class:'actions'},
      button('使用情况',()=>usageView(item,()=>itemDetail(itemId,back,skip))),
      button(item.status==='ACTIVE'?'归档题目':'恢复使用',async()=>{await api('/library/questions/'+itemId,'PATCH',{revision:item.revision,name:item.name,status:item.status==='ACTIVE'?'ARCHIVED':'ACTIVE'});await itemDetail(itemId,back,skip);}))));
  if(item.workingDraft)root.append(el('section',{class:'panel'},el('h2',{},'未发布工作稿'),
    versionBody({payload:item.workingDraft.payload,summaryPolicy:item.workingDraft.summaryPolicy,versionNo:'工作稿'}),
    button('继续编辑工作稿',()=>editVersion(item,{id:item.workingDraft.baseVersionId,payload:item.workingDraft.payload,summaryPolicy:item.workingDraft.summaryPolicy},()=>itemDetail(itemId,back,skip))),
    button('保存工作稿为新版本',async()=>{const result=await api(`/library/questions/${itemId}/versions`,'POST',{revision:item.revision,operationKey:key()});notice(result.headAdvanced?'新版本已保存':'版本已保存为分支，默认指针未推进');await itemDetail(itemId,back,skip);})));
  for(const v of history.items){
    const section=el('section',{class:'panel'},versionBody(v),el('p',{class:'muted'},
      `${v.id===item.headVersionId?'默认版本 · ':''}${v.operation} · 父版本 ${short(v.parentVersionId)} · 恢复来源 ${short(v.restoredFromVersionId)} · 另存来源 ${short(v.derivedFromVersionId)} · ${time(v.createdAt)}`),
      el('div',{class:'actions'},button('版本详情与共享',()=>versionView(v,()=>itemDetail(itemId,back,skip),true)),
        button('从此版本修改',()=>editVersion(item,v,()=>itemDetail(itemId,back,skip))),
        button('恢复为新版本',async()=>{if(!confirm('将本版内容复制为一个新版本？旧版本及问卷保持原样。'))return;
          await api(`/library/questions/${itemId}/restore`,'POST',{revision:item.revision,versionId:v.id,operationKey:key()});await itemDetail(itemId,back,skip);}),
        button('跨问卷统计',()=>crossView(item.id,v,()=>itemDetail(itemId,back,skip)))));
    root.append(section);
  }
  root.append(pager(skip,history.total,n=>itemDetail(itemId,back,n)));
}

function editVersion(item,v,back){
  show(heading('编辑工作稿',`基于版本 ${short(v.id)}；保存工作稿不会改动任何正式版本。`),
    questionForm(v.payload,v.summaryPolicy,async data=>{
      let current=item;
      if(data.name!==item.name)current=await api('/library/questions/'+item.id,'PATCH',{revision:item.revision,name:data.name,status:item.status});
      await api(`/library/questions/${item.id}/draft`,'PUT',{revision:current.revision,baseVersionId:v.id,payload:data.payload,summaryPolicy:data.summaryPolicy});
      notice('工作稿已保存，可继续编辑或保存为新版本');await back();
    },item.name),button('返回版本列表',back));
}

async function versionView(v,back,owned){
  show(heading('题目版本 v'+v.versionNo,'本页展示固定版本内容。'),el('section',{class:'panel'},versionBody(v)),
    el('div',{class:'actions'},button('返回',back),button('另存为我的题目',()=>{
      const name=el('input',{value:v.payload.title});root.append(el('section',{class:'panel'},field('新题名称',name),
        button('确认另存',async()=>{const result=await api('/library/versions/'+v.id+'/fork','POST',{name:name.value});await itemDetail(result.item.id,back);})));
    }),button('加入题库',()=>addToBank(v,()=>versionView(v,back,owned))),
    button('查看该版汇总',()=>crossView(v.libraryQuestionId,v,()=>versionView(v,back,owned)))));
  if(!owned)return;
  const grants=await api('/library/versions/'+v.id+'/shares');
  const username=el('input',{'aria-label':'共享目标账号'});
  const section=el('section',{class:'panel'},el('h2',{},'指定账号共享此版本'),field('账号名称',username),
    button('授予复用权限',async()=>{const old=grants.items.find(g=>g.username===username.value);
      await api('/library/versions/'+v.id+'/shares','PUT',{username:username.value,active:true,revision:old?.revision||0});await versionView(v,back,true);}));
  for(const g of grants.items)section.append(el('div',{class:'summary-line'},`${g.username} · ${g.active?'有效':'已撤销'} `,
    button(g.active?'撤销共享':'重新授予',async()=>{await api('/library/versions/'+v.id+'/shares','PUT',{username:g.username,active:!g.active,revision:g.revision});await versionView(v,back,true);})));
  root.append(section);
}

export async function confirmReuse(version,proceed,cancel){
  const policy=await api('/library/policy');let accepted=false;
  show(heading('确认复用范围','选择确切版本后导入；不会自动跟随未来版本。'),el('section',{class:'panel'},versionBody(version),
    el('p',{},policy.notice),el('p',{class:'muted'},`当前低样本量参数 k=${policy.privacyK}，为待最终确认的建议参数。`),
    check('我已阅读并确认上述可见范围',false,v=>accepted=v),el('div',{class:'actions'},
      button('确认使用此版本',async()=>{if(!accepted)throw new Error('请先确认复用范围');await proceed({reusePolicyVersion:policy.reusePolicyVersion,acknowledged:true});},'primary'),button('取消',cancel))));
}

export async function pickVersion(chosen,back,mode='own',skip=0,bankId=null){
  const bankMode=mode==='bank';
  const url=bankMode?`/banks/${bankId}/items`:mode==='shared'?'/library/shared-with-me':'/library/questions';
  const data=await api(url+`?skip=${skip}&limit=20`);
  show(heading('选择题目版本','从我的题目、收到的共享或固定题库成员中选择。'),el('div',{class:'actions'},
    button('我的题目',()=>pickVersion(chosen,back)),button('收到的共享',()=>pickVersion(chosen,back,'shared')),
    button('从题库选择',async()=>{
      const banks=await api('/banks?limit=100');
      show(heading('选择题库','题库成员绑定确切版本。'),...banks.items.map(b=>button(b.name,()=>pickVersion(chosen,back,'bank',0,b.id))),button('返回',back));
    }),button('返回',back)));
  for(const entry of data.items){
    if(mode==='own')root.append(el('section',{class:'panel'},el('h3',{},entry.name),button('选择具体版本',async()=>{
      await pickItemVersions(entry,chosen,()=>pickVersion(chosen,back,mode,skip),0);
    })));
    else{
      const v=bankMode?(entry.available?await api('/library/versions/'+entry.questionVersionId):null):entry.version;
      root.append(el('section',{class:'panel'},v?versionBody(v):el('p',{},`${entry.name}：共享已撤销或已归档`),v?button('选择此版本',()=>chosen(v),'primary'):null));
    }
  }
  root.append(pager(skip,data.total,n=>pickVersion(chosen,back,mode,n,bankId)));
}
async function pickItemVersions(item,chosen,back,skip){
  const history=await api(`/library/questions/${item.id}/versions?skip=${skip}&limit=20`);
  show(heading(item.name,'明确选择一个固定版本。'),button('返回选题',back));
  for(const v of history.items)root.append(el('section',{class:'panel'},versionBody(v),button('选择此版本',()=>chosen(v),'primary')));
  root.append(pager(skip,history.total,n=>pickItemVersions(item,chosen,back,n)));
}

async function addToBank(v,back){
  const banks=await api('/banks?limit=100');show(heading('加入题库','仅保存版本引用；以后导入问卷仍检查共享权限。'));
  for(const b of banks.items.filter(b=>b.status==='ACTIVE'))root.append(button(b.name,async()=>{await api('/banks/'+b.id+'/items','POST',{versionId:v.id});notice('已加入题库');await back();}));
  root.append(button('返回',back));
}

export async function bankHome(back,skip=0){
  const data=await api(`/banks?skip=${skip}&limit=20`);const name=el('input'),description=el('input');
  show(heading('我的题库','个人题库固定保存题目版本，升级不会改动已有问卷。'),button('返回问卷',back),
    el('section',{class:'panel'},field('题库名称',name),field('说明',description),button('创建题库',async()=>{await api('/banks','POST',{name:name.value,description:description.value});await bankHome(back);},'primary')));
  for(const b of data.items)root.append(el('section',{class:'panel'},el('h2',{},b.name),el('p',{},b.description),button('管理成员',()=>bankView(b.id,()=>bankHome(back,skip)))));
  root.append(pager(skip,data.total,n=>bankHome(back,n)));
}

async function bankView(bankId,back,skip=0){
  const data=await api(`/banks/${bankId}/items?skip=${skip}&limit=20`);const bank=data.bank;
  const name=el('input',{value:bank.name}),description=el('textarea',{},bank.description);
  show(heading(bank.name,bank.status==='ACTIVE'?'选择、移除或显式替换成员版本。':'已归档'),button('返回题库',back),
    el('section',{class:'panel'},field('名称',name),field('说明',description),el('div',{class:'actions'},
      button('保存题库信息',async()=>{await api('/banks/'+bankId,'PATCH',{revision:bank.revision,name:name.value,description:description.value,status:bank.status});await bankView(bankId,back,skip);}),
      button(bank.status==='ACTIVE'?'归档题库':'恢复题库',async()=>{await api('/banks/'+bankId,'PATCH',{revision:bank.revision,name:bank.name,description:bank.description,status:bank.status==='ACTIVE'?'ARCHIVED':'ACTIVE'});await bankView(bankId,back,skip);}),
      bank.status==='ACTIVE'?button('添加题目版本',()=>pickVersion(async v=>{await api('/banks/'+bankId+'/items','POST',{versionId:v.id});await bankView(bankId,back,skip);},()=>bankView(bankId,back,skip))):null)));
  for(const m of data.items)root.append(el('section',{class:'panel'},el('h3',{},`${m.name} · v${m.versionNo}`),el('p',{class:'muted'},m.available?'可选用':'权限已撤销或题目归档；不能新选用'),
    el('div',{class:'actions'},button('更新成员版本',()=>pickVersion(async v=>{await api(`/banks/${bankId}/items/${m.id}`,'PATCH',{revision:m.revision,versionId:v.id,position:m.position});await bankView(bankId,back,skip);},()=>bankView(bankId,back,skip))),
      button('移除成员',async()=>{await api(`/banks/${bankId}/items/${m.id}`,'DELETE',{revision:m.revision});await bankView(bankId,back,skip);},'danger'))));
  root.append(pager(skip,data.total,n=>bankView(bankId,back,n)));
}

async function usageView(item,back,skip=0){
  const data=await api(`/library/questions/${item.id}/usages?skip=${skip}&limit=20`);
  show(heading('题目使用情况',item.name+'；他人问卷仅显示固定标识、版本和状态。'),button('返回',back));
  for(const use of data.items)root.append(el('section',{class:'panel'},el('h3',{},use.title||'问卷 '+use.displayId),el('p',{},statuses[use.status]),
    ...use.instances.map(i=>el('p',{},`版本 v${i.versionNo} · ${i.linkStatus==='SUSPENDED'?'关联暂停':'有效采用'}`))));
  root.append(pager(skip,data.total,n=>usageView(item,back,n)));
}

export async function crossView(itemId,v,back){
  const data=await api(`/library/questions/${itemId}/stats?versionIds=${v.id}`);const result=data.versions[0];
  show(heading('单题跨问卷统计',`${v.payload.title} · 确切版本 v${result.versionNo} · ${data.scope==='AUTHOR_ALL'?'全部有效采用':'仅自有问卷'}`),button('返回',back),
    el('p',{class:'muted'},`按正式答案实例计数；答卷数另行去重，不提供全局独立人数。k=${data.privacyK}为建议参数，尚待最终确认。`));
  for(const [label,summary]of [['自有问卷',result.own],['他人问卷',result.foreign],['合并结果',result.combined]]){
    const section=el('section',{class:'panel'},el('h2',{},label));
    if(!summary)section.append(el('p',{},privacyNames[result.foreignStatus]));
    else{
      section.append(el('p',{},`有效回答 ${summary.answerCount} · 答卷 ${summary.responseCount}${summary.mean!==null?' · 均值 '+summary.mean:''}`));
      for(const cell of summary.distribution)section.append(el('div',{class:'summary-line'},`${cell.label??`[${cell.lower??'−∞'}, ${cell.upper??'+∞'})`}：${cell.count}`));
    }
    root.append(section);
  }
}

export async function legacyView(survey,back){
  show(heading('问卷题目与历史关联',survey.title+'；保存库题和建立统计关联是两个独立操作。'),button('返回问卷',back));
  for(const q of survey.questions){
    const section=el('section',{class:'panel'},el('h2',{},q.title),el('p',{class:'muted'},types[q.type]),
      button('保存为我的题目',()=>{
        const name=el('input',{value:q.title}),cuts=el('input');
        show(heading('保存本卷题目','保留选项ID；不会改写问卷，也不会自动关联历史答案。'),el('section',{class:'panel'},field('管理名称',name),
          q.type==='NUMBER'?field('数字切点（无上下界时必填）',cuts):null,button('确认保存为题目',async()=>{
            const data={name:name.value};if(cuts.value.trim())data.summaryPolicy={policyVersion:1,numericCuts:cuts.value.split(/[,，]/).map(s=>s.trim())};
            const saved=await api(`/surveys/${survey.id}/questions/${q.questionId}/save-to-library`,'POST',data);
            notice('题目已保存；历史回答尚未关联');await legacyView(survey,back);
          },'primary'),button('返回',()=>legacyView(survey,back))));
      }));
    if(q.sourceRef)section.append(el('p',{},'已绑定固定版本 '+short(q.sourceRef.questionVersionId)),
      button('查看该版汇总',()=>crossView(q.sourceRef.libraryQuestionId,{id:q.sourceRef.questionVersionId,payload:payload(q)},()=>legacyView(survey,back))));
    else if(survey.schemaVersion===1&&survey.status!=='DRAFT'){
      const path=`/surveys/${survey.id}/questions/${q.questionId}/library-link`;
      const link=await api(path);section.append(el('p',{},link.current?`${link.current.operation==='SUSPEND'?'已暂停':'已关联'}：${short(link.current.questionVersionId)} · 修订 ${link.head.revision}`:'尚未关联'));
      const perform=async(v,operation,reason='')=>confirmReuse(v,async ack=>{
        await api(path+(operation==='BIND'?'':'/corrections'),operation==='BIND'?'PUT':'POST',{
          ...ack,versionId:v.id,expectedLinkRevision:link.head?.revision||0,operationKey:key(),operation,reason});
        notice('关联状态已保存');await legacyView(survey,back);
      },()=>legacyView(survey,back));
      section.append(button(link.current?'更正关联版本':'选择版本并关联',()=>pickVersion(async v=>{
        if(!link.current)return perform(v,'BIND');
        const reason=el('input');show(heading('更正历史关联','新版本必须与旧快照内容一致，不重写旧答案。'),field('更正原因',reason),
          button('继续确认',()=>perform(v,'CORRECT',reason.value)),button('返回',()=>legacyView(survey,back)));
      },()=>legacyView(survey,back))));
      if(link.current)section.append(button(link.current.operation==='SUSPEND'?'恢复关联':'暂停关联',()=>{
        const reason=el('input');const operation=link.current.operation==='SUSPEND'?'RESUME':'SUSPEND';
        show(heading(operation==='RESUME'?'恢复关联':'暂停关联','只修改关联指针，不改原问卷或答卷。'),field('原因',reason),button('确认操作',async()=>{
          const apply=async ack=>{await api(path+'/corrections','POST',{versionId:link.current.questionVersionId,expectedLinkRevision:link.head.revision,operationKey:key(),operation,reason:reason.value,...ack});await legacyView(survey,back);};
          if(operation==='RESUME')await confirmReuse(await api('/library/versions/'+link.current.questionVersionId),apply,()=>legacyView(survey,back));
          else await apply({reusePolicyVersion:1,acknowledged:false});
        }),button('返回',()=>legacyView(survey,back)));
      }),button('关联历史',async()=>{
        const data=await api(path+'/history?limit=100');show(heading('关联历史',q.title),...data.items.map(r=>el('section',{class:'panel'},`${r.operation} · ${short(r.questionVersionId)} · ${r.reason||'首次关联'} · ${time(r.createdAt)}`)),button('返回',()=>legacyView(survey,back)));
      }));
    }
    root.append(section);
  }
}
