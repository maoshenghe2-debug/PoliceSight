/* PoliceSight 看板前端逻辑（离线、无外部依赖）。
 * 安全说明：本页为本地只读演示 —— 所有数据均来自本仓库合成数据管线产出的 JSON
 * （仅监听 127.0.0.1、无用户输入、无外部内容），innerHTML 仅拼接自有数据字段；
 * 若未来接入外部数据源，须改为 textContent / 模板转义。 */
"use strict";

const TYPE_COLORS = {"盗窃":"#2563eb","抢劫":"#dc2626","诈骗":"#d97706","伤害":"#7c3aed","寻衅滋事":"#059669"};
const LEVEL_COLORS = {red:"#dc2626", orange:"#f59e0b", yellow:"#eab308"};
const DISTRICT_CENTERS = {"滨江商务区":[3000,1500],"南湖景区":[9000,1500],"老城区":[3000,4500],"东湖新城":[9000,4500],"西郊片区":[3000,7500],"北岸片区":[9000,7500]};

const S = {meta:null, frames:null, frameMode:false, playing:false, timer:null, typeFilter:"全部"};

let map, kdeLayer, frameLayer, clusterLayers = [], groupLayer, alertLayer, caseLayer, casesData = [];
let trendChart, hwChart, bounds;

async function getJSON(url){ const r = await fetch(url); if(!r.ok) throw new Error(url+" -> HTTP "+r.status); return r.json(); }

function heatColor(v){ // 黄 → 橙 → 红 → 深红
  const stops = [[255,237,160],[253,141,60],[227,26,28],[153,27,30]];
  const p = Math.max(0, Math.min(0.999, v)) * (stops.length - 1);
  const i = Math.floor(p), f = p - i, a = stops[i], b = stops[Math.min(i+1, stops.length-1)];
  return [Math.round(a[0]+(b[0]-a[0])*f), Math.round(a[1]+(b[1]-a[1])*f), Math.round(a[2]+(b[2]-a[2])*f)];
}

function makeHeatCanvas(values, nx, ny, maxV){
  const small = document.createElement("canvas"); small.width = nx; small.height = ny;
  const sctx = small.getContext("2d");
  const img = sctx.createImageData(nx, ny);
  for (let i = 0; i < values.length; i++){
    const v = values[i] / maxV;
    if (!(v > 0.03)) continue;
    const [r,g,b] = heatColor(v);
    const alpha = Math.min(0.88, 0.10 + 0.85 * Math.sqrt(v));
    const row = Math.floor(i / nx), col = i % nx;
    const y = ny - 1 - row;               // 翻转：numpy 行 0 在南侧
    const o = (y * nx + col) * 4;
    img.data[o] = r; img.data[o+1] = g; img.data[o+2] = b; img.data[o+3] = Math.round(alpha * 255);
  }
  sctx.putImageData(img, 0, 0);
  const big = document.createElement("canvas"); big.width = nx * 8; big.height = ny * 8;
  const bctx = big.getContext("2d"); bctx.imageSmoothingEnabled = true;
  bctx.drawImage(small, 0, 0, big.width, big.height);
  return big.toDataURL();
}

function frameValues(frame){
  const v = new Float64Array(S.frames.nx * S.frames.ny);
  for (const [flat, count] of frame.cells) v[flat] = count;
  return v;
}

function districtOfAlert(a){
  if (a.center_m) return a.center_m;
  const c = DISTRICT_CENTERS[a.district];
  return c ? c : [3000, 4500];
}

async function main(){
  try{
    S.meta = await getJSON("/data/meta.json");
    document.getElementById("metaLine").textContent =
      `${S.meta.city} · 案件 ${S.meta.cases.toLocaleString()} 条 / ${S.meta.days} 天 · 起点 ${S.meta.start_date} · 真值（热点 ${S.meta.truth.hotspots} / 系列案 ${S.meta.truth.series_groups} / 突增 ${S.meta.truth.anomalies}）`;

    const b = S.meta.bbox_m;
    bounds = [[b[1], b[0]], [b[3], b[2]]];
    map = L.map("map", {crs: L.CRS.Simple, minZoom: -2, maxZoom: 2, zoomSnap: 0.25, attributionControl: false});
    map.fitBounds(bounds);

    // ── 底图 ──
    const basemap = await getJSON("/data/basemap.json");
    L.geoJSON(basemap, {
      interactive: false,
      style: f => {
        const k = f.properties.kind;
        if (k === "water") return {color:"#8ab6d6", weight:0.5, fillColor:"#b8d4ea", fillOpacity:0.95};
        if (k === "road")  return {color:"#cfcfcf", weight:2.4, opacity:0.9};
        if (k === "block") return {color:"#ececec", weight:0.4, fillColor:"#f6f6f7", fillOpacity:0.65};
        if (k === "district") return {color:"#e5e7eb", weight:1, dashArray:"3 5", fillColor:f.properties.color, fillOpacity:0.30};
        return {color:"#ddd", weight:0.5};
      }
    }).addTo(map);
    L.geoJSON(basemap, {
      filter: f => f.properties.kind === "district",
      style: {weight:0, fillOpacity:0},
      onEachFeature: (f, ly) => ly.bindTooltip(f.properties.name, {permanent:true, direction:"center", className:"district-label"})
    }).addTo(map);

    // ── KDE 全期 ──
    const kde = await getJSON("/data/kde.json");
    const kdeMax = Math.max(...kde.values);
    kdeLayer = L.imageOverlay(makeHeatCanvas(kde.values, kde.nx, kde.ny, kdeMax), bounds, {opacity:0.78});
    kdeLayer.addTo(map);

    // ── 回放帧 ──
    S.frames = await getJSON("/data/frames.json");
    frameLayer = L.imageOverlay("", bounds, {opacity:0.85});
    const slider = document.getElementById("weekSlider");
    slider.max = S.frames.frames.length - 1; slider.value = S.frames.frames.length - 1;
    slider.addEventListener("input", () => { setFrameMode(true); showFrame(Number(slider.value)); });
    document.getElementById("playBtn").addEventListener("click", togglePlay);
    showFrame(slider.value);

    // ── 聚类 ──
    const clusters = await getJSON("/data/clusters.json");
    const clusterGroup = L.layerGroup();
    for (const c of clusters){
      if (c.n < 10) continue;
      const color = TYPE_COLORS[c.ty] || "#4b5563";
      const circle = L.circle([c.cy, c.cx], {radius: c.r, color, weight: 1.4, fillColor: color, fillOpacity: 0.06});
      circle.bindTooltip(`时空簇 #${c.id} · ${c.n} 例 · 主导「${c.ty}」`, {sticky:true});
      clusterGroup.addLayer(circle);
    }
    clusterGroup.addTo(map); clusterLayers.push(["lyrClusters", clusterGroup]);

    // ── 预警 ──
    const alertsDoc = await getJSON("/data/alerts.json");
    alertLayer = L.layerGroup();
    for (const a of alertsDoc.alerts){
      const [cx, cy] = districtOfAlert(a);
      const color = LEVEL_COLORS[a.level] || "#f59e0b";
      const marker = L.circleMarker([cy, cx], {radius: 5.5, color:"#fff", weight:1, fillColor: color, fillOpacity:0.95});
      marker.bindPopup(`<b>${a.level.toUpperCase()}</b> · ${a.district}${a.grid ? " "+a.grid : ""}<br>` +
        `${a.type} · ${a.week[0]} 周（${a.current} 起 / 均值 ${a.baseline} · ${a.factor}×）<br><span style="color:#6b7280">${a.advice}</span>`);
      alertLayer.addLayer(marker);
    }
    alertLayer.addTo(map); clusterLayers.push(["lyrAlerts", alertLayer]);

    // ── 疑似系列案组 ──
    groupLayer = L.layerGroup();
    let groupsDoc = null;
    try { groupsDoc = await getJSON("/data/groups.json"); } catch(e){ /* 可缺省 */ }
    if (groupsDoc){
      for (const g of groupsDoc.top){
        const color = "#7c3aed";
        const centroid = L.circleMarker([g.cy, g.cx], {radius: 7, color:"#fff", weight:1.4, fillColor: color, fillOpacity:0.95});
        centroid.bindPopup(`疑组 <b>${g.id}</b> · ${g.n} 例 · 手法：${g.methods.join("、")}<br>可疑度 ${g.suspect_score} · 半径 ${g.radius_m}m`);
        groupLayer.addLayer(centroid);
        for (const [px, py] of g.pts){
          groupLayer.addLayer(L.circleMarker([py, px], {radius: 2.6, color, weight: 0, fillColor: color, fillOpacity: 0.55}));
          groupLayer.addLayer(L.polyline([[g.cy, g.cx], [py, px]], {color, weight: 0.7, opacity: 0.22}));
        }
      }
      groupLayer.addTo(map); clusterLayers.push(["lyrGroups", groupLayer]);
    }

    // ── 案件点（采样）──
    casesData = await getJSON("/data/cases.json");
    caseLayer = L.layerGroup();
    const step = Math.max(1, Math.floor(casesData.length / 3000));
    for (let i = 0; i < casesData.length; i += step){
      const c = casesData[i];
      if (S.typeFilter !== "全部" && c.ty !== S.typeFilter) continue;
      caseLayer.addLayer(L.circleMarker([c.y, c.x], {radius: 1.7, color:"#64748b", weight:0, fillOpacity:0.5}));
    }
    clusterLayers.push(["lyrCases", caseLayer]);

    // ── 图层开关 ──
    for (const [id, layer] of clusterLayers){
      document.getElementById(id).addEventListener("change", ev => {
        if (ev.target.checked){ layer.addTo(map); } else { map.removeLayer(layer); }
      });
    }
    document.getElementById("lyrKde").addEventListener("change", ev => {
      if (ev.target.checked && !S.frameMode) kdeLayer.addTo(map);
      else if (!ev.target.checked) map.removeLayer(kdeLayer);
    });

    // ── 类型筛选 chips ──
    const chips = document.getElementById("chips");
    for (const t of ["全部", ...S.meta.types]){
      const el = document.createElement("span");
      el.className = "chip" + (t === "全部" ? " on" : "");
      el.textContent = t;
      if (t !== "全部") el.style.borderColor = TYPE_COLORS[t];
      el.addEventListener("click", () => {
        S.typeFilter = t;
        [...chips.children].forEach(c => c.classList.remove("on"));
        el.classList.add("on");
        rebuildCases();
      });
      chips.appendChild(el);
    }

    // ── 侧栏列表 ──
    renderStats(alertsDoc, groupsDoc);
    renderAlerts(alertsDoc.alerts.slice(0, 12));
    if (groupsDoc){ renderGroups(groupsDoc); }

    // ── 图表 ──
    const trend = await getJSON("/data/trend.json");
    buildCharts(trend);

    window.addEventListener("resize", () => { map.invalidateSize(); trendChart && trendChart.resize(); hwChart && hwChart.resize(); });
    document.getElementById("metaLine").setAttribute("data-ready", "1");
  } catch (err){
    const el = document.getElementById("metaLine");
    el.innerHTML = `<span id="err">看板初始化失败：${String(err.message || err)}</span>`;
    console.error(err);
  }
}

function setFrameMode(on){
  S.frameMode = on;
  if (on){ map.removeLayer(kdeLayer); if (!map.hasLayer(frameLayer)) frameLayer.addTo(map); }
}

function showFrame(idx){
  const f = S.frames.frames[Math.max(0, Math.min(idx, S.frames.frames.length - 1))];
  if (!f) return;
  const values = frameValues(f);
  const maxV = Math.max(4, ...values);
  frameLayer.setUrl(makeHeatCanvas(values, S.frames.nx, S.frames.ny, maxV));
  const start = new Date(S.meta.start_date);
  const ds = new Date(start.getTime() + f.from * 86400000);
  const de = new Date(start.getTime() + f.to * 86400000);
  const fmt = d => `${d.getMonth() + 1}/${d.getDate()}`;
  document.getElementById("weekLabel").textContent = `第 ${f.w + 1} 帧 · ${fmt(ds)}~${fmt(de)}`;
}

function togglePlay(){
  S.playing = !S.playing;
  const btn = document.getElementById("playBtn");
  if (S.playing){
    btn.textContent = "⏸ 暂停";
    setFrameMode(true);
    let idx = document.getElementById("weekSlider").valueAsNumber;
    S.timer = setInterval(() => {
      idx += 1;
      if (idx >= S.frames.frames.length){ idx = 0; }
      document.getElementById("weekSlider").value = idx;
      showFrame(idx);
    }, 700);
  } else {
    btn.textContent = "▶ 播放";
    clearInterval(S.timer); S.timer = null;
  }
}

function rebuildCases(){
  if (!caseLayer) return;
  caseLayer.clearLayers();
  const step = Math.max(1, Math.floor(casesData.length / 3000));
  for (let i = 0; i < casesData.length; i += step){
    const c = casesData[i];
    if (S.typeFilter !== "全部" && c.ty !== S.typeFilter) continue;
    caseLayer.addLayer(L.circleMarker([c.y, c.x], {radius: 1.7, color:"#64748b", weight:0, fillOpacity:0.5}));
  }
  if (document.getElementById("lyrCases").checked && !map.hasLayer(caseLayer)) caseLayer.addTo(map);
}

function renderStats(alertsDoc, groupsDoc){
  const acc = alertsDoc.acceptance;
  const el = document.getElementById("statsBox");
  el.innerHTML = `
    <div>案件总数<br><b>${S.meta.cases.toLocaleString()}</b></div>
    <div>时间跨度<br><b>${S.meta.days} 天</b></div>
    <div>时空簇<br><b>${S.meta.grid.nx * S.meta.grid.ny} 网格</b></div>
    <div>预警条数<br><b>${acc.alerts_total}</b></div>
    <div>突增命中<br><b>${acc.hit}/${acc.anomalies}</b></div>
    <div>无关预警<br><b>${acc.false_alerts}</b></div>`;
  document.getElementById("alertCount").textContent = `（共 ${acc.alerts_total} 条 · 突增 ${acc.hit}/${acc.anomalies}）`;
}

function renderAlerts(list){
  const ul = document.getElementById("alertList");
  ul.innerHTML = "";
  for (const a of list){
    const li = document.createElement("li");
    li.innerHTML = `<span class="badge b-${a.level}">${a.level}</span>
      <span><b>${a.district}${a.grid ? " "+a.grid : ""}</b>·${a.type}<br>
      <span class="hint">${a.week[0]} 周 · ${a.current} 起 / 基线 ${a.baseline} · ${a.factor}×</span></span>`;
    li.addEventListener("click", () => {
      const [cx, cy] = districtOfAlert(a);
      map.setView([cy, cx], Math.max(map.getZoom(), 1));
    });
    ul.appendChild(li);
  }
}

function renderGroups(groupsDoc){
  const ol = document.getElementById("groupList");
  ol.innerHTML = "";
  groupsDoc.top.slice(0, 10).forEach(g => {
    const li = document.createElement("li");
    li.innerHTML = `<b>${g.id}</b> · ${g.n} 例 · ${g.methods.join("、")}
      <span class="score">${g.suspect_score}</span><br>
      <span class="hint">半径 ${g.radius_m}m · 时间跨度 ${g.t_span_days[0]}~${g.t_span_days[1]} 天</span>`;
    li.addEventListener("click", () => { map.setView([g.cy, g.cx], Math.max(map.getZoom(), 1.5)); });
    ol.appendChild(li);
  });
  const ev = groupsDoc.evaluation;
  document.getElementById("groupEval").textContent =
    `对照真值（${groupsDoc.total_groups} 组中 Top 排序）：纯度 ${ev.purity} · 召回 ${ev.recall} · 杂散组 ${ev.spurious_groups}`;
}

function buildCharts(trend){
  trendChart = echarts.init(document.getElementById("trendChart"));
  let cum = 0;
  const cumData = trend.total.map(v => (cum += v));
  trendChart.setOption({
    title: {text: "周案件量（累计线）", left: 12, top: 8, textStyle: {fontSize: 12.5, color: "#374151"}},
    grid: {left: 46, right: 16, top: 34, bottom: 24},
    xAxis: {type: "category", data: trend.weeks.map(w => w.slice(5)), axisLabel: {fontSize: 10, interval: 3}},
    yAxis: {type: "value", axisLabel: {fontSize: 10}},
    tooltip: {trigger: "axis"},
    series: [
      {name: "周案件量", type: "bar", data: trend.total, itemStyle: {color: "#93c5fd"}, barMaxWidth: 10},
      {name: "累计", type: "line", data: cumData, smooth: true, itemStyle: {color: "#1d4ed8"}, symbol: "none"}
    ]
  });
  hwChart = echarts.init(document.getElementById("hwChart"));
  hwChart.setOption({
    title: {text: "小时 × 星期 分布", left: 10, top: 8, textStyle: {fontSize: 12.5, color: "#374151"}},
    grid: {left: 40, right: 12, top: 34, bottom: 20},
    xAxis: {type: "category", data: [...Array(24).keys()].map(h => h), axisLabel: {fontSize: 9, interval: 5}},
    yAxis: {type: "category", data: ["周一","周二","周三","周四","周五","周六","周日"], axisLabel: {fontSize: 9}},
    visualMap: {show: false, min: 0, max: Math.max(1, ...trend.hour_weekday.flat())},
    series: [{
      type: "heatmap",
      data: trend.hour_weekday.flatMap((row, r) => row.map((v, c) => [c, r, v])),
      itemStyle: {borderRadius: 1},
      emphasis: {itemStyle: {shadowBlur: 4}},
      color: ["#f1f5f9", "#93c5fd", "#1d4ed8", "#1e3a8a"]
    }]
  });
}

main();
