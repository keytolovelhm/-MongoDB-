import {api, el, root, field, button, types, heading, notice, select, time} from './core.js';

export async function filler(slug) {
  const survey = await api('/public/'+slug);
  let attempt=null, current=null, pendingKey=crypto.randomUUID();
  const recent=await api('/public/'+slug+'/my-attempts');
  function start(){
    root.replaceChildren(heading(survey.title,survey.description,'填写问卷'));
    const panel=el('section',{class:'panel'},el('h2',{},survey.effectiveStatus==='PUBLISHED'?'开始填写':'问卷已结束'),
      el('p',{class:'muted'},`截止时间：${time(survey.closesAt)}。${survey.allowMultipleSubmissions?'允许多次填写，每次提交独立保存。':'每个账号限提交一次。'}`));
    if(survey.effectiveStatus==='PUBLISHED'){
      let mode='IDENTIFIED';
      panel.append(field('参与方式',select([['IDENTIFIED','实名填写'],...(survey.anonymousEnabled?[['ANONYMOUS','对创建者匿名']]:[])],mode,v=>mode=v)),
        el('p',{class:'muted'},'每次点击“保存并继续”后保存进度。匿名填写仍需要登录，系统使用问卷内伪名限制重复；创建者看不到匿名者账号。'),
        button('新建一次填写',async()=>{
          attempt=await api('/public/'+slug+'/attempts','POST',{attemptKey:pendingKey,participationMode:mode});
          pendingKey=crypto.randomUUID();current=attempt.nextQuestionId;render();
        },'primary'));
    }
    root.append(panel);
    if(recent.items.length){
      const list=el('section',{class:'panel'},el('h2',{},'我的近期填写'));
      for(const item of recent.items)list.append(el('div',{class:'toolbar'},el('span',{},`${time(item.startedAt)} · ${item.participationMode==='ANONYMOUS'?'匿名':'实名'} · ${item.status==='SUBMITTED'?'已提交':'草稿'}`),
        button(item.status==='SUBMITTED'?'查看回执':survey.effectiveStatus==='PUBLISHED'?'恢复草稿':'查看已保存内容',async()=>{
          attempt=await api('/attempts/'+item.id);current=attempt.nextQuestionId;render();
        })));
      root.append(list);
    }
  }
  function render(){
    root.replaceChildren(heading(survey.title,survey.description,'填写问卷'));
    const readonly=attempt.status==='SUBMITTED'||survey.effectiveStatus!=='PUBLISHED';
    const values=Object.fromEntries(attempt.answers.map(a=>[a.questionId,a.value]));
    if(readonly){
      root.append(el('section',{class:'panel'},el('h2',{class:'success'},attempt.status==='SUBMITTED'?'提交成功，感谢填写':'问卷已结束，以下为已保存内容'),
        el('p',{},`填写回执：${attempt.id}`),el('p',{class:'muted'},`参与方式：${attempt.participationMode==='ANONYMOUS'?'匿名':'实名'}；${attempt.submittedAt?'提交时间：'+time(attempt.submittedAt):'尚未提交，不计入统计'}`),summary(values),button('返回填写记录',async()=>{await filler(slug);})));
      return;
    }
    const nav=el('div',{class:'question-nav'});
    survey.questions.forEach((q,i)=>{if(attempt.visitedQuestionIds.includes(q.questionId))nav.append(button(`${i+1}`,()=>{current=q.questionId;render();},current===q.questionId?'active':''));});
    root.append(el('p',{class:'saved'},`已保存 ${attempt.answers.length} 题 · 回看修改会重算路径，可能保守清理后续旧答案`),nav);
    if(attempt.removedQuestionIds?.length){
      const removed=new Set(attempt.removedQuestionIds);
      const labels=survey.questions.map((q,i)=>removed.has(q.questionId)?`第${i+1}题「${q.title}」`:null).filter(Boolean);
      root.append(el('section',{class:'panel',role:'status','aria-live':'polite','aria-label':'已清除答案提示'},
        el('h2',{},`已清除${removed.size}题已保存答案`),el('p',{class:'long-text'},labels.join('；')),
        el('p',{class:'muted'},'路径已重新计算；新出现的待答题之后的旧答案也会保守清除。请沿当前路径重新填写，已清除的内容不会自动恢复。')));
    }
    if(!current){
      root.append(el('section',{class:'panel'},el('h2',{},'填写完成，请核对后提交'),summary(values),el('div',{class:'actions'},
        button('提交问卷',async()=>{attempt=await api('/attempts/'+attempt.id+'/submit','POST',{revision:attempt.revision});render();},'primary'),
        button('刷新已保存内容',async()=>{attempt=await api('/attempts/'+attempt.id);current=attempt.nextQuestionId;render();}))));return;
    }
    const q=survey.questions.find(q=>q.questionId===current);
    const form=el('section',{class:'panel'},el('p',{class:'eyebrow'},types[q.type]),el('h2',{},q.title,q.required?el('span',{class:'required'},' *'):''));
    let getValue;
    if(q.type==='SINGLE'||q.type==='MULTI'){
      const inputs=q.options.map(o=>el('input',{type:q.type==='SINGLE'?'radio':'checkbox',name:'answer',value:o.optionId,
        checked:q.type==='SINGLE'?values[q.questionId]===o.optionId:(values[q.questionId]||[]).includes(o.optionId)}));
      q.options.forEach((o,i)=>form.append(el('label',{class:'answer-option'},inputs[i],o.label)));
      if(q.type==='SINGLE'&&!q.required)form.append(button('清空选择',()=>inputs.forEach(i=>i.checked=false)));
      getValue=()=>q.type==='SINGLE'?(inputs.find(i=>i.checked)?.value||null):inputs.filter(i=>i.checked).map(i=>i.value);
    }else{
      const input=q.type==='TEXT'?el('textarea',{'aria-label':q.title},values[q.questionId]??''):el('input',{type:'text',inputmode:'decimal','aria-label':q.title,value:values[q.questionId]??''});
      form.append(input);getValue=()=>input.value;
    }
    const c=q.constraints;
    let hint=q.required?'必答。':'可留空，点击保存后跳过。';
    if(q.type==='MULTI')hint+=` 最少${c.minSelections??0}项，最多${c.maxSelections??q.options.length}项。`;
    if(q.type==='TEXT')hint+=` 去除首尾空白后长度${c.minLength??0}至${c.maxLength??10000}个Unicode码点。`;
    if(q.type==='NUMBER')hint+=` ${c.integerOnly?'要求整数。':''}${c.minValue!==null&&c.minValue!==undefined?'最小值'+c.minValue+'。':''}${c.maxValue!==null&&c.maxValue!==undefined?'最大值'+c.maxValue+'。':''}`;
    form.append(el('p',{class:'muted'},hint),button('保存并继续',async()=>{
      attempt=await api('/attempts/'+attempt.id+'/answer','PUT',{revision:attempt.revision,questionId:q.questionId,value:getValue()});
      current=attempt.nextQuestionId;
      notice(attempt.removedQuestionIds.length?`已保存，并清理${attempt.removedQuestionIds.length}题失效答案`:'答案已保存');render();
    },'primary'));root.append(form);
  }
  function summary(values){
    return el('div',{},...survey.questions.filter(q=>q.questionId in values).map(q=>{
      let value=values[q.questionId];if(q.type==='SINGLE')value=q.options.find(o=>o.optionId===value)?.label??'未填写';
      if(q.type==='MULTI')value=(value||[]).map(v=>q.options.find(o=>o.optionId===v)?.label||v).join('、');
      return el('div',{class:'summary-line'},el('strong',{},q.title),el('div',{class:'long-text'},value===null||value===''?'未填写':value));
    }));
  }
  start();
}
