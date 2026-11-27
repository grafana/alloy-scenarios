/* Grafana loads panel entry points as AMD modules. All replay data comes from its query frame. */
define(["exports", "react", "@grafana/data"], function (exports, React, grafana) {
  "use strict";
  const assets = "/public/plugins/alloy-journeyatlas-panel/";
  const clock = minute => {
    const seconds = Math.round(minute * 60);
    const pair = n => String(n).padStart(2, "0");
    return [Math.floor(seconds/3600), Math.floor(seconds/60)%60, seconds%60].map(pair).join(":");
  };
  const point = row => [row.x * 10.02, row.y * 6.68];
  const route = rows => rows.map(row => point(row).map(n => n.toFixed(1)).join(",")).join(" ");
  function renderAtlas(root, rows) {
    root.innerHTML = `
<link rel="stylesheet" href="${assets}atlas.css">
<main class="atlas">
  <header><div class="mast"><div class="sigil">✥</div><div><div class="eyebrow">Eastern Kingdoms &nbsp;/&nbsp; Forsaken territory</div>
  <h1>Tirisfal Glades</h1><p>A field journal of Vesper Ashvale’s first ten levels.</p></div></div>
  <div class="edition"><i></i> Simulated journey <small>3 hours &nbsp;·&nbsp; Undead priest</small></div></header>
  <div class="columns"><section class="mapcard"><div class="cardtop"><h2>Route atlas</h2><div class="legend"><i></i> Traveled <b></b> Ahead</div></div>
  <svg class="map" role="img" aria-label="Simulated route on a grid of Tirisfal Glades zone coordinates" viewBox="155 175 606 350">
    <image href="/api/datasources/proxy/uid/wow-journey/api/journey/grid.webp" width="1002" height="668"/>
    <polyline class="future"/><polyline class="shadow"/><polyline class="past"/>
    <g class="pins"></g><g class="maplabels">
      <text x="339" y="459">Deathknell</text><text x="263" y="387" text-anchor="middle">Night Web’s Hollow</text>
      <text x="628" y="356">Brill</text><text x="372" y="330" text-anchor="middle">Solliden</text>
      <text x="468" y="238" text-anchor="middle">Agamand Mills</text></g><g class="marker"><circle r="10" fill="#19211b" stroke="#f8d895" stroke-width="1.3"/><circle r="4.5" fill="#ffdf97"/></g>
  </svg>
  <div class="mapfoot"><div><span class="locator">⌖</span> <strong data-v="place"></strong></div><span class="mono" data-v="coords"></span></div>
  <div class="playback"><button class="play"></button><div class="scrub"><div><span>Session replay</span><output></output></div>
  <input type="range" aria-label="Replay position" min="0" step="1"></div></div></section>
  <aside><section class="character"><div class="eyebrow">Character sheet</div><div class="identity"><div class="crest">☾</div><div><h2>Vesper Ashvale</h2><p>Undead &nbsp;·&nbsp; Priest</p></div><div class="level"><small>LVL</small><strong data-v="level"></strong></div></div>
  <div class="vitals"></div><div class="counters"></div></section>
  <section class="journal"><div class="cardtop"><h2>Quest journal</h2><span class="eyebrow">Latest entries</span></div><div class="entries"></div><a class="trace" target="_blank" rel="noopener">Explore chapter trace ↗</a></section></aside></div>
  <section class="profile"><div class="cardtop"><div><div class="eyebrow">Character progression</div><h2>Experience gained</h2></div>
  <div class="chartvalue"><strong data-v="total"></strong><span> total XP</span></div></div>
  <svg class="xpchart" aria-label="Cumulative experience over three hours" role="img" viewBox="0 0 1000 62" preserveAspectRatio="none"><path class="xpfill"/><path class="xpline"/><line class="cursor" y1="0" y2="62"/></svg>
  <div class="axis"><span>0h</span><span>1h</span><span>2h</span><span>3h</span></div>
  <div class="jump"><span>Jump to level</span><div class="ticks"></div></div></section>
  <footer><a href="https://www.wowhead.com/classic/guide/quests/horde-reputation-quests-leveling" target="_blank" rel="noopener">Quest route research · Wowhead ↗</a></footer>
</main>`;
    const el = selector => root.querySelector(selector);
    const value = (key, text) => { el('[data-v="' + key + '"]').textContent = text; };
    const last = rows.length - 1;
    const range = el("input");
    range.max = last;
    let index = last, interval;
    const levels = rows.filter((row, i) => !i || row.level !== rows[i-1].level);
    const chartX = row => row.minute / rows[last].minute * 1000;
    const chartY = row => 60 - row.total_xp / rows[last].total_xp * 56;
    const line = rows.map((r, i) => (i ? "L" : "M") + chartX(r) + "," + chartY(r)).join(" ");
    el(".xpfill").setAttribute("d", line + " L1000,62 L0,62 Z");
    el(".xpline").setAttribute("d", line);
    el(".future").setAttribute("points", route(rows));
    for (const row of rows.filter((r,i) => !i || r.chapter !== rows[i-1].chapter)) {
      const dot = document.createElementNS("http://www.w3.org/2000/svg","circle");
      const [x,y] = point(row);
      dot.setAttribute("cx",x); dot.setAttribute("cy",y); dot.setAttribute("r",3.2);
      el(".pins").append(dot);
    }
    for (const row of levels) {
      const btn = document.createElement("button");
      btn.textContent = "Lv " + row.level;
      btn.title = "Jump to level " + row.level + " at " + clock(row.minute);
      btn.onclick = () => { stop(); draw(rows.indexOf(row)); };
      el(".ticks").append(btn);
    }
    const vitals = [["Health","hp","max_hp"],["Mana","mana","max_mana"],["Experience","xp","next_xp"]];
    el(".vitals").innerHTML = vitals.map(([name,key]) => `<div class="vital ${key}"><div><span>${name}</span><strong></strong></div><div class="rail"><i></i></div></div>`).join("");
    el(".counters").innerHTML = [["quests","Quests"],["kills","Kills"],["coin","Purse"],["gear","Avg. item level"],["achievements","Achievements"]].map(([key,label]) =>
      `<div><strong data-v="${key}"></strong><span>${label}</span></div>`).join("");
    function stop() { clearInterval(interval); interval = null; }
    function draw(next) {
      index = next;
      const r = rows[index];
      range.value = index;
      range.setAttribute("aria-valuetext", clock(r.minute));
      range.style.setProperty("--pct", (index/last * 100) + "%");
      el("output").textContent = clock(r.minute) + " / " + clock(rows[last].minute);
      el(".play").textContent = interval ? "Ⅱ  Pause" : (index === last ? "▶  Replay" : "▶  Play");
      el(".past").setAttribute("points", route(rows.slice(0,index+1)));
      el(".shadow").setAttribute("points", el(".past").getAttribute("points"));
      el(".marker").setAttribute("transform","translate(" + point(r).join(" ") + ")");
      value("place", r.place); value("coords", r.x.toFixed(1) + ", " + r.y.toFixed(1) + "  ·  " + r.activity);
      value("level", r.level); value("quests", r.quests); value("kills", r.kills);
      value("coin", Math.floor(r.copper/100) + "s " + r.copper%100 + "c");
      value("gear", r.item_level); value("achievements", r.achievements);
      value("total", r.total_xp.toLocaleString());
      for (const [,k,max] of vitals) {
        el("." + k + " strong").textContent = r[k].toLocaleString() + " / " + r[max].toLocaleString();
        el("." + k + " i").style.width = (100*r[k]/r[max]) + "%";
      }
      const recent = rows.slice(0,index+1).filter(row => row.event).slice(-3).reverse();
      el(".entries").replaceChildren(...recent.map(row => {
        const div = document.createElement("div");
        div.innerHTML = '<time></time><div><a target="_blank" rel="noopener"></a><small></small></div>';
        div.querySelector("time").textContent = clock(row.minute).slice(0,5);
        const link = div.querySelector("a");
        link.textContent = row.event; link.href = "https://www.wowhead.com/forever/quest=" + row.quest_id;
        div.querySelector("small").textContent = row.who;
        return div;
      }));
      const trace = el(".trace");
      trace.hidden = !r.trace_id;
      if (r.trace_id) {
        const panes = {jrn:{datasource:"tempo",queries:[{refId:"A",queryType:"traceql",query:r.trace_id,datasource:{type:"tempo",uid:"tempo"}}],range:{from:"now-2d",to:"now"}}};
        trace.href = "/explore?schemaVersion=1&panes=" + encodeURIComponent(JSON.stringify(panes));
      }
      const cursor = el(".cursor");
      cursor.setAttribute("x1",chartX(r)); cursor.setAttribute("x2",chartX(r));
      el(".ticks").childNodes.forEach((button,i) => button.setAttribute("aria-pressed", levels[i].level===r.level));
    }
    el(".play").onclick = () => {
      if (interval) { stop(); draw(index); return; }
      if (index === last) index = 0;
      interval = setInterval(() => {
        const next = Math.min(index+1,last);
        if (next === last) stop();
        draw(next);
      }, 250);
      draw(index);
    };
    range.oninput = () => { stop(); draw(Number(range.value)); };
    draw(index);
    return stop;
  }

  function AtlasPanel({data, height}) {
    const host = React.useRef(null);
    const frame = data.series[0];
    React.useEffect(() => {
      const root = host.current.shadowRoot || host.current.attachShadow({mode:"open"});
      if (!frame || !frame.length) {
        root.textContent = data.error?.message || "Waiting for the local journey replay…";
        return;
      }
      const rows = Array.from({length:frame.length}, (_, i) => Object.fromEntries(
        frame.fields.map(field => [field.name,field.values[i]])
      ));
      return renderAtlas(root, rows);
    }, [frame, data.error]);
    return React.createElement("div",{ref:host, style:{height, width:"100%",overflow:"auto"}});
  }
  exports.plugin = new grafana.PanelPlugin(AtlasPanel);
});
