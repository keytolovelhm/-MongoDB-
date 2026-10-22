import {api, el, root, heading, button, time, types} from './core.js';

export async function stats(survey, back){
  const data=await api('/surveys/'+survey.id+'/stats');
  root.replaceChildren(heading(survey.title,'统计仅包含正式提交的有效答卷；被跳过或失效的答案不参与计算。','结果统计'),button('返回问卷列表',back),
    el('div',{class:'toolbar'},el('div',{class:'grid'},metric(data.responseCount,'有效答卷数'),metric(data.respondentCount,'独立填写账号数')),
      button('刷新统计',()=>stats(survey,back))));
  for(const q of data.questions){
    const panel=el('section',{class:'panel'},el('p',{class:'eyebrow'},types[q.type]),el('h2',{},q.title),
      el('p',{class:'muted'},`有效回答 ${q.answerCount} 份 · 独立回答账号 ${q.respondentCount} 个 · 到达 ${q.reachedCount} 份`));
    if(q.options)for(const o of q.options)panel.append(el('div',{class:'stat-row'},el('span',{},o.label),el('progress',{max:Math.max(q.answerCount,1),value:o.count}),el('span',{},`${o.count} 次 / ${o.respondentCount} 账号`)));
    if(q.type==='MULTI')panel.append(el('small',{},'每个选项按出现的答卷计次；合计可超过答卷数。'));
    if(q.type==='NUMBER')panel.append(el('p',{},'数字平均值：',el('strong',{},q.mean??'暂无数据')));
    const values=el('div',{});panel.append(values);
    panel.append(button('查看全部回答（分页）',()=>loadAnswers(q.questionId,values,0)));
    root.append(panel);
  }
  function metric(value,label){return el('div',{class:'metric'},el('strong',{},value),el('span',{},label));}
  async function loadAnswers(qid,container,skip){
    const result=await api(`/surveys/${survey.id}/stats/${qid}/answers?skip=${skip}&limit=20`);
    const definition=survey.questions.find(q=>q.questionId===qid);
    const table=el('table',{},el('thead',{},el('tr',{},...['填写内容','参与方式','提交时间'].map(t=>el('th',{},t)))),el('tbody',{},...result.items.map(row=>{
      let value=row.value;
      if(definition.type==='SINGLE')value=definition.options.find(o=>o.optionId===value)?.label||value;
      if(definition.type==='MULTI')value=value.map(v=>definition.options.find(o=>o.optionId===v)?.label||v).join('、');
      return el('tr',{},el('td',{class:'long-text'},value),el('td',{},row.participationMode==='ANONYMOUS'?'匿名':'实名'),el('td',{},time(row.submittedAt)));
    })));
    container.replaceChildren(el('p',{class:'muted'},`共${result.total}条，本页${skip+1}至${Math.min(skip+20,result.total)}条`),el('div',{class:'table-wrap'},table),
      el('div',{class:'actions'},skip>0?button('上一页',()=>loadAnswers(qid,container,Math.max(0,skip-20))):null,
        skip+20<result.total?button('下一页',()=>loadAnswers(qid,container,skip+20)):null));
  }
}
