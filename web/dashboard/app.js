/* APB UART verification workbench. Buildless, offline, no fetch or external code. */
(() => {
  "use strict";

  const root = document.getElementById("workspace");
  const title = document.getElementById("page-title");
  const nav = document.getElementById("workspace-nav");
  const raw = window.UART_DASHBOARD;
  const SVG = "http://www.w3.org/2000/svg";
  const VIEWS = {overview:"验证总览",plan:"验证计划",regressions:"回归记录",frontend:"实现与 DFT",coverage:"覆盖与缺口",waveforms:"波形与总线",architecture:"验证架构",defects:"缺陷对照"};
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
  function resultBadges(run, open) {
    const raw = open ? button(text(run.raw_status), open, {className:"badge badge--fail plan-status-button",
      "aria-label":`查看 ${text(run.test)} · seed ${text(run.seed)} 的失败证据`}) : badge(run.raw_status);
    return el("div",{className:"stack vertical"},raw,
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
  const frontendChecks=list(data.frontend_checks).filter(check=>check&&hasId(check.id));
  const frontendComparison=data.frontend_comparison&&typeof data.frontend_comparison==="object"?data.frontend_comparison:null;
  const frontendStages=list(frontendComparison?.stages).filter(stage=>stage&&hasId(stage.id));
  const planGroups=list(data.verification_plan?.groups).filter(group=>group&&hasId(group.id)&&list(group.items).length);
  const planByRun = new Map();
  for (const group of planGroups) for (const item of list(group.items)) for (const id of list(item?.run_ids)) {
    if (!planByRun.has(id)) planByRun.set(id,{groupId:group.id,itemId:item.id});
  }
  const suitesById=new Map(suites.map(suite=>[suite.id,suite]));
  const runsById=new Map(runs.filter(run=>hasId(run.id)).map(run=>[run.id,run]));
  const suiteTitle = id => text(suitesById.get(id)?.title || id);
  const state={tab:"overview",caseIndex:1,plan:{groupId:"",itemId:"",runId:"",failures:false},
    reg:{runId:"",suite:"",variant:"",test:"",seed:"",status:"",phase:"",query:"",page:1,size:25,sort:"recorded"},
    coverageId:coverage[0]?.id,coverageMode:"source",coverageFile:"",waveId:waves[0]?.id,waveState:new Map(),waveReturn:null,
    timingPathsOpen:new Set()};
  let cleanupView=()=>{};

  function isReproductionWave(wave) {
    return !!wave?.reproduction || hasId(wave?.reproduction_of);
  }
  function reproductionInfo(wave) {
    const record=wave?.reproduction;
    return record?.kind==="new_execution" && hasId(record.original_run_id) &&
      wave.reproduction_of===record.original_run_id && hasId(wave.id) &&
      wave.id===wave.run_id && wave.id!==record.original_run_id &&
      (!hasId(record.reproduction_id)||record.reproduction_id===wave.id) ? record : null;
  }
  function originalWaveFor(run, predicate=()=>true) {
    return hasId(run?.id) ? waves.find(wave=>!isReproductionWave(wave)&&wave.run_id===run.id&&predicate(wave)) : null;
  }
  function reproductionWaveFor(run) {
    return run?.raw_status==="FAIL" ? waves.find(wave=>reproductionInfo(wave)?.original_run_id===run.id) : null;
  }
  function reproductionEvidence(run) {
    const wave=reproductionWaveFor(run);
    if(!wave)return null;
    const record=reproductionInfo(wave);
    return el("div", {className:"trace-reproduction-evidence", "aria-label":"独立 TRACE 复现证据",
      "data-original-run-id":String(run.id), "data-reproduction-id":String(wave.id)},
      el("strong", {className:"trace-reproduction-label"}, "TRACE 复现"),
      el("span", {className:"secondary"}, "独立执行"),
      button("查看复现波形",()=>showWave(wave.id),{className:"link-button"}),
      record.log_url?link("复现日志",record.log_url,{target:"_blank",rel:"noopener"}):null);
  }

  function counts(rows) {
    return {total:rows.length,pass:rows.filter(run=>run.raw_status==="PASS").length,fail:rows.filter(run=>run.raw_status==="FAIL").length,
      detected:rows.filter(run=>run.raw_status==="FAIL"&&run.classification==="DETECTED").length,
      expected:rows.filter(run=>run.raw_status==="FAIL"&&run.expected===true&&run.classification!=="DETECTED").length,
      other:rows.filter(run=>!["PASS","FAIL"].includes(run.raw_status)).length};
  }

  function setView(name, focus=false) {
    if (!VIEWS[name]) name="overview";
    if (name === "plan" && !planGroups.length) name="regressions";
    if (name !== "waveforms") state.waveReturn = null;
    cleanupView();cleanupView=()=>{};state.tab=name;
    title.textContent=VIEWS[name];
    document.title=`${VIEWS[name]} · ${text(data.project?.title || "APB UART")}`;
    nav.querySelectorAll("button[data-tab]").forEach(node=>{
      if(node.dataset.tab===name||(node.dataset.tab==="plan"&&["regressions","frontend"].includes(name)))node.setAttribute("aria-current","page");else node.removeAttribute("aria-current");
    });
    try { if(location.hash!=="#"+name)history.replaceState(null,"","#"+name); } catch (_) { if(location.hash!=="#"+name)location.hash=name; }
    root.replaceChildren();
    ({overview:renderOverview,plan:renderVerificationPlan,regressions:renderRegressions,frontend:renderFrontend,coverage:renderCoverage,waveforms:renderWaveforms,architecture:renderArchitecture,defects:renderDefects})[name]();
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
  function showWave(id, eventId = null) {
    state.waveReturn = {view:state.tab, filters:state.tab === "regressions" ? {...state.reg} : null};
    state.waveId = id;
    state.waveFocusEventId = eventId;
    setView("waveforms", true);
  }
  function intro(message) { root.append(el("div",{className:"view-intro"},el("p",{},message))); }
  function evidenceLinks(items) { return el("div",{className:"evidence-links"},list(items).map(item=>link(text(item.label),item.url))); }

  function uartAssociationCase() {
    const test = "uart_error_association_test";
    const stimulus = [
      {payload:0x10, expectedFlags:0x00},
      {payload:0x96, expectedFlags:0x04},
      {payload:0x20, expectedFlags:0x00},
    ];
    const readValue = event => {
      const value = event?.read_data;
      return typeof value === "string" && /^0x[0-9a-f]{1,8}$/i.test(value) ? Number(value) : null;
    };
    const isRead = (event, register) => event?.write === false && event?.register === register &&
      event?.status === "OK" && finite(event.end) && readValue(event) !== null;
    function extract(run) {
      if (!run) return null;
      const trace = originalWaveFor(run, wave=>wave.unit==="ns");
      const events = list(trace?.apb_events);
      // Match the complete LSR/RBR sequence from the strict requirement test.
      for (let start = 0; start + 6 <= events.length; start++) {
        const reads = stimulus.map(({payload, expectedFlags}, index) => {
          const lsr = events[start + index * 2];
          const rbr = events[start + index * 2 + 1];
          if (!isRead(lsr, "LSR") || !isRead(rbr, "RBR") || readValue(rbr) !== payload || lsr.end >= rbr.end) return null;
          const value = readValue(lsr);
          return {payload, expectedFlags, lsr:value, parityError:(value & 4) !== 0, event:lsr};
        });
        if (reads.every(Boolean)) return {run, trace, reads};
      }
      return null;
    }
    const candidates = runs.filter(run => run.suite_id === "uart_core" && run.test === test);
    for (const fixedRun of candidates.filter(run => run.variant === "fixed" && run.raw_status === "PASS")) {
      const upstream = extract(candidates.find(run => run.variant === "upstream" && run.seed === fixedRun.seed &&
        run.raw_status === "FAIL" && run.expected === true));
      const fixed = extract(fixedRun);
      if (upstream && fixed && upstream.reads.every(read => !read.parityError) &&
          fixed.reads.every(read => (read.lsr & 0x0c) === read.expectedFlags)) return {upstream, fixed};
    }
    return null;
  }

  const caseHex = value => `0x${value.toString(16).toUpperCase().padStart(2, "0")}`;

  function caseSignalSegments(trace, id, start, end) {
    const signal = prepareWave(trace).signals.find(item => item.id === id);
    if (!signal) return [];
    const changes = [[start, valueAt(signal, start)]];
    for (let index = valueIndex(signal.events, start) + 1; index < signal.events.length; index++) {
      const [timestamp, value] = signal.events[index];
      if (timestamp >= end) break;
      if (changes.at(-1)[0] === timestamp) changes.at(-1)[1] = value;
      else if (changes.at(-1)[1] !== value) changes.push([timestamp, value]);
    }
    return changes.map(([from, value], index) => ({from, to:changes[index + 1]?.[0] ?? end, value}));
  }

  function renderCaseTrace(upstream, fixed, original, repaired) {
    const {start:setup, end:sample} = repaired.event;
    const start = sample - 20, end = sample + 20;
    const unavailable = () => el("p", {className:"case-context"}, "此对读取缺少可对齐的波形窗口，仍可查看各自的归档证据。");
    if (!finite(setup) || setup < start || setup >= sample ||
        original.event.start !== setup || original.event.end !== sample ||
        [upstream, fixed].some(record => !validRange(record.trace.range) ||
          start < record.trace.range[0] || end > record.trace.range[1])) return unavailable();
    const signals = [upstream, fixed].map(record => ({
      enable:caseSignalSegments(record.trace, "apb.penable", start, end),
      data:caseSignalSegments(record.trace, "apb.prdata", start, end),
    }));
    const [orig, fix] = signals;
    const segmentAtSample = segments => segments.find(({from, to}) => from <= sample && sample < to);
    const sampled = signals.map(signal => segmentAtSample(signal.data));
    // Display the measured bus at the marker only when it agrees with the
    // decoded handshake. Same-timestamp signal changes can otherwise disagree.
    if (orig.enable.length === 0 || orig.enable.some(segment => !/^[01]$/.test(segment.value)) ||
        JSON.stringify(orig.enable) !== JSON.stringify(fix.enable) ||
        segmentAtSample(orig.enable)?.value !== "1" ||
        sampled.some((segment,index) => !segment?.value || !/^[01]+$/.test(segment.value) ||
          Number.parseInt(segment.value, 2) !== [original, repaired][index].lsr)) return unavailable();

    const x = timestamp => 1000 * (timestamp - start) / (end - start);
    const position = timestamp => `${x(timestamp) / 10}%`;
    const trace = el("div", {className:"case-trace", role:"img",
      "aria-label":`${time(start)}–${time(end)} ns，共用 PENABLE。LSR 在 ${time(sample)} ns 采样，原版 ${caseHex(original.lsr)}，修复版 ${caseHex(repaired.lsr)}。`});
    trace.style.setProperty("--sample", position(sample));
    trace.style.setProperty("--access-start", position(setup));
    trace.style.setProperty("--access-width", `${(x(sample) - x(setup)) / 10}%`);
    const row = (name, signal, content, tone = "") => el("div", {className:"case-trace-row"},
      el("span", {className:"case-trace-label"}, el("strong", {}, name), el("small", {}, signal)),
      el("div", {className:`case-trace-lane ${tone}`}, content));
    const waveform = (className, children) => svgEl("svg", {
      class:className, viewBox:"0 0 1000 40", preserveAspectRatio:"none", "aria-hidden":"true", focusable:"false"
    }, children);
    const path = (d, props={}) => svgEl("path", {d, "vector-effect":"non-scaling-stroke", ...props});
    const levels = orig.enable.map((segment, index) => {
      const y = segment.value === "1" ? 11 : 29;
      return `${index ? "V" : `M${x(segment.from)} `}${y}H${x(segment.to)}`;
    }).join("");
    const axis = el("div", {className:"case-trace-row case-trace-row--axis"},
      el("span", {className:"case-trace-label"}, "相对采样 · ns"),
      el("div", {className:"case-trace-lane"}, [-20, -10, 0, 10, 20].map((delta, index) => {
        const tick = el("span", {className:`case-trace-axis-label${index === 0 ? " is-first" : index === 4 ? " is-last" : ""}`},
          delta === 0 ? "0" : delta > 0 ? `+${delta}` : `−${-delta}`);
        tick.style.setProperty("--position", position(sample + delta));
        return tick;
      })));
    trace.append(axis, row("PENABLE", "两版共用", waveform("case-trace-digital", path(levels))));
    for (const [index, name, tone, read] of [[0,"原版","is-upstream",original],[1,"修复版","is-fixed",repaired]]) {
      const bus = signals[index].data.map(segment => {
        const from = x(segment.from), to = x(segment.to);
        const bevel = Math.min(12, (to - from) / 2);
        return path(`M${from} 20L${from + bevel} 9H${to - bevel}L${to} 20L${to - bevel} 31H${from + bevel}Z`,
          {class:segment === sampled[index] ? "is-sampled" : null});
      });
      const value = el("code", {className:`case-trace-value is-sampled ${tone}`}, caseHex(read.lsr));
      value.style.setProperty("--position", position(sample + 1));
      trace.append(row(name, "PRDATA", [waveform("case-trace-bus", bus), value], tone));
    }
    return trace;
  }

  function renderAssociationCase() {
    const comparison = uartAssociationCase();
    if (!comparison) return null;
    const {upstream, fixed} = comparison;
    const context = el("span", {className:"case-context"});
    const traceHost = el("div");
    const summary = el("div", {className:"case-sample-summary"});
    const choices = fixed.reads.map((read, index) =>
      button(caseHex(read.payload), () => select(index, true), {className:"case-payload",
        "aria-label":`队首字节 ${caseHex(read.payload)}`, "aria-pressed":"false"}));
    function select(index, notify=false) {
      state.caseIndex = index;
      choices.forEach((choice,i) => choice.setAttribute("aria-pressed", String(i === index)));
      const original = upstream.reads[index], repaired = fixed.reads[index];
      const times = original.event.end === repaired.event.end ? time(repaired.event.end) :
        `${time(original.event.end)} / ${time(repaired.event.end)}`;
      const expectedPE = Number((repaired.expectedFlags & 4) !== 0);
      context.textContent = `期望 PE=${expectedPE} · seed ${text(fixed.run.seed)} · 采样 ${times} ns`;
      traceHost.replaceChildren(renderCaseTrace(upstream, fixed, original, repaired));
      summary.replaceChildren(...[[upstream,original,"原版","is-upstream"],[fixed,repaired,"修复版","is-fixed"]].map(
        ([record, read, label, tone]) => el("div", {className:`case-run-summary ${tone}`},
          el("div", {className:"case-run-result"}, el("strong", {}, label),
            el("code", {}, `LSR ${caseHex(read.lsr)}`),
            el("code", {className:Number(read.parityError) !== expectedPE ? "is-mismatch" : read.parityError ? "is-set" : null},
              `PE=${Number(read.parityError)}`)),
          button("完整波形", () => showWave(record.trace.id, read.event.id), {
            className:"link-button", "aria-label":`查看${label}完整波形`
          }))));
      if (notify) announce(`队首字节 ${caseHex(repaired.payload)}；${context.textContent}；原版 PE=${Number(original.parityError)}，修复版 PE=${Number(repaired.parityError)}。`);
    }
    select(state.caseIndex);
    return el("section", {className:"association-case", "aria-labelledby":"case-title"},
      el("header", {className:"case-intro"}, el("h2", {id:"case-title"}, "RX FIFO 校验错误关联"),
        el("p", {}, "依次读取 LSR 和 RBR，验证校验错误位是否跟随当前队首字节。")),
      el("figure", {className:"case-figure"},
        el("div", {className:"case-toolbar"},
          el("fieldset", {className:"case-payload-picker"}, el("legend", {className:"sr-only"}, "FIFO 队首字节"), choices),
          context),
        traceHost, summary),
      renderAssociationEvidence(upstream, fixed));
  }

  function renderAssociationEvidence(upstream, fixed) {
    const {source_url:repo, commit} = data.project || {};
    const pinned = /^https:\/\/github\.com\/[\w.-]+\/[\w.-]+$/.test(repo || "") && /^[a-f0-9]{40}$/i.test(commit || "");
    const source = (label, path, line) => pinned ? link(label,
      `${repo}/blob/${commit}/${path}${commit === "127f21e0d695cd0e6aa32b46541b158196058679" ? "#L" + line : ""}`) : null;
    const links = (...items) => el("div", {className:"evidence-links"}, items);
    const sameTest = runs.filter(run => run.suite_id === upstream.run.suite_id && run.test === upstream.run.test);
    const passRatio = variant => {
      const result = counts(sameTest.filter(run => run.variant === variant));
      return `${result.pass}/${result.total}`;
    };
    const openComparison = () => {
      state.defectRunId = upstream.run.id;
      setView("defects", true);
    };
    return el("div", {className:"case-evidence"},
      el("div", {className:"case-evidence-actions"},
        button("查看此用例回归", openComparison, {className:"link-button"}),
        el("span", {className:"case-context"}, `PASS · 原版 ${passRatio("upstream")} · 修复版 ${passRatio("fixed")}`)),
      el("details", {className:"case-traceability"},
        el("summary", {}, "需求、检查与修复"),
        el("dl", {className:"case-proof"},
          el("dt", {}, "验证需求"),
          el("dd", {}, "错误标记随 RX FIFO 队首更新。对正常、坏校验、正常三个字节，期望 PE 依次为 0、1、0。",
            links(source("定向测试", "tb/test/uart_extended_tests.sv", 116))),
          el("dt", {}, "检查与定位"),
          el("dd", {}, el("code", {}, "expect_bits"), " 用掩码 ", el("code", {}, "0x0C"),
            " 检查 LSR[3:2]。Scoreboard 独立比对 RBR 数据，这里由状态检查报告 ", el("code", {}, "[STATUS]"), "。",
            links(source("状态检查", "tb/test/base_test.sv", 33),
              source("RBR 数据比对", "tb/scoreboard/apb_uart_scoreboard.sv", 148),
              link("原版日志", upstream.run.log_url))),
          el("dt", {}, "修复与复测"),
          el("dd", {}, "原版在校验检查前提交字节，顶层固定清除错误。修复版在帧检查完成后随字节保存 PE、FE，由当前有效队首生成 LSR。",
            links(source("原版 RX 提交", "rtl/uart_rx.sv", 132), source("LSR 修复", "rtl_fixed/apb_uart.sv", 209),
              link("修复版日志", fixed.run.log_url))))));
  }

  function renderOverview() {
    const project=data.project||{};
    const headline=data.headline||{};
    const headlineIds=list(headline.suite_ids);
    const headlineRuns=runs.filter(run=>headlineIds.includes(run.suite_id)&&run.variant===headline.variant);
    const h=counts(headlineRuns);
    const passing=headlineRuns.filter(run=>run.raw_status==="PASS");
    const tx=sumComplete(passing,"tx"),rx=sumComplete(passing,"rx");
    const core=coverage.find(item=>item.suite_id===headlineIds[0]&&item.variant===headline.variant);
    const associationCase = renderAssociationCase();
    if (associationCase) root.append(associationCase);
    const metric = (value, label) => el("li", {}, el("strong", {}, value), el("span", {}, label));
    root.append(el("ul", {className:"overview-metrics", "aria-label":"UART 验证结果"},
      metric(headlineRuns.length ? `${h.pass} / ${h.total}` : missing, "修复版 UART 核心 + RAL 通过"),
      metric(finite(tx) && finite(rx) ? number(tx + rx) : missing, "成功比对帧"),
      metric(percent(core?.metrics?.functional_bins), "核心功能覆盖")));
    const failures = counts(runs).fail;
    const timeoutWave = waves.find(wave => {
      if(isReproductionWave(wave))return false;
      const run = runsById.get(wave.run_id);
      return run?.suite_id === "apb_protocol" && run.phase === "negative" && run.raw_status === "FAIL";
    });
    const debugEntries = [
      failures ? button(`原始 FAIL · ${number(failures)} 次`, () => showRuns({status: "FAIL"}), {className:"link-button"}) : null,
      timeoutWave ? button("APB 超时波形", () => showWave(timeoutWave.id), {className:"link-button"}) : null,
      core ? button("覆盖缺口", () => {
        state.coverageId = core.id;
        state.coverageMode = "functional";
        setView("coverage", true);
        const gaps = document.getElementById("coverage-gaps");
        gaps?.focus({preventScroll:true});
        gaps?.scrollIntoView({block:"start"});
      }, {className:"link-button"}) : null
    ].filter(Boolean);
    if (debugEntries.length) {
      root.append(el("nav", {className:"overview-actions", "aria-label":"调试入口"}, debugEntries));
    }
    const scopeRows=[];
    for(const suite of suites) {
      const variants=[...new Set(runs.filter(run=>run.suite_id===suite.id).map(run=>run.variant))];
      for(const variant of variants) {
        const c=counts(runs.filter(run=>run.suite_id===suite.id&&run.variant===variant));
        scopeRows.push(el("tr",{},el("td",{},button(text(suite.title),()=>showRuns({suite:suite.id,variant:variant??""}),{className:"link-button"}),el("span",{className:"row-secondary"},text(suite.scope))),el("td",{},variantName(variant)),el("td",{},number(c.total)),el("td",{},badge("PASS","pass"),el("span",{className:"row-secondary"},number(c.pass))),el("td",{},badge("FAIL","fail"),el("span",{className:"row-secondary"},number(c.fail))),el("td",{},`${c.detected} DETECTED`,el("span",{className:"row-secondary"},`预期失败 ${c.expected}${c.other?` · 其他状态 ${c.other}`:""}`))));
      }
    }
    const chain=list(project.toolchain);
    const chainLabels=chain.length?chain.map(item=>typeof item==="string"?item:[item?.name,item?.version].filter(Boolean).join(" ")):typeof project.toolchain==="string"?[project.toolchain]:project.toolchain&&typeof project.toolchain==="object"?Object.entries(project.toolchain).map(([key,value])=>`${key} ${text(value)}`):[];
    const provenance=panel("来源与实现边界",null,
      project.source_note?el("p",{className:"inline-note"},project.source_note):null,
      project.commit?el("p",{className:"hash"},`${suites.some(suite=>suite.id==="subsystem")?"UART 实测提交":"实测提交"} ${project.commit}`):null,
      chainLabels.length?el("div",{className:"toolchain"},chainLabels.map(value=>el("span",{},value))):null,
      list(data.limitations).length?el("ul",{},data.limitations.map(value=>el("li",{},value))):el("p",{className:"muted"},"数据未附加实现边界说明。"));
    const inputs=list(data.inputs),inputsKnown=Array.isArray(data.inputs);
    provenance.append(el("details",{},el("summary",{},inputsKnown?`输入清单 · ${inputs.length} 个文件`:"输入清单 · 未记录"),inputs.length?table(["路径","大小","SHA-256"],inputs.map(input=>el("tr",{},el("td",{},link(text(input.path),input.path)),el("td",{className:"nowrap"},finite(input.bytes)?`${number(input.bytes)} bytes`:missing),el("td",{className:"hash"},text(input.sha256)))),{className:"table-scroll file-list"}):empty("尚无输入清单","未记录文件清单或 SHA-256。")));
    root.append(el("details", {className:"overview-details"},
      el("summary", {}, "全部验证结果与证据来源"),
      panel("验证范围与结果", "DETECTED 记录负向检查结果。", scopeRows.length ?
        table(["测试范围","版本","运行数","原始 PASS","原始 FAIL","独立分类"], scopeRows) :
        empty("没有范围记录", "数据中尚未提供可分组的运行。")), provenance));
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

  function planNavigation() {
    const views=[["plan","验证计划"],["regressions","全部运行"]];
    if(frontendChecks.length||frontendStages.length)views.push(["frontend","实现与 DFT"]);
    return el("div", {className:"coverage-modes", role:"group", "aria-label":"计划与回归视图"},
      views.map(([view,label]) =>
        button(label, () => setView(view, true), {className:"coverage-mode", "aria-pressed":String(state.tab===view)})));
  }

  function frontendStatus(check) {
    return badge(check.status,check.status==="TIMING_VIOLATION"?"timing":undefined);
  }
  function frontendWaveContext(id) {
    for(const stage of frontendStages)for(const side of ["before","after"]){
      const check=stage[side];
      if(hasId(check?.waveform_id)&&check.waveform_id===id)return {...check,
        title:text(stage.title||stage.id),variant:side==="before"?"基线":"Hold 调整后",summary:frontendComparison.summary};
    }
    return frontendChecks.find(check=>check.waveform_id===id)||null;
  }
  function frontendArtifacts(check) {
    const waveform=hasId(check?.waveform_id)?waves.find(wave=>wave.id===check.waveform_id):null;
    return el("div",{className:"frontend-check-artifacts"},
      list(check?.artifacts).map(item=>item?link(text(item.label),item.url):null),
      waveform?button(waveform.kind==="scan"?"查看扫描波形":"查看同次波形",()=>showWave(waveform.id),
        {className:"link-button","data-waveform-id":String(waveform.id)}):null);
  }
  function renderHoldTiming(paths) {
    const valid=list(paths).filter(path=>path&&hasId(path.id)&&finite(path.arrival_ns)&&finite(path.required_ns)&&finite(path.slack_ns));
    if(!valid.length)return null;
    const formatter=new Intl.NumberFormat("zh-CN",{maximumFractionDigits:6});
    const ps=(ns,signed=false)=>finite(ns)?`${signed&&ns>0?"+":""}${formatter.format(ns*1000)} ps`:missing;
    const values=valid.flatMap(path=>[path.arrival_ns,path.required_ns,...list(path.points).map(point=>point?.time_ns).filter(finite)]);
    const low=Math.min(0,...values),high=Math.max(...values);
    const span=high-low||0.01,maximum=Math.ceil((high+span*.06)*100)/100;
    const position=ns=>`${100*(ns-low)/(maximum-low)}%`;
    const rows=valid.map(path=>{
      const tone=path.status==="VIOLATED"?"is-violated":path.status==="MET"?"is-met":"";
      const points=list(path.points).filter(point=>point&&typeof point==="object");
      const details=el("details",{className:`hold-path ${tone}`,"data-path-id":String(path.id),open:state.timingPathsOpen.has(path.id),
        onToggle:event=>{if(event.currentTarget.open)state.timingPathsOpen.add(path.id);else state.timingPathsOpen.delete(path.id);}},
        el("summary",{className:"hold-path-summary"},
          el("span",{className:"hold-path-heading"},el("strong",{},text(path.title||path.id)),
            el("span",{className:"hold-path-endpoints"},"发射 ",el("code",{},text(path.startpoint))," → 捕获 ",el("code",{},text(path.endpoint)))),
          el("span",{className:"hold-path-plot","aria-hidden":"true",style:`--arrival:${position(path.arrival_ns)};--required:${position(path.required_ns)}`},
            el("i",{className:"hold-arrival-bar"}),el("i",{className:"hold-required"}),el("i",{className:"hold-arrival"})),
          el("span",{className:"hold-path-values"},
            el("span",{},el("small",{},"数据到达"),el("code",{},ps(path.arrival_ns))),
            el("span",{},el("small",{},"最早允许"),el("code",{},ps(path.required_ns))),
            el("span",{className:"hold-path-slack"},el("small",{},"报告 slack"),el("strong",{},ps(path.slack_ns,true)),el("small",{},text(path.status)))),
          el("span",{className:"hold-path-expand","aria-hidden":"true"},"逐级")),
        el("div",{className:"hold-path-detail"},
          points.length?table(["Pin","单元","转换","增量 / ps","累计 / ps"],points.map(point=>el("tr",{className:point.cell==="BUF_X1"?"hold-pin-buffer":null},
            el("th",{scope:"row"},el("code",{},text(point.pin))),el("td",{},el("code",{},text(point.cell))),
            el("td",{title:text(point.edge)},point.edge==="^"?"↑":point.edge==="v"?"↓":text(point.edge)),
            el("td",{},el("code",{},finite(point.delay_ns)?formatter.format(point.delay_ns*1000):missing)),
            el("td",{},el("code",{},finite(point.time_ns)?formatter.format(point.time_ns*1000):missing)))),
            {className:"table-scroll hold-pin-table",tabIndex:0,"aria-label":"STA 路径点，可横向滚动"}):el("p",{className:"secondary"},"逐级路径点未记录。"),
          path.report_url?el("div",{className:"evidence-links"},link("原始精确 STA",path.report_url)):null));
      return details;
    });
    const axis=el("div",{className:"hold-timing-axis","aria-hidden":"true"},el("div",{className:"hold-axis-scale"},
      [low,(low+maximum)/2,maximum].map((value,index)=>el("span",{className:`hold-axis-tick hold-axis-tick--${index}`,style:`--position:${position(value)}`},ps(value)))));
    return el("section",{className:"hold-timing","aria-labelledby":"hold-timing-title"},
      el("div",{className:"hold-timing-heading"},el("h3",{id:"hold-timing-title"},"Hold 路径到达检查"),
        el("div",{className:"hold-timing-legend"},el("span",{className:"hold-legend-arrival"},"数据到达"),el("span",{className:"hold-legend-required"},"最早允许"))),
      el("p",{className:"hold-timing-note"},"共用 STA 时间刻度（ps）。数据不得早于最早允许时刻。slack 保留报告原值。展开查看路径点。"),
      axis,rows);
  }
  function renderFrontendComparison() {
    const comparison=frontendComparison;
    const metrics=list(comparison.metrics).filter(metric=>metric&&typeof metric.label==="string");
    const hasDelta=metrics.some(metric=>typeof metric.delta==="string"||finite(metric.delta));
    const value=entry=>typeof entry==="string"||finite(entry)?text(entry):missing;
    const result=el("section",{className:"frontend-comparison","aria-labelledby":"frontend-comparison-title"},
      el("h2",{id:"frontend-comparison-title"},"控制器 Hold 调整对照"),
      comparison.summary?el("p",{className:"frontend-comparison-scope"},comparison.summary):null);
    if(metrics.length){
      const measurement=table(["测量项","基线","Hold 调整后",...(hasDelta?["变化"]:[])],metrics.map(metric=>el("tr",{},
        el("th",{scope:"row"},metric.label),el("td",{"data-label":"基线"},el("code",{},value(metric.before))),
        el("td",{"data-label":"Hold 调整后"},el("code",{},value(metric.after))),
        hasDelta?el("td",{"data-label":"变化"},el("code",{},value(metric.delta))):null)),
        {className:`table-scroll frontend-metric-table${hasDelta?" has-delta":""}`});
      measurement.querySelectorAll("table,thead,tbody,tr,th,td").forEach(node=>node.setAttribute("role",
        ({TABLE:"table",THEAD:"rowgroup",TBODY:"rowgroup",TR:"row",TD:"cell"})[node.tagName]||
        (node.getAttribute("scope")==="row"?"rowheader":"columnheader")));
      result.append(measurement);
    }
    const timing=renderHoldTiming(comparison.timing_paths);
    if(timing)result.append(timing);
    const rows=frontendStages.map(stage=>el("tr",{"data-stage-id":String(stage.id)},
      el("th",{scope:"row"},text(stage.title||stage.id)),
      ["before","after"].map(side=>{
        const check=stage[side];
        return el("td",{"data-side":side,"data-label":side==="before"?"基线":"Hold 调整后",
          className:check?.status==="TIMING_VIOLATION"?"is-timing-violation":null},
          check?frontendStatus(check):el("span",{className:"secondary"},missing),check?frontendArtifacts(check):null);
      })));
    const workflow=table(["检查阶段","基线","Hold 调整后"],rows,{className:"table-scroll frontend-stage-table"});
    // Mobile rearranges these same rows; explicit roles retain their table
    // semantics in accessibility trees when CSS changes their display mode.
    workflow.querySelectorAll("table,thead,tbody,tr,th,td").forEach(node=>node.setAttribute("role",
      ({TABLE:"table",THEAD:"rowgroup",TBODY:"rowgroup",TR:"row",TD:"cell"})[node.tagName]||
      (node.getAttribute("scope")==="row"?"rowheader":"columnheader")));
    result.append(workflow);
    const diagnosis=(Array.isArray(comparison.diagnosis)?comparison.diagnosis:[comparison.diagnosis]).filter(item=>typeof item==="string"&&item.trim());
    if(diagnosis.length)result.append(el("p",{className:"frontend-path-summary"},diagnosis[0]));
    if(diagnosis.length>1)result.append(el("details",{className:"frontend-diagnosis"},el("summary",{},"路径、ECO 与分析边界"),
      diagnosis.slice(1).map(item=>el("p",{},item))));
    result.append(el("p",{className:"inline-note frontend-comparison-boundary"},"两列保留各次执行的状态与文件。扫描检查覆盖定向移位和功能捕获，ATPG 故障覆盖率未纳入此处。"));
    return result;
  }
  function renderFrontend() {
    root.append(planNavigation());
    if(frontendStages.length){root.append(renderFrontendComparison());return;}
    intro("综合、STA、门级比较和扫描检查按实际执行分别记录，状态独立于 UVM 回归结果。");
    if(!frontendChecks.length){root.append(empty("尚无实现检查记录","当前证据包未包含综合、时序或扫描检查报告。"));return;}
    const rows=frontendChecks.map(check=>{
      const timing=check.status==="TIMING_VIOLATION";
      return el("li",{className:`frontend-check${timing?" frontend-check--timing":""}`,"data-check-id":String(check.id)},
        el("div",{className:"frontend-check-heading"},el("h2",{},text(check.title||check.id)),frontendStatus(check)),
        check.summary?el("p",{className:"frontend-check-summary"},check.summary):null,
        timing?el("p",{className:"frontend-timing-note"},"时序检查记录了 hold 违例。可用 SDC 和完整时序路径复核。" ):null,
        frontendArtifacts(check));
    });
    root.append(el("section",{className:"frontend-results","aria-label":"实现与 DFT 检查记录"},
      el("ol",{className:"frontend-check-list"},rows),
      el("p",{className:"inline-note frontend-boundary"},"扫描证据覆盖定向图样移位与功能捕获。面积和时序的测量范围见各项报告。")));
  }

  function renderPlanRun(run) {
    const waveform = originalWaveFor(run);
    const diagnostics = [...list(run.failure_excerpt), ...list(run.diagnostic_excerpt)]
      .filter(line => typeof line === "string" && line.trim());
    const context = [suiteTitle(run.suite_id), variantName(run.variant), `seed ${text(run.seed)}`];
    if (run.phase) context.push(phaseName(run.phase));
    if (run.mutation) context.push(run.mutation);
    return el("section", {className:"plan-run-evidence", "aria-label":"当前运行证据"},
      el("div", {className:"plan-evidence-header"},
        el("div", {}, el("h3", {}, el("code", {className:"wrap-anywhere"}, text(run.test))),
          el("p", {className:"secondary"}, context.join(" · "))),
        resultBadges(run)),
      el("div", {className:"row-actions"},
        run.log_url ? link("原始日志", run.log_url, {target:"_blank", rel:"noopener"}) : null,
        waveform ? button("查看同次波形", () => showWave(waveform.id), {className:"link-button"}) : null,
        run.report_url ? link("原始报告", run.report_url, {target:"_blank", rel:"noopener"}) : null),
      waveform ? null : el("p", {className:"plan-wave-status secondary"}, run.waveform_unavailable || "本次运行未归档波形。"),
      diagnostics.length ? el("pre", {className:"plan-log-excerpt", tabIndex:0, "aria-label":"原始日志摘录"}, diagnostics.join("\n")) : null,
      reproductionEvidence(run));
  }

  function renderVerificationPlan() {
    const plan = state.plan;
    const runsFor = item => [...new Set(list(item?.run_ids))].map(id => runsById.get(id)).filter(Boolean);
    const itemsOf = group => list(group.items).filter(item => item && hasId(item.id));
    let group = planGroups.find(candidate => candidate.id === plan.groupId) ||
      planGroups.find(candidate => itemsOf(candidate).some(item => runsFor(item).some(run => run.raw_status === "FAIL"))) || planGroups[0];
    const listHost = el("div");
    const itemHost = el("div", {id:"plan-item-evidence"});
    const selectGroup = makeSelect(planGroups.map(item => ({value:String(item.id),label:text(item.title)})),
      String(group.id), id => {
        group = planGroups.find(candidate => String(candidate.id) === id) || group;
        Object.assign(plan,{groupId:group.id, itemId:"", runId:"", failures:false});
        updateItems();
      }, {"aria-label":"验证范围"});
    plan.groupId = group.id;
    root.append(planNavigation(),
      el("section", {className:"panel plan-points"},
        el("div", {className:"plan-scope"}, makeField("验证范围", selectGroup),
          el("span", {className:"secondary"}, "验证项关联用例与已归档运行。")),
        listHost),
      itemHost);

    function updateItems() {
      const items = itemsOf(group);
      const rowControls = [];
      const itemRows = items.map(item => {
        const results = counts(runsFor(item));
        const tests = new Set(list(item.checks).flatMap(check => list(check?.tests)));
        const title = button(text(item.title), () => {
          if (plan.itemId === item.id && !plan.failures) {
            Object.assign(plan,{itemId:"",runId:""});
            title.setAttribute("aria-expanded","false");
            itemHost.replaceChildren();
          } else open(item, false);
        }, {
          className:"link-button plan-point-button", "aria-controls":"plan-item-evidence",
          "aria-expanded":String(plan.itemId === item.id)
        });
        rowControls.push({item, title});
        const statuses = el("div", {className:"stack plan-statuses"},
          results.pass ? badge(`PASS ${results.pass}`, "pass") : null,
          results.fail ? button(`FAIL ${results.fail}`, () => open(item, true), {
            className:"badge badge--fail plan-status-button",
            "aria-label":`查看${text(item.title)}的 ${results.fail} 次原始 FAIL`,
            "aria-controls":"plan-item-evidence"
          }) : null,
          results.other ? badge(`其他状态 ${results.other}`, "unknown") : null,
          results.total ? null : badge("未记录", "unknown"),
          item.binding_status === "partial" ? el("span", {className:"secondary"}, "部分用例未记录") : null);
        return el("tr", {}, el("th", {scope:"row"}, title), el("td", {}, `${number(tests.size)} 个用例`), el("td", {}, statuses));
      });
      listHost.replaceChildren(table(["验证项", "映射用例", "归档结果"], itemRows, {className:"table-scroll compact plan-point-table"}));
      function open(item, failures) {
        if (item.id !== plan.itemId || failures !== plan.failures) plan.runId = "";
        Object.assign(plan,{itemId:item.id, failures});
        rowControls.forEach(row => row.title.setAttribute("aria-expanded", String(row.item === item)));
        updateRuns(item);
        if (failures) document.getElementById("plan-selected-run")?.scrollIntoView({block:"nearest"});
      }
      const selected = items.find(item => item.id === plan.itemId);
      if (selected) updateRuns(selected);
      else itemHost.replaceChildren();
    }

    function updateRuns(item) {
      const allRuns = runsFor(item);
      const report = counts(allRuns);
      const selectedRuns = plan.failures ? allRuns.filter(run=>run.raw_status==="FAIL") : allRuns;
      const evidence = el("div", {id:"plan-selected-run"});
      const runButtons = [];
      const choose = run => {
        plan.runId = run.id;
        runButtons.forEach(entry => entry.control.setAttribute("aria-pressed", String(entry.run === run)));
        evidence.replaceChildren(renderPlanRun(run));
      };
      const body = selectedRuns.map(run => {
        const context = [variantName(run.variant), `seed ${text(run.seed)}`];
        if (run.mutation) context.push(run.mutation);
        const control = button(text(run.raw_status), () => {
          choose(run);
          evidence.scrollIntoView({block:"nearest"});
        }, {
          className:`badge badge--${run.raw_status === "FAIL" ? "fail" : run.raw_status === "PASS" ? "pass" : "unknown"} plan-status-button`,
          "aria-pressed":"false", "aria-controls":"plan-selected-run",
          "aria-label":`${text(run.test)} · ${context.join(" · ")} · ${text(run.raw_status)}`
        });
        runButtons.push({run, control});
        return el("tr", {}, el("th", {scope:"row"}, el("code", {className:"wrap-anywhere"}, text(run.test))),
          el("td", {}, context.join(" · ")),
          el("td", {}, el("div", {className:"stack plan-statuses"}, control,
            run.classification === "DETECTED" ? badge("DETECTED","detected") : null)));
      });
      const showMode = failures => {
        plan.failures = failures;
        updateRuns(item);
        // Keep keyboard focus on the matching filter within the rebuilt region.
        itemHost.querySelector(".plan-run-filter[aria-pressed=true]")?.focus({preventScroll:true});
      };
      const mode = el("div", {className:"plan-run-modes", role:"group", "aria-label":"当前验证项运行"},
        button(`全部 ${report.total}`, () => showMode(false), {className:"button small plan-run-filter", "aria-pressed":String(!plan.failures)}),
        report.fail ? button(`原始 FAIL ${report.fail}`, () => showMode(true),
          {className:"button small plan-run-filter", "aria-pressed":String(plan.failures)}) : null);
      const unrecorded = list(item.checks).flatMap(check => list(check?.missing_tests));
      itemHost.replaceChildren(panel(text(item.title), item.summary || null, mode,
        unrecorded.length ? el("p", {className:"secondary"}, `未归档用例 · ${unrecorded.join("、")}`) : null,
        body.length ? table(["UVM 用例", "版本 / seed", "原始状态"], body,
          {className:"table-scroll compact plan-run-table", tabIndex:0, "aria-label":"归档运行"}) :
          el("p", {className:"secondary"}, "当前筛选无归档运行。"), evidence));
      const selected = selectedRuns.find(run => run.id === plan.runId) || (plan.failures ? selectedRuns[0] : null);
      if (selected) choose(selected);
    }
    updateItems();
  }

  function renderRegressions() {
    if (planGroups.length) root.append(planNavigation());
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
          const associated=originalWaveFor(run);
          const point = run.raw_status === "FAIL" ? planByRun.get(run.id) : null;
          const actions=el("div",{className:"row-actions"},run.log_url?link("原始日志",run.log_url):null,run.report_url?link("原始报告",run.report_url):null,associated?button("查看同次波形",()=>showWave(associated.id),{className:"link-button"}):null);
          const diagnostics=`${number(run.metrics?.errors)} / ${number(run.metrics?.fatals)}`;
          const duration=finite(run.metrics?.duration_s)?`${number(run.metrics.duration_s)} s`:"用时未记录";
          const more=el("details",{className:"regression-more"},el("summary",{},"更多运行信息"),
            el("dl",{className:"detail-list"},
              el("dt",{},"版本"),el("dd",{},variantName(run.variant)),
              el("dt",{},"运行阶段"),el("dd",{},run.phase?phaseName(run.phase):missing),
              el("dt",{},"比对 / 总线计数"),el("dd",{},countersFor(run)),
              el("dt",{},"ERROR / FATAL"),el("dd",{className:"mono"},diagnostics),
              el("dt",{},"用时"),el("dd",{},duration)));
          return el("tr",{className:"regression-row"},
            el("td",{className:"reg-col-test","data-label":"测试 / 范围"},el("code",{},text(run.test)),el("span",{className:"row-secondary"},suiteTitle(run.suite_id))),
            el("td",{className:"reg-col-variant","data-label":"版本"},variantName(run.variant)),
            el("td",{className:"reg-col-seed mono","data-label":"Seed"},text(run.seed)),
            el("td",{className:"reg-col-phase","data-label":"阶段"},run.phase?badge(phaseName(run.phase),"phase"):el("span",{className:"secondary"},missing)),
            el("td",{className:"reg-col-status","data-label":"原始状态 / 分类"},resultBadges(run, point ? () => {
              Object.assign(state.plan,point,{runId:run.id,failures:true});
              setView("plan",true);
              document.getElementById("plan-selected-run")?.scrollIntoView({block:"nearest"});
            } : null)),
            el("td",{className:"reg-col-counts","data-label":"日志比对或总线计数"},countersFor(run)),
            el("td",{className:"reg-col-diagnostics nowrap mono","data-label":"ERROR / FATAL"},diagnostics,el("span",{className:"row-secondary"},duration)),
            el("td",{className:"reg-col-evidence","data-label":"证据"},actions,reproductionEvidence(run),more));
        });
        const regressionTable=table(["测试 / 范围","版本","Seed","阶段","原始状态 / 分类","日志比对或总线计数","ERROR / FATAL","证据"],body,{className:"table-scroll regression-table"});
        const columns=["test","variant","seed","phase","status","counts","diagnostics","evidence"];
        regressionTable.querySelector("table").setAttribute("role","table");
        regressionTable.querySelectorAll("thead,tbody").forEach(node=>node.setAttribute("role","rowgroup"));
        regressionTable.querySelectorAll("tr").forEach(node=>node.setAttribute("role","row"));
        regressionTable.querySelectorAll("th").forEach((node,index)=>{
          node.setAttribute("role","columnheader");
          node.classList.add(`reg-col-${columns[index]}`);
        });
        regressionTable.querySelectorAll("td").forEach(node=>node.setAttribute("role","cell"));
        resultPanel.append(regressionTable);
        resultPanel.append(el("div",{className:"pagination"},el("span",{},`第 ${start+1}–${Math.min(start+state.reg.size,rows.length)} 条，共 ${rows.length} 条`),el("div",{className:"button-group"},button("上一页",()=>{state.reg.page--;updateResults();},{disabled:state.reg.page<=1,className:"button small"}),el("span",{},`${state.reg.page} / ${pages}`),button("下一页",()=>{state.reg.page++;updateResults();},{disabled:state.reg.page>=pages,className:"button small"}))));
      }
      resultPanel.append(el("p",{className:"table-note"},"TX/RX 为日志中的比对计数。成功帧汇总仅包含明确 UART 范围中的原始 PASS；APB completed、读写与等待周期单独呈现。未提供的计数显示“未记录”。"));
      resultBox.replaceChildren(resultPanel);
    }
    updateResults();
  }

  function coverageMetric(label,metric,kind,definition) {
    const m=metricPair(metric);
    const remainder=m?m.total-m.hit:null;
    const description=m?`${label}：已命中 ${metricText(m)}，未命中 ${number(remainder)}，${percent(m)}`:`${label}：${missing}`;
    return el("article",{className:`coverage-metric coverage-measure${m?"":" coverage-measure--unknown"}`},
      el("div",{className:"coverage-measure-heading"},el("h3",{title:definition},label),
        el("div",{className:"coverage-measure-count"},el("strong",{className:"mono nowrap"},metricText(metric)),
          el("span",{className:"coverage-percent"},percent(metric)),
          el("span",{className:"coverage-missing"},m?`未命中 ${number(remainder)}`:"缺口未记录"))),
      el("div",{className:"bar-track",role:m?"progressbar":"img","aria-label":description,
        "aria-valuemin":m?0:null,"aria-valuemax":m?m.total:null,"aria-valuenow":m?m.hit:null,"aria-valuetext":description},
        m?el("div",{className:`bar-fill ${kind||""}`,style:{width:`${100*m.hit/m.total}%`}}):null));
  }

  function renderCoverageSources(profile) {
    const absent = metric => {
      const pair = metricPair(metric);
      return pair ? pair.total - pair.hit : metric?.total === 0 ? 0 : null;
    };
    const files = list(profile.code_files).filter(file => file && hasId(file.source_path))
      .sort((a,b) => absent(b.branches) - absent(a.branches) || collator.compare(a.source_path, b.source_path));
    if (!files.length) return null;
    const detail = el("div", {className:"coverage-source-detail"});
    const sourceName = file => text(file.source_path).split("/").at(-1);
    const fileMetric = (value, color) => {
      const pair = metricPair(value);
      if (!pair) return el("span", {className:"secondary"}, value?.total === 0 ? "无计数项" : missing);
      return el("div", {className:"coverage-file-metric"},
        el("span", {className:"bar-track", "aria-hidden":"true"},
          el("span", {className:`bar-fill ${color}`, style:{width:percent(pair)}})),
        el("code", {}, metricText(pair)));
    };
    const rows = files.map(file => {
      const control = button(sourceName(file), () => select(file, true), {
        className:"coverage-file-button", title:file.source_path, "aria-pressed":"false"
      });
      const tr = el("tr", {}, el("th", {scope:"row"}, control),
        el("td", {}, fileMetric(file.lines, "code-line")), el("td", {}, fileMetric(file.branches, "code-branch")));
      return {file, control, tr};
    });
    const fileTable = table(["RTL 文件","可执行行","分支记录"], rows.map(row => row.tr),
      {className:"table-scroll compact coverage-file-list"});
    const archive = list(profile.evidence_urls).find(item => item?.label === "LCOV");
    const section = panel("RTL 源码覆盖", "分支列按 Verilator 的 LCOV 导出记录计数。选择文件查看未命中位置。", fileTable, detail);
    section.classList.add("coverage-source-panel");

    function select(file, notify=false) {
      state.coverageFile = file.source_path;
      rows.forEach(row => { row.control.setAttribute("aria-pressed", String(row.file === file)); });
      const gaps = list(file.gaps).filter(gap => gap && Number.isInteger(gap.line) && gap.line > 0);
      const gapRows = gaps.map(gap => {
        const offset = `L${gap.line}`;
        return el("tr", {},
          el("th", {scope:"row"}, file.source_url ? link(offset, `${file.source_url}#${offset}`, {
            "aria-label":`打开 ${sourceName(file)} 第 ${gap.line} 行`
          }) : offset),
          el("td", {className:"mono"}, number(gap.line_hits),
            gap.line_hits > 0 && gap.line_misses > 0 ?
              el("span", {className:"row-secondary"}, `${number(gap.line_misses)} 条行记录未命中`) : null),
          el("td", {className:"mono"}, gap.branches_total > 0 ?
            `${number(gap.branches_total - gap.branches_hit)} / ${number(gap.branches_total)}` : "—"));
      });
      const remaining = `未命中 ${number(absent(file.lines))} 行 · ${number(absent(file.branches))} 条分支记录`;
      detail.replaceChildren(el("div", {className:"coverage-source-caption"},
        el("h3", {}, el("code", {}, file.source_path)),
        el("span", {}, remaining),
        archive?.url ? link("原始 LCOV", archive.url) : null),
        gapRows.length ? table(["源码位置","行命中次数","未命中 / 分支记录"], gapRows,
          {className:"table-scroll compact coverage-source-locations", tabIndex:0, "aria-label":"未命中位置"})
          : el("p", {className:"secondary"}, Array.isArray(file.gaps) ? "当前 LCOV 没有列出此文件的缺口。" : "未提供逐行明细。"));
      if (notify) announce(`${sourceName(file)}，${remaining}`);
    }
    select(files.find(file => file.source_path === state.coverageFile) || files[0]);
    return section;
  }

  function renderCoverage() {
    const profiles=coverage.filter(item=>item&&typeof item==="object");
    if(!profiles.length){root.append(empty("没有覆盖率数据","尚未提供可复核的覆盖率记录。"));return;}
    const selected=profiles.find(item=>item.id===state.coverageId)||profiles[0];state.coverageId=selected.id;
    const picker=makeSelect(profiles.map(item=>({value:String(item.id),label:item.suite_id?`${suiteTitle(item.suite_id)} · ${variantName(item.variant)}`:text(item.title||item.id)})),String(selected.id),value=>{state.coverageId=value;setView("coverage");},{"aria-label":"选择覆盖报告"});
    const profileRuns=runs.filter(run=>run.suite_id===selected.suite_id&&run.variant===selected.variant);
    const passCount=profileRuns.filter(run=>run.raw_status==="PASS").length;
    const scope=profileRuns.length?`仅合并 ${number(passCount)} 次 PASS${profileRuns.length>passCount?`；其余 ${number(profileRuns.length-passCount)} 次未合并`:""}${selected.suite_id==="uart_ral"?"；RAL 专项与核心分开":""}`:text(selected.scope);
    root.append(el("div",{className:"toolbar coverage-scope"},makeField("统计范围",picker),el("p",{className:"inline-note"},scope)));
    const definitions=[
      ["功能 bins · 未加权",selected.metrics?.functional_bins,"","按原生计数和 at_least 阈值；非加权 covergroup 百分比。"],
      ["RTL 可执行行 · LCOV",selected.metrics?.rtl_lines,"code-line","只统计报告声明的 RTL 源码范围。"],
      ["RTL 分支 · LCOV",selected.metrics?.rtl_branches,"code-branch","分支计数独立于功能 bins 与行覆盖率。"]
    ];
    root.append(el("div",{className:"coverage-metrics coverage-measures"},definitions.map(values=>coverageMetric(...values))));
    const gaps=list(selected.gaps).filter(gap=>gap&&typeof gap==="object"),gapResults=el("div",{});
    const functional=metricPair(selected.metrics?.functional_bins);
    const search=el("input",{type:"search",placeholder:"分组、bin 或记录的原因…","aria-label":"筛选覆盖缺口"});
    const gapPanel=panel("未命中的功能 bins",functional?`${number(functional.total-functional.hit)} / ${number(functional.total)} 未命中；按记录的原因复核。`:"功能覆盖分母未记录；不从缺口列表推定完整覆盖。",makeField("查找缺口",search),gapResults);
    gapPanel.id="coverage-gaps";gapPanel.tabIndex=-1;
    function updateGaps(){
      const q=search.value.trim().toLowerCase();
      const filtered=gaps.filter(gap=>!q||[gap.group,gap.bin,gap.reason,gap.source_path].some(value=>String(value??"").toLowerCase().includes(q)));
      const rows=filtered.map(gap=>{
        const sourceName=typeof gap.source_path==="string"?gap.source_path.split(/[\\/]/).pop():"源码位置";
        return el("tr",{},el("td",{},el("code",{className:"wrap-anywhere"},text(gap.group||gap.bin)),el("span",{className:"row-secondary"},`命中 ${number(gap.hits)} / 阈值 ${number(gap.at_least)}`)),
          el("td",{className:"gap-reason"},gap.reason||missing),
          el("td",{},gap.source_url?link(`${sourceName}${gap.source_line?":"+text(gap.source_line):""}`,gap.source_url):el("span",{className:"secondary"},missing)));
      });
      gapResults.replaceChildren(el("p",{className:"count-label"},Array.isArray(selected.gaps)?`显示 ${number(filtered.length)} / ${number(gaps.length)} 条缺口记录`:"缺口明细未记录"),
        rows.length?table(["未命中 bin","记录的原因","源码"],rows):empty(gaps.length?"没有匹配的缺口":"数据中未列出缺口",gaps.length?"调整关键词后重试。":"空列表本身不证明完整覆盖；请核对实际分子、分母及原生数据库。"));
    }
    search.addEventListener("input",updateGaps);updateGaps();
    const sourcePanel = renderCoverageSources(selected);
    if (sourcePanel) {
      const content = el("div", {id:"coverage-content"});
      const modes = [
        {id:"source", label:"RTL 源码", panel:sourcePanel},
        {id:"functional", label:"功能缺口", panel:gapPanel},
      ];
      const modeButtons = modes.map(mode => button(mode.label, () => selectMode(mode), {
        className:"coverage-mode", "aria-pressed":"false", "aria-controls":"coverage-content"
      }));
      function selectMode(mode) {
        state.coverageMode = mode.id;
        modeButtons.forEach((node,index) => node.setAttribute("aria-pressed", String(modes[index] === mode)));
        content.replaceChildren(mode.panel);
      }
      root.append(el("div", {className:"coverage-modes", role:"group", "aria-label":"覆盖明细"}, modeButtons), content);
      selectMode(modes.find(mode => mode.id === state.coverageMode) || modes[0]);
    } else {
      root.append(gapPanel);
    }
    const groups=list(selected.groups).filter(group=>group&&typeof group==="object");
    const groupRows=groups.map(group=>el("tr",{},el("td",{},el("code",{title:text(group.id)},text(group.title||group.id))),el("td",{className:"mono nowrap"},metricText(group)),el("td",{className:"mono nowrap"},percent(group))));
    root.append(el("details",{className:"panel coverage-details"},el("summary",{},"分组、度量定义与原始证据"),
      el("p",{className:"inline-note"},selected.note||"只读取已记录的覆盖项，各度量分母独立。"),
      el("dl",{className:"detail-list"},el("dt",{},"记录范围"),el("dd",{},text(selected.scope)),
        definitions.map(values=>[el("dt",{},values[0]),el("dd",{},values[3])])),
      el("h3",{},"Coverpoint / cross 分组"),groups.length?table(["分组","已命中 / 有效 bins","未加权命中率"],groupRows):el("p",{className:"secondary"},"分组计数未记录。"),
      el("h3",{},"原始覆盖证据"),list(selected.evidence_urls).length?evidenceLinks(selected.evidence_urls):el("p",{className:"secondary"},"原生数据库与 LCOV 链接未记录。")));
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
  function defaultWaveSignals(signals,kind) {
    const matches=(signal,name)=>[signal.id,signal.label].some(value=>typeof value==="string"&&(value===name||value.endsWith("."+name)||(name==="apb.rst_n"&&value==="rst_n")));
    if(kind==="scan")return ["scan.clk","scan.en","scan.in","scan.out","scan.capture_checks"].map(name=>signals.find(signal=>matches(signal,name))).filter(Boolean);
    if(kind==="gate")return ["apb.rst_n","apb.psel","apb.penable","apb.pready","apb.pwrite","apb.paddr","apb.prdata","gate.prdata","scan_gate.prdata"].map(name=>signals.find(signal=>matches(signal,name))).filter(Boolean);
    if(signals.some(signal=>matches(signal,"control.fault_enable"))){
      const diagnostic=["apb.rst_n","apb.paddr","apb.prdata","control.fault_enable","dut.memory_controller_i.busy_q",
        "dut.memory_controller_i.step_q","control.ram_addr","dut.memory_controller_i.ram_rdata","dut.memory_controller_i.fail_q"];
      return diagnostic.map(name=>signals.find(signal=>matches(signal,name))).filter(Boolean);
    }
    const hasUART=signals.some(signal=>["uart.rx","uart.tx","uart.irq"].some(name=>matches(signal,name)));
    const priority=hasUART?["apb.rst_n","uart.rx","uart.tx","uart.irq","apb.psel","apb.penable","apb.pready","apb.pwrite","apb.prdata"]:
      ["apb.rst_n","apb.psel","apb.penable","apb.pready","apb.pwrite","apb.paddr","apb.pwdata","apb.prdata","apb.pslverr"];
    return priority.map(name=>signals.find(signal=>matches(signal,name))).filter(Boolean).slice(0,9);
  }
  function renderWaveforms() {
    if(!waves.length){root.append(empty("没有波形记录","尚未提供 VCD 采样事件。可从回归日志继续核对运行结果。"));return;}
    const source=waves.find(wave=>String(wave.id)===String(state.waveId))||waves[0];state.waveId=source.id;
    const wave=prepareWave(source);
    const scan=wave.kind==="scan",frontend=scan||wave.kind==="gate";
    const frontendCheck=frontend?frontendWaveContext(wave.id):null;
    const reproduced=isReproductionWave(wave),reproduction=reproductionInfo(wave);
    if(reproduced&&!reproduction){root.append(empty("复现来源无法核对","复现波形需要独立执行身份与对应原始运行的明确关联。请核对归档元数据。"));return;}
    const original=reproduction?runsById.get(reproduction.original_run_id):null;
    if(reproduced){
      title.textContent="波形与总线 · TRACE 复现";
      document.title=`${title.textContent} · ${text(data.project?.title||"APB UART")}`;
    }else if(frontend){
      title.textContent=scan?"实现波形 · 扫描检查":"实现波形 · 门级比较";
      if(frontendCheck?.variant)title.textContent+=` · ${frontendCheck.variant}`;
      document.title=`${title.textContent} · ${text(data.project?.title||"APB UART")}`;
    }
    if(!validRange(wave.range)){root.append(empty("波形时间范围未记录","需要有效的 range:[start,end] 才能显示真实时间轴。"));return;}
    const domain=wave.range, domainSpan=domain[1]-domain[0], minSpan=Math.max(domainSpan/100000,0.001);
    const defaults = defaultWaveSignals(wave.signals,wave.kind);
    const signalMatches=(signal,name)=>[signal.id,signal.label].some(value=>typeof value==="string"&&(value===name||value.endsWith("."+name)||(name==="apb.rst_n"&&value==="rst_n")));
    const priority=scan?["scan.clk","scan.en","scan.in","scan.out","scan.capture_checks"]:["apb.rst_n","apb.psel","apb.penable","apb.pready","apb.pwrite","uart.rx","uart.tx","uart.irq"];
    const firstSignals=priority.map(name=>wave.signals.find(signal=>signalMatches(signal,name))).filter(Boolean);
    const orderedSignals=firstSignals.concat(wave.signals.filter(signal=>!firstSignals.includes(signal)));
    let ws=state.waveState.get(wave.id);
    if(!ws){const initial=validRange(wave.default_window)?[Math.max(domain[0],wave.default_window[0]),Math.min(domain[1],wave.default_window[1])]:domain.slice();const window=validRange(initial)?initial:domain.slice();ws={start:window[0],end:window[1],cursor:(window[0]+window[1])/2,selected:new Set(defaults.map(signal=>signal.id)),eventId:null,eventPage:1,eventsInView:true,eventKind:"all",eventQuery:"",density:"compact"};state.waveState.set(wave.id,ws);}
    if(!["compact","comfortable"].includes(ws.density))ws.density="compact";
    const waveformPanel=el("section",{className:"panel waveform-panel"});
    const picker=makeSelect(waves.map(item=>{
      const record=reproductionInfo(item);
      const label=record?["TRACE 复现",text(record.test),`seed ${text(record.seed)}`,
        record.mutation||record.phase&&phaseName(record.phase)].filter(Boolean).join(" · "):
        `${isReproductionWave(item)?"TRACE 复现 · ":item.kind==="scan"?"DFT 扫描 · ":item.kind==="gate"?"门级比较 · ":""}${frontendWaveContext(item.id)?.variant?frontendWaveContext(item.id).variant+" · ":""}${text(item.title)}`;
      return {value:String(item.id),label};
    }),String(wave.id),id=>{state.waveId=id;setView("waveforms");},{"aria-label":"选择真实波形"});
    const controls=el("div",{className:"wave-controls"});
    waveformPanel.append(el("div",{className:"wave-select-bar wave-record-picker"},makeField("波形记录",picker)));
    const related=!frontend&&!reproduced&&hasId(wave.run_id)?runsById.get(wave.run_id):null;
    if(frontend){
      waveformPanel.append(el("section",{className:"wave-frontend-context",role:"note","aria-label":"实现检查来源"},
        el("div",{className:"frontend-check-heading"},el("strong",{},frontendCheck?[frontendCheck.title,frontendCheck.variant].filter(Boolean).join(" · "):scan?"扫描检查":"门级比较"),frontendCheck?frontendStatus(frontendCheck):null),
        frontendCheck?.summary?el("p",{},frontendCheck.summary):null,
        scan?el("p",{className:"secondary"},"窗口聚焦同次仿真中功能捕获后的扫描移出区间。" ):null));
    }
    if(reproduction){
      const context=[original?suiteTitle(original.suite_id):null,
        original?variantName(original.variant):null,`seed ${text(reproduction.seed)}`,
        reproduction.phase?phaseName(reproduction.phase):null,reproduction.mutation].filter(Boolean);
      waveformPanel.append(el("section",{className:"wave-reproduction-context",role:"note",
        "aria-label":"TRACE 复现来源","data-original-run-id":String(reproduction.original_run_id),
        "data-reproduction-id":String(wave.id)},
        el("div",{className:"wave-reproduction-heading"},el("strong",{},"TRACE 复现"),el("span",{},"独立执行")),
        el("p",{className:"wave-reproduction-scope"},el("code",{},text(reproduction.test)),` · ${context.join(" · ")}`),
        el("div",{className:"row-actions"},
          reproduction.log_url?link("复现日志",reproduction.log_url,{target:"_blank",rel:"noopener"}):null,
          reproduction.report_url?link("复现报告",reproduction.report_url,{target:"_blank",rel:"noopener"}):null,
          original?button("查看原始运行",()=>showRun(original),{className:"link-button"}):null),
        original?.waveform_unavailable?el("p",{className:"secondary"},`原始记录：${original.waveform_unavailable}`):null));
    }
    const quickActions=el("div",{className:"wave-quick-actions"});
    const actionBar=el("div",{className:"wave-action-bar"},reproduction||related?el("div",{className:"wave-essential-status"},resultBadges(reproduction||related)):null,quickActions);
    waveformPanel.append(actionBar);
    const runContext=reproduction?el("div",{className:"wave-run-context"},
      el("dl",{className:"detail-list"},[
        ["复现执行",reproduction.reproduction_id||wave.id],
        ["关联原始运行",reproduction.original_run_id],
        ["原始运行状态",reproduction.original_raw_status],
        ["复现源码快照 SHA-256",reproduction.source_snapshot_sha256],
        ["复现二进制 SHA-256",reproduction.binary_sha256],
        ["原始源码快照 SHA-256",reproduction.original_source_snapshot_sha256],
        ["原始二进制 SHA-256",reproduction.original_binary_sha256],
        ["二进制与原始记录",reproduction.binary_matches_original===true?"一致":reproduction.binary_matches_original===false?"不同":null]
      ].filter(([,value])=>hasId(value)).map(([label,value])=>[
        el("dt",{},label),el("dd",{className:/^[a-f0-9]{64}$/i.test(String(value))?"hash":"wrap-anywhere"},text(value))])),
      el("div",{className:"evidence-links wave-run-links"},
        original?.log_url||reproduction.original_log_url?link("原始运行日志",original?.log_url||reproduction.original_log_url):null,
        original?.report_url||reproduction.original_report_url?link("原始运行报告",original?.report_url||reproduction.original_report_url):null,
        reproduction.source_snapshot_url?link("复现源码快照",reproduction.source_snapshot_url):null,
        reproduction.index_url?link("复现清单",reproduction.index_url):null)):
      frontendCheck?el("div",{className:"wave-run-context"},evidenceLinks(frontendCheck.artifacts)):
      related?el("div",{className:"wave-run-context"},
      related?el("div",{className:"legend wave-run-identity"},el("span",{},el("code",{},text(related.test)),` · seed ${text(related.seed)} · ${variantName(related.variant)}`),resultBadges(related),el("span",{},suiteTitle(related.suite_id),related.phase?` · ${phaseName(related.phase)}`:"")):null,
      el("div",{className:"evidence-links wave-run-links"},related?.log_url?link("同次运行日志",related.log_url):null,related?.report_url?link("同次原始报告",related.report_url):null,
        button("查看此运行",()=>showRun(related),{className:"button small"}))):null;
    const signalCount=el("span",{className:"wave-signal-count"});
    const signalPanel=el("section",{className:"signal-panel wave-signal-picker"},el("h3",{},"显示信号",signalCount));
    const signalList=el("div",{className:"signal-list"});
    const svg=svgEl("svg",{class:"wave-chart",tabindex:"0",role:"group","aria-label":`${scan?"真实扫描波形":"真实波形与 APB 事务轨"}：左右键移动游标，加减键缩放，Shift 加左右键平移，Home 查看全程`});
    const chartFrame=el("div",{className:"wave-chart-frame"},svg);
    const values=el("div",{className:"cursor-values"});
    const status=el("p",{className:"wave-status",role:"status"});
    const startInput=el("input",{type:"number",step:"any","aria-label":`窗口起点 ${wave.unit||"ns"}`});
    const endInput=el("input",{type:"number",step:"any","aria-label":`窗口终点 ${wave.unit||"ns"}`});
    const cursorInput=el("input",{type:"number",step:"any","aria-label":`时间游标 ${wave.unit||"ns"}`});
    const windowForm=el("form",{className:"wave-window-form",onSubmit:event=>{event.preventDefault();applyWindow();}},makeField(`窗口起点 (${wave.unit||"ns"})`,startInput),makeField(`窗口终点 (${wave.unit||"ns"})`,endInput),button("应用范围",applyWindow,{className:"button small"}),makeField(`游标 (${wave.unit||"ns"})`,cursorInput),button("定位",()=>{const t=inputNumber(cursorInput);if(!finite(t)||t<domain[0]||t>domain[1]){invalid("请输入记录范围内的游标时间。");return;}ws.cursor=t;centerCursor();},{className:"button small"}));
    const density=makeSelect([{value:"compact",label:"紧凑"},{value:"comfortable",label:"舒展"}],ws.density,value=>{ws.density=value;scheduleDraw();},{"aria-label":"波形行密度"});
    const viewOptions=el("div",{className:"wave-view-options"},el("div",{className:"wave-chart-legend"},!scan?el("span",{},el("i",{className:"wave-key--transaction","aria-hidden":"true"}),"事务范围"):null,el("span",{},el("i",{className:"wave-key--cursor","aria-hidden":"true"}),"时间游标")),el("label",{className:"wave-density"},el("span",{},"行密度"),density));
    const transactionDetails=el("div",{className:"wave-transaction-details wave-selection-details"});
    // Only link the project's published archives; never forward arbitrary data URLs.
    const publishedArchives=new Set(["release/inputs/018_waves.vcd","release/inputs/024_waves.vcd","release/inputs/066_waves.vcd","release/inputs/116_waves.vcd","release/inputs/164_waves.vcd","protocol/inputs/008_waves.vcd","protocol/inputs/012_waves.vcd","protocol/inputs/025_waves.vcd"]);
    const publicWave=data.project?.source_url==="https://github.com/jiangzheyi1234-star/apb-uart-uvm"&&publishedArchives.has(wave.source?.url)&&/^[a-f0-9]{64}$/i.test(wave.source?.sha256||"")&&list(data.inputs).some(input=>input&&input.path===wave.source.url&&input.sha256===wave.source.sha256);
    function surferUrl(){
      const viewer=new URL("https://app.surfer-project.org/");
      viewer.searchParams.set("load_url","https://jiangzheyi1234-star.github.io/apb-uart-uvm/"+wave.source.url);
      const commands=["psel","penable","pready","pwrite","prdata"].map(name=>"variable_add tb_top.apb."+name);
      const ns=value=>value.toFixed(9).replace(/\.?0+$/,"")+"ns";
      if(wave.unit==="ns"){
        if(finite(ws.cursor)&&ws.cursor>=domain[0]&&ws.cursor<=domain[1])commands.push("cursor_set "+ns(ws.cursor));
        if(validRange([ws.start,ws.end])&&ws.start>=domain[0]&&ws.end<=domain[1])commands.push("zoom_to "+ns(ws.start)+" "+ns(ws.end));
      }
      viewer.searchParams.set("startup_commands",commands.join(";"));
      return viewer.href;
    }
    const professionalLink=publicWave?link("用 Surfer 打开",surferUrl(),{title:"在 Surfer 浏览器版中打开已公开的原始 VCD，带当前游标与时间窗口"}):null;
    const more=el("details",{className:"wave-more"},el("summary",{},"信号、缩放与运行证据"),el("div",{className:"wave-more-body"},
      el("section",{className:"wave-view-settings"},el("h3",{},"视图与时间范围"),controls,viewOptions,windowForm,status,transactionDetails),
      signalPanel,
      el("section",{className:"wave-evidence"},el("h3",{},reproduced?"复现执行与文件":frontend?"实现检查与原始文件":"同次运行与原始文件"),runContext,
        wave.source?el("div",{className:"provenance"},el("div",{className:"evidence-links"},wave.source.url?link(reproduced?"打开复现 VCD":"打开原始 VCD",wave.source.url):el("span",{className:"secondary"},reproduced?"复现 VCD 链接未记录":"原始 VCD 链接未记录"),professionalLink),wave.source.sha256?el("p",{className:"hash",style:{marginTop:"8px"}},"SHA-256 ",wave.source.sha256):null,wave.source.note?el("p",{className:"secondary"},wave.source.note):null):null),
      el("p",{className:"wave-help"},`${scan?"":"点击事务轨选中事务；"}滚轮缩放、拖动平移。← → 移动游标，+ / − 缩放，Shift + ← → 平移，Home 全程。`)));
    const waveMain=el("div",{className:"wave-main"},chartFrame,more);
    waveformPanel.append(el("div",{className:"wave-layout wave-layout--full"},waveMain));
    root.append(waveformPanel);
    const eventResults=el("div",{}),allEvents=list(wave.apb_events),waitEvents=allEvents.filter(eventHasWait),issueEvents=allEvents.filter(eventHasIssue);
    const eventSearch=el("input",{type:"search",value:ws.eventQuery,placeholder:"地址、数据、状态…","aria-label":"筛选 APB 事件"});
    const eventKind=makeSelect([{value:"all",label:`全部记录 (${allEvents.length})`},{value:"wait",label:`有等待 (${waitEvents.length})`},{value:"issue",label:`异常记录 (${issueEvents.length})`}],ws.eventKind,value=>{ws.eventKind=value;ws.eventPage=1;renderEvents();},{"aria-label":"APB 事件类型"});
    const inView=el("input",{type:"checkbox",checked:ws.eventsInView,onChange:event=>{ws.eventsInView=event.target.checked;ws.eventPage=1;renderEvents();}});
    const locatable=event=>finite(event.start)&&event.start>=domain[0]&&event.start<=domain[1];
    if(!scan||allEvents.length)root.append(el("details",{className:"wave-event-disclosure"},el("summary",{},"APB 事件记录"),el("div",{className:"wave-event-body"},
      el("div",{className:"toolbar wave-event-tools"},makeField("事件类型",eventKind),makeField("搜索事件",eventSearch),el("label",{className:"check-field"},inView,"仅当前窗口")),
      el("p",{className:"inline-note"},"点击事件时间定位到对应采样窗口。快捷定位扫描整份波形，并清除事件搜索条件。异常记录包括非 OK 状态或 PSLVERR；复位中止、未完成及未知记录需结合日志判断。"),eventResults)));
    eventSearch.addEventListener("input",()=>{ws.eventQuery=eventSearch.value;ws.eventPage=1;renderEvents();});
    signalPanel.append(el("div",{className:"button-group"},button("全选",()=>{ws.selected=new Set(wave.signals.map(signal=>signal.id));refreshSignals();scheduleDraw(true);},{className:"button small"}),button("清空",()=>{ws.selected.clear();refreshSignals();scheduleDraw(true);},{className:"button small"})),signalList,values);
    function refreshSignals(){signalCount.textContent=`${ws.selected.size} / ${wave.signals.length}`;signalList.replaceChildren(...orderedSignals.map(signal=>el("label",{className:"signal-check"},el("input",{type:"checkbox",checked:ws.selected.has(signal.id),onChange:event=>{if(event.target.checked)ws.selected.add(signal.id);else ws.selected.delete(signal.id);signalCount.textContent=`${ws.selected.size} / ${wave.signals.length}`;scheduleDraw(true);}}),el("span",{},text(signal.label||signal.id),finite(signal.width)?el("small",{},`[${signal.width}]`):null))));}
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
    const eventSummary = el("div", {className:"wave-transaction-summary wave-focus-bar",role:"status",hidden:true});
    function updateEventSummary(event) {
      eventSummary.hidden=!event;eventSummary.style.display=event?"":"none";
      if(!event){eventSummary.replaceChildren();transactionDetails.replaceChildren();return;}
      const direction=event.write===true?"WRITE":event.write===false?"READ":missing;
      const data=event.write===true?event.write_data:event.write===false?event.read_data:null;
      const duration=finite(event.start)&&finite(event.end)&&event.end>=event.start?`${time(event.end-event.start)} ${wave.unit||"ns"}`:missing;
      eventSummary.replaceChildren(el("strong",{className:"wave-event-direction"},direction),el("code",{},`${formatBus(event.address)} → ${formatBus(data)}`),el("span",{className:"wave-event-wait"},`等待 ${number(event.wait_cycles)}`),el("span",{className:`wave-event-status${eventHasIssue(event)?" is-issue":""}`},text(event.status)),button("取消选择",()=>{ws.eventId=null;updateEventSummary(null);scheduleDraw(true);},{className:"link-button"}));
      transactionDetails.replaceChildren(el("strong",{},"选中事务"),el("span",{},`区间 ${time(event.start)}–${time(event.end)} ${wave.unit||"ns"}`),el("span",{},`持续 ${duration}`),el("span",{},`等待 ${number(event.wait_cycles)} 周期`));
    }
    updateEventSummary(ws.eventId === null ? null : allEvents.find(event => event.id === ws.eventId));
    const jumpControls = el("div", {className:"button-group wave-jump-controls", "aria-label":"APB 事件定位"},
      waitEvents.some(locatable)?button("下一个等待", () => jumpEvent("wait"), {className:"button small"}):null,
      issueEvents.some(locatable)?button("下一个异常", () => jumpEvent("issue"), {className:"button small"}):null);
    quickActions.append(jumpControls);
    const origin = state.waveReturn;
    const returnLabel = {overview:"返回总览", plan:"返回验证计划", frontend:"返回实现与 DFT", defects:"返回缺陷对照", regressions:"返回筛选结果"}[origin?.view];
    if (returnLabel) quickActions.append(button(returnLabel, () => {
      if (origin.filters) Object.assign(state.reg, origin.filters);
      setView(origin.view, true);
    }, {className:"button small"}));
    waveformPanel.insertBefore(eventSummary, waveformPanel.querySelector(".wave-layout"));
    function dimensions(){const width=Math.max(260,chartFrame.clientWidth-2);const left=width<500?116:174;return {width,left,right:14,plot:Math.max(80,width-left-14)};}
    function pointerX(event){const d=dimensions(),rect=svg.getBoundingClientRect();return (event.clientX-rect.left)*d.width/Math.max(1,rect.width);}
    function pointerTime(event){const d=dimensions();return ws.start+(Math.max(0,Math.min(d.plot,pointerX(event)-d.left))/d.plot)*(ws.end-ws.start);}
    const absoluteFormatter=new Intl.NumberFormat("zh-CN",{maximumFractionDigits:9});
    const absoluteTime=value=>finite(value)?absoluteFormatter.format(value):missing;
    function axisTicks(start,end,pixels){
      const count=Math.max(1,Math.floor(pixels/115)),rawStep=(end-start)/count,power=10**Math.floor(Math.log10(rawStep)),candidates=[1,2,5,10].map(value=>value*power);
      const step=candidates.find(value=>value>=rawStep*(1-1e-12)&&value<=end-start)||candidates.filter(value=>value<=end-start).pop()||power;
      const digits=Math.min(9,Math.max(0,-Math.floor(Math.log10(step)))),formatter=new Intl.NumberFormat("zh-CN",{maximumFractionDigits:digits});
      const first=Math.ceil(start/step-1e-9),last=Math.floor(end/step+1e-9),ticks=[];
      for(let offset=0;offset<count+3&&first+offset<=last;offset++){const value=Number(((first+offset)*step).toFixed(digits));if(value>=start&&value<=end&&(!ticks.length||value>ticks[ticks.length-1].value))ticks.push({value,label:formatter.format(value)});}
      return ticks;
    }
    function draw(){
      const d=dimensions(),selected=orderedSignals.filter(signal=>ws.selected.has(signal.id)),axis=78,row=ws.density==="comfortable"?54:40,height=axis+Math.max(1,selected.length)*row+16,span=ws.end-ws.start;
      svg.setAttribute("viewBox",`0 0 ${d.width} ${height}`);svg.setAttribute("height",String(height));svg.replaceChildren();
      const x=t=>d.left+(t-ws.start)/span*d.plot;
      const fit=(value,pixels)=>{const string=String(value),limit=Math.max(0,Math.floor(pixels/8.5));return string.length<=limit?string:limit>=3?string.slice(0,limit-1)+"…":"";};
      svg.append(svgEl("rect",{x:0,y:0,width:d.width,height:height,fill:"#fcfeff"}),svgEl("rect",{x:0,y:0,width:d.width,height:axis,fill:"#edf4f8"}));
      for(let i=0;i<Math.max(1,selected.length);i++)svg.append(svgEl("rect",{x:d.left,y:axis+i*row,width:d.plot,height:row,fill:i%2?"#f2f7fa":"#fcfeff",class:`wave-lane${i%2?" wave-lane--alternate":""}`}));
      svg.append(svgEl("rect",{x:0,y:axis,width:d.left,height:height-axis,fill:"#edf3f7"}),svgEl("line",{x1:d.left,y1:0,x2:d.left,y2:height,stroke:"#c7d8e2"}));
      const activeEvent=allEvents.find(event=>event.id===ws.eventId);
      if(!activeEvent)updateEventSummary(null);
      if(activeEvent&&finite(activeEvent.start)&&finite(activeEvent.end)&&activeEvent.end>=ws.start&&activeEvent.start<=ws.end){const a=x(Math.max(ws.start,activeEvent.start)),b=x(Math.min(ws.end,activeEvent.end));svg.append(svgEl("rect",{x:a,y:axis-3,width:Math.max(1,b-a),height:height-axis-9,fill:"#0c8b88","fill-opacity":.09,class:"wave-selected-range"}));for(const t of [activeEvent.start,activeEvent.end])if(t>=ws.start&&t<=ws.end)svg.append(svgEl("line",{x1:x(t),y1:70,x2:x(t),y2:height-12,stroke:"#087f83","stroke-width":1.5,"stroke-dasharray":"3 3",class:"wave-selected-boundary"}));}
      let previousLabelRight=-Infinity;
      for(const tick of axisTicks(ws.start,ws.end,d.plot)){const px=x(tick.value),labelWidth=tick.label.length*8.5,anchor=px-d.left<labelWidth/2?"start":d.width-d.right-px<labelWidth/2?"end":"middle",labelLeft=px-(anchor==="end"?labelWidth:anchor==="middle"?labelWidth/2:0);svg.append(svgEl("line",{x1:px,y1:24,x2:px,y2:height-12,stroke:"#d9e5ed","stroke-width":1,class:"wave-time-grid"}));if(labelLeft>=previousLabelRight+12){const label=svgEl("text",{x:px,y:18,"text-anchor":anchor,class:"wave-axis wave-time-tick","data-time":String(tick.value)},tick.label);label.append(svgEl("title",{},`绝对时间 ${absoluteTime(tick.value)} ${wave.unit||"ns"}`));svg.append(label);previousLabelRight=labelLeft+labelWidth;}}
      svg.append(svgEl("text",{x:12,y:18,class:"wave-axis"},"信号 / 游标值"),svgEl("text",{x:12,y:38,class:"wave-axis"},`绝对时间 ${wave.unit||"ns"}`),svgEl("text",{x:12,y:65,class:"wave-axis"},scan&&!allEvents.length?"扫描时序":"APB 事务"));
      for(const event of allEvents){if(!finite(event.start)||!finite(event.end)||event.end<ws.start||event.start>ws.end)continue;const a=x(Math.max(ws.start,event.start)),b=x(Math.min(ws.end,event.end)),isSelected=event.id===ws.eventId,issue=eventHasIssue(event),direction=event.write===true?"W":event.write===false?"R":"?",label=`${direction} ${formatBus(event.address)}`,description=`${label} · ${text(event.status)} · 等待 ${number(event.wait_cycles)} 周期 · ${time(event.start)}–${time(event.end)} ${wave.unit||"ns"}`;
        const group=svgEl("g",{class:"wave-event-track",tabindex:"0",role:"button","aria-label":description,"aria-pressed":isSelected?"true":"false","data-apb-event-id":String(event.id),style:"cursor:pointer"});
        group.append(svgEl("rect",{x:a,y:51,width:Math.max(1,b-a),height:20,rx:3,fill:isSelected?"#0a7c80":issue?"#f5e3bd":event.write===true?"#d7eceb":"#dce9f7",stroke:isSelected?"#075d60":issue?"#a97727":event.write===true?"#71aaa6":"#87a8c7","stroke-width":isSelected?2:1,class:`wave-event-band wave-event-band--${issue?"issue":event.write===true?"write":"read"}${isSelected?" wave-event-band--selected":""}`}));
        const display=fit(label,b-a-12);if(display)group.append(svgEl("text",{x:(a+b)/2,y:65,"text-anchor":"middle",fill:isSelected?"#ffffff":"#284c63","font-size":12,"font-family":"ui-monospace,Consolas,monospace",class:`wave-event-label${isSelected?" is-selected":""}`},display));
        if(isSelected&&event.start<ws.start)group.append(svgEl("path",{d:`M${a+6},55L${a+2},61L${a+6},67`,stroke:"#ffffff","stroke-width":1.5,fill:"none",class:"wave-event-clipped-start"}));
        if(isSelected&&event.end>ws.end)group.append(svgEl("path",{d:`M${b-6},55L${b-2},61L${b-6},67`,stroke:"#ffffff","stroke-width":1.5,fill:"none",class:"wave-event-clipped-end"}));
        group.append(svgEl("title",{},description));group.addEventListener("pointerdown",event=>event.stopPropagation());group.addEventListener("click",click=>{click.stopPropagation();svg.focus({preventScroll:true});focusEvent(event);});group.addEventListener("keydown",key=>{if(key.key==="Enter"||key.key===" "){key.preventDefault();key.stopPropagation();svg.focus({preventScroll:true});focusEvent(event);}});svg.append(group);
      }
      if(!selected.length)svg.append(svgEl("text",{x:d.left+12,y:axis+27,class:"wave-axis"},"请选择显示信号"));
      for(let i=0;i<selected.length;i++){
        const signal=selected[i],top=axis+i*row,bottom=top+row,high=top+8,low=bottom-9,middle=(high+low)/2;
        const label=String(signal.label||signal.id),cursorValue=formatBits(valueAt(signal,ws.cursor),signal.width),handshake=priority.slice(0,5).some(name=>signalMatches(signal,name));
        const labelNode=svgEl("text",{x:12,y:top+16,class:`wave-label${handshake?" wave-label--handshake":""}`},fit(label,d.left-22));labelNode.append(svgEl("title",{},label));
        const valueNode=svgEl("text",{x:12,y:top+32,fill:"#386077","font-size":13,"font-family":"ui-monospace,Consolas,monospace",class:"wave-inline-value"},fit(cursorValue,d.left-22));valueNode.append(svgEl("title",{},`${label} @ ${absoluteTime(ws.cursor)} ${wave.unit||"ns"}: ${cursorValue}`));
        if(handshake)svg.append(svgEl("rect",{x:0,y:top+5,width:3,height:row-10,rx:1,fill:"#218e90",class:"wave-handshake-accent"}));
        svg.append(labelNode,valueNode,svgEl("line",{x1:0,y1:bottom,x2:d.width,y2:bottom,stroke:"#dce7ee","stroke-width":1}));
        const events=signal.events,index=valueIndex(events,ws.start);let j=index>=0?index:0;let t=ws.start;let value=index>=0?events[index][1]:null;
        const segments=[];
        if(index<0&&events.length&&events[0][0]>ws.start){segments.push([ws.start,Math.min(ws.end,events[0][0]),null]);t=events[0][0];value=events[0][1];j=0;}
        while(j+1<events.length&&events[j+1][0]<=ws.end){const next=events[j+1][0];if(next>=t)segments.push([Math.max(ws.start,t),next,value]);t=next;value=events[++j][1];}
        if(t<=ws.end)segments.push([Math.max(ws.start,t),ws.end,value]);
        if(!events.length)segments.splice(0,segments.length,[ws.start,ws.end,null]);
        if(signal.width===1){let path="",previousY=null;
          for(const [a,b,v] of segments){if(b<ws.start||a>ws.end)continue;const pa=x(Math.max(a,ws.start)),pb=x(Math.min(b,ws.end));if(v===null||/[xz]/i.test(v)){svg.append(svgEl("line",{x1:pa,y1:middle,x2:pb,y2:middle,class:"wave-unknown"}));if(pb-pa>55)svg.append(svgEl("text",{x:(pa+pb)/2,y:middle-5,"text-anchor":"middle",class:"wave-axis"},v===null?"未记录":v.toUpperCase()));previousY=null;continue;}const y=v.endsWith("1")?high:low;if(v.endsWith("1"))svg.append(svgEl("rect",{x:pa,y:high,width:Math.max(0,pb-pa),height:low-high,fill:"#1e9290","fill-opacity":.07,class:"wave-level-high"}));path+=(previousY===null?`M${pa},${y}`:`L${pa},${previousY}L${pa},${y}`)+`L${pb},${y}`;previousY=y;}
          if(path)svg.append(svgEl("path",{d:path,class:"wave-trace"}));
        }else{for(const [a,b,v] of segments){if(b<ws.start||a>ws.end)continue;const pa=x(Math.max(a,ws.start)),pb=x(Math.min(b,ws.end)),cut=Math.min(4,Math.max(0,(pb-pa)/4));if(v===null){svg.append(svgEl("line",{x1:pa,y1:middle,x2:pb,y2:middle,class:"wave-unknown"}));continue;}const busValue=formatBits(v,signal.width),shape=svgEl("path",{d:`M${pa},${middle}L${pa+cut},${high+2}L${pb-cut},${high+2}L${pb},${middle}L${pb-cut},${low-2}L${pa+cut},${low-2}Z`,class:`wave-bus${/[xz]/i.test(v)?" wave-bus--unknown":""}`});shape.append(svgEl("title",{},`${label}: ${busValue} · ${time(a)}–${time(b)} ${wave.unit||"ns"}`));svg.append(shape);const display=fit(busValue,pb-pa-16);if(display)svg.append(svgEl("text",{x:(pa+pb)/2,y:middle+5,"text-anchor":"middle",class:"wave-value"},display));}}
      }
      if(ws.cursor>=ws.start&&ws.cursor<=ws.end){const px=x(ws.cursor),label=`t=${absoluteTime(ws.cursor)} ${wave.unit||"ns"}`,width=Math.min(d.plot,Math.max(78,label.length*8+18)),left=Math.max(d.left,Math.min(d.width-d.right-width,px-width/2)),text=svgEl("text",{x:left+width/2,y:40,"text-anchor":"middle",fill:"#ffffff","font-size":12,"font-family":"ui-monospace,Consolas,monospace",class:"wave-cursor-text"},fit(label,width-12));text.append(svgEl("title",{},`游标绝对时间 ${absoluteTime(ws.cursor)} ${wave.unit||"ns"}`));svg.append(svgEl("line",{x1:px,y1:44,x2:px,y2:height-11,class:"cursor-line"}),svgEl("rect",{x:left,y:26,width:width,height:19,rx:4,fill:"#b83c4d",class:"wave-cursor-label"}),text,svgEl("path",{d:`M${px-5},44L${px+5},44L${px},50Z`,class:"cursor-handle","data-cursor-handle":"true"}),svgEl("rect",{x:px-8,y:73,width:16,height:height-84,fill:"transparent","data-cursor-handle":"true",style:"cursor:ew-resize"}));}
      if(document.activeElement!==startInput)startInput.value=String(Number(ws.start.toFixed(6)));if(document.activeElement!==endInput)endInput.value=String(Number(ws.end.toFixed(6)));if(document.activeElement!==cursorInput)cursorInput.value=String(Number(ws.cursor.toFixed(6)));
      if(professionalLink)professionalLink.setAttribute("href",surferUrl());
      status.classList.remove("invalid");status.textContent=`窗口 ${absoluteTime(ws.start)}–${absoluteTime(ws.end)} ${wave.unit||"ns"} · 游标绝对时间 ${absoluteTime(ws.cursor)} ${wave.unit||"ns"} · ${selected.length}/${wave.signals.length} 个信号`;
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
    svg.addEventListener("pointerdown",event=>{if(event.button!==0)return;const d=dimensions(),px=pointerX(event);if(px<d.left)return;svg.focus({preventScroll:true});drag={x:px,start:ws.start,end:ws.end,plot:d.plot,mode:event.target.hasAttribute("data-cursor-handle")?"cursor":"pan",moved:false};svg.setPointerCapture(event.pointerId);svg.classList.add("dragging");});
    svg.addEventListener("pointermove",event=>{if(!drag)return;const delta=pointerX(event)-drag.x;drag.moved=drag.moved||Math.abs(delta)>3;if(drag.mode==="cursor")ws.cursor=Math.max(domain[0],Math.min(domain[1],pointerTime(event)));else if(drag.moved){const shift=-delta/drag.plot*(drag.end-drag.start);[ws.start,ws.end]=clampWindow(drag.start+shift,drag.end+shift);pendingEvents=true;}scheduleDraw();});
    function endDrag(event){if(!drag)return;if(!drag.moved&&drag.mode!=="cursor")ws.cursor=Math.max(domain[0],Math.min(domain[1],pointerTime(event)));drag=null;svg.classList.remove("dragging");try{svg.releasePointerCapture(event.pointerId);}catch(_){}scheduleDraw(true);}
    svg.addEventListener("pointerup",endDrag);svg.addEventListener("pointercancel",endDrag);
    svg.addEventListener("keydown",event=>{const span=ws.end-ws.start,step=span/100;let handled=true;if(event.key==="ArrowLeft"||event.key==="ArrowRight"){const direction=event.key==="ArrowRight"?1:-1;if(event.shiftKey)setWindow(ws.start+direction*span*.1,ws.end+direction*span*.1);else{ws.cursor=Math.max(domain[0],Math.min(domain[1],ws.cursor+direction*step));if(ws.cursor<ws.start||ws.cursor>ws.end)centerCursor();else scheduleDraw();}}else if(["+","="].includes(event.key))zoom(.5);else if(["-","−"].includes(event.key))zoom(2);else if(event.key==="Home")setWindow(...domain);else handled=false;if(handled){event.preventDefault();announce(`游标 ${time(ws.cursor)} ${wave.unit||"ns"}`);}});
    let observer=null;const onResize=()=>scheduleDraw();if(typeof ResizeObserver!=="undefined"){observer=new ResizeObserver(onResize);observer.observe(chartFrame);}else window.addEventListener("resize",onResize);
    cleanupView=()=>{if(frame!==null)cancelAnimationFrame(frame);if(observer)observer.disconnect();else window.removeEventListener("resize",onResize);};
    draw();renderEvents();
    if(hasId(state.waveFocusEventId)){const event=allEvents.find(event=>event.id===state.waveFocusEventId);if(event){state.waveFocusEventId=null;focusEvent(event);}}
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
    const defects=list(data.defects).filter(defect=>defect&&typeof defect==="object");
    if(!defects.length){root.append(empty("没有缺陷对照记录","数据中尚未提供可核对的原版 / 修复版条目。"));return;}
    const rows=defects.map((defect,index)=>{
      const tests=list(defect.test_ids).filter(hasId),declared=[...new Set(list(defect.suite_ids).filter(hasId))];
      const allowed=!declared.length||declared.includes("uart_core");
      const related=allowed?runs.filter(run=>run.suite_id==="uart_core"&&tests.includes(run.test)&&["upstream","fixed"].includes(run.variant)):[];
      return {id:`defect-${index}`,label:text(defect.title||defect.id),defect,related};
    });
    const seeds=[...new Set(["1","2","3",...rows.flatMap(row=>row.related.filter(run=>hasId(run.seed)).map(run=>String(run.seed)))])].sort(collator.compare);
    const columns=["upstream","fixed"].flatMap(variant=>seeds.map(seed=>({id:`${variant}:${seed}`,label:`${variantName(variant)} · seed ${seed}`,variant,seed})));
    const entries=new Map();
    for(const row of rows)for(const run of row.related)if(hasId(run.id)&&!entries.has(String(run.id)))entries.set(String(run.id),{row,run});
    const cells=rows.flatMap(row=>columns.map(column=>{
      const matches=row.related.filter(run=>run.variant===column.variant&&String(run.seed)===column.seed);
      // A cell represents exactly one archived run; do not invent an aggregate
      // status when a record is missing or the input contains ambiguous runs.
      const run=matches.length===1?matches[0]:null;
      return {rowId:row.id,columnId:column.id,status:run?.raw_status??null,runId:run&&hasId(run.id)?run.id:null};
    }));
    const recorded=[...entries.values()];
    const association=entry=>entry.run.test==="uart_error_association_test"&&String(entry.run.seed)==="1";
    const initial=entries.get(String(state.defectRunId))||recorded.find(entry=>association(entry)&&entry.run.variant==="upstream")||recorded.find(association)||recorded[0];
    let selectedRunId=initial?.run.id??null,chart=null,fallbackButtons=[];
    const matrixHost=el("div",{className:"defect-matrix-host",role:"group","aria-label":"严格需求、版本和 seed 的原始结果矩阵"});
    const detail=el("section",{className:"panel defect-selected-detail","aria-live":"polite"});
    const options=recorded.map(({row,run})=>({value:String(run.id),label:`${row.label} · ${variantName(run.variant)} · seed ${text(run.seed)} · ${text(run.raw_status)}`}));
    const picker=makeSelect(options,String(selectedRunId??""),id=>selectRun(id),{"aria-label":"选择严格需求运行",disabled:!recorded.length});
    const selection=el("details",{className:"defect-run-select"},el("summary",{},"按运行选择"),picker);
    root.append(panel("UART 严格需求","每格对应一次归档运行，点选即可查证。",matrixHost,selection),detail);

    function disposeChart(){
      const previous=chart;chart=null;
      if(previous&&typeof previous.dispose==="function")try{previous.dispose();}catch(_){}
    }
    function updateDetail(){
      const entry=entries.get(String(selectedRunId));
      if(!entry){detail.replaceChildren(empty("没有可选运行","此处没有匹配 UART 严格需求及声明范围的真实记录。"));return;}
      const {row,run}=entry,source=row.defect[run.variant];
      const trace=originalWaveFor(run);
      const actions=el("div",{className:"row-actions"},
        run.log_url?link("本次原始日志",run.log_url):el("span",{className:"secondary"},"原始日志未记录"),
        run.report_url?link("本次原始报告",run.report_url):null,
        trace?button("本次波形",()=>showWave(trace.id),{className:"link-button"}):el("span",{className:"secondary"},"本次运行未归档波形"),
        source?.source_url?link(run.variant==="upstream"?"上游源码":"修复源码",source.source_url):el("span",{className:"secondary"},"源码位置未记录"),
        button("本次回归记录",()=>showRun(run),{className:"link-button"}));
      detail.replaceChildren(el("div",{className:"panel-heading"},el("div",{},el("h2",{},row.label),
        el("p",{},`${variantName(run.variant)} · seed ${text(run.seed)}`)),resultBadges(run)),
        row.defect.summary?el("p",{},row.defect.summary):null,
        source?.description?el("p",{className:"secondary"},source.description):null,
        el("dl",{className:"detail-list"},el("dt",{},"测试"),el("dd",{},el("code",{className:"wrap-anywhere"},text(run.test))),
          el("dt",{},"ERROR / FATAL"),el("dd",{className:"mono"},`${number(run.metrics?.errors)} / ${number(run.metrics?.fatals)}`),
          el("dt",{},"TX / RX 比对"),el("dd",{className:"mono"},`${number(run.metrics?.tx)} / ${number(run.metrics?.rx)}`)),actions,reproductionEvidence(run));
    }
    function updateFallbackSelection(){
      for(const item of fallbackButtons)item.node.setAttribute("aria-pressed",String(String(item.runId)===String(selectedRunId)));
    }
    function renderFallback(){
      disposeChart();fallbackButtons=[];
      const body=rows.map(row=>el("tr",{},el("th",{scope:"row"},row.label),columns.map(column=>{
        const cell=cells.find(item=>item.rowId===row.id&&item.columnId===column.id);
        if(!cell||!hasId(cell.runId))return el("td",{},cell?.status?badge(cell.status):el("span",{className:"secondary"},missing));
        const node=button(text(cell.status),()=>selectRun(cell.runId),{className:"button small",
          "aria-label":`${row.label}，${column.label}，原始 ${text(cell.status)}`});
        fallbackButtons.push({node,runId:cell.runId});
        return el("td",{},node);
      })));
      matrixHost.replaceChildren(table(["严格需求",...columns.map(column=>column.label)],body));
      updateFallbackSelection();
    }
    function selectRun(id,syncChart=true){
      const entry=entries.get(String(id));
      if(!entry)return;
      const changed=String(selectedRunId)!==String(entry.run.id);
      selectedRunId=entry.run.id;state.defectRunId=selectedRunId;picker.value=String(selectedRunId);
      updateDetail();updateFallbackSelection();
      if(syncChart&&chart&&changed){
        if(typeof chart.setSelected==="function")try{chart.setSelected(selectedRunId);}catch(_){renderFallback();}
        else renderFallback();
      }
    }
    if(initial)selectRun(initial.run.id,false);else updateDetail();
    try{
      if(typeof window.UARTCharts?.renderMatrix!=="function")renderFallback();
      else{
        chart=window.UARTCharts.renderMatrix(matrixHost,{rows:rows.map(row=>({id:row.id,label:row.label})),
          columns,cells,selectedRunId,
          onSelect:id=>selectRun(id)});
        if(!chart||typeof chart.dispose!=="function")renderFallback();
      }
    }catch(_){renderFallback();}
    cleanupView=disposeChart;
  }

  const project=data.project||{};
  const meta=document.getElementById("project-meta");
  if(project.version)meta.append(el("span",{className:"secondary"},`证据 ${text(project.version)}`));
  if(project.source_url)meta.append(link("源码",project.source_url));
  document.getElementById("generated-at").textContent=project.generated_utc?`数据生成 UTC：${String(project.generated_utc).replace("T"," ").replace(/Z$/,"")}`:"数据生成时间未记录";
  nav.addEventListener("click",event=>{const target=event.target.closest("button[data-tab]");if(target)setView(target.dataset.tab,true);});
  nav.addEventListener("keydown",event=>{const buttons=[...nav.querySelectorAll("button[data-tab]")],index=buttons.indexOf(document.activeElement);if(index<0)return;let next=null;if(["ArrowDown","ArrowRight"].includes(event.key))next=(index+1)%buttons.length;if(["ArrowUp","ArrowLeft"].includes(event.key))next=(index-1+buttons.length)%buttons.length;if(event.key==="Home")next=0;if(event.key==="End")next=buttons.length-1;if(next!==null){event.preventDefault();buttons[next].focus();}});
  window.addEventListener("hashchange",()=>{const requested=location.hash.slice(1);if(VIEWS[requested]&&requested!==state.tab)setView(requested);});
  setView(VIEWS[location.hash.slice(1)]?location.hash.slice(1):"overview");
})();
