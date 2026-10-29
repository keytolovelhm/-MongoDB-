import {api, el, root, field, select, button, check, types, heading, notice, dateInput} from './core.js';
import {pickVersion,confirmReuse,legacyView} from './library.js';

const uid = () => crypto.randomUUID().replaceAll('-', '');
function question(type='SINGLE') { return {questionId:uid(), order:0, title:'', type, required:false, options:type==='SINGLE'||type==='MULTI'?[{optionId:uid(),label:'选项一'},{optionId:uid(),label:'选项二'}]:[], constraints:{}, rules:[]}; }
export function sample() {
  const questions = [question(), question('TEXT'), question('MULTI'), question('NUMBER'), question('TEXT')];
  questions.forEach((q,i)=>{q.order=i;});
  questions[0].title='请选择填写路径'; questions[0].required=true;
  questions[0].options[0].label='直接进入最后一题'; questions[0].options[1].label='填写多选题与数字题';
  questions[0].rules=[{ruleId:uid(),priority:0,condition:{op:'eq',value:questions[0].options[0].optionId},target:questions[4].questionId},
    {ruleId:uid(),priority:1,condition:{op:'eq',value:questions[0].options[1].optionId},target:questions[2].questionId}];
  questions[1].title='本题会被上述两条规则跳过'; questions[1].required=true;
  questions[2].title='喜欢的水果（至少1项，最多2项）'; questions[2].options[0].label='苹果';questions[2].options[1].label='香蕉';
  questions[2].constraints={minSelections:1,maxSelections:2}; questions[2].required=true;
  questions[3].title='年龄（0至120的整数）';questions[3].constraints={minValue:'0',maxValue:'120',integerOnly:true};questions[3].required=true;
  questions[4].title='还有什么想补充的？';questions[4].constraints={maxLength:1000};
  return {title:'跳转与校验演示问卷',description:'示例数据由AI生成，用于演示单选跳转、多选限制、数字校验和文本填写。',anonymousEnabled:true,allowMultipleSubmissions:true,closesAt:null,questions};
}

export async function editor(survey, back) {
  const draft = structuredClone(survey || {title:'',description:'',anonymousEnabled:false,allowMultipleSubmissions:false,closesAt:null,questions:[]});
  async function persist(){
    const payload={title:draft.title,description:draft.description,anonymousEnabled:draft.anonymousEnabled,allowMultipleSubmissions:draft.allowMultipleSubmissions,closesAt:draft.closesAt,
      questions:draft.questions.map((q,i)=>Object.fromEntries([...['questionId','title','type','required','options','constraints','rules'].map(k=>[k,q[k]]),['order',i]]))};
    const saved=draft.id?await api('/surveys/'+draft.id,'PUT',{...payload,revision:draft.revision}):await api('/surveys','POST',payload);
    Object.assign(draft,saved);return saved;
  }
  async function choose(replaceQuestionId=null){
    await persist();
    await pickVersion(v=>confirmReuse(v,async ack=>{
      const saved=await api('/surveys/'+draft.id+'/questions/import','POST',{...ack,revision:draft.revision,versionId:v.id,replaceQuestionId});
      Object.assign(draft,saved);notice('已导入固定版本');render();
    },render),render);
  }
  function render() {
    root.replaceChildren(heading(draft.id ? '编辑问卷' : '新建问卷', '保存草稿后可继续编辑；发布后题目、选项、规则和参与策略会冻结。'));
    const title = el('input',{value:draft.title,required:true,maxlength:200,onInput:e=>draft.title=e.target.value});
    const description=el('textarea',{maxlength:5000,onInput:e=>draft.description=e.target.value},draft.description);
    const deadline=dateInput(draft.closesAt);deadline.addEventListener('change',()=>draft.closesAt=deadline.value?new Date(deadline.value).toISOString():null);
    const basic=el('section',{class:'panel'},el('h2',{},'基本信息'),field('问卷标题',title),field('问卷说明',description),field('截止时间（可留空）',deadline),
      check('允许登录者对创建者匿名',draft.anonymousEnabled,v=>draft.anonymousEnabled=v),check('允许同一账号多次填写',draft.allowMultipleSubmissions,v=>draft.allowMultipleSubmissions=v));
    root.append(basic);
    const questions=el('section',{class:'panel'},el('h2',{},'题目与跳转规则'));
    draft.questions.forEach((q,i)=>questions.append(questionEditor(q,i)));
    questions.append(el('div',{class:'actions'},button('＋ 添加题目',()=>{draft.questions.push(question());render();}),
      button('从题目库选题',()=>choose()),draft.id?button('保存本卷题目到题目库',async()=>{await persist();await legacyView(draft,render);}):null));root.append(questions);
    root.append(el('div',{class:'toolbar'},button('返回列表',()=>{if(confirm('离开编辑页面？未保存的改动会丢失。'))back();}),
      button('保存草稿',async()=>{
        await persist();notice('草稿已保存');render();
      },'primary')));
  }
  function questionEditor(q,index) {
    const title=el('input',{value:q.title,maxlength:1000,onInput:e=>q.title=e.target.value});
    const body=el('article',{class:'question-editor'},el('div',{class:'section-title'},el('h3',{},`第 ${index+1} 题`),el('div',{class:'actions'},
      button('上移',()=>{if(index){[draft.questions[index-1],draft.questions[index]]=[q,draft.questions[index-1]];render();}}),
      button('下移',()=>{if(index<draft.questions.length-1){[draft.questions[index+1],draft.questions[index]]=[q,draft.questions[index+1]];render();}}),
      button('删除',()=>{if(confirm('删除题目？引用它的跳转规则也需要调整。')){draft.questions.splice(index,1);render();}},'danger'))),
      field('题干',title),field('题型',select(Object.entries(types),q.type,v=>{const fresh=question(v);q.type=v;q.options=fresh.options;q.constraints={};q.rules=[];render();})),check('必答题',q.required,v=>q.required=v));
    if(['SINGLE','MULTI'].includes(q.type)) {
      body.append(el('p',{class:'muted'},'选项文字可修改，选项ID保持不变。'));
      q.options.forEach((o,i)=>body.append(el('div',{class:'option-editor'},el('input',{value:o.label,'aria-label':`第${index+1}题选项${i+1}`,onInput:e=>o.label=e.target.value}),button('移除',()=>{q.options.splice(i,1);render();}))));
      body.append(button('添加选项',()=>{q.options.push({optionId:uid(),label:'新选项'});render();}));
    }
    const constraints=el('div',{class:'two'});q.constraints ||= {};
    const fields={MULTI:[['minSelections','最少选择'],['maxSelections','最多选择']],TEXT:[['minLength','最短长度'],['maxLength','最长长度']],NUMBER:[['minValue','最小值'],['maxValue','最大值']]}[q.type]||[];
    for(const [key,label]of fields)constraints.append(field(label,el('input',{type:q.type==='NUMBER'?'text':'number',value:q.constraints[key]??'',onInput:e=>{
      if(e.target.value==='') delete q.constraints[key];else q.constraints[key]=q.type==='NUMBER'?e.target.value:Number(e.target.value);
    }})));
    body.append(constraints);
    if(q.type==='MULTI')body.append(el('small',{},'恰好选择N项：将最少和最多都设为N。非必答题留空可跳过。'));
    if(q.type==='TEXT')body.append(el('small',{},'长度按去除首尾空白后的Unicode码点计算。'));
    if(q.type==='NUMBER')body.append(check('只允许整数',q.constraints.integerOnly||false,v=>q.constraints.integerOnly=v));
    if(q.sourceRef){
      const content=el('fieldset',{disabled:true,class:'snapshot-body'});
      for(const child of [...body.children].slice(1))content.append(child);
      body.append(content,el('p',{class:'muted'},'库题固定快照 · 版本 '+q.sourceRef.questionVersionId.slice(-8)+'；正文只读，顺序和本卷规则可调整。'),
        button('选择其他版本替换',()=>choose(q.questionId)));
    }
    if(q.type!=='TEXT'){
      body.append(el('h3',{},'条件跳转'),el('p',{class:'muted'},'优先级数字越小越先匹配；第一条命中即生效。未命中进入下一题。'));
      q.rules.forEach((rule,rindex)=>body.append(ruleEditor(q,rule,rindex,index)));
      body.append(button('添加跳转规则',()=>{
        q.rules.push({ruleId:uid(),priority:q.rules.length?Math.max(...q.rules.map(r=>r.priority))+1:0,condition:{op:q.type==='MULTI'?'contains_any':'eq',value:q.type==='MULTI'?[q.options[0]?.optionId||'']:q.type==='SINGLE'?q.options[0]?.optionId||'':'0'},target:'END'});render();
      }));
    }
    return body;
  }
  function ruleEditor(q,r,ri,qi){
    const ops=q.type==='SINGLE'?[['eq','等于']]:q.type==='MULTI'?[['contains_any','包含任一'],['contains_all','包含全部'],['set_equals','恰好这些']]:[['eq','等于'],['gt','大于'],['gte','大于等于'],['lt','小于'],['lte','小于等于'],['between','闭区间']];
    const targetOptions=[['END','结束问卷'],...draft.questions.slice(qi+1).map((v,i)=>[v.questionId,`第${qi+i+2}题 ${v.title.slice(0,18)}`])];
    if(!targetOptions.some(x=>x[0]===r.target))targetOptions.push([r.target,'失效目标，请重新选择']);
    const valueBox=el('div',{});
    if(q.type==='SINGLE') valueBox.append(field('匹配选项',select(q.options.map(o=>[o.optionId,o.label]),r.condition.value,v=>r.condition.value=v)));
    else if(q.type==='MULTI'){
      valueBox.append(el('small',{},'匹配选项'));
      q.options.forEach(o=>valueBox.append(check(o.label,Array.isArray(r.condition.value)&&r.condition.value.includes(o.optionId),yes=>{
        const set=new Set(Array.isArray(r.condition.value)?r.condition.value:[]);yes?set.add(o.optionId):set.delete(o.optionId);r.condition.value=[...set];
      })));
    }else valueBox.append(field(r.condition.op==='between'?'上下界（逗号分隔）':'阈值',el('input',{value:Array.isArray(r.condition.value)?r.condition.value.join(','):r.condition.value,onInput:e=>{
      r.condition.value=r.condition.op==='between'?e.target.value.split(',').map(v=>v.trim()):e.target.value;
    }})));
    return el('div',{class:'rule'},el('div',{class:'rule-fields'},field('优先级',el('input',{type:'number',min:0,value:r.priority,onInput:e=>r.priority=Number(e.target.value)})),
      field('条件',select(ops,r.condition.op,v=>{r.condition.op=v;r.condition.value=q.type==='NUMBER'&&v==='between'?['0','1']:q.type==='NUMBER'?'0':r.condition.value;render();})),valueBox,
      field('跳转目标',select(targetOptions,r.target,v=>r.target=v))),button('删除规则',()=>{q.rules.splice(ri,1);render();},'danger'));
  }
  render();
}
