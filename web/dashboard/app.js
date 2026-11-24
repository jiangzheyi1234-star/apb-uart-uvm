/* APB UART verification workbench. Buildless, offline, no fetch or external code. */
(() => {
  "use strict";

  const root = document.getElementById("workspace");
  const title = document.getElementById("page-title");
  const nav = document.getElementById("workspace-nav");
  const raw = window.UART_DASHBOARD;
  const SVG = "http://www.w3.org/2000/svg";
  const VIEWS = {overview:"验证总览",regressions:"回归记录",coverage:"覆盖与缺口",waveforms:"波形与总线",architecture:"验证架构",defects:"缺陷对照"};
  const missing = "未记录";
  const list = value => Array.isArray(value) ? value : [];
  const finite = value => typeof value === "number" && Number.isFinite(value);
  const hasId = value => (typeof value === "string" && value.trim() !== "") || finite(value);
  const inputNumber = input => input.value.trim() === "" ? null : Number(input.value);
  const text = value => value === null || value === undefined || value === "" ? missing : String(value);
  const number = value => finite(value) ? new Intl.NumberFormat("zh-CN", {maximumFractionDigits:3}).format(value) : missing;
  const time = value => finite(value) ? new Intl.NumberFormat("zh-CN", {maximumFractionDigits:3}).format(value) : missing;
  const plural = (count, noun) => `${number(count)} ${noun}`;
  const collator = new Intl.Collator("zh-CN", {numeric:true, sensitivity:"base"});
  const phaseName = value => ({positive:"正向",negative:"负向",recovery:"故障后恢复",control_before:"注入前控制",control_after:"注入后控制",mutation:"指定故障"})[value] || text(value);
  const variantName = value => ({fixed:"修复版",upstream:"未修改原版"})[value] || text(value);

  function el(tag, props, ...children) {
    const node = document.createElement(tag);
    for (const [key,value] of Object.entries(props || {})) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "className") node.className = value;
      else if (key === "style" && typeof value === "object") Object.assign(node.style, value);
      else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2).toLowerCase(), value);
      else if (["value","checked","disabled","hidden","selected","tabIndex"].includes(key)) node[key] = value;
      else node.setAttribute(key, value === true ? "" : String(value));
    }
    for (const child of children.flat(Infinity)) {
      if (child !== null && child !== undefined && child !== false) node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  function svgEl(tag, props, ...children) {
    const node = document.createElementNS(SVG, tag);
    for (const [key,value] of Object.entries(props || {})) if (value !== null && value !== undefined) node.setAttribute(key,String(value));
    for (const child of children.flat(Infinity)) if (child !== null && child !== undefined) node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    return node;
  }

  function safeHref(value) {
    if (typeof value !== "string" || !value.trim()) return null;
    const href = value.trim();
    if (/^(https?):\/\//i.test(href)) return href;
    if (/^[a-z][a-z0-9+.-]*:/i.test(href) || href.startsWith("//") || /[\u0000-\u001f]/.test(href)) return null;
    return href;
  }

  function link(label, href, props = {}) {
    const safe = safeHref(href);
    if (!safe) return el("span",{className:"secondary"},label);
    return el("a",{href:safe,...(/^https?:/i.test(safe) ? {target:"_blank",rel:"noopener noreferrer"} : {}),...props},label);
  }

  const button = (label, action, props = {}) => el("button",{type:"button",className:"button",onClick:action,...props},label);
  const empty = (heading, message) => el("div",{className:"empty-state"},el("h3",{},heading),el("p",{},message));
  function announce(message) { document.getElementById("live-message").textContent = message; }
  function panel(heading, description, ...content) {
    return el("section",{className:"panel"},el("div",{className:"panel-heading"},el("div",{},el("h2",{},heading),description ? el("p",{},description) : null)),...content);
  }
  function table(headers, rows, props = {}) {
    return el("div",{className:"table-scroll",...props},el("table",{},el("thead",{},el("tr",{},headers.map(item=>el("th",{scope:"col"},item)))),el("tbody",{},rows)));
  }
  function badge(value, type) {
    let kind = type || (value === "PASS" ? "pass" : ["FAIL","ERROR","FATAL","TIMEOUT","BUILD_FAIL","INVALID"].includes(value) ? "fail" : "unknown");
    return el("span",{className:`badge badge--${kind}`},text(value));
  }
  function resultBadges(run) {
    return el("div",{className:"stack vertical"},badge(run.raw_status),
      run.classification === "DETECTED" ? badge("DETECTED","detected") :
      run.expected === true && run.raw_status === "FAIL" ? badge("预期失败","expected") :
      run.expected === false && run.raw_status === "FAIL" ? badge("非预期失败","fail") : null);
  }
  function metricPair(metric) {
    return metric && finite(metric.hit) && finite(metric.total) && metric.hit >= 0 && metric.total > 0 && metric.hit <= metric.total ? metric : null;
  }
  const percent = metric => { const m = metricPair(metric); return m ? `${(100*m.hit/m.total).toFixed(2)}%` : missing; };
  const metricText = metric => { const m=metricPair(metric); return m ? `${number(m.hit)} / ${number(m.total)}` : missing; };
  function sumComplete(rows, name) {
    return rows.length && rows.every(run=>finite(run.metrics?.[name])) ? rows.reduce((total,run)=>total+run.metrics[name],0) : null;
  }
  function makeField(label, control, props={}) {
    return el("label",{className:`field${props.wide ? " wide" : ""}`},el("span",{className:"field-label"},label),control);
  }
  function makeSelect(options, value, callback, props={}) {
    const select = el("select",{...props,onChange:event=>callback(event.target.value)});
    for (const item of options) select.append(el("option",{value:item.value},item.label));
    select.value = String(value ?? "");
    return select;
  }
  function downloadCSV(filename, columns, rows) {
    const cell = value => {
      let string = value === null || value === undefined ? "" : String(value);
      if (/^[=+@-]/.test(string)) string="'"+string;
      return '"'+string.replaceAll('"','""')+'"';
    };
    const csv = [columns,...rows].map(row=>row.map(cell).join(",")).join("\r\n");
    const url=URL.createObjectURL(new Blob(["\ufeff",csv],{type:"text/csv;charset=utf-8"}));
    const anchor=el("a",{href:url,download:filename});document.body.append(anchor);anchor.click();anchor.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }

  if (!raw || raw.schema_version !== 1 || !Array.isArray(raw.runs)) {
    root.replaceChildren(el("div",{className:"empty-state error-state",role:"alert"},el("h2",{},"报告数据缺失"),el("p",{},"请解压同版本证据包，并保留 assets 和 data 目录。也可直接打开下方原始报告。"),el("div",{className:"evidence-links",style:{justifyContent:"center"}},link("原始回归报告","release/index.html"),link("专项证据","features/index.html"))));
    nav.querySelectorAll("button").forEach(node=>node.disabled=true);
    return;
  }

  const data=raw;
  const runs=list(data.runs).filter(value=>value&&typeof value==="object");
  const suites=list(data.suites);
  const coverage=list(data.coverage);
  const waves=list(data.waveforms);
  const suitesById=new Map(suites.map(suite=>[suite.id,suite]));
  const runsById=new Map(runs.filter(run=>hasId(run.id)).map(run=>[run.id,run]));
  const suiteTitle = id => text(suitesById.get(id)?.title || id);
  const state={tab:"overview",reg:{runId:"",suite:"",variant:"",test:"",seed:"",status:"",phase:"",query:"",page:1,size:25,sort:"recorded"},coverageId:coverage[0]?.id,waveId:waves[0]?.id,waveState:new Map(),waveReturn:null};
  let cleanupView=()=>{};

  function counts(rows) {
    return {total:rows.length,pass:rows.filter(run=>run.raw_status==="PASS").length,fail:rows.filter(run=>run.raw_status==="FAIL").length,
      detected:rows.filter(run=>run.raw_status==="FAIL"&&run.classification==="DETECTED").length,
      expected:rows.filter(run=>run.raw_status==="FAIL"&&run.expected===true&&run.classification!=="DETECTED").length,
      other:rows.filter(run=>!["PASS","FAIL"].includes(run.raw_status)).length};
  }

  function setView(name, focus=false) {
    if (!VIEWS[name]) name="overview";
    cleanupView();cleanupView=()=>{};state.tab=name;
    title.textContent=VIEWS[name];
    document.title=`${VIEWS[name]} · ${text(data.project?.title || "APB UART")}`;
    nav.querySelectorAll("button[data-tab]").forEach(node=>{
      if(node.dataset.tab===name)node.setAttribute("aria-current","page");else node.removeAttribute("aria-current");
    });
    try { if(location.hash!=="#"+name)history.replaceState(null,"","#"+name); } catch (_) { if(location.hash!=="#"+name)location.hash=name; }
    root.replaceChildren();
    ({overview:renderOverview,regressions:renderRegressions,coverage:renderCoverage,waveforms:renderWaveforms,architecture:renderArchitecture,defects:renderDefects})[name]();
    if(focus) {
      root.focus({preventScroll:true});
      window.scrollTo(0, 0);
    }
  }

  function showRuns(filters) {
    Object.assign(state.reg,{runId:"",suite:"",variant:"",test:"",seed:"",status:"",phase:"",query:"",page:1},filters);
    setView("regressions",true);
  }
  function showRun(run) {
    if(!hasId(run.id))return;
    showRuns({runId:run.id,suite:String(run.suite_id??"__missing__"),variant:String(run.variant??"__missing__"),test:String(run.test??"__missing__"),seed:String(run.seed??"__missing__"),phase:run.phase?String(run.phase):""});
  }
  function showWave(id) {
    state.waveReturn = state.tab === "regressions" ? {...state.reg} : null;
    state.waveId = id;
    setView("waveforms", true);
  }
  function intro(message) { root.append(el("div",{className:"view-intro"},el("p",{},message))); }
  function evidenceLinks(items) { return el("div",{className:"evidence-links"},list(items).map(item=>link(text(item.label),item.url))); }

  function renderOverview() {
    const project=data.project||{};
    const headline=data.headline||{};
    const headlineIds=list(headline.suite_ids);
    const headlineRuns=runs.filter(run=>headlineIds.includes(run.suite_id)&&run.variant===headline.variant);
    const h=counts(headlineRuns);
    const passing=headlineRuns.filter(run=>run.raw_status==="PASS");
    const tx=sumComplete(passing,"tx"),rx=sumComplete(passing,"rx");
    const core=coverage.find(item=>item.suite_id===headlineIds[0]&&item.variant===headline.variant);
    const card=(label,value,detail)=>el("article",{className:"metric-card"},el("span",{className:"metric-label"},label),el("strong",{className:`metric-number${String(value).length>15 ? " small-value" : ""}`},value),el("div",{className:"metric-detail"},detail));
    root.append(el("div",{className:"metrics-grid"},
      card("修复版 UART · 核心 + RAL",headlineRuns.length?`${h.pass} / ${h.total}`:missing,"原始 PASS / 已记录运行；不含协议及故障对照"),
      card("UART 成功比对帧",finite(tx)&&finite(rx)?number(tx+rx):missing,finite(tx)&&finite(rx)?`TX ${number(tx)} · RX ${number(rx)}；仅上述 PASS` : "需有完整的 TX / RX 计数"),
      card("核心功能 bins · 未加权",metricText(core?.metrics?.functional_bins),percent(core?.metrics?.functional_bins)),
      card("核心 RTL 代码行",metricText(core?.metrics?.rtl_lines),`${percent(core?.metrics?.rtl_lines)} · LCOV 独立口径`)));
    const failures = counts(runs).fail;
    const timeoutWave = waves.find(wave => {
      const run = runsById.get(wave.run_id);
      return run?.suite_id === "apb_protocol" && run.phase === "negative" && run.raw_status === "FAIL";
    });
    const taskLink = (label, detail, action) => el("button", {
      type: "button", className: "debug-entry", onClick: action
    }, el("strong", {}, label), el("span", {}, detail));
    const debugEntries = [
      failures ? taskLink("查看原始 FAIL", `${number(failures)} 条记录 · 按范围筛选并打开日志`,
        () => showRuns({status: "FAIL"})) : null,
      timeoutWave ? taskLink("打开 APB 超时波形", "查看等待、复位中止与恢复事务",
        () => showWave(timeoutWave.id)) : null,
      core ? taskLink("检查覆盖缺口", `${metricText(core.metrics?.functional_bins)} 功能 bins`, () => {
        state.coverageId = core.id;
        setView("coverage", true);
        const gaps = document.getElementById("coverage-gaps");
        gaps?.focus({preventScroll:true});
        gaps?.scrollIntoView({block:"start"});
      }) : null
    ].filter(Boolean);
    if (debugEntries.length) {
      root.append(el("section", {className: "debug-entry-section", "aria-label": "常用调试入口"},
        el("h2", {}, "常用调试入口"), el("div", {className: "debug-entry-grid"}, debugEntries)));
    }
    const separate=suites.filter(suite=>suite.id==="apb_protocol"||suite.id==="fault_control"||["protocol","negative_control","fault_control"].includes(suite.kind));
    if(separate.length) {
      root.append(el("div",{className:"card-grid"},separate.map(suite=>{
        const rows=runs.filter(run=>run.suite_id===suite.id);const c=counts(rows);
        const positive=rows.filter(run=>run.phase==="positive").length;
        const recovery=rows.filter(run=>run.phase==="recovery").length;
        const phaseLine=positive||recovery?`其中正向 ${positive} · 故障后恢复 ${recovery}`:"注入前后的干净对照单独保留";
        return el("section",{className:"panel"},el("h2",{},text(suite.title)),el("p",{className:"secondary"},text(suite.scope||suite.note)),el("div",{className:"scope-counts"},el("div",{className:"scope-count"},"正常运行",el("strong",{},`${c.pass} PASS`)),el("div",{className:"scope-count"},"指定负向控制",el("strong",{},`${c.detected} DETECTED`))),el("p",{className:"inline-note"},`${phaseLine}；原始 FAIL ${c.fail}。`),suite.note?el("p",{className:"inline-note"},suite.note):null,button("查看这组运行",()=>showRuns({suite:suite.id}),{className:"button small"}));
      })));
    }
    const scopeRows=[];
    for(const suite of suites) {
      const variants=[...new Set(runs.filter(run=>run.suite_id===suite.id).map(run=>run.variant))];
      for(const variant of variants) {
        const c=counts(runs.filter(run=>run.suite_id===suite.id&&run.variant===variant));
        scopeRows.push(el("tr",{},el("td",{},button(text(suite.title),()=>showRuns({suite:suite.id,variant:variant??""}),{className:"link-button"}),el("span",{className:"row-secondary"},text(suite.scope))),el("td",{},variantName(variant)),el("td",{},number(c.total)),el("td",{},badge("PASS","pass"),el("span",{className:"row-secondary"},number(c.pass))),el("td",{},badge("FAIL","fail"),el("span",{className:"row-secondary"},number(c.fail))),el("td",{},`${c.detected} DETECTED`,el("span",{className:"row-secondary"},`预期失败 ${c.expected}${c.other?` · 其他状态 ${c.other}`:""}`))));
      }
    }
    root.append(panel("按证据范围核对", "raw FAIL 不会因为属于预期或已检出而改成 PASS。",scopeRows.length?table(["测试范围","版本","运行数","原始 PASS","原始 FAIL","独立分类"],scopeRows):empty("没有范围记录","数据中尚未提供可分组的运行。")));
    const chain=list(project.toolchain);
    const chainLabels=chain.length?chain.map(item=>typeof item==="string"?item:[item?.name,item?.version].filter(Boolean).join(" ")):typeof project.toolchain==="string"?[project.toolchain]:project.toolchain&&typeof project.toolchain==="object"?Object.entries(project.toolchain).map(([key,value])=>`${key} ${text(value)}`):[];
    const provenance=panel("来源与实现边界","输入哈希用于复核记录；不同源码快照与覆盖统计范围分别保留。",
      project.source_note?el("p",{className:"inline-note"},project.source_note):null,
      chainLabels.length?el("div",{className:"toolchain"},chainLabels.map(value=>el("span",{},value))):null,
      list(data.limitations).length?el("ul",{},data.limitations.map(value=>el("li",{},value))):el("p",{className:"muted"},"数据未附加实现边界说明。"));
    const inputs=list(data.inputs),inputsKnown=Array.isArray(data.inputs);
    provenance.append(el("details",{},el("summary",{},inputsKnown?`输入清单 · ${inputs.length} 个文件`:"输入清单 · 未记录"),inputs.length?table(["路径","大小","SHA-256"],inputs.map(input=>el("tr",{},el("td",{},link(text(input.path),input.path)),el("td",{className:"nowrap"},finite(input.bytes)?`${number(input.bytes)} bytes`:missing),el("td",{className:"hash"},text(input.sha256)))),{className:"table-scroll file-list"}):empty("尚无输入清单","未记录文件清单或 SHA-256。")));
    root.append(provenance);
  }

  function distinctOptions(key, labeler=text) {
    const values=[...new Set(runs.map(run=>run[key]))].sort((a,b)=>collator.compare(text(a),text(b)));
    return [{value:"",label:"全部"},...values.map(value=>({value:value===null||value===undefined?"__missing__":String(value),label:labeler(value)}))];
  }
  function filteredRuns() {
    const f=state.reg;
    let selected=runs.filter(run=>{
      if(hasId(f.runId)&&run.id!==f.runId)return false;
      for(const [filter,key] of [["suite","suite_id"],["variant","variant"],["test","test"],["seed","seed"],["status","raw_status"],["phase","phase"]]) {
        if(f[filter]&&String(run[key]??"__missing__")!==f[filter])return false;
      }
      const query=f.query.trim().toLowerCase();
      return !query||[run.test,run.id,run.variant,run.classification,run.raw_status,run.phase,suiteTitle(run.suite_id)].some(value=>String(value??"").toLowerCase().includes(query));
    });
    if(f.sort==="fail_first")selected=selected.slice().sort((a,b)=>(a.raw_status==="FAIL"?0:1)-(b.raw_status==="FAIL"?0:1)||collator.compare(text(a.test),text(b.test))||(a.seed??0)-(b.seed??0));
    if(f.sort==="test")selected=selected.slice().sort((a,b)=>collator.compare(text(a.test),text(b.test))||collator.compare(text(a.variant),text(b.variant))||(a.seed??0)-(b.seed??0));
    return selected;
  }
  function countersFor(run) {
    const m=run.metrics||{};
    if(finite(m.apb_completed)||finite(m.apb_reads)||finite(m.apb_writes)) {
      return el("div",{},`完成 ${number(m.apb_completed)}`,el("span",{className:"row-secondary"},`读 ${number(m.apb_reads)} · 写 ${number(m.apb_writes)}`),finite(m.max_wait)?el("span",{className:"row-secondary"},`最大等待 ${m.max_wait} 周期`):null);
    }
    return el("div",{},`TX ${number(m.tx)}`,el("span",{className:"row-secondary"},`RX ${number(m.rx)}`));
  }
  function renderRegressions() {
    intro("通过范围、版本、测试、seed、原始状态及阶段交叉筛选。故障检出是附加分类，原始 FAIL 始终可见。");
    const resultBox=el("div",{});
    const fields=el("div",{className:"filters"});
    const add=(label,name,options)=>fields.append(makeField(label,makeSelect(options,state.reg[name],value=>{state.reg[name]=value;state.reg.page=1;updateResults();})));
    add("范围","suite",[{value:"",label:"全部"},...suites.map(suite=>({value:String(suite.id),label:text(suite.title)}))]);
    add("版本","variant",distinctOptions("variant",variantName));
    add("测试","test",distinctOptions("test"));
    add("Seed","seed",distinctOptions("seed"));
    add("原始状态","status",distinctOptions("raw_status"));
    add("运行阶段","phase",distinctOptions("phase",phaseName));
    const search=el("input",{type:"search",value:state.reg.query,placeholder:"测试名、记录 ID、分类…",onInput:event=>{state.reg.query=event.target.value;state.reg.page=1;updateResults();}});
    fields.append(makeField("搜索记录",search,{wide:true}));
    fields.append(makeField("排序",makeSelect([{value:"recorded",label:"记录顺序"},{value:"fail_first",label:"原始 FAIL 优先"},{value:"test",label:"测试名称 / seed"}],state.reg.sort,value=>{state.reg.sort=value;state.reg.page=1;updateResults();})));
    const filterPanel=panel("筛选记录",null,fields,
      hasId(state.reg.runId)?el("div",{className:"filter-chip"},"精确定位",el("code",{},String(state.reg.runId)),button("取消单条定位",()=>{state.reg.runId="";state.reg.page=1;setView("regressions");},{className:"link-button"})):null,
      el("div",{className:"toolbar-end"},button("清除筛选",()=>{Object.assign(state.reg,{runId:"",suite:"",variant:"",test:"",seed:"",status:"",phase:"",query:"",page:1,sort:"recorded"});setView("regressions");})));
    root.append(filterPanel,resultBox);
    function updateResults() {
      const rows=filteredRuns(), c=counts(rows), pages=Math.max(1,Math.ceil(rows.length/state.reg.size));
      state.reg.page=Math.min(Math.max(1,state.reg.page),pages);
      const start=(state.reg.page-1)*state.reg.size;
      const toolbar=el("div",{className:"toolbar"},el("span",{className:"count-label",role:"status","aria-live":"polite"},`筛选 ${rows.length} / ${runs.length} 条 · PASS ${c.pass} · 原始 FAIL ${c.fail} · DETECTED ${c.detected}`),el("div",{className:"toolbar-end"},makeField("每页",makeSelect([25,50,100].map(value=>({value:String(value),label:String(value)})),String(state.reg.size),value=>{state.reg.size=Number(value);state.reg.page=1;updateResults();})),button("导出筛选 CSV",()=>downloadCSV("uart-regressions.csv",["run_id","suite","variant","test","seed","phase","raw_status","classification","expected","TX","RX","UVM_ERROR","UVM_FATAL","APB_completed","duration_s","log_url"],rows.map(run=>[run.id,run.suite_id,run.variant,run.test,run.seed,run.phase,run.raw_status,run.classification,run.expected,run.metrics?.tx,run.metrics?.rx,run.metrics?.errors,run.metrics?.fatals,run.metrics?.apb_completed,run.metrics?.duration_s,run.log_url])),{disabled:!rows.length})));
      const resultPanel=el("section",{className:"panel"},toolbar);
      if(!rows.length)resultPanel.append(empty("没有符合条件的记录","调整筛选条件，或清除筛选后重新查看。没有记录不代表测试通过。"));
      else {
        const body=rows.slice(start,start+state.reg.size).map(run=>{
          const associated=hasId(run.id)?waves.find(wave=>hasId(wave.run_id)&&wave.run_id===run.id):null;
          const actions=el("div",{className:"row-actions"},run.log_url?link("日志",run.log_url):null,run.report_url?link("原始报告",run.report_url):null,associated?button("查看波形",()=>showWave(associated.id),{className:"link-button"}):null);
          return el("tr",{},el("td",{},el("code",{},text(run.test)),el("span",{className:"row-secondary"},suiteTitle(run.suite_id))),el("td",{},variantName(run.variant)),el("td",{className:"mono"},text(run.seed)),el("td",{},run.phase?badge(phaseName(run.phase),"phase"):el("span",{className:"secondary"},missing)),el("td",{},resultBadges(run)),el("td",{},countersFor(run)),el("td",{className:"nowrap mono"},`${number(run.metrics?.errors)} / ${number(run.metrics?.fatals)}`,el("span",{className:"row-secondary"},finite(run.metrics?.duration_s)?`${number(run.metrics.duration_s)} s`:"用时未记录")),el("td",{},actions));
        });
        resultPanel.append(table(["测试 / 范围","版本","Seed","阶段","原始状态 / 分类","日志比对或总线计数","ERROR / FATAL","证据"],body));
        resultPanel.append(el("div",{className:"pagination"},el("span",{},`第 ${start+1}–${Math.min(start+state.reg.size,rows.length)} 条，共 ${rows.length} 条`),el("div",{className:"button-group"},button("上一页",()=>{state.reg.page--;updateResults();},{disabled:state.reg.page<=1,className:"button small"}),el("span",{},`${state.reg.page} / ${pages}`),button("下一页",()=>{state.reg.page++;updateResults();},{disabled:state.reg.page>=pages,className:"button small"}))));
      }
      resultPanel.append(el("p",{className:"table-note"},"TX/RX 为日志中的比对计数。成功帧汇总仅包含明确 UART 范围中的原始 PASS；APB completed、读写与等待周期单独呈现。未提供的计数显示“未记录”。"));
      resultBox.replaceChildren(resultPanel);
    }
    updateResults();
  }

  function coverageMetric(label,metric,kind,definition) {
    const m=metricPair(metric);
    return el("article",{className:"coverage-metric"},el("h3",{},label),el("div",{className:"coverage-value"},metricText(metric)),el("p",{className:"secondary"},definition),el("div",{className:"bar-track",role:"img","aria-label":`${label}：${metricText(metric)}，${percent(metric)}`},m?el("div",{className:`bar-fill ${kind||""}`,style:{width:`${100*m.hit/m.total}%`}}):null),el("div",{className:"coverage-percent"},percent(metric)));
  }
  function renderCoverage() {
    intro("功能 bins、RTL 可执行行与 RTL 分支采用独立的分子和分母。仅显示数据中指定的统计范围，不把 RAL 子集、协议对照或故障注入混入核心覆盖率。");
    if(!coverage.length){root.append(empty("没有覆盖率数据","尚未提供可复核的覆盖率记录。"));return;}
    let selected=coverage.find(item=>item.id===state.coverageId)||coverage[0];state.coverageId=selected.id;
    const picker=makeSelect(coverage.map(item=>({value:String(item.id),label:text(item.title)})),String(selected.id),value=>{state.coverageId=value;setView("coverage");},{"aria-label":"选择覆盖报告"});
    root.append(panel("选择报告范围",null,makeField("覆盖报告",picker),el("dl",{className:"detail-list"},el("dt",{},"记录范围"),el("dd",{},text(selected.scope)),el("dt",{},"版本"),el("dd",{},variantName(selected.variant))),selected.note?el("p",{className:"source-note",style:{marginTop:"16px",marginBottom:"0"}},selected.note):null));
    root.append(el("div",{className:"coverage-metrics"},coverageMetric("功能 bins · 未加权",selected.metrics?.functional_bins,"","按原生计数和 at_least 阈值；非加权 covergroup 百分比。"),coverageMetric("RTL 可执行行 · LCOV",selected.metrics?.rtl_lines,"code-line","只统计报告声明的 RTL 源码范围。"),coverageMetric("RTL 分支 · LCOV",selected.metrics?.rtl_branches,"code-branch","分支计数独立于功能 bins 与行覆盖率。")));
    if(list(selected.evidence_urls).length)root.append(panel("覆盖证据",null,evidenceLinks(selected.evidence_urls)));
    const groups=list(selected.groups);
    const groupRows=groups.map(group=>{
      const m=metricPair(group);return el("tr",{},el("td",{},el("code",{},text(group.title||group.id))),el("td",{className:"mono nowrap"},metricText(group)),el("td",{},el("div",{className:"group-progress"},el("div",{className:"bar-track"},m?el("div",{className:"bar-fill",style:{width:`${100*m.hit/m.total}%`}}):null),el("span",{className:"count-label"},percent(group)))));
    });
    root.append(panel("Coverpoint / cross 分组", "分组只合并已记录的 bin 身份，不增加覆盖点或推定不可达项。",groups.length?table(["分组","已命中 / 有效 bins","未加权命中率"],groupRows):empty("没有分组记录","该报告未提供 coverpoint 或 cross 的分组计数。")));
    const gaps=list(selected.gaps), gapResults=el("div",{});
    const search=el("input",{type:"search",placeholder:"分组、bin 或记录的原因…","aria-label":"筛选覆盖缺口"});
    const gapPanel=panel("未命中的有效 bins","未记录原因时保留空缺，不以推断替代工程说明。",makeField("查找缺口",search),el("div",{style:{height:"16px"}}),gapResults);
    gapPanel.id = "coverage-gaps";
    gapPanel.tabIndex = -1;
    function updateGaps(){const q=search.value.trim().toLowerCase();const filtered=gaps.filter(gap=>!q||[gap.group,gap.bin,gap.reason].some(value=>String(value??"").toLowerCase().includes(q)));
      gapResults.replaceChildren(filtered.length?table(["分组 / bin","实际命中 / 阈值","记录的原因","源码"],filtered.map(gap=>el("tr",{},el("td",{},el("span",{className:"secondary"},text(gap.group)),el("br"),el("code",{},text(gap.bin))),el("td",{className:"mono nowrap"},`${number(gap.hits)} / ${number(gap.at_least)}`),el("td",{className:"gap-reason"},gap.reason||missing),el("td",{},gap.source_url?link("源码位置",gap.source_url):el("span",{className:"secondary"},missing))))):empty(gaps.length?"没有匹配的缺口":"数据中未列出缺口",gaps.length?"调整关键词后重试。":"空列表本身不证明完整覆盖；请同时核对上方分子、分母及原生数据库。"));}
    search.addEventListener("input",updateGaps);updateGaps();root.append(gapPanel);
  }

  const preparedWaves=new Map();
  function prepareWave(wave) {
    if(preparedWaves.has(wave.id))return preparedWaves.get(wave.id);
    const signals=list(wave.signals).map(signal=>({...signal,events:list(signal.events).filter(event=>Array.isArray(event)&&finite(event[0])&&typeof event[1]==="string"&&/^[01xz]+$/i.test(event[1])).map(event=>[event[0],event[1].toLowerCase()]).sort((a,b)=>a[0]-b[0])}));
    const prepared={...wave,signals};preparedWaves.set(wave.id,prepared);return prepared;
  }
  function valueIndex(events,t) {let low=0,high=events.length;while(low<high){const middle=(low+high)>>>1;if(events[middle][0]<=t)low=middle+1;else high=middle;}return low-1;}
  function valueAt(signal,t) {const i=valueIndex(signal.events,t);return i<0?null:signal.events[i][1];}
  function formatBits(value,width) {
    if(value===null||value===undefined)return missing;
    if(/[xz]/i.test(value))return /^[xz]+$/i.test(value)?value.toUpperCase():"b"+value.toUpperCase();
    if(width===1)return value;
    try{return "0x"+BigInt("0b"+value).toString(16).toUpperCase().padStart(Math.ceil((width||value.length)/4),"0");}catch(_){return value;}
  }
  function formatBus(value) {return finite(value)?"0x"+Math.trunc(value).toString(16).toUpperCase():text(value);}
  function eventHasWait(event) {return finite(event.wait_cycles)&&event.wait_cycles>0;}
  function eventHasIssue(event) {return event.slverr===true||(finite(event.slverr)&&event.slverr!==0)||(typeof event.status==="string"&&event.status.trim()!==""&&event.status.toUpperCase()!=="OK");}
  function validRange(range) {return Array.isArray(range)&&finite(range[0])&&finite(range[1])&&range[1]>range[0];}
  function defaultWaveSignals(signals) {
    const matches=(signal,name)=>[signal.id,signal.label].some(value=>typeof value==="string"&&(value===name||value.endsWith("."+name)||(name==="apb.rst_n"&&value==="rst_n")));
    const hasUART=signals.some(signal=>["uart.rx","uart.tx","uart.irq"].some(name=>matches(signal,name)));
    const priority=hasUART?["apb.rst_n","uart.rx","uart.tx","uart.irq","apb.psel","apb.penable","apb.pready","apb.pwrite","apb.prdata"]:
      ["apb.rst_n","apb.psel","apb.penable","apb.pready","apb.pwrite","apb.paddr","apb.pwdata","apb.prdata","apb.pslverr"];
    return priority.map(name=>signals.find(signal=>matches(signal,name))).filter(Boolean).slice(0,9);
  }
  function renderWaveforms() {
    intro("由原始 VCD 的真实离散事件绘制，窗口之外不补造状态。拖动平移、缩放并定位游标，随后用 APB 事件和原始文件核对时序。");
    if(!waves.length){root.append(empty("没有波形记录","尚未提供 VCD 采样事件。可从回归日志继续核对运行结果。"));return;}
    const source=waves.find(wave=>String(wave.id)===String(state.waveId))||waves[0];state.waveId=source.id;
    const wave=prepareWave(source);
    if(!validRange(wave.range)){root.append(empty("波形时间范围未记录","需要有效的 range:[start,end] 才能显示真实时间轴。"));return;}
    const domain=wave.range, domainSpan=domain[1]-domain[0], minSpan=Math.max(domainSpan/100000,0.001);
    const defaults = defaultWaveSignals(wave.signals);
    const orderedSignals = defaults.concat(wave.signals.filter(signal => !defaults.includes(signal)));
    let ws=state.waveState.get(wave.id);
    if(!ws){const initial=validRange(wave.default_window)?[Math.max(domain[0],wave.default_window[0]),Math.min(domain[1],wave.default_window[1])]:domain.slice();const window=validRange(initial)?initial:domain.slice();ws={start:window[0],end:window[1],cursor:(window[0]+window[1])/2,selected:new Set(defaults.map(signal=>signal.id)),eventId:null,eventPage:1,eventsInView:true,eventKind:"all",eventQuery:""};state.waveState.set(wave.id,ws);}
    const waveformPanel=el("section",{className:"panel"});
    const picker=makeSelect(waves.map(item=>({value:String(item.id),label:text(item.title)})),String(wave.id),id=>{state.waveId=id;setView("waveforms");},{"aria-label":"选择真实波形"});
    const controls=el("div",{className:"wave-controls"});
    waveformPanel.append(el("div",{className:"wave-select-bar"},makeField("波形记录",picker),controls));
    const related=hasId(wave.run_id)?runsById.get(wave.run_id):null;
    if(related||state.waveReturn)waveformPanel.append(el("div",{className:"wave-run-context"},
      related?el("div",{className:"legend legend-inline"},el("span",{},el("code",{},text(related.test)),` · seed ${text(related.seed)} · ${variantName(related.variant)}`),resultBadges(related),el("span",{},suiteTitle(related.suite_id),related.phase?` · ${phaseName(related.phase)}`:"")):null,
      el("div",{className:"evidence-links"},related?.log_url?link("同次运行日志",related.log_url):null,related?.report_url?link("同次原始报告",related.report_url):null,
        related?button("查看此运行",()=>showRun(related),{className:"button small"}):null,
        state.waveReturn?button("返回筛选结果",()=>{Object.assign(state.reg,state.waveReturn);setView("regressions",true);},{className:"button small"}):null)));
    const signalPanel=el("aside",{className:"signal-panel","aria-label":"信号选择"},el("h3",{},"显示信号"));
    const signalList=el("div",{className:"signal-list"});
    const svg=svgEl("svg",{class:"wave-chart",tabindex:"0",role:"img","aria-label":"可操作的真实波形：左右键移动游标，加减键缩放，Shift 加左右键平移，Home 查看全程"});
    const chartFrame=el("div",{className:"wave-chart-frame"},svg);
    const values=el("div",{className:"cursor-values"});
    const status=el("p",{className:"wave-status",role:"status"});
    const startInput=el("input",{type:"number",step:"any","aria-label":`窗口起点 ${wave.unit||"ns"}`});
    const endInput=el("input",{type:"number",step:"any","aria-label":`窗口终点 ${wave.unit||"ns"}`});
    const cursorInput=el("input",{type:"number",step:"any","aria-label":`时间游标 ${wave.unit||"ns"}`});
    const windowForm=el("form",{className:"wave-window-form",onSubmit:event=>{event.preventDefault();applyWindow();}},makeField(`窗口起点 (${wave.unit||"ns"})`,startInput),makeField(`窗口终点 (${wave.unit||"ns"})`,endInput),button("应用范围",applyWindow,{className:"button small"}),makeField(`游标 (${wave.unit||"ns"})`,cursorInput),button("定位",()=>{const t=inputNumber(cursorInput);if(!finite(t)||t<domain[0]||t>domain[1]){invalid("请输入记录范围内的游标时间。");return;}ws.cursor=t;centerCursor();},{className:"button small"}));
    const waveMain=el("div",{className:"wave-main"},chartFrame,el("p",{className:"wave-help"},"滚轮以指针为中心缩放；拖动背景平移；点击设置游标，拖动红色手柄移动。键盘：左右键移动游标，+ / − 缩放，Shift + 左右键平移，Home 全程。"),windowForm,status,values);
    waveformPanel.append(el("div",{className:"wave-layout"},signalPanel,waveMain));
    if(wave.source)waveformPanel.append(el("div",{className:"provenance"},wave.source.url?link("打开原始 VCD",wave.source.url):el("span",{className:"secondary"},"原始 VCD 链接未记录"),wave.source.sha256?el("p",{className:"hash",style:{marginTop:"8px"}},"SHA-256 ",wave.source.sha256):null,wave.source.note?el("p",{className:"secondary"},wave.source.note):null));
    root.append(waveformPanel);
    const eventResults=el("div",{}),allEvents=list(wave.apb_events),waitEvents=allEvents.filter(eventHasWait),issueEvents=allEvents.filter(eventHasIssue);
    const eventSearch=el("input",{type:"search",value:ws.eventQuery,placeholder:"地址、数据、状态…","aria-label":"筛选 APB 事件"});
    const eventKind=makeSelect([{value:"all",label:`全部记录 (${allEvents.length})`},{value:"wait",label:`有等待 (${waitEvents.length})`},{value:"issue",label:`异常记录 (${issueEvents.length})`}],ws.eventKind,value=>{ws.eventKind=value;ws.eventPage=1;renderEvents();},{"aria-label":"APB 事件类型"});
    const inView=el("input",{type:"checkbox",checked:ws.eventsInView,onChange:event=>{ws.eventsInView=event.target.checked;ws.eventPage=1;renderEvents();}});
    const locatable=event=>finite(event.start)&&event.start>=domain[0]&&event.start<=domain[1];
    root.append(panel("APB 事件", "点击事件时间定位到对应采样窗口。",
      el("div",{className:"toolbar wave-event-tools"},makeField("事件类型",eventKind),makeField("搜索事件",eventSearch),el("label",{className:"check-field"},inView,"仅当前窗口")),
      el("p",{className:"inline-note"},"快捷定位扫描整份波形，并清除事件搜索条件。异常记录包括非 OK 状态或 PSLVERR；复位中止、未完成及未知记录需结合日志判断。"),eventResults));
    eventSearch.addEventListener("input",()=>{ws.eventQuery=eventSearch.value;ws.eventPage=1;renderEvents();});
    signalPanel.append(el("div",{className:"button-group"},button("全选",()=>{ws.selected=new Set(wave.signals.map(signal=>signal.id));refreshSignals();scheduleDraw(true);},{className:"button small"}),button("清空",()=>{ws.selected.clear();refreshSignals();scheduleDraw(true);},{className:"button small"})),signalList);
    function refreshSignals(){signalList.replaceChildren(...orderedSignals.map(signal=>el("label",{className:"signal-check"},el("input",{type:"checkbox",checked:ws.selected.has(signal.id),onChange:event=>{if(event.target.checked)ws.selected.add(signal.id);else ws.selected.delete(signal.id);scheduleDraw(true);}}),el("span",{},text(signal.label||signal.id),finite(signal.width)?el("small",{},`[${signal.width}]`):null))));}
    refreshSignals();
    let frame=null,pendingEvents=false,drag=null;
    function scheduleDraw(events=false){pendingEvents=pendingEvents||events;if(frame!==null)return;frame=requestAnimationFrame(()=>{frame=null;draw();if(pendingEvents){pendingEvents=false;renderEvents();}});}
    function clampWindow(start,end){let span=Math.min(domainSpan,Math.max(minSpan,end-start));let left=Math.max(domain[0],Math.min(domain[1]-span,start));return [left,left+span];}
    function setWindow(start,end){[ws.start,ws.end]=clampWindow(start,end);ws.eventPage=1;scheduleDraw(true);}
    function zoom(factor,anchor=ws.cursor){const ratio=Math.max(0,Math.min(1,(anchor-ws.start)/(ws.end-ws.start)));const span=Math.min(domainSpan,Math.max(minSpan,(ws.end-ws.start)*factor));setWindow(anchor-ratio*span,anchor+(1-ratio)*span);}
    function centerCursor(){const span=ws.end-ws.start;setWindow(ws.cursor-span/2,ws.cursor+span/2);}
    function invalid(message){status.classList.add("invalid");status.textContent=message;}
    function applyWindow(){const start=inputNumber(startInput),end=inputNumber(endInput);if(!finite(start)||!finite(end)||end<=start||start<domain[0]||end>domain[1]){invalid("请填写有效起止时间；终点须大于起点，且窗口应位于记录范围内。");return;}setWindow(start,end);}
    controls.append(button("放大",()=>zoom(.5),{className:"button small"}),button("缩小",()=>zoom(2),{className:"button small"}),button("全程",()=>setWindow(...domain),{className:"button small"}),button("初始窗口",()=>setWindow(...(validRange(wave.default_window)?wave.default_window:domain)),{className:"button small"}),button("居中游标",centerCursor,{className:"button small"}));
    const eventSummary = el("span", {className:"count-label"});
    function updateEventSummary(event) {
      eventSummary.textContent = event ? `${text(event.status)} · ${number(event.wait_cycles)} 等待周期 · ${time(event.start)}–${time(event.end)} ${wave.unit || "ns"}` : "";
    }
    updateEventSummary(ws.eventId === null ? null : allEvents.find(event => event.id === ws.eventId));
    const jumpControls = el("div", {className:"button-group wave-jump-controls", "aria-label":"APB 事件定位"},
      button("下一个等待", () => jumpEvent("wait"), {className:"button small", disabled:!waitEvents.some(locatable)}),
      button("下一个异常", () => jumpEvent("issue"), {className:"button small", disabled:!issueEvents.some(locatable)}),
      eventSummary);
    waveformPanel.insertBefore(jumpControls, waveformPanel.querySelector(".wave-layout"));
    function dimensions(){const width=Math.max(260,chartFrame.clientWidth-2);const left=width<500?108:148;return {width,left,right:14,plot:Math.max(80,width-left-14)};}
    function pointerTime(event){const d=dimensions(),rect=svg.getBoundingClientRect();return ws.start+(Math.max(0,Math.min(d.plot,event.clientX-rect.left-d.left))/d.plot)*(ws.end-ws.start);}
    function draw(){
      const d=dimensions(),selected=orderedSignals.filter(signal=>ws.selected.has(signal.id)),axis=47,row=47,height=axis+Math.max(1,selected.length)*row+19,span=ws.end-ws.start;
      svg.setAttribute("viewBox",`0 0 ${d.width} ${height}`);svg.setAttribute("height",String(height));svg.replaceChildren();
      svg.append(svgEl("rect",{x:0,y:0,width:d.width,height:height,fill:"#fcfeff"}),svgEl("rect",{x:0,y:0,width:d.left,height:height,fill:"#f0f5f8"}));
      const x=t=>d.left+(t-ws.start)/span*d.plot;
      const tickCount=Math.max(2,Math.floor(d.plot/115));
      for(let i=0;i<=tickCount;i++){const t=ws.start+span*i/tickCount,px=x(t);svg.append(svgEl("line",{x1:px,y1:29,x2:px,y2:height-12,stroke:"#dce7ed","stroke-width":1}),svgEl("text",{x:px,y:20,"text-anchor":i===0?"start":i===tickCount?"end":"middle",class:"wave-axis"},time(t)));}
      svg.append(svgEl("text",{x:12,y:20,class:"wave-axis"},wave.unit||"ns"));
      for(const event of list(wave.apb_events)){if(!finite(event.start)||!finite(event.end)||event.end<ws.start||event.start>ws.end)continue;const a=Math.max(ws.start,event.start),b=Math.min(ws.end,event.end);svg.append(svgEl("rect",{x:x(a),y:33,width:Math.max(1,x(b)-x(a)),height:7,class:"event-band"}));}
      if(!selected.length)svg.append(svgEl("text",{x:d.left+12,y:axis+27,class:"wave-axis"},"请选择显示信号"));
      for(let i=0;i<selected.length;i++){
        const signal=selected[i],top=axis+i*row,bottom=top+row;
        const label=String(signal.label||signal.id),display=label.length>(d.width<500?12:18)?label.slice(0,d.width<500?11:17)+"…":label;
        const labelNode=svgEl("text",{x:12,y:top+28,class:"wave-label"},display);labelNode.append(svgEl("title",{},label));svg.append(labelNode,svgEl("line",{x1:0,y1:bottom,x2:d.width,y2:bottom,stroke:"#e2ebf0","stroke-width":1}));
        const events=signal.events,index=valueIndex(events,ws.start);let j=index>=0?index:0;let t=ws.start;let value=index>=0?events[index][1]:null;
        const segments=[];
        if(index<0&&events.length&&events[0][0]>ws.start){segments.push([ws.start,Math.min(ws.end,events[0][0]),null]);t=events[0][0];value=events[0][1];j=0;}
        while(j+1<events.length&&events[j+1][0]<=ws.end){const next=events[j+1][0];if(next>=t)segments.push([Math.max(ws.start,t),next,value]);t=next;value=events[++j][1];}
        if(t<=ws.end)segments.push([Math.max(ws.start,t),ws.end,value]);
        if(!events.length)segments.splice(0,segments.length,[ws.start,ws.end,null]);
        if(signal.width===1){let path="",previousY=null;
          for(const [a,b,v] of segments){if(b<ws.start||a>ws.end)continue;const pa=x(Math.max(a,ws.start)),pb=x(Math.min(b,ws.end));if(v===null||/[xz]/i.test(v)){svg.append(svgEl("line",{x1:pa,y1:top+24,x2:pb,y2:top+24,class:"wave-unknown"}));if(pb-pa>55)svg.append(svgEl("text",{x:(pa+pb)/2,y:top+19,"text-anchor":"middle",class:"wave-axis"},v===null?"未记录":v.toUpperCase()));previousY=null;continue;}const y=v.endsWith("1")?top+11:top+35;path+=(previousY===null?`M${pa},${y}`:`L${pa},${previousY}L${pa},${y}`)+`L${pb},${y}`;previousY=y;}
          if(path)svg.append(svgEl("path",{d:path,class:"wave-trace"}));
        }else{for(const [a,b,v] of segments){if(b<ws.start||a>ws.end)continue;const pa=x(Math.max(a,ws.start)),pb=x(Math.min(b,ws.end)),cut=Math.min(4,Math.max(0,(pb-pa)/4));if(v===null){svg.append(svgEl("line",{x1:pa,y1:top+24,x2:pb,y2:top+24,class:"wave-unknown"}));continue;}svg.append(svgEl("path",{d:`M${pa},${top+24}L${pa+cut},${top+13}L${pb-cut},${top+13}L${pb},${top+24}L${pb-cut},${top+35}L${pa+cut},${top+35}Z`,class:"wave-bus"}));if(pb-pa>48)svg.append(svgEl("text",{x:(pa+pb)/2,y:top+29,"text-anchor":"middle",class:"wave-value"},formatBits(v,signal.width)));}}
      }
      if(ws.cursor>=ws.start&&ws.cursor<=ws.end){const px=x(ws.cursor);svg.append(svgEl("line",{x1:px,y1:29,x2:px,y2:height-11,class:"cursor-line"}),svgEl("path",{d:`M${px-7},24L${px+7},24L${px+7},32L${px},40L${px-7},32Z`,class:"cursor-handle","data-cursor-handle":"true"}),svgEl("rect",{x:px-9,y:22,width:18,height:height-30,fill:"transparent","data-cursor-handle":"true",style:"cursor:ew-resize"}));}
      if(document.activeElement!==startInput)startInput.value=String(Number(ws.start.toFixed(6)));if(document.activeElement!==endInput)endInput.value=String(Number(ws.end.toFixed(6)));if(document.activeElement!==cursorInput)cursorInput.value=String(Number(ws.cursor.toFixed(6)));
      status.classList.remove("invalid");status.textContent=`窗口 ${time(ws.start)}–${time(ws.end)} ${wave.unit||"ns"} · 游标 ${time(ws.cursor)} ${wave.unit||"ns"} · ${selected.length}/${wave.signals.length} 个信号`;
      values.replaceChildren(...selected.map(signal=>el("div",{className:"cursor-value"},el("span",{},text(signal.label||signal.id)),el("code",{},formatBits(valueAt(signal,ws.cursor),signal.width)))));
    }
    function focusEvent(event){if(!finite(event.start))return;ws.eventId=event.id;ws.cursor=finite(event.end)?event.end:event.start;const duration=finite(event.end)?Math.max(0,event.end-event.start):0;const span=Math.max(duration*8,domainSpan/3000,minSpan*8);setWindow(ws.cursor-span*.6,ws.cursor+span*.4);updateEventSummary(event);announce(`定位 APB 事件，游标 ${time(ws.cursor)} ${wave.unit||"ns"}`);}
    function jumpEvent(kind){const candidates=(kind==="wait"?waitEvents:issueEvents).filter(locatable).slice().sort((a,b)=>a.start-b.start);if(!candidates.length)return;let index=candidates.findIndex(event=>event.start>ws.cursor);const wrapped=index<0;if(wrapped)index=0;ws.eventKind=kind;eventKind.value=kind;ws.eventQuery="";eventSearch.value="";ws.eventsInView=true;inView.checked=true;focusEvent(candidates[index]);announce(`${wrapped?"已回到首项；":""}定位${kind==="wait"?"等待事件":"异常记录"} ${index+1}/${candidates.length}，游标 ${time(ws.cursor)} ${wave.unit||"ns"}`);}
    function renderEvents(){const q=eventSearch.value.trim().toLowerCase();const events=list(wave.apb_events).filter(event=>{
      if(ws.eventKind==="wait"&&!eventHasWait(event)||ws.eventKind==="issue"&&!eventHasIssue(event))return false;
      if(ws.eventsInView&&(!finite(event.start)||event.start>ws.end||(finite(event.end)?event.end:event.start)<ws.start))return false;
      return !q||[event.address,event.write_data,event.read_data,event.status,formatBus(event.address),event.id].some(value=>String(value??"").toLowerCase().includes(q));
    });const per=25,pages=Math.max(1,Math.ceil(events.length/per));ws.eventPage=Math.max(1,Math.min(pages,ws.eventPage));const offset=(ws.eventPage-1)*per;
      if(!events.length){eventResults.replaceChildren(empty("当前没有 APB 事件",list(wave.apb_events).length?"尝试选择全部记录、扩大时间窗口、清空关键词或取消“仅当前窗口”。":"该波形没有附加 APB 事件表；仍可检查真实引脚采样。"));return;}
      const rows=events.slice(offset,offset+per).map(event=>el("tr",{"data-event-id":String(event.id),className:event.id===ws.eventId?"is-selected":"",onClick:()=>focusEvent(event)},el("td",{},button(`${time(event.start)}–${time(event.end)}`,()=>focusEvent(event),{className:"link-button"})),el("td",{},event.write===true?"WRITE":event.write===false?"READ":missing),el("td",{className:"mono"},formatBus(event.address)),el("td",{className:"mono"},formatBus(event.write===true?event.write_data:event.write===false?event.read_data:null)),el("td",{className:"mono"},number(event.wait_cycles)),el("td",{},event.slverr===true?"1":event.slverr===false?"0":finite(event.slverr)?String(event.slverr):missing),el("td",{},text(event.status))));
      eventResults.replaceChildren(el("p",{className:"count-label"},`${events.length} 条事件 · 时间单位 ${wave.unit||"ns"}`),table(["时间起止（点击定位）","方向","地址","数据","等待周期","PSLVERR","记录状态"],rows,{className:"table-scroll apb-event-table"}),el("div",{className:"pagination"},el("span",{},`${offset+1}–${Math.min(offset+per,events.length)} / ${events.length}`),el("div",{className:"button-group"},button("上一页",()=>{ws.eventPage--;renderEvents();},{disabled:ws.eventPage<=1,className:"button small"}),el("span",{},`${ws.eventPage} / ${pages}`),button("下一页",()=>{ws.eventPage++;renderEvents();},{disabled:ws.eventPage>=pages,className:"button small"}))));
    }
    svg.addEventListener("wheel",event=>{event.preventDefault();zoom(event.deltaY<0?.7:1/.7,pointerTime(event));},{passive:false});
    svg.addEventListener("pointerdown",event=>{if(event.button!==0)return;const d=dimensions(),rect=svg.getBoundingClientRect();if(event.clientX-rect.left<d.left)return;svg.focus({preventScroll:true});drag={x:event.clientX,start:ws.start,end:ws.end,plot:d.plot,mode:event.target.hasAttribute("data-cursor-handle")?"cursor":"pan",moved:false};svg.setPointerCapture(event.pointerId);svg.classList.add("dragging");});
    svg.addEventListener("pointermove",event=>{if(!drag)return;const delta=event.clientX-drag.x;drag.moved=drag.moved||Math.abs(delta)>3;if(drag.mode==="cursor")ws.cursor=Math.max(domain[0],Math.min(domain[1],pointerTime(event)));else if(drag.moved){const shift=-delta/drag.plot*(drag.end-drag.start);[ws.start,ws.end]=clampWindow(drag.start+shift,drag.end+shift);pendingEvents=true;}scheduleDraw();});
    function endDrag(event){if(!drag)return;if(!drag.moved&&drag.mode!=="cursor")ws.cursor=Math.max(domain[0],Math.min(domain[1],pointerTime(event)));drag=null;svg.classList.remove("dragging");try{svg.releasePointerCapture(event.pointerId);}catch(_){}scheduleDraw(true);}
    svg.addEventListener("pointerup",endDrag);svg.addEventListener("pointercancel",endDrag);
    svg.addEventListener("keydown",event=>{const span=ws.end-ws.start,step=span/100;let handled=true;if(event.key==="ArrowLeft"||event.key==="ArrowRight"){const direction=event.key==="ArrowRight"?1:-1;if(event.shiftKey)setWindow(ws.start+direction*span*.1,ws.end+direction*span*.1);else{ws.cursor=Math.max(domain[0],Math.min(domain[1],ws.cursor+direction*step));if(ws.cursor<ws.start||ws.cursor>ws.end)centerCursor();else scheduleDraw();}}else if(["+","="].includes(event.key))zoom(.5);else if(["-","−"].includes(event.key))zoom(2);else if(event.key==="Home")setWindow(...domain);else handled=false;if(handled){event.preventDefault();announce(`游标 ${time(ws.cursor)} ${wave.unit||"ns"}`);}});
    let observer=null;const onResize=()=>scheduleDraw();if(typeof ResizeObserver!=="undefined"){observer=new ResizeObserver(onResize);observer.observe(chartFrame);}else window.addEventListener("resize",onResize);
    cleanupView=()=>{if(frame!==null)cancelAnimationFrame(frame);if(observer)observer.disconnect();else window.removeEventListener("resize",onResize);};
    draw();renderEvents();
  }

  function renderArchitecture() {
    intro("组件与数据通路由项目记录提供。节点可通过 Tab 聚焦并打开对应源码；图只表达记录的连接关系。");
    const architecture=data.architecture||{},nodes=list(architecture.nodes),edges=list(architecture.edges);
    if(!nodes.length){root.append(empty("没有架构记录","尚未提供组件节点与源码链接。"));return;}
    const validNodes=nodes.filter(node=>finite(node.x)&&finite(node.y));
    if(!validNodes.length){root.append(empty("组件布局未记录","需要节点的 SVG 坐标，避免推断不存在的连接与位置。"));return;}
    const width=Math.max(1000,...validNodes.map(node=>node.x+(finite(node.width)?node.width:180)+25));
    const height=Math.max(500,...validNodes.map(node=>node.y+(finite(node.height)?node.height:82)+30));
    const diagram=svgEl("svg",{class:"architecture-diagram",viewBox:`0 0 ${width} ${height}`,role:"group","aria-label":"验证环境组件图；有源码的节点可聚焦并打开链接"});
    diagram.append(svgEl("title",{},"APB UART 验证组件与记录的数据通路"));
    const defs=svgEl("defs",{},svgEl("marker",{id:"arch-arrow",viewBox:"0 0 10 10",refX:"9",refY:"5",markerWidth:"7",markerHeight:"7",orient:"auto-start-reverse"},svgEl("path",{d:"M0 0L10 5L0 10Z",fill:"#88a2b3"})));diagram.append(defs);
    const lookup=new Map(validNodes.map(node=>[node.id,{...node,width:finite(node.width)?node.width:180,height:finite(node.height)?node.height:82}]));
    for(const edge of edges){const a=lookup.get(edge.from),b=lookup.get(edge.to);if(!a||!b)continue;let start,end;if(Math.abs((b.x+b.width/2)-(a.x+a.width/2))>Math.abs((b.y+b.height/2)-(a.y+a.height/2))){const forward=b.x>=a.x;start=[a.x+(forward?a.width:0),a.y+a.height/2];end=[b.x+(forward?0:b.width),b.y+b.height/2];}else{const down=b.y>=a.y;start=[a.x+a.width/2,a.y+(down?a.height:0)];end=[b.x+b.width/2,b.y+(down?0:b.height)];}const dx=end[0]-start[0],dy=end[1]-start[1],horizontal=Math.abs(dx)>=Math.abs(dy),path=horizontal?`M${start}C${start[0]+dx*.45},${start[1]} ${end[0]-dx*.45},${end[1]} ${end}`:`M${start}C${start[0]},${start[1]+dy*.45} ${end[0]},${end[1]-dy*.45} ${end}`;diagram.append(svgEl("path",{d:path,class:"diagram-edge","marker-end":"url(#arch-arrow)"}));if(edge.label)diagram.append(svgEl("text",{x:(start[0]+end[0])/2,y:(start[1]+end[1])/2-7,"text-anchor":"middle",class:"edge-label"},edge.label));}
    const inspector=el("aside",{className:"architecture-inspector"},el("h3",{},"查看组件"),el("p",{},"聚焦或悬停一个节点可查看描述；有源码链接的节点可点击打开。"));
    function inspect(node){inspector.replaceChildren(el("h3",{},text(node.label)),el("p",{},node.detail||"该节点未附加描述。"),node.source_url?link("打开对应源码",node.source_url):el("p",{className:"secondary"},"源码链接未记录。"));}
    for(const node of lookup.values()){const href=safeHref(node.source_url),group=svgEl(href?"a":"g",{...(href?{href,target:"_blank",rel:"noopener noreferrer"}:{}),tabindex:"0","aria-label":`${text(node.label)}${href?"，打开源码":""}`});group.append(svgEl("rect",{x:node.x,y:node.y,width:node.width,height:node.height,class:"node-box"}),svgEl("text",{x:node.x+14,y:node.y+29,class:"node-label"},text(node.label)));if(node.detail){const label=String(node.detail),limit=Math.floor((node.width-24)/8);group.append(svgEl("text",{x:node.x+14,y:node.y+53,class:"node-detail"},label.length>limit?label.slice(0,Math.max(3,limit-1))+"…":label));}group.append(svgEl("title",{},[node.label,node.detail].filter(Boolean).join(" · ")));group.addEventListener("focus",()=>inspect(node));group.addEventListener("mouseenter",()=>inspect(node));diagram.append(group);}
    root.append(panel("验证通路与源码", "组件名、关系及源码 URL 均来自当前数据快照。",el("div",{className:"architecture-layout"},el("div",{className:"architecture-scroll"},diagram),inspector)));
  }

  function renderDefects() {
    intro("把未修改上游行为、局部修复和对应严格需求放在一起核对。受控故障用于检查器敏感性，不增加真实 DUT 缺陷的数量。");
    const defects=list(data.defects);
    if(!defects.length){root.append(empty("没有缺陷对照记录","数据中尚未提供可核对的原版 / 修复版条目。"));return;}
    for(const defect of defects){
      const testNames=list(defect.test_ids),declaredSuites=[...new Set(list(defect.suite_ids).filter(hasId))];
      const scopeSuites=declaredSuites.length?declaredSuites:["uart_core"];
      const related=runs.filter(run=>scopeSuites.includes(run.suite_id)&&testNames.includes(run.test));
      const card=el("article",{className:"panel defect-card"},el("div",{className:"panel-heading"},el("div",{},el("h2",{},text(defect.title)),defect.summary?el("p",{},defect.summary):null),defect.id?el("code",{className:"meta-chip"},defect.id):null),el("div",{className:"defect-grid"},el("section",{className:"defect-side upstream"},el("h3",{},"未修改上游"),el("p",{},defect.upstream?.description||missing),defect.upstream?.source_url?link("上游源码依据",defect.upstream.source_url):null),el("section",{className:"defect-side fixed"},el("h3",{},"本地修复"),el("p",{},defect.fixed?.description||missing),defect.fixed?.source_url?link("修复源码",defect.fixed.source_url):null)));
      if(testNames.length)card.append(el("div",{className:"test-links"},testNames.flatMap(test=>scopeSuites.map(suite=>button(scopeSuites.length>1?`${suiteTitle(suite)} / ${test}`:`查看 ${test}`,()=>showRuns({test,suite}),{className:"button small"})))));
      const variants=[...new Set(related.map(run=>run.variant))];
      if(related.length)card.append(el("div",{className:"defect-counts"},variants.map(variant=>{const c=counts(related.filter(run=>run.variant===variant));return `${variantName(variant)}：原始 PASS ${c.pass} / FAIL ${c.fail}`;}).join("；")));
      if(list(defect.evidence_urls).length)card.append(evidenceLinks(defect.evidence_urls));root.append(card);
    }
  }

  const project=data.project||{};
  const meta=document.getElementById("project-meta");
  if(project.version)meta.append(el("span",{className:"meta-chip"},text(project.version)));
  if(project.commit)meta.append(el("span",{className:"meta-chip mono",title:String(project.commit)},String(project.commit).slice(0,12)));
  if(project.source_url)meta.append(link("源码",project.source_url,{className:"meta-chip"}));
  document.getElementById("generated-at").textContent=project.generated_utc?`数据生成 UTC：${String(project.generated_utc).replace("T"," ").replace(/Z$/,"")}`:"数据生成时间未记录";
  nav.addEventListener("click",event=>{const target=event.target.closest("button[data-tab]");if(target)setView(target.dataset.tab,true);});
  nav.addEventListener("keydown",event=>{const buttons=[...nav.querySelectorAll("button[data-tab]")],index=buttons.indexOf(document.activeElement);if(index<0)return;let next=null;if(["ArrowDown","ArrowRight"].includes(event.key))next=(index+1)%buttons.length;if(["ArrowUp","ArrowLeft"].includes(event.key))next=(index-1+buttons.length)%buttons.length;if(event.key==="Home")next=0;if(event.key==="End")next=buttons.length-1;if(next!==null){event.preventDefault();buttons[next].focus();}});
  window.addEventListener("hashchange",()=>{const requested=location.hash.slice(1);if(VIEWS[requested]&&requested!==state.tab)setView(requested);});
  setView(VIEWS[location.hash.slice(1)]?location.hash.slice(1):"overview");
})();
